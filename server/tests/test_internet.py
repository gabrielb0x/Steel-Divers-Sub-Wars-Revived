"""Tests of the public side of the server: UPnP (against a fake router), STUN, players at home.

    cd server && python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from sdsw_server import __main__ as entry, internet, stun, testclient, upnp
from sdsw_server.internet import Internet
from sdsw_server.natcheck import NatCheckService
from sdsw_server.realm import Realm, RealmConfig

from .test_server import free_udp_port

PUBLIC = "1.2.3.4"                     # stands for the router's internet address (never contacted)

DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
 <device><deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType><modelName>Fake Box</modelName>
  <deviceList><device><deviceType>urn:schemas-upnp-org:device:WANDevice:1</deviceType>
   <deviceList><device><deviceType>urn:schemas-upnp-org:device:WANConnectionDevice:1</deviceType>
    <serviceList><service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
     <controlURL>/ctl/IPConn</controlURL></service></serviceList>
   </device></deviceList>
  </device></deviceList>
 </device>
</root>"""


class FakeRouter:
    """An Internet Gateway Device on 127.0.0.1: description, and the WANIPConnection actions the server uses."""

    def __init__(self, external_ip: str = PUBLIC, permanent_only: bool = False, taken: tuple[int, ...] = ()):
        self.external_ip = external_ip
        self.permanent_only = permanent_only
        self.taken = set(taken)                         # ports already forwarded to another device
        self.mappings: dict[tuple[str, int], dict[str, str]] = {}
        router = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = DESCRIPTION.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = self.headers["SOAPAction"].strip('"').split("#")[1]
                args = dict(re.findall(r"<(New\w+)>([^<]*)</New\w+>", data))
                status, answer = router.handle(action, args)
                body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                        f'xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1"><s:Body>{answer}</s:Body>'
                        "</s:Envelope>").encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.gateway = upnp.Gateway(f"http://127.0.0.1:{self.http.server_address[1]}/ctl/IPConn",
                                    "urn:schemas-upnp-org:service:WANIPConnection:1", "192.168.1.10", "Fake Box")

    @staticmethod
    def error(code: int) -> tuple[int, str]:
        return 500, ("<s:Fault><detail><UPnPError xmlns=\"urn:schemas-upnp-org:control-1-0\">"
                     f"<errorCode>{code}</errorCode><errorDescription>error</errorDescription></UPnPError>"
                     "</detail></s:Fault>")

    def handle(self, action: str, args: dict[str, str]) -> tuple[int, str]:
        key = (args.get("NewProtocol", ""), int(args.get("NewExternalPort") or 0))
        if action == "GetExternalIPAddress":
            return 200, f"<u:GetExternalIPAddressResponse><NewExternalIPAddress>{self.external_ip}" \
                        "</NewExternalIPAddress></u:GetExternalIPAddressResponse>"
        if action == "AddPortMapping":
            if key[1] in self.taken:
                return self.error(718)
            if self.permanent_only and args["NewLeaseDuration"] != "0":
                return self.error(725)
            self.mappings[key] = args
            return 200, "<u:AddPortMappingResponse/>"
        if action == "DeletePortMapping":
            if self.mappings.pop(key, None) is None:
                return self.error(714)
            return 200, "<u:DeletePortMappingResponse/>"
        if action == "GetSpecificPortMappingEntry":
            if key not in self.mappings:
                return self.error(714)
            m = self.mappings[key]
            return 200, (f"<u:R><NewInternalPort>{m['NewInternalPort']}</NewInternalPort>"
                         f"<NewInternalClient>{m['NewInternalClient']}</NewInternalClient></u:R>")
        return self.error(401)

    def close(self):
        self.http.shutdown()
        self.http.server_close()


class FakeStun(asyncio.DatagramProtocol):
    """Answers binding requests with a fixed mapped address."""

    def __init__(self, mapped: tuple[str, int]):
        self.mapped = mapped

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        transaction = data[8:20]
        port = self.mapped[1] ^ (stun.MAGIC >> 16)
        ip = struct.unpack(">I", socket.inet_aton(self.mapped[0]))[0] ^ stun.MAGIC
        attribute = struct.pack(">HHBBHI", stun.XOR_MAPPED_ADDRESS, 8, 0, 1, port, ip)
        self.transport.sendto(struct.pack(">HHI", stun.BINDING_SUCCESS, len(attribute), stun.MAGIC)
                              + transaction + attribute, addr)


