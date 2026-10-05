"""How players far away reach the server, and how they see the players of the server's own network.

* Public address: given in serveur.toml (public_address = "1.2.3.4" or a name), or "auto": the address the
  router reports (UPnP), else the one a STUN server sees.
* Router forwards: with upnp = true the server asks the router to forward its UDP ports to it (UPnP IGD),
  renews them while it runs and removes them when it stops. Without UPnP they are forwarded by hand.
* Players at home: a console on the server's machine or network logs in through 127.0.0.1 or the local
  network, so the server sees a local address that means nothing to a player far away. The battle is peer to
  peer (Pia), and a console that joins a host compares the host's public address with its own
  (pia::inet::NexConnectStationJob::StartupImpl): the same one means "same network, use the private address",
  another one "use the public address". When the server has a public address on the internet, it presents
  the players at home with it everywhere the game learns a public address: SecureConnection::Register, the
  NAT check answers and the station URLs given to the others. The port of their Pia socket is forwarded on the
  router as well (UPnP); without it the router must keep the port of their packets, as most routers do.

Standard library only. The UPnP and STUN requests block: they run in a thread.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import urllib.parse

from . import stun, upnp

log = logging.getLogger("internet")

SERVER_LEASE = 3600              # seconds asked for the server's forwards, renewed every RENEW seconds
PLAYER_LEASE = 7200              # forward of the Pia socket of a player at home, removed when it leaves
RENEW = 1200
DESCRIPTION = "Sub Wars Open Sourced"


def route_source(ip: str) -> str | None:
    """This machine's address on the way to ip (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((ip, 9))
            return s.getsockname()[0]
    except OSError:
        return None


def internet_source() -> str | None:
    """This machine's address on its way to the internet (its address on the router's network)."""
    return route_source("192.0.2.1")                 # TEST-NET-1: only picks the default route


