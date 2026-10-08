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

from sdsw_server import matchmaking, testclient
from sdsw_server.crypto import RC4, derive_user_key, kerberos_decrypt, kerberos_encrypt, KerberosError
from sdsw_server.ddl import MatchmakeSession, criterion_matches
from sdsw_server.matchmaking import BotSettings
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


def run_realm(test, max_players=8, cheats="separes", bots=None, anticheat_ban=30, duration=10):
    """Starts a realm on free ports, runs test(realm, port) inside the event loop."""
    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            config = RealmConfig(name="test", listen="127.0.0.1", public_address="127.0.0.1",
                                 auth_port=free_udp_port(), secure_port=free_udp_port(), data_dir=Path(tmp),
                                 max_players=max_players, cheats=cheats, anticheat_ban=anticheat_ban,
                                 duration=duration, bots=bots or BotSettings(enabled=False))
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


async def console(port: int, pid: int, flags: str = "", checksum: int = testclient.V0, lobby: int = 1):
    """A simulated console in a match: (its connection, the session)."""
    secure, _ = await testclient.login("127.0.0.1", port, pid, "password", flags)
    session = await testclient.matchmake(secure, 3, checksum=checksum, lobby=lobby)
    if session.owner_pid == pid:
        params = StreamOut(); params.u32(session.id)
        await secure.call(109, 2, params)                         # OpenParticipation, as the lobby does
    return secure, session


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class AntiCheat(unittest.TestCase):
    """Games that caught themselves cheating say so (attribute 4) at their next search for a match."""

    def test_watching_only_where_cheats_are_not_allowed(self):
        async def test(realm, port):
            secure, _ = await testclient.login("127.0.0.1", port, 0x10000001, "password")
            await testclient.matchmake(secure, 3, report=0x100)
            await asyncio.sleep(0.2)
            return secure.game_globals().get("server.anticheat")
        self.assertEqual(run_realm(test, cheats="refuses"), 1)
        self.assertEqual(run_realm(test, cheats="separes"), 1)
        self.assertEqual(run_realm(test, cheats="autorises"), 0)

    def test_caught_cheating_is_kept_out(self):
        async def test(realm, port):
            secure, _ = await testclient.login("127.0.0.1", port, 0x10000001, "password")
            with self.assertRaises(testclient.ClientError):
                await testclient.matchmake(secure, 3, report=0x100 | 8 | 1 << 16)   # kick 1: impossible speed
            try:
                await testclient.login("127.0.0.1", port, 0x10000001, "password")
                again = True
            except testclient.ClientError:
                again = False
            other, _ = await testclient.login("127.0.0.1", port, 0x10000002, "password")
            return again, realm.status()["caught_cheating"]
        again, caught = run_realm(test, cheats="refuses")
        self.assertFalse(again)                     # excluded for anticheat_ban minutes
        self.assertEqual(caught, 1)

    def test_each_kick_is_dealt_with_once(self):
        async def test(realm, port):
            secure, _ = await testclient.login("127.0.0.1", port, 0x10000001, "password")
            counts = []
            for kick in (1, 1, 2):                  # the save keeps the last kick: reported at every search
                await testclient.matchmake(secure, 3, report=0x100 | 2 | kick << 16)
                counts.append(realm.status()["caught_cheating"])
            return counts
        self.assertEqual(run_realm(test, cheats="refuses", anticheat_ban=0), [1, 1, 2])

    def test_caught_cheating_with_the_cheaters(self):
        async def test(realm, port):
            fair = await matchmade(port, 0x10000001)
            secure, _ = await testclient.login("127.0.0.1", port, 0x10000002, "password")
            caught = await testclient.matchmake(secure, 3, report=0x100 | 2 | 1 << 16)
            cheater = await matchmade(port, 0x10000003, "triche")
            again = await testclient.matchmake(secure, 3, report=0x100 | 2 | 1 << 16)
            return fair.id, caught.id, cheater.id, again.id, realm.status()["caught_cheating"]
        fair, caught, cheater, again, count = run_realm(test, cheats="separes")
        self.assertNotEqual(fair, caught)
        self.assertEqual(caught, cheater)
        self.assertEqual(again, cheater)            # still with the cheaters for anticheat_ban minutes
        self.assertEqual(count, 1)

    def test_reports_are_not_criteria(self):
        async def test(realm, port):
            a, _ = await testclient.login("127.0.0.1", port, 0x10000001, "password")
            b, _ = await testclient.login("127.0.0.1", port, 0x10000002, "password")
            first = await testclient.matchmake(a, 3, report=0x100)
            second = await testclient.matchmake(b, 3)                 # a game without the online mod's report
            return first.id, second.id
        first, second = run_realm(test, cheats="autorises")
        self.assertEqual(first, second)