class UPnP(unittest.TestCase):
    def setUp(self):
        self.router = FakeRouter()

    def tearDown(self):
        self.router.close()

    def test_description(self):
        control, service, name = upnp.parse_description(DESCRIPTION.encode(), "http://192.168.1.1:5000/root.xml")
        self.assertEqual(control, "http://192.168.1.1:5000/ctl/IPConn")
        self.assertEqual(service, "urn:schemas-upnp-org:service:WANIPConnection:1")
        self.assertEqual(name, "Fake Box")

    def test_search_answer(self):
        answer = b"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nLOCATION: http://192.168.1.1:5000/root.xml\r\n\r\n"
        self.assertEqual(upnp.search_answer(answer, "192.168.1.1"), "http://192.168.1.1:5000/root.xml")
        self.assertIsNone(upnp.search_answer(answer, "192.168.1.2"))          # points to another device
        public = b"HTTP/1.1 200 OK\r\nLOCATION: http://1.2.3.4/root.xml\r\n\r\n"
        self.assertIsNone(upnp.search_answer(public, "1.2.3.4"))               # not on the local network

    def test_actions(self):
        gw = self.router.gateway
        self.assertEqual(upnp.external_ip(gw), PUBLIC)
        upnp.add_mapping(gw, "UDP", 61000, 61000, 3600, "test")
        self.assertEqual(upnp.get_mapping(gw, "UDP", 61000)["NewInternalClient"], "192.168.1.10")
        upnp.delete_mapping(gw, "UDP", 61000)
        self.assertIsNone(upnp.get_mapping(gw, "UDP", 61000))
        with self.assertRaises(upnp.UPnPError) as e:
            upnp.delete_mapping(gw, "UDP", 61000)
        self.assertEqual(e.exception.code, 714)


def start_internet(router: FakeRouter | None, setting="auto", stun_servers=(), ports=(("UDP", 61000),)):
    async def main():
        net = Internet(setting, use_upnp=router is not None, stun_servers=stun_servers)
        with mock.patch.object(upnp, "discover", lambda timeout=2.0: router.gateway if router else None):
            await net.start(list(ports))
        status = net.status()
        mapped = dict(router.mappings) if router else {}
        await net.close()
        return net, status, mapped
    return asyncio.run(main())


class PublicAddress(unittest.TestCase):
    def test_configured(self):
        net = Internet("5.6.7.8")
        self.assertEqual((net.public_ip, net.source), ("5.6.7.8", "config"))
        self.assertTrue(net.hosts_publicly())
        self.assertFalse(Internet("127.0.0.1").hosts_publicly())             # a local server

    def test_router_forwards_and_removes(self):
        router = FakeRouter()
        try:
            net, status, mapped = start_internet(router, ports=[("UDP", 61000), ("UDP", 61001), ("TCP", 8730)])
        finally:
            router.close()
        self.assertEqual((net.public_ip, net.source), (PUBLIC, "upnp"))
        self.assertEqual(sorted(mapped), [("TCP", 8730), ("UDP", 61000), ("UDP", 61001)])
        self.assertEqual(mapped[("UDP", 61000)]["NewLeaseDuration"], str(internet.SERVER_LEASE))
        self.assertEqual(status["upnp"]["forwarded"], ["TCP 8730", "UDP 61000", "UDP 61001"])
        self.assertEqual(router.mappings, {})                                 # removed when stopping

    def test_permanent_only_and_conflicts(self):
        router = FakeRouter(permanent_only=True, taken=(10025,))
        try:
            _, status, mapped = start_internet(router, ports=[("UDP", 61000), ("UDP", 10025)])
        finally:
            router.close()
        self.assertEqual(mapped[("UDP", 61000)]["NewLeaseDuration"], "0")
        self.assertEqual(list(status["upnp"]["failed"]), ["UDP 10025"])
        self.assertIn("718", status["upnp"]["failed"]["UDP 10025"])

    def test_stun_and_double_nat(self):
        async def with_stun(router):
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(lambda: FakeStun((PUBLIC, 40000)),
                                                               local_addr=("127.0.0.1", 0))
            server = f"127.0.0.1:{transport.get_extra_info('sockname')[1]}"
            try:
                return await asyncio.to_thread(start_internet, router, "auto", (server,))
            finally:
                transport.close()
        router = FakeRouter(external_ip="100.64.3.4")                        # the operator's NAT in front
        try:
            net, status, _ = asyncio.run(with_stun(router))
        finally:
            router.close()
        self.assertEqual((net.public_ip, net.source), (PUBLIC, "stun"))
        self.assertTrue(status["double_nat"])
        net, status, _ = asyncio.run(with_stun(None))                          # no UPnP: STUN alone
        self.assertEqual((net.public_ip, net.source, status["double_nat"]), (PUBLIC, "stun", False))

    def test_nothing_known(self):
        net, status, _ = start_internet(None)
        self.assertIsNone(net.public_ip)
        self.assertEqual(status["upnp"]["router"], None)