def is_global(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


class Internet:
    def __init__(self, public_address: str = "auto", use_upnp: bool = False, stun_servers=stun.SERVERS) -> None:
        self.setting = (public_address or "auto").strip()
        self.use_upnp = use_upnp
        self.stun_servers = tuple(stun_servers)
        self.gateway: upnp.Gateway | None = None
        self.public_ip: str | None = None        # numeric public address
        self.public_name: str | None = None      # what players far away are told: the configured name, or the IP
        self.source = ""                         # where the public address comes from: config, upnp, stun
        self.router_ip: str | None = None        # internet address the router reports
        self.stun_ip: str | None = None
        self.ports: list[tuple[str, int]] = []   # the server's own ports
        self.forwards: dict[tuple[str, int], tuple[str, int, int]] = {}   # (protocol, external port) -> client
        self.failed: dict[tuple[str, int], str] = {}
        self.upnp_error = ""
        self.double_nat = False                  # the router's internet address is not the one the internet sees
        self.resolve_error = ""
        self.on_change = None                    # called when status() changes
        self.ready = False                       # public address and forwards looked for
        self._tasks: set[asyncio.Task] = set()
        if self.setting != "auto":
            self._configured()

    # -- setup ---------------------------------------------------------------------------------------

    def _configured(self) -> None:
        try:
            self.public_ip = str(ipaddress.IPv4Address(self.setting))
        except ValueError:
            self.public_name = self.setting
            try:
                self.public_ip = socket.gethostbyname(self.setting)
            except OSError as e:
                self.resolve_error = f"cannot resolve public_address {self.setting!r}: {e}"
                log.warning("%s", self.resolve_error)
        self.source = "config"

    async def start(self, ports: list[tuple[str, int]]) -> None:
        self.ports = list(ports)
        await asyncio.to_thread(self._setup)
        if self.use_upnp or self.setting == "auto":
            self._spawn(self._renew())
        self.ready = True
        self._changed()

    def _setup(self) -> None:
        if self.use_upnp:
            self._find_router()
        if self.setting == "auto":
            self._detect()
        if self.public_ip:
            log.info("public address %s (%s)%s", self.public_name or self.public_ip, self.source,
                     "" if is_global(self.public_ip) else ": not an internet address, players far away cannot join")
        else:
            log.warning("public address unknown: only players on this network can join "
                        "(public_address in serveur.toml)")

    def _find_router(self) -> None:
        self.gateway = upnp.discover()
        if self.gateway is None:
            self.upnp_error = "no UPnP router answered on the local network"
            log.warning("UPnP: no router answered: forward the ports by hand on the router (%s) to %s",
                        ", ".join(f"{p} {n}" for p, n in self.ports), internet_source())
            return
        self.upnp_error = ""
        log.info("UPnP: router %s, this machine is %s", self.gateway, self.gateway.local_ip)
        self._router_address()
        for protocol, port in self.ports:
            self._forward(protocol, port, port, None, SERVER_LEASE)

    def _router_address(self) -> None:
        try:
            self.router_ip = upnp.external_ip(self.gateway) or None
        except upnp.UPnPError as e:
            log.warning("UPnP: %s", e)

    def _detect(self) -> None:
        if self.router_ip and is_global(self.router_ip):
            self.public_ip, self.source = self.router_ip, "upnp"
            return
        found = stun.public_address(self.stun_servers)
        self.stun_ip = found[0] if found else None
        if self.stun_ip:
            self.public_ip, self.source = self.stun_ip, "stun"
        double = bool(self.router_ip and self.stun_ip and self.router_ip != self.stun_ip)
        if double and not self.double_nat:
            log.warning("the router's internet address is %s but the internet sees %s: another NAT (the "
                        "operator's, or a second router) is in front of the router, and forwards on the router "
                        "cannot make this server reachable", self.router_ip, self.stun_ip)
        self.double_nat = double

    def _forward(self, protocol: str, external: int, internal: int, client: str | None, lease: int) -> bool:
        key = (protocol, external)
        try:
            try:
                upnp.add_mapping(self.gateway, protocol, external, internal, lease, DESCRIPTION, client)
            except upnp.UPnPError as e:
                if e.code != 725:
                    raise
                lease = 0                            # permanent only: removed when the server stops
                upnp.add_mapping(self.gateway, protocol, external, internal, lease, DESCRIPTION, client)
        except upnp.UPnPError as e:
            self.failed[key] = str(e)
            log.warning("UPnP: cannot forward %s %d: %s", protocol, external, e)
            return False
        renewed = key in self.forwards
        self.forwards[key] = (client or self.gateway.local_ip, internal, lease)
        self.failed.pop(key, None)
        (log.debug if renewed else log.info)("UPnP: %s %d forwarded to %s:%d%s", protocol, external,
                                             client or self.gateway.local_ip, internal, "" if lease else " (permanent)")
        return True

    async def _renew(self) -> None:
        while True:
            await asyncio.sleep(RENEW)
            await asyncio.to_thread(self._refresh)
            self._changed()

    def _refresh(self) -> None:
        if self.use_upnp and self.gateway is None:
            self._find_router()                      # UPnP turned on in the router since
        elif self.gateway:
            self._router_address()
            for (protocol, external), (client, internal, lease) in list(self.forwards.items()):
                if lease:
                    self._forward(protocol, external, internal, client, lease)
            for protocol, port in self.ports:
                if (protocol, port) in self.failed:
                    self._forward(protocol, port, port, None, SERVER_LEASE)
        if self.setting == "auto":
            before = self.public_ip
            self._detect()
            if self.public_ip != before:
                log.info("public address now %s (%s)", self.public_ip, self.source)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self.gateway and self.forwards:
            await asyncio.to_thread(self._remove_all)

    def _remove_all(self) -> None:
        for protocol, external in list(self.forwards):
            try:
                upnp.delete_mapping(self.gateway, protocol, external)
            except upnp.UPnPError as e:
                log.debug("UPnP: %s", e)
            del self.forwards[(protocol, external)]
        log.info("UPnP: forwards removed")

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    def _spawn(self, coroutine) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- players at home -----------------------------------------------------------------------------

    def hosts_publicly(self) -> bool:
        return bool(self.public_ip) and is_global(self.public_ip)

    def at_home(self, ip: str) -> bool:
        """A client on this machine, or on its local network behind the same router."""
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if address.is_loopback:
            return True
        if address.is_global:
            return False
        source = route_source(ip)                    # a VPN peer goes through another interface
        return source is not None and source == internet_source()

    def seen_as(self, addr: tuple[str, int]) -> tuple[str, int]:
        """The address under which players far away see a client: the public one for the players at home."""
        if self.hosts_publicly() and self.at_home(addr[0]):
            return self.public_ip, addr[1]
        return addr

    def secure_address(self, client_ip: str, configured: str = "auto") -> str:
        """Address of the secure server in the ticket of a client: the public one for a client that comes
        from the internet, else this machine's address on the way to it (loopback, local network, VPN)."""
        local = route_source(client_ip)
        public = configured if configured != "auto" else (self.public_name or self.public_ip)
        if is_global(client_ip) and local == internet_source():
            return public or local or "127.0.0.1"
        return local or public or "127.0.0.1"

    def forward_player(self, ip: str, port: int, private_ip: str | None = None) -> bool:
        """Forwards the Pia port of a player at home on the router (in a thread); True when asked."""
        if not (self.gateway and self.hosts_publicly() and self.at_home(ip)) or ("UDP", port) in self.forwards:
            return False
        client = self.home_machine(ip, private_ip)

        async def work() -> None:
            await asyncio.to_thread(self._forward, "UDP", port, port, client, PLAYER_LEASE)
            self._changed()
        self._spawn(work())
        return True

    def home_machine(self, ip: str, private_ip: str | None = None) -> str:
        """Address on the router's network of the machine of a player at home: the one its console announces
        (private station URL) when it is on that network, else the one its packets come from. Packets sent to
        the public address come back from the router itself (hairpinning): not a target."""
        if not self.gateway:
            return ip
        router = urllib.parse.urlsplit(self.gateway.control_url).hostname
        network = ipaddress.ip_network(f"{self.gateway.local_ip}/16", strict=False)    # a home network, roughly
        for candidate in (private_ip, ip):
            try:
                address = ipaddress.ip_address(candidate or "")
            except ValueError:
                continue
            if address in network and not address.is_loopback and candidate != router:
                return candidate
        return self.gateway.local_ip

    def release_player(self, port: int) -> None:
        if ("UDP", port) not in self.forwards or ("UDP", port) in self.ports:
            return
        self.forwards.pop(("UDP", port), None)

        async def work() -> None:
            try:
                await asyncio.to_thread(upnp.delete_mapping, self.gateway, "UDP", port)
            except upnp.UPnPError as e:
                log.debug("UPnP: %s", e)
            self._changed()
        self._spawn(work())

    # -- state -----------------------------------------------------------------------------------------

    def status(self) -> dict:
        own = set(self.ports)
        forwards, failed = list(self.forwards), dict(self.failed)       # workers may change them
        return {"public_address": self.public_name or self.public_ip, "public_ip": self.public_ip,
                "source": self.source, "global": self.hosts_publicly(), "lan_address": internet_source(),
                "router_address": self.router_ip, "stun_address": self.stun_ip, "double_nat": self.double_nat,
                "resolve_error": self.resolve_error,
                "upnp": {"enabled": self.use_upnp, "router": str(self.gateway) if self.gateway else None,
                         "error": self.upnp_error,
                         "forwarded": sorted(f"{p} {n}" for p, n in forwards if (p, n) in own),
                         "players": len([k for k in forwards if k not in own]),
                         "failed": {f"{p} {n}": e for (p, n), e in sorted(failed.items())}},
                "ports": [f"{p} {n}" for p, n in self.ports], "ready": self.ready, "updated": int(time.time())}
