"""A NEX client that logs in and matchmakes like the game does, to test a server without the game.

    cd server && python3 -m sdsw_server.testclient [--server 127.0.0.1:61000] [--pid N] [--players 2]

It follows what the game's code does (see realm.py and prudp.py): PRUDP v1, LoginEx with an
AuthenticationInfo token, RequestTicket, Kerberos CONNECT to the secure server, Register,
AutoMatchmakeWithSearchCriteria_Postpone with the game's criteria, GetSessionURLs, NAT traversal requests.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import struct
import sys

from .accounts import TOKEN_PREFIX
from .crypto import RC4, derive_user_key, kerberos_decrypt, kerberos_encrypt
from .ddl import MatchmakeSession, RVConnectionData
from .prudp import (CONNECT, DATA, FLAG_ACK, FLAG_MULTI_ACK, FLAG_NEED_ACK, FLAG_RELIABLE, SYN, Packet,
                    Signer, decode_datagram, encode_packet)
from .streams import StationURL, StreamIn, StreamOut

log = logging.getLogger("client")
ACCESS_KEY = "fb9537fe"


class ClientError(Exception):
    pass


class PRUDPClient(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.signer = Signer(ACCESS_KEY)
        self.transport = None
        self.queue: asyncio.Queue[Packet] = asyncio.Queue()
        self.session_key = b""
        self.server_sig = b""
        self.client_sig = os.urandom(16)
        self.session = random.randint(1, 255)
        self.server_session = 0
        self.seq = 2
        self.in_next = 1
        self.rc4_in = RC4(b"CD&ML")
        self.rc4_out = RC4(b"CD&ML")
        self.src, self.dst = 0xAF, 0xA1
        self.calls: dict[int, asyncio.Future] = {}
        self.call_id = 1
        self.incoming_calls: list[tuple[int, int, bytes]] = []
        self.fragments: list[bytes] = []
        self.bad_signatures = 0

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        for p in decode_datagram(data):
            self.check(p)
            self.queue.put_nowait(p)

    def check(self, p: Packet) -> None:
        if p.type == SYN:
            expected = self.signer.sign(p.header8, b"", b"", p.options_raw, p.payload)
        elif p.type == CONNECT:
            expected = self.signer.sign(p.header8, b"", self.client_sig, p.options_raw, p.payload)
        else:
            expected = self.signer.sign(p.header8, self.session_key, self.client_sig, p.options_raw, p.payload)
        if expected != p.signature:
            self.bad_signatures += 1
            log.error("bad signature on %s", p.describe())

    def send(self, p: Packet, with_key: bool = True) -> None:
        conn_sig = b"" if p.type == SYN else self.server_sig
        key = self.session_key if with_key and p.type not in (SYN, CONNECT) else b""
        self.transport.sendto(encode_packet(p, self.signer, key, conn_sig))

    async def wait(self, type_: int, flags: int, timeout: float = 5.0) -> Packet:
        while True:
            p = await asyncio.wait_for(self.queue.get(), timeout)
            if p.type == type_ and (p.flags & flags) == flags:
                return p
            self.handle_other(p)

    async def connect(self, payload: bytes = b"") -> bytes:
        self.send(Packet(src=self.src, dst=self.dst, type=SYN, flags=FLAG_NEED_ACK, seq=0,
                         supported_functions=3, conn_sig=bytes(16), max_substream_id=0))
        ack = await self.wait(SYN, FLAG_ACK)
        self.server_sig = ack.conn_sig
        self.send(Packet(src=self.src, dst=self.dst, type=CONNECT, flags=FLAG_RELIABLE | FLAG_NEED_ACK,
                         session_id=self.session, seq=1, supported_functions=3, conn_sig=self.client_sig,
                         max_substream_id=0, payload=payload))
        ack = await self.wait(CONNECT, FLAG_ACK)
        self.server_session = ack.session_id
        asyncio.get_running_loop().create_task(self.pump())
        return ack.payload

    def set_key(self, key: bytes) -> None:
        self.session_key = key
        self.rc4_in, self.rc4_out = RC4(key), RC4(key)

    async def pump(self) -> None:
        while True:
            self.handle_other(await self.queue.get())

    def handle_other(self, p: Packet) -> None:
        if p.flags & FLAG_ACK:
            return
        if p.type == DATA and p.flags & FLAG_RELIABLE:
            # aggregate ACK, as the game does with a minor version >= 2
            ack = Packet(src=self.src, dst=self.dst, type=DATA, flags=FLAG_MULTI_ACK, session_id=self.session,
                         substream_id=1, seq=0, fragment_id=0, payload=struct.pack("<BBH", 0, 0, p.seq))
            self.send(ack)
            if p.seq != self.in_next:
                return
            self.in_next += 1
            self.fragments.append(self.rc4_in.crypt(p.payload))
            if p.fragment_id == 0:
                self.handle_rmc(b"".join(self.fragments))
                self.fragments = []

    def handle_rmc(self, payload: bytes) -> None:
        s = StreamIn(payload)
        size = s.u32()
        proto = s.u8()
        if proto & 0x80:                        # a call from the server: answer it
            call_id, method = s.u32(), s.u32()
            self.incoming_calls.append((proto & 0x7F, method, s.read(s.remaining())))
            body = struct.pack("<BBII", proto & 0x7F, 1, call_id, method | 0x8000)
            self.send_data(struct.pack("<I", len(body)) + body)
            return
        ok = s.u8()
        if ok:
            call_id, method = s.u32(), s.u32()
            fut = self.calls.pop(call_id, None)
            if fut:
                fut.set_result(StreamIn(s.read(s.remaining())))
        else:
            code, call_id = s.u32(), s.u32()
            fut = self.calls.pop(call_id, None)
            if fut:
                fut.set_exception(ClientError(f"error {code:#010x}"))

    def send_data(self, payload: bytes) -> None:
        p = Packet(src=self.src, dst=self.dst, type=DATA, flags=FLAG_RELIABLE | FLAG_NEED_ACK,
                   session_id=self.session, seq=self.seq, fragment_id=0, payload=self.rc4_out.crypt(payload))
        self.seq += 1
        self.send(p)

    async def call(self, proto: int, method: int, params: StreamOut) -> StreamIn:
        call_id = self.call_id
        self.call_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.calls[call_id] = fut
        body = struct.pack("<BII", proto | 0x80, call_id, method) + params.get()
        self.send_data(struct.pack("<I", len(body)) + body)
        return await asyncio.wait_for(fut, 5.0)


CLIENTS: list[PRUDPClient] = []


async def open_client(host: str, port: int) -> PRUDPClient:
    loop = asyncio.get_running_loop()
    _, client = await loop.create_datagram_endpoint(PRUDPClient, remote_addr=(host, port))
    CLIENTS.append(client)
    return client


def close_clients() -> None:
    while CLIENTS:
        client = CLIENTS.pop()
        if client.transport:
            client.transport.close()


def authentication_info(token: str) -> StreamOut:
    """AnyDataHolder<AuthenticationInfo> as JobCTRLogin::StepGameLogin builds it."""
    s = StreamOut()
    s.string("AuthenticationInfo")
    body = StreamOut()
    body.u8(0); body.u32(0)                                  # Data
    info = StreamOut()
    info.string(token); info.u32(3); info.u8(0); info.u32(1000)
    body.u8(0); body.u32(len(info.data)); body.write(info.get())
    s.u32(len(body.data) + 4); s.u32(len(body.data)); s.write(body.get())
    return s


async def login(host: str, port: int, pid: int, password: str, flags: str = "") -> tuple[PRUDPClient, int]:
    key = derive_user_key(pid, password)
    auth = await open_client(host, port)
    await auth.connect()
    params = StreamOut()
    params.string(str(pid))
    params.write(authentication_info(TOKEN_PREFIX + key.hex() + (f":{flags}" if flags else "")).get())
    s = await auth.call(10, 2, params)
    result, pid_out = s.u32(), s.pid()
    kerberos_decrypt(key, s.buffer())                         # ValidateKey
    _, sub = s.structure_header()
    secure_url = StationURL.parse(sub.string())
    build = s.string()
    log.info("pid %d: LoginEx %#x, secure server %s, %r", pid, result, secure_url, build)

    params = StreamOut(); params.pid(pid); params.pid(int(secure_url.get("PID")))
    s = await auth.call(10, 3, params)
    s.u32()
    t = StreamIn(kerberos_decrypt(key, s.buffer()))
    session_key, target, ticket = t.read(32), t.pid(), t.buffer()

    secure = await open_client(secure_url.get("address"), int(secure_url.get("port")))
    check = random.getrandbits(32)
    request = StreamOut(); request.pid(pid); request.u32(1); request.u32(check)
    payload = StreamOut(); payload.buffer(ticket); payload.buffer(kerberos_encrypt(session_key, request.get()))
    answer = StreamIn(await secure.connect(payload.get()))
    if answer.buffer() != struct.pack("<I", (check + 1) & 0xFFFFFFFF):
        raise ClientError("bad check value")
    secure.set_key(session_key)
    local = f"prudp:/address=192.168.1.{pid % 200 + 2};port=60000;natf=0;natm=0;pmp=0;sid=15;type=2;upnp=0"
    params = StreamOut(); params.list([local], StreamOut.string)
    s = await secure.call(11, 1, params)
    result, cid, public = s.u32(), s.u32(), s.string()
    log.info("pid %d: registered cid %d, public %s", pid, cid, public)
    return secure, cid


def game_criteria(level: int) -> StreamOut:
    """setupCriteriaList / joinSession: continent 2 (Europe), lobby type 1, level, version checksum."""
    s = StreamOut()
    s.u32(1)
    c = StreamOut()
    c.list(["2", "1", str(level), str(0xB95D7F2B), "", ""], StreamOut.string)
    c.string("1000"); c.string(""); c.string(""); c.string("1")
    c.bool(True); c.bool(True); c.bool(False); c.u32(0); c.u16(1)
    s.u8(0); s.u32(len(c.data)); s.write(c.get())
    return s


async def matchmake(secure: PRUDPClient, level: int) -> MatchmakeSession:
    proposal = MatchmakeSession(min_participants=1, max_participants=8, flags=0x10, description="Steel Matcher",
                                game_mode=1000, attributes=[2, 1, level, 0xB95D7F2B, 0, 0],
                                matchmake_system_type=1, application_buffer=b"\x01\x02\x03")
    params = StreamOut()
    params.write(game_criteria(level).get())
    params.anydata("MatchmakeSession", proposal)
    params.string("Steel Diver 2 Auto matchmake")
    s = await secure.call(109, 15, params)
    name, data = s.anydata()
    return MatchmakeSession.decode(data)


async def scenario(host: str, port: int, players: int) -> int:
    clients = []
    for n in range(players):
        pid = random.randint(0x10000000, 0x7FFFFFFF)
        secure, cid = await login(host, port, pid, f"password{n}")
        clients.append((pid, secure, cid))
    sessions = []
    for pid, secure, _ in clients:
        session = await matchmake(secure, 3)
        sessions.append(session)
        log.info("pid %d: session %d owner %d", pid, session.id, session.owner_pid)
        if session.owner_pid == pid:
            params = StreamOut(); params.u32(session.id)
            await secure.call(109, 2, params)                     # OpenParticipation
        else:
            params = StreamOut(); params.u32(session.id)
            s = await secure.call(21, 41, params)                  # GetSessionURLs
            urls = s.list(StreamIn.string)
            log.info("pid %d: host URLs %s", pid, urls)
            mine = StreamOut()
            mine.list(urls, StreamOut.string)
            mine.string(f"prudp:/address=127.0.0.1;port=1;PID={pid};RVCID={clients[0][2]}")
            await secure.call(3, 3, mine)                          # RequestProbeInitiationExt
    await asyncio.sleep(0.5)
    host_pid, host, _ = clients[0]
    log.info("host received calls: %s", [(p, m) for p, m, _ in host.incoming_calls])
    for pid, secure, _ in clients[1:]:
        params = StreamOut(); params.u32(sessions[0].id); params.string("bye")
        s = await secure.call(50, 1, params)
        log.info("pid %d: EndParticipation -> %s", pid, s.bool())
    await asyncio.sleep(0.3)
    bad = sum(c.bad_signatures for _, c, _ in clients)
    ok = all(s.id == sessions[0].id for s in sessions) and bad == 0
    log.info("%s", "OK" if ok else f"FAILED (bad signatures: {bad})")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="127.0.0.1:61000")
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    host, _, port = args.server.rpartition(":")
    sys.exit(asyncio.run(scenario(host, int(port), args.players)))


if __name__ == "__main__":
    main()
