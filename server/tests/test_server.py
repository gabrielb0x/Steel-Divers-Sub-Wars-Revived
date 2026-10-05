"""Tests of the server: formats, cryptography, and a full session between simulated consoles.

    cd server && python3 -m unittest -v
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
import tempfile
import unittest
from pathlib import Path

from sdsw_server import testclient
from sdsw_server.crypto import RC4, derive_user_key, kerberos_decrypt, kerberos_encrypt, KerberosError
from sdsw_server.ddl import MatchmakeSession, criterion_matches
from sdsw_server.natcheck import NatCheckService
from sdsw_server.prudp import CONNECT, DATA, FLAG_NEED_ACK, FLAG_RELIABLE, Packet, Signer, decode_datagram, encode_packet
from sdsw_server.realm import Realm, RealmConfig
from sdsw_server.status import StatusServer
from sdsw_server.streams import StationURL, StreamIn, StreamOut


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Formats(unittest.TestCase):
    def test_rc4(self):
        # RFC 6229 style check with the well-known "Key"/"Plaintext" vector
        self.assertEqual(RC4(b"Key").crypt(b"Plaintext").hex(), "bbf316e8d940af0ad3")
        self.assertEqual(RC4(b"").crypt(b"abc"), b"abc")

    def test_rc4_is_a_stream(self):
        a, b = RC4(b"CD&ML"), RC4(b"CD&ML")
        self.assertEqual(a.crypt(b"hello") + a.crypt(b" world"), b.crypt(b"hello world"))

    def test_kerberos(self):
        key = derive_user_key(1234567, "password")
        self.assertEqual(len(key), 16)
        data = kerberos_encrypt(key, b"ticket")
        self.assertEqual(kerberos_decrypt(key, data), b"ticket")
        with self.assertRaises(KerberosError):
            kerberos_decrypt(bytes(16), data)

    def test_mod_and_server_derive_the_same_key(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mod", Path(__file__).parents[2] / "tools" / "mod.py")
        if spec is None:
            self.skipTest("tools/mod.py not found")
        import sys
        sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except ImportError as e:
            self.skipTest(f"tools/mod.py needs {e.name}")
        self.assertEqual(mod.user_key(424242, "abc"), derive_user_key(424242, "abc").hex())

    def test_string_and_structures(self):
        s = StreamOut()
        s.string("Steel Matcher")
        s.list([1, 2], StreamOut.u32)
        session = MatchmakeSession(id=7, owner_pid=5, game_mode=1000, attributes=[2, 1], description="x")
        s.anydata("MatchmakeSession", session)
        self.assertEqual(s.get()[:2], struct.pack("<H", 14))
        r = StreamIn(s.get())
        self.assertEqual(r.string(), "Steel Matcher")
        self.assertEqual(r.list(StreamIn.u32), [1, 2])
        name, data = r.anydata()
        back = MatchmakeSession.decode(data)
        self.assertEqual((name, back.id, back.owner_pid, back.attributes), ("MatchmakeSession", 7, 5, [2, 1]))

    def test_station_url(self):
        text = "prudp:/address=1.2.3.4;port=5;sid=15;type=2"
        url = StationURL.parse(text)
        self.assertEqual(str(url), text)
        url["PID"] = 9
        self.assertEqual(url.get_int("PID"), 9)

    def test_criteria(self):
        self.assertTrue(criterion_matches("", 5))
        self.assertTrue(criterion_matches("3,7", 5))
        self.assertFalse(criterion_matches("6", 5))

    def test_prudp_packet(self):
        signer = Signer("fb9537fe")
        p = Packet(src=0xAF, dst=0xA1, type=DATA, flags=FLAG_RELIABLE | FLAG_NEED_ACK, session_id=3, seq=2,
                   fragment_id=0, payload=b"abc")
        raw = encode_packet(p, signer, b"key", bytes(16))
        (q,) = decode_datagram(raw)
        self.assertEqual((q.type, q.seq, q.fragment_id, q.payload), (DATA, 2, 0, b"abc"))
        self.assertEqual(q.signature, signer.sign(q.header8, b"key", bytes(16), q.options_raw, q.payload))
        c = Packet(src=0xAF, dst=0xA1, type=CONNECT, supported_functions=3, conn_sig=b"s" * 16, max_substream_id=0)
        (q,) = decode_datagram(encode_packet(c, signer, b"", b""))
        self.assertEqual((q.supported_functions, q.conn_sig, q.max_substream_id), (3, b"s" * 16, 0))


def run_realm(test, max_players=8, cheats="separes"):
    """Starts a realm on free ports, runs test(realm, port) inside the event loop."""
    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            config = RealmConfig(name="test", listen="127.0.0.1", public_address="127.0.0.1",
                                 auth_port=free_udp_port(), secure_port=free_udp_port(), data_dir=Path(tmp),
                                 max_players=max_players, cheats=cheats)
            realm = Realm(config, NatCheckService())
            await realm.start()
            try:
                return await test(realm, config.auth_port)
            finally:
                testclient.close_clients()
                realm.close()
    return asyncio.run(main())


async def matchmade(port: int, pid: int, flags: str = ""):
    secure, _ = await testclient.login("127.0.0.1", port, pid, "password", flags)
    return await testclient.matchmake(secure, 3)


class Options(unittest.TestCase):
    """serveur.toml options: max_players (more AI subs) and the cheat policy."""

    def test_max_players(self):
        async def test(realm, port):
            sessions = [await matchmade(port, 0x10000000 + n) for n in range(3)]
            return [s.id for s in sessions], sessions[0].max_participants
        ids, maximum = run_realm(test, max_players=2)
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[1], ids[2])
        self.assertEqual(maximum, 2)

    def test_cheaters_kept_apart(self):
        async def test(realm, port):
            fair = await matchmade(port, 0x10000001)
            cheater = await matchmade(port, 0x10000002, "triche")
            other = await matchmade(port, 0x10000003, "triche")
            return fair.id, cheater.id, other.id
        fair, cheater, other = run_realm(test, cheats="separes")
        self.assertNotEqual(fair, cheater)
        self.assertEqual(cheater, other)

    def test_changed_characteristics_count_as_cheating(self):
        async def test(realm, port):
            fair = await matchmade(port, 0x10000001, "premium")
            specs = await matchmade(port, 0x10000002, "specs")
            cheater = await matchmade(port, 0x10000003, "premium,triche")
            return fair.id, specs.id, cheater.id
        fair, specs, cheater = run_realm(test, cheats="separes")
        self.assertNotEqual(fair, specs)
        self.assertEqual(specs, cheater)

    def test_banned_player_refused(self):
        async def test(realm, port):
            (realm.config.data_dir / "bannis.txt").write_text("# trouble makers\n0x10000002\n")
            await matchmade(port, 0x10000001)
            try:
                await matchmade(port, 0x10000002)
            except Exception:
                return True
            return False
        self.assertTrue(run_realm(test))

    def test_status(self):
        async def test(realm, port):
            await matchmade(port, 0x10000001)
            await matchmade(port, 0x10000002)
            await matchmade(port, 0x10000003, "triche")
            status = StatusServer([realm])
            web = free_tcp_port()
            await status.start("127.0.0.1", web)
            reader, writer = await asyncio.open_connection("127.0.0.1", web)
            writer.write(b"GET /status.json HTTP/1.0\r\nHost: x\r\n\r\n")
            answer = await reader.read()
            writer.close()
            page = status.page()
            status.close()
            return json.loads(answer.split(b"\r\n\r\n", 1)[1]), page
        data, page = run_realm(test)
        realm = data["realms"][0]
        self.assertEqual(realm["players_online"], 3)
        self.assertEqual(realm["cheaters_online"], 1)
        self.assertEqual(sorted((m["players"], m["cheaters"]) for m in realm["matches"]), [(1, True), (2, False)])
        self.assertNotIn("268435457", json.dumps(data))      # no player id (0x10000001)
        self.assertIn("3</b> joueur(s)", page)

    def test_cheaters_allowed(self):
        async def test(realm, port):
            return (await matchmade(port, 0x10000001)).id, (await matchmade(port, 0x10000002, "triche")).id
        fair, cheater = run_realm(test, cheats="autorises")
        self.assertEqual(fair, cheater)

    def test_cheaters_refused(self):
        async def test(realm, port):
            with self.assertRaises(testclient.ClientError):
                await matchmade(port, 0x10000002, "triche")
            return (await matchmade(port, 0x10000001)).id
        self.assertTrue(run_realm(test, cheats="refuses"))

    def test_bad_option(self):
        with self.assertRaises(ValueError):
            RealmConfig(name="x", listen="", public_address="", auth_port=1, secure_port=2, data_dir=Path("."),
                        max_players=9)


class Session(unittest.TestCase):
    """Three simulated consoles log in, matchmake into one session and leave it."""

    def test_full_session(self):
        logging.basicConfig(level=logging.WARNING)

        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                config = RealmConfig(name="test", listen="127.0.0.1", public_address="127.0.0.1",
                                     auth_port=free_udp_port(), secure_port=free_udp_port(), data_dir=Path(tmp))
                realm = Realm(config, NatCheckService())
                await realm.start()
                try:
                    result = await testclient.scenario("127.0.0.1", config.auth_port, 3)
                    self.assertEqual(len(realm.matchmaker.sessions), 1)
                    self.assertEqual(realm.accounts.count(), 3)
                    return result
                finally:
                    testclient.close_clients()
                    realm.close()

        self.assertEqual(asyncio.run(scenario()), 0)


if __name__ == "__main__":
    unittest.main()
