"""PRUDP, the reliable UDP transport of NEX, server side, as the game's client expects it.

What the game does (libOnlineCore, nn::nex::PRUDPEndPoint / PRUDPMessageV1, EUR v0):
  * Streams of type 10 (RVSecure: authentication and secure servers) use PRUDP version 1: the stream
    constructor takes the version from a NEX global initialised to 1 (byte 0x00399D2E).
    PRUDPMessageSelector also accepts V0 packets, but the client never sends them for these streams.
  * V1 packet: EA D0 | version 1 | options size | payload size | source | destination | type+flags (u16)
    | session id | substream id | sequence id | signature (16) | options | payload.
  * Options: SYN/CONNECT: 0 supported functions (u32, minor version in the low byte, 3 for the client),
    1 connection signature (16), [3 initial unreliable sequence id (u16), CONNECT only, if not 0],
    4 maximum substream id (u8); DATA: 2 fragment id (u8).
  * Signature: HMAC-MD5 keyed with MD5(access key) over header[4:12], the session key (DATA and other
    packets once connected), the u32 sum of the access key bytes, the connection signature, the options
    and the payload (PRUDPMessageV1::CalcSignatureHelper, methods 5 and 6).
  * Payloads of reliable DATA packets go through RC4 (PacketEncDec), one stream per direction, keyed
    with the Kerberos session key on the secure server and with "CD&ML" on the authentication server
    (seen in the game's first LoginEx; the key does not appear as a string in the executable). The
    signatures only include the session key, so none on the authentication server.
  * Reliable packets are delivered in order; the first one the client expects from us has sequence id 1
    (PacketDispatchQueue starts at 1). The client's CONNECT uses 1 and its first DATA 2.
  * With a minor version >= 1 the client acknowledges our DATA with aggregate ACKs (flag MULTI_ACK).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from dataclasses import dataclass, field

from .crypto import RC4, hmac_md5

log = logging.getLogger("prudp")

# Packet types and flags (flags are stored above the 4 type bits).
SYN, CONNECT, DATA, DISCONNECT, PING, USER = 0, 1, 2, 3, 4, 5
FLAG_ACK, FLAG_RELIABLE, FLAG_NEED_ACK, FLAG_HAS_SIZE, FLAG_MULTI_ACK = 0x1, 0x2, 0x4, 0x8, 0x200
TYPE_NAMES = {SYN: "SYN", CONNECT: "CONNECT", DATA: "DATA", DISCONNECT: "DISCONNECT", PING: "PING", USER: "USER"}

SERVER_MINOR_VERSION = 3            # what the client announces (byte 0x005E4C78 = 3)
DEFAULT_KEY = b"CD&ML"              # RC4 key of connections without a session key
FRAGMENT_SIZE = 1000                # payload bytes per fragment we send
RESEND_INTERVAL = 0.5               # seconds before resending an unacknowledged packet
MAX_RESENDS = 20
IDLE_TIMEOUT = 90.0                 # seconds without any packet before dropping a connection


def seq_lt(a: int, b: int) -> bool:
    """a < b for 16-bit sequence ids (wrapping)."""
    return ((a - b) & 0xFFFF) >= 0x8000


@dataclass
class Packet:
    src: int = 0
    dst: int = 0
    type: int = DATA
    flags: int = 0
    session_id: int = 0
    substream_id: int = 0
    seq: int = 0
    signature: bytes = b""
    supported_functions: int | None = None
    conn_sig: bytes | None = None
    initial_unreliable_seq: int | None = None
    max_substream_id: int | None = None
    fragment_id: int | None = None
    payload: bytes = b""
    header8: bytes = b""            # bytes signed by the HMAC (as received)
    options_raw: bytes = b""

    def has(self, flag: int) -> bool:
        return bool(self.flags & flag)

    def describe(self) -> str:
        flags = "|".join(n for f, n in ((FLAG_ACK, "ACK"), (FLAG_RELIABLE, "REL"), (FLAG_NEED_ACK, "NEED_ACK"),
                                        (FLAG_HAS_SIZE, "SIZE"), (FLAG_MULTI_ACK, "MULTI")) if self.flags & f)
        extra = ""
        if self.fragment_id is not None:
            extra += f" frag={self.fragment_id}"
        if self.supported_functions is not None:
            extra += f" func={self.supported_functions:#x}"
        if self.max_substream_id is not None:
            extra += f" maxsub={self.max_substream_id}"
        return (f"{TYPE_NAMES.get(self.type, self.type)} [{flags}] seq={self.seq} sess={self.session_id:#x} "
                f"sub={self.substream_id} {self.src:#04x}->{self.dst:#04x}{extra} len={len(self.payload)}")


def encode_options(p: Packet) -> bytes:
    out = bytearray()
    if p.type in (SYN, CONNECT):
        out += struct.pack("<BBI", 0, 4, p.supported_functions or 0)
        out += struct.pack("<BB", 1, 16) + (p.conn_sig or bytes(16))
        if p.type == CONNECT and p.initial_unreliable_seq:
            out += struct.pack("<BBH", 3, 2, p.initial_unreliable_seq)
        out += struct.pack("<BBB", 4, 1, p.max_substream_id or 0)
    if p.type == DATA:
        out += struct.pack("<BBB", 2, 1, p.fragment_id or 0)
    return bytes(out)


def decode_options(p: Packet, data: bytes) -> None:
    pos = 0
    while pos + 2 <= len(data):
        oid, size = data[pos], data[pos + 1]
        value = data[pos + 2:pos + 2 + size]
        pos += 2 + size
        if oid == 0 and size == 4:
            p.supported_functions = struct.unpack("<I", value)[0]
        elif oid == 1 and size == 16:
            p.conn_sig = value
        elif oid == 2 and size == 1:
            p.fragment_id = value[0]
        elif oid == 3 and size == 2:
            p.initial_unreliable_seq = struct.unpack("<H", value)[0]
        elif oid == 4 and size == 1:
            p.max_substream_id = value[0]


def decode_datagram(data: bytes) -> list[Packet]:
    """Splits a datagram into V1 packets (several can be bundled)."""
    packets = []
    pos = 0
    while pos + 30 <= len(data):
        if data[pos:pos + 2] != b"\xEA\xD0":
            raise ValueError("not a PRUDP V1 packet")
        version, opt_size, payload_size, src, dst, type_flags, session, substream, seq = \
            struct.unpack_from("<BBHBBHBBH", data, pos + 2)
        if version != 1:
            raise ValueError(f"PRUDP V1 version byte {version}")
        header8 = data[pos + 6:pos + 14]
        signature = data[pos + 14:pos + 30]
        options = data[pos + 30:pos + 30 + opt_size]
        payload = data[pos + 30 + opt_size:pos + 30 + opt_size + payload_size]
        if len(payload) != payload_size:
            raise ValueError("truncated packet")
        p = Packet(src=src, dst=dst, type=type_flags & 0xF, flags=type_flags >> 4, session_id=session,
                   substream_id=substream, seq=seq, signature=signature, payload=payload,
                   header8=header8, options_raw=options)
        decode_options(p, options)
        packets.append(p)
        pos += 30 + opt_size + payload_size
    return packets


class Signer:
    """HMAC-MD5 packet signatures, keyed with MD5(access key)."""

    def __init__(self, access_key: str) -> None:
        key = access_key.encode("ascii")
        self.hmac_key = hashlib.md5(key).digest()
        self.key_sum = struct.pack("<I", sum(key))

    def sign(self, header8: bytes, session_key: bytes, conn_sig: bytes, options: bytes, payload: bytes) -> bytes:
        return hmac_md5(self.hmac_key, header8, session_key, self.key_sum, conn_sig, options, payload)

    def connection_signature(self, addr: tuple[str, int]) -> bytes:
        # The client only echoes it back; NEX itself uses an HMAC of the address (method 1).
        ip = bytes(int(x) for x in addr[0].split(".")) if addr[0].count(".") == 3 else addr[0].encode()
        return hmac_md5(self.hmac_key, ip, struct.pack(">H", addr[1]))


def encode_packet(p: Packet, signer: Signer, session_key: bytes, conn_sig: bytes) -> bytes:
    p.flags |= FLAG_HAS_SIZE
    options = encode_options(p)
    header = struct.pack("<BBHBBHBBH", 1, len(options), len(p.payload), p.src, p.dst,
                         p.type | (p.flags << 4), p.session_id, p.substream_id, p.seq)
    p.signature = signer.sign(header[4:], session_key, conn_sig, options, p.payload)
    return b"\xEA\xD0" + header + p.signature + options + p.payload


@dataclass
class Outgoing:
    seq: int
    data: bytes
    sent: float
    tries: int = 1


@dataclass
class Connection:
    server: "PRUDPServer"
    addr: tuple[str, int]
    client_port: int                         # source byte of the client's packets
    server_port: int                         # destination byte (our stream type / port)
    server_signature: bytes
    state: str = "syn"
    minor_version: int = SERVER_MINOR_VERSION
    supported_functions: int = SERVER_MINOR_VERSION
    max_substream_id: int = 0
    client_signature: bytes = bytes(16)
    client_session: int = 0
    server_session: int = 0
    session_key: bytes = b""
    rc4_in: RC4 = field(default_factory=lambda: RC4(DEFAULT_KEY))
    rc4_out: RC4 = field(default_factory=lambda: RC4(DEFAULT_KEY))
    in_next: int = 2                          # next reliable sequence id expected from the client
    in_buffer: dict[int, Packet] = field(default_factory=dict)
    fragments: list[bytes] = field(default_factory=list)
    out_next: int = 1
    unacked: dict[int, Outgoing] = field(default_factory=dict)
    connect_ack: bytes | None = None
    last_seen: float = field(default_factory=time.monotonic)
    pid: int = 0
    data: dict = field(default_factory=dict)  # protocol state (RMC layer, matchmaking...)

    def __str__(self) -> str:
        who = f" pid={self.pid}" if self.pid else ""
        return f"{self.addr[0]}:{self.addr[1]}{who}"

    def set_session_key(self, key: bytes) -> None:
        self.session_key = key
        self.rc4_in = RC4(key)
        self.rc4_out = RC4(key)

    # -- sending -------------------------------------------------------------------------------

    def _packet(self, type_: int, flags: int, seq: int, payload: bytes = b"", **kw) -> Packet:
        return Packet(src=self.server_port, dst=self.client_port, type=type_, flags=flags,
                      session_id=self.server_session, substream_id=0, seq=seq, payload=payload, **kw)

    def _encode(self, p: Packet, with_key: bool = True) -> bytes:
        key = self.session_key if with_key else b""
        conn_sig = self.client_signature if p.type != SYN else b""
        return encode_packet(p, self.server.signer, key, conn_sig)

    def send_data(self, payload: bytes) -> None:
        """Sends an RMC message as reliable DATA, fragmented and encrypted."""
        chunks = [payload[i:i + FRAGMENT_SIZE] for i in range(0, len(payload), FRAGMENT_SIZE)] or [b""]
        for n, chunk in enumerate(chunks):
            frag = 0 if n == len(chunks) - 1 else n + 1
            seq = self.out_next
            self.out_next = (self.out_next + 1) & 0xFFFF
            p = self._packet(DATA, FLAG_RELIABLE | FLAG_NEED_ACK, seq, self.rc4_out.crypt(chunk),
                             fragment_id=frag)
            raw = self._encode(p)
            self.unacked[seq] = Outgoing(seq, raw, time.monotonic())
            self.server.send_raw(raw, self.addr)
            log.debug("%s <- %s", self, p.describe())

    def send_ack(self, p: Packet) -> None:
        kw = {"fragment_id": p.fragment_id or 0} if p.type == DATA else {}
        ack = self._packet(p.type, FLAG_ACK, p.seq, **kw)
        ack.substream_id = p.substream_id
        self.server.send_raw(self._encode(ack), self.addr)

    def acknowledge(self, seqs) -> None:
        for s in seqs:
            self.unacked.pop(s, None)

    def resend(self, now: float) -> bool:
        """Resends late packets; False when the client stopped answering."""
        for out in self.unacked.values():
            if now - out.sent >= RESEND_INTERVAL * min(out.tries, 4):
                if out.tries >= MAX_RESENDS:
                    return False
                out.tries += 1
                out.sent = now
                self.server.send_raw(out.data, self.addr)
        return True


class PRUDPServer(asyncio.DatagramProtocol):
    """One UDP port, many client connections. Subclasses implement the hooks."""

    def __init__(self, name: str, access_key: str) -> None:
        self.name = name
        self.signer = Signer(access_key)
        self.transport: asyncio.DatagramTransport | None = None
        self.connections: dict[tuple[str, int], Connection] = {}
        self.log = logging.getLogger(name)
        self._task: asyncio.Task | None = None

    # -- hooks ---------------------------------------------------------------------------------

    def on_connect(self, conn: Connection, payload: bytes) -> bytes | None:
        """CONNECT payload -> CONNECT-ACK payload, or None to refuse."""
        return b""

    def on_data(self, conn: Connection, payload: bytes) -> None:
        pass

    def on_disconnect(self, conn: Connection, reason: str) -> None:
        pass

    # -- asyncio -------------------------------------------------------------------------------

    def connection_made(self, transport) -> None:
        self.transport = transport
        self._task = asyncio.get_running_loop().create_task(self._maintenance())

    def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self.transport:
            self.transport.close()

    def send_raw(self, data: bytes, addr) -> None:
        if self.transport is not None:
            self.transport.sendto(data, addr)

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            for addr, conn in list(self.connections.items()):
                if now - conn.last_seen > IDLE_TIMEOUT:
                    self.drop(conn, "timeout")
                elif not conn.resend(now):
                    self.drop(conn, "no acknowledgement")

    def drop(self, conn: Connection, reason: str) -> None:
        if self.connections.get(conn.addr) is conn:
            del self.connections[conn.addr]
            self.log.info("%s disconnected (%s)", conn, reason)
            if conn.state == "connected":
                try:
                    self.on_disconnect(conn, reason)
                except Exception:
                    self.log.exception("on_disconnect failed")

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            packets = decode_datagram(data)
        except ValueError as e:
            self.log.debug("ignored datagram from %s:%s (%s): %s", addr[0], addr[1], e, data[:32].hex())
            return
        for p in packets:
            try:
                self.handle_packet(p, addr)
            except Exception:
                self.log.exception("error while handling %s from %s:%s", p.describe(), *addr)

    # -- packets -------------------------------------------------------------------------------

    def check_signature(self, conn: Connection, p: Packet) -> None:
        if p.type == SYN:
            expected = self.signer.sign(p.header8, b"", b"", p.options_raw, p.payload)
        elif p.type == CONNECT:
            expected = self.signer.sign(p.header8, b"", conn.server_signature, p.options_raw, p.payload)
        else:
            expected = self.signer.sign(p.header8, conn.session_key, conn.server_signature, p.options_raw,
                                        p.payload)
        if expected != p.signature:
            self.log.debug("%s: signature mismatch on %s", conn, p.describe())

    def handle_packet(self, p: Packet, addr) -> None:
        conn = self.connections.get(addr)
        if p.type == SYN and not p.has(FLAG_ACK):
            self.handle_syn(p, addr, conn)
            return
        if conn is None:
            self.log.debug("packet from unknown %s:%s: %s", addr[0], addr[1], p.describe())
            return
        conn.last_seen = time.monotonic()
        self.check_signature(conn, p)
        self.log.debug("%s -> %s", conn, p.describe())

        if p.has(FLAG_ACK) or p.has(FLAG_MULTI_ACK):
            self.handle_ack(conn, p)
            return
        if p.type == CONNECT:
            self.handle_connect(conn, p)
            return
        if conn.state != "connected":
            return
        if p.has(FLAG_NEED_ACK):
            conn.send_ack(p)
        if p.type == DISCONNECT:
            for _ in range(2):
                conn.send_ack(p)
            self.drop(conn, "client disconnected")
            return
        if p.has(FLAG_RELIABLE):
            self.handle_reliable(conn, p)
        elif p.type == DATA and p.payload:
            self.log.debug("%s: unreliable DATA ignored", conn)

    def handle_syn(self, p: Packet, addr, conn: Connection | None) -> None:
        if conn is not None and conn.state == "connected":
            self.drop(conn, "new connection from the same address")
            conn = None
        client_minor = (p.supported_functions or 0) & 0xFF
        if conn is None:
            conn = Connection(server=self, addr=addr, client_port=p.src, server_port=p.dst,
                              server_signature=self.signer.connection_signature(addr))
            self.connections[addr] = conn
        conn.minor_version = min(client_minor, SERVER_MINOR_VERSION)
        conn.supported_functions = conn.minor_version          # no optional functions
        conn.max_substream_id = 0
        ack = Packet(src=p.dst, dst=p.src, type=SYN, flags=FLAG_ACK, session_id=0, seq=p.seq,
                     supported_functions=conn.supported_functions, conn_sig=conn.server_signature,
                     max_substream_id=conn.max_substream_id)
        self.send_raw(encode_packet(ack, self.signer, b"", b""), addr)
        self.log.info("%s:%s SYN (PRUDP v1, minor %d)", addr[0], addr[1], client_minor)

    def handle_connect(self, conn: Connection, p: Packet) -> None:
        if conn.connect_ack is not None:          # our CONNECT-ACK was lost: send it again
            self.send_raw(conn.connect_ack, conn.addr)
            return
        conn.client_signature = p.conn_sig or bytes(16)
        conn.client_session = p.session_id
        conn.server_session = (os.urandom(1)[0] % 0xFF) + 1
        conn.in_next = (p.seq + 1) & 0xFFFF
        try:
            response = self.on_connect(conn, p.payload)
        except Exception:
            self.log.exception("%s: CONNECT refused", conn)
            response = None
        if response is None:
            self.drop(conn, "connection refused")
            return
        ack = Packet(src=conn.server_port, dst=conn.client_port, type=CONNECT, flags=FLAG_ACK,
                     session_id=conn.server_session, seq=p.seq,
                     supported_functions=p.supported_functions if p.supported_functions is not None
                     else conn.supported_functions,
                     conn_sig=bytes(16), max_substream_id=conn.max_substream_id, payload=response)
        # Minor version >= 2: the client checks this signature with its own connection signature.
        conn_sig = conn.client_signature if conn.minor_version >= 2 else b""
        conn.connect_ack = encode_packet(ack, self.signer, b"", conn_sig)
        conn.state = "connected"
        self.send_raw(conn.connect_ack, conn.addr)
        self.log.info("%s connected", conn)

    def handle_ack(self, conn: Connection, p: Packet) -> None:
        """Single ACK (flag ACK), or aggregate ACK: a DATA packet with flag MULTI_ACK (no ACK flag) and
        substream id 1, whose payload is u8 substream, u8 count, u16 last sequence id acknowledged
        with all those before it, then count more u16 ids (PRUDPEndPoint::SendAggregateACKNew)."""
        if p.type != DATA:
            return
        if p.has(FLAG_MULTI_ACK):
            if conn.minor_version >= 2 and len(p.payload) >= 4:
                _sub, count, base = struct.unpack_from("<BBH", p.payload)
                extra = struct.unpack_from(f"<{count}H", p.payload, 4) if len(p.payload) >= 4 + 2 * count else ()
            else:
                base = p.seq
                extra = struct.unpack_from(f"<{len(p.payload) // 2}H", p.payload)
            acked = [s for s in conn.unacked if not seq_lt(base, s)]
            conn.acknowledge(acked + list(extra))
            self.log.debug("%s: aggregate ACK up to %d %s", conn, base, list(extra) or "")
        else:
            conn.acknowledge([p.seq])

    def handle_reliable(self, conn: Connection, p: Packet) -> None:
        if seq_lt(p.seq, conn.in_next):
            return                                  # duplicate, already acknowledged again
        conn.in_buffer[p.seq] = p
        while conn.in_next in conn.in_buffer:
            q = conn.in_buffer.pop(conn.in_next)
            conn.in_next = (conn.in_next + 1) & 0xFFFF
            if q.type != DATA:
                continue
            conn.fragments.append(conn.rc4_in.crypt(q.payload))
            if not q.fragment_id:
                payload = b"".join(conn.fragments)
                conn.fragments = []
                try:
                    self.on_data(conn, payload)
                except Exception:
                    self.log.exception("%s: error while processing a message", conn)
