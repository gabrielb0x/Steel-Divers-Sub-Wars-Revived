"""RMC (remote method calls) over PRUDP DATA payloads.

  request   u32 size, u8 protocol | 0x80, u32 call id, u32 method id, parameters
  response  u32 size, u8 protocol, u8 1, u32 call id, u32 method id | 0x8000, results
  error     u32 size, u8 protocol, u8 0, u32 result code, u32 call id

The server also calls methods on the clients (notifications, NAT traversal probes): same format, the
client answers with a response (method id | 0x8000) that only needs to be read.
"""

from __future__ import annotations

import logging
import struct
from typing import Callable

from .prudp import Connection
from .streams import StreamIn, StreamOut

log = logging.getLogger("rmc")

# NEX result codes used here (nn::nex::QResult values seen in the client)
SUCCESS = 0x00010001
CORE_NOT_IMPLEMENTED = 0x80010002
CORE_INVALID_ARGUMENT = 0x8001000A
RV_INVALID_USERNAME = 0x80030064
RV_INVALID_PASSWORD = 0x80030065
RV_ACCOUNT_DISABLED = 0x80030067
RV_INVALID_PID = 0x8003006B
RV_INVALID_GID = 0x8003006D
RV_SESSION_VOID = 0x80030073
RV_SESSION_FULL = 0x800300C8
RV_NOT_PARTICIPATED = 0x800300D4

PROTOCOL_NAMES = {3: "NATTraversal", 10: "TicketGranting", 11: "SecureConnection", 14: "Notification",
                  21: "MatchMaking", 50: "MatchMakingExt", 100: "NintendoNotification",
                  109: "MatchmakeExtension"}


class RMCError(Exception):
    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"{code:#010x} {message}")
        self.code = code


Handler = Callable[[Connection, StreamIn], StreamOut | None]


def frame(body: bytes) -> bytes:
    return struct.pack("<I", len(body)) + body


class RMCDispatcher:
    """Routes the RMC requests of one PRUDP server to registered handlers."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.handlers: dict[tuple[int, int], tuple[str, Handler]] = {}
        self.log = logging.getLogger(name)

    def register(self, protocol: int, method: int, name: str, handler: Handler) -> None:
        self.handlers[(protocol, method)] = (name, handler)

    def call_name(self, protocol: int, method: int) -> str:
        if (protocol, method) in self.handlers:
            return self.handlers[(protocol, method)][0]
        return f"{PROTOCOL_NAMES.get(protocol, protocol)}#{method}"

    def handle_payload(self, conn: Connection, payload: bytes) -> None:
        pos = 0
        while pos + 4 <= len(payload):
            size = struct.unpack_from("<I", payload, pos)[0]
            message = payload[pos + 4:pos + 4 + size]
            pos += 4 + size
            if len(message) != size:
                self.log.warning("%s: truncated RMC message: %s", conn, payload.hex())
                return
            self.handle_message(conn, message)

    def handle_message(self, conn: Connection, message: bytes) -> None:
        stream = StreamIn(message)
        proto = stream.u8()
        is_request = bool(proto & 0x80)
        proto &= 0x7F
        if proto == 0x7F:
            proto = stream.u16()
        if not is_request:
            self.handle_client_response(conn, proto, stream)
            return
        call_id = stream.u32()
        method = stream.u32()
        name = self.call_name(proto, method)
        entry = self.handlers.get((proto, method))
        if entry is None:
            self.log.warning("%s: %s not implemented, params %s", conn, name, message[9:].hex())
            self.send_error(conn, proto, call_id, CORE_NOT_IMPLEMENTED)
            return
        try:
            out = entry[1](conn, stream) or StreamOut()
        except RMCError as e:
            self.log.info("%s: %s -> error %#010x", conn, name, e.code)
            self.send_error(conn, proto, call_id, e.code)
            return
        except Exception:
            self.log.exception("%s: %s failed, params %s", conn, name, message[9:].hex())
            self.send_error(conn, proto, call_id, CORE_INVALID_ARGUMENT)
            return
        if not stream.eof():
            self.log.debug("%s: %s left %d bytes unread", conn, name, stream.remaining())
        body = struct.pack("<BBII", proto, 1, call_id, method | 0x8000) + out.get()
        conn.send_data(frame(body))

    def send_error(self, conn: Connection, proto: int, call_id: int, code: int) -> None:
        conn.send_data(frame(struct.pack("<BBII", proto, 0, code, call_id)))

    # -- calls from the server to a client -------------------------------------------------------

    def call_client(self, conn: Connection, proto: int, method: int, params: StreamOut) -> None:
        call_id = conn.data.get("next_call_id", 1)
        conn.data["next_call_id"] = (call_id + 1) & 0xFFFFFFFF or 1
        body = struct.pack("<BII", proto | 0x80, call_id, method) + params.get()
        self.log.debug("%s: calling %s on the client", conn, self.call_name(proto, method))
        conn.send_data(frame(body))

    def handle_client_response(self, conn: Connection, proto: int, stream: StreamIn) -> None:
        ok = stream.u8()
        if ok:
            call_id, method = stream.u32(), stream.u32()
            self.log.debug("%s: client answered call %d (%s)", conn, call_id,
                           self.call_name(proto, method & 0x7FFF))
        else:
            code, call_id = stream.u32(), stream.u32()
            self.log.info("%s: client returned error %#010x for call %d", conn, code, call_id)
