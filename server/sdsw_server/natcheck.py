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
    def __init__(self) -> None:
        self.ports: dict[int, NatCheckPort] = {}
        self.observed: dict[str, tuple[int, float]] = {}   # public IP -> last port seen, time

    def public_port(self, ip: str, max_age: float = 120.0) -> int | None:
        """Port of the last NAT check from this address: the public port of the client's Pia socket."""
        seen = self.observed.get(ip)
        if seen and time.monotonic() - seen[1] < max_age:
            return seen[0]
        return None

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
        try:
            reply = message(type_, addr, extra)
        except ipaddress.AddressValueError:
            return
        log.debug("type %d from %s:%d on %d", type_, addr[0], addr[1], port)
        if type_ in (1, 101):
            self.observed[addr[0]] = (addr[1], time.monotonic())
        if type_ in (2, 3, 102):
            self.send(other, reply, addr)
        else:
            self.send(port, reply, addr)
        if type_ == 101:
            self.send(port, message(103, addr, extra), addr)