class Bots(unittest.TestCase):
    """A player alone in a match for bots_delay seconds is told to play against bots."""

    def run_bots(self, test, **settings):
        bots = BotSettings(**({"delay": 60} | settings))

        async def wrapped(realm, port):
            clock = Clock()
            realm.matchmaker.clock = clock
            return await test(realm, port, clock)
        return run_realm(wrapped, bots=bots)

    def test_alone_gets_bots(self):
        async def test(realm, port, clock):
            secure, session = await console(port, 0x10000001)
            clock.now += 30
            first = realm.matchmaker.tick()
            clock.now += 31
            second = realm.matchmaker.tick()
            await asyncio.sleep(0.3)
            return first, second, secure.game_globals()
        first, second, values = self.run_bots(test, mine=1, other=4, map=5, level="expert", countdown=15)
        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)
        bots = {k: v for k, v in values.items() if k[12:15] in ("nam", "sub", "cre") or k.startswith("server.bots.lv")}
        others = {k: v for k, v in values.items() if k not in bots and k.startswith("server.bots")}
        self.assertEqual(others, {"server.bots": 1, "server.bots.mine": 1, "server.bots.other": 4,
                                  "server.bots.stage": 14, "server.bots.level": 3, "server.bots.countdown": 15000,
                                  "server.bots.duration": 600})
        names = [values[f"server.bots.name{k}"] for k in range(1, 8)]
        self.assertEqual(len(set(names)), 7)                       # seven players, all different
        self.assertTrue(all(1 <= values[f"server.bots.sub{k}"] <= 23 for k in range(1, 8)))
        for k in range(1, 8):                                       # an expert's crew: 4 or 5 members that only add
            packed = values[f"server.bots.crew{k}"]
            crew = [((packed >> (6 * i)) & 63) - 1 for i in range(5)]
            members = [c for c in crew if c >= 0]
            self.assertIn(len(members), (4, 5))
            self.assertEqual(len(set(members)), len(members))
            self.assertTrue(all(c in matchmaking.CREW_STRONG and c < 32 for c in members), members)

    def test_two_players_no_bots(self):
        async def test(realm, port, clock):
            a, _ = await console(port, 0x10000001)
            b, _ = await console(port, 0x10000002)
            clock.now += 120
            started = realm.matchmaker.tick()
            await asyncio.sleep(0.3)
            return started, a.game_globals(), b.game_globals()
        started, a, b = self.run_bots(test)
        self.assertEqual(started, [])
        self.assertEqual(a.get("server.bots"), 0)
        self.assertEqual(b.get("server.bots"), 0)

    def test_newcomer_joins_the_bots(self):
        async def test(realm, port, clock):
            a, _ = await console(port, 0x10000001)
            clock.now += 61
            realm.matchmaker.tick()
            b, _ = await console(port, 0x10000002)
            await asyncio.sleep(0.3)
            return b.game_globals()
        self.assertEqual(self.run_bots(test).get("server.bots"), 1)

    def test_next_round_starts_over(self):
        async def test(realm, port, clock):
            a, session = await console(port, 0x10000001)
            clock.now += 61
            realm.matchmaker.tick()
            params = StreamOut(); params.u32(session.id)
            await a.call(109, 1, params)                            # CloseParticipation: the battle
            params = StreamOut(); params.u32(session.id)
            await a.call(109, 2, params)                            # back in the lobby
            await asyncio.sleep(0.3)
            after = a.game_globals()["server.bots"]
            clock.now += 61
            again = realm.matchmaker.tick()
            return after, len(again)
        self.assertEqual(self.run_bots(test), (0, 1))

    def test_no_bots_in_a_chat_room(self):
        async def test(realm, port, clock):
            await console(port, 0x10000001, lobby=2)              # v0's Morse chat room: no battle
            clock.now += 61
            return realm.matchmaker.tick()
        self.assertEqual(self.run_bots(test), [])

    def test_bots_of_the_update(self):
        async def test(realm, port, clock):
            secure, _ = await console(port, 0x10000001, checksum=testclient.V5200)
            clock.now += 61
            realm.matchmaker.tick()
            await asyncio.sleep(0.3)
            return secure.game_globals()
        values = self.run_bots(test)
        self.assertEqual(values["server.bots"], 1)
        self.assertTrue(all(1 <= values[f"server.bots.sub{k}"] <= 36 for k in range(1, 8)))

    def test_settings(self):
        b = BotSettings.from_config({"bots_format": "2v3", "bots_map": "4", "bots_level": "normal",
                                     "bots_delay": 30, "bots_countdown": 20, "duration": 8,
                                     "bots_names": "Un, Deux, Trois, Quatre, Cinq, Six, Sept, Huit"})
        self.assertEqual((b.mine, b.other, b.map, b.level, b.delay, b.countdown, b.duration),
                         (2, 3, 4, "normal", 30, 20, 8))
        self.assertEqual(b.names[:2], ("Un", "Deux"))
        with self.assertRaises(ValueError):
            BotSettings.from_config({"bots_names": ["Un", "Deux"]})
        self.assertEqual(BotSettings.from_config({}).format, "4v4")
        for bad in ({"bots_format": "5v1"}, {"bots_map": "3"}, {"bots_level": "facile"}, {"bots_delay": 1}):
            with self.assertRaises(ValueError):
                BotSettings.from_config(bad)


class Options(unittest.TestCase):
    """serveur.toml options: max_players (more AI subs) and the cheat policy."""

    def test_versions_never_meet(self):
        async def test(realm, port):
            _, old = await console(port, 0x10000001)
            _, new = await console(port, 0x10000002, checksum=testclient.V5200)
            _, old2 = await console(port, 0x10000003)
            _, new2 = await console(port, 0x10000004, checksum=testclient.V5200)
            return old.id, new.id, old2.id, new2.id
        old, new, old2, new2 = run_realm(test)
        self.assertNotEqual(old, new)
        self.assertEqual(old, old2)
        self.assertEqual(new, new2)

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
        with self.assertRaises(ValueError):
            RealmConfig(name="x", listen="", public_address="", auth_port=1, secure_port=2, data_dir=Path("."),
                        duration=0)

    def test_battle_duration(self):
        async def test(realm, port):
            secure, _ = await testclient.login("127.0.0.1", port, 0x10000001, "password")
            await testclient.matchmake(secure, 3)
            await asyncio.sleep(0.2)
            return secure.game_globals().get("server.duration")
        self.assertEqual(run_realm(test), 600)
        self.assertEqual(run_realm(test, duration=3), 180)


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