class PlayersAtHome(unittest.TestCase):
    """A console on the server's machine is shown to the others with the server's public address."""

    def test_seen_as(self):
        net = Internet(PUBLIC)
        self.assertTrue(net.at_home("127.0.0.1"))
        self.assertEqual(net.seen_as(("127.0.0.1", 50000)), (PUBLIC, 50000))
        self.assertEqual(net.seen_as(("8.8.8.8", 50000)), ("8.8.8.8", 50000))      # from the internet
        self.assertEqual(Internet("127.0.0.1").seen_as(("127.0.0.1", 50000)), ("127.0.0.1", 50000))
        self.assertEqual(net.secure_address("127.0.0.1"), "127.0.0.1")              # no hairpinning needed

    def test_nat_check_answer(self):
        sent = []
        service = NatCheckService(Internet(PUBLIC))
        service.send = lambda port, data, addr: sent.append((port, struct.unpack(">IIII", data), addr))
        service.answer(10025, 101, ("127.0.0.1", 50000), 0)
        public = struct.unpack(">I", socket.inet_aton(PUBLIC))[0]
        self.assertEqual([(t, p, ip) for _, (t, p, ip, _), _ in sent], [(101, 50000, public), (103, 50000, public)])
        self.assertEqual({addr for _, _, addr in sent}, {("127.0.0.1", 50000)})     # sent to the real address
        self.assertEqual(service.public_port("127.0.0.1", 50000), 50000)

    def test_public_port_of_two_consoles_on_one_address(self):
        service = NatCheckService()
        service.send = lambda *args: None
        service.answer(10025, 101, ("127.0.0.1", 50000), 0)
        service.answer(10025, 101, ("127.0.0.1", 50001), 0)
        self.assertEqual(service.public_port("127.0.0.1", 50000), 50000)
        self.assertEqual(service.public_port("127.0.0.1", 50001), 50001)
        self.assertEqual(service.public_port("127.0.0.1", 40000), 50001)            # unknown: the latest

    def test_register_gives_the_public_address(self):
        async def main():
            with tempfile.TemporaryDirectory() as tmp:
                config = RealmConfig(name="test", listen="127.0.0.1", public_address=PUBLIC,
                                     auth_port=free_udp_port(), secure_port=free_udp_port(), data_dir=Path(tmp))
                realm = Realm(config, NatCheckService())
                await realm.start()
                try:
                    secure, _ = await testclient.login("127.0.0.1", config.auth_port, 0x10000001, "password")
                    return secure.secure_url, secure.public_url
                finally:
                    testclient.close_clients()
                    realm.close()
        secure_url, public_url = asyncio.run(main())
        self.assertEqual(secure_url.get("address"), "127.0.0.1")
        self.assertEqual((public_url.get("address"), public_url.get("type")), (PUBLIC, "3"))


class StateFile(unittest.TestCase):
    def test_written_while_running(self):
        async def main(tmp: Path):
            config = tmp / "server.toml"
            config.write_text(f'[server]\nlisten = "127.0.0.1"\npublic_address = "{PUBLIC}"\nupnp = false\n'
                              f'nat_check = false\n[[realm]]\nname = "test"\nauth_port = {free_udp_port()}\n'
                              f'secure_port = {free_udp_port()}\n', encoding="utf-8")
            server, realms = entry.load_config(config, None)
            state = tmp / "data" / "server.json"
            task = asyncio.get_running_loop().create_task(entry.run(server, realms, config, state))
            for _ in range(50):
                await asyncio.sleep(0.05)
                if state.exists() and json.loads(state.read_text())["internet"]["ready"]:
                    break
            written = json.loads(state.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return written, state.exists()
        with tempfile.TemporaryDirectory() as tmp:
            written, still_there = asyncio.run(main(Path(tmp)))
        self.assertEqual(written["internet"]["public_address"], PUBLIC)
        self.assertEqual(written["realms"][0]["name"], "test")
        self.assertFalse(still_there)


if __name__ == "__main__":
    unittest.main()
