"""NAT check service: the UDP "nncs" servers that Pia and NEX use to learn the player's NAT.

From the game (Pia NatTraverser::updateNatServerAddress, NatPropertyDetecter, NatPortDetecter, NEX
JobPerformNATCheck): two servers, nncs1 and nncs2.app.nintendowifi.net, each on UDP ports 10025 and 10125.
Messages are NATCheckMessage, 16 bytes in network byte order: type, port, address, extra. A server answers
with the type it received and the address and port it saw the request come from.

Pia's NAT property detection sends type 101 and 102 to nncs1:10025 and type 103 to the other server
(another IP, same port); it needs the answers to 101 and 103 (else HandleResult fails), and uses 102 for
the filtering test (the real server answered 102 from its other address). With a single IP address,
both names point here, Pia finds no second server and never sends 103: we answer 103 along with every
101 (Pia does not check where answers come from), which reports a NAT whose mapping does not depend on the
destination, the common case. 102 is answered from the other port.

NEX's own check (JobPerformNATCheck, types 1 to 5) is answered the same way: 2 from the other port
(filtering test), 3 from the other port, the rest from the port that received them.

A console on the server's machine or network is told the server's public address instead of its local one
(internet.Internet.seen_as): the address under which the players far away see it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import struct
import time

log = logging.getLogger("natcheck")

PORTS = (10025, 10125)


def message(type_: int, addr: tuple[str, int], extra: int = 0) -> bytes:
    ip = int(ipaddress.IPv4Address(addr[0]))
    return struct.pack(">IIII", type_, addr[1], ip, extra)


class NatCheckPort(asyncio.DatagramProtocol):
    def __init__(self, service: "NatCheckService", port: int) -> None:
        self.service = service
        self.port = port
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) != 16:
            return
        type_, _port, _ip, extra = struct.unpack(">IIII", data)
        if type_ == 0:
            return                                   # "dummy" packets that only open the NAT
        self.service.answer(self.port, type_, addr, extra)


class NatCheckService:
    def __init__(self, internet=None) -> None:
        self.internet = internet                         # internet.Internet: public address of local players
        self.ports: dict[int, NatCheckPort] = {}
        self.observed: dict[str, dict[int, float]] = {}   # IP -> port seen -> time, recent ones

    def public_port(self, ip: str, local_port: int | None = None, max_age: float = 120.0) -> int | None:
        """Public port of a client's Pia socket: the port its NAT checks came from. Several consoles behind
        one address (one home, one machine) are told apart by their local port, which a NAT usually keeps;
        otherwise the latest port."""
        now = time.monotonic()
        seen = {port: t for port, t in self.observed.get(ip, {}).items() if now - t < max_age}
        if local_port in seen:
            return local_port
        return max(seen, key=seen.get) if seen else None

    async def start(self, host: str) -> None:
        loop = asyncio.get_running_loop()
        for port in PORTS:
            _, proto = await loop.create_datagram_endpoint(lambda p=port: NatCheckPort(self, p),
                                                           local_addr=(host, port))
            self.ports[port] = proto
        log.info("NAT check on UDP %s", ", ".join(map(str, PORTS)))

    def send(self, from_port: int, data: bytes, addr) -> None:
        proto = self.ports.get(from_port)
        if proto and proto.transport:
            proto.transport.sendto(data, addr)

    def answer(self, port: int, type_: int, addr, extra: int) -> None:
        other = PORTS[1] if port == PORTS[0] else PORTS[0]
        seen = self.internet.seen_as(addr) if self.internet else addr
        try:
            reply = message(type_, seen, extra)
        except ipaddress.AddressValueError:
            return
        log.debug("type %d from %s:%d on %d%s", type_, addr[0], addr[1], port,
                  f" (answered as {seen[0]})" if seen != addr else "")
        if type_ in (1, 101):
            now = time.monotonic()
            if len(self.observed) > 4096:                # forget the addresses not seen for a while
                self.observed = {ip: ports for ip, ports in self.observed.items() if now - max(ports.values()) < 600}
            ports = self.observed.setdefault(addr[0], {})
            ports[addr[1]] = now
            if len(ports) > 16:
                del ports[min(ports, key=ports.get)]
        if type_ in (2, 3, 102):
            self.send(other, reply, addr)
        else:
            self.send(port, reply, addr)
        if type_ == 101:
            self.send(port, message(103, seen, extra), addr)
