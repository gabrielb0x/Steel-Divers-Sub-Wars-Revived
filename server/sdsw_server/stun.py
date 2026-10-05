"""STUN (RFC 5389) binding request: the address and port under which the internet sees a UDP socket.

Used when the router does not tell its public address (no UPnP), and to notice a second NAT in front of it
(an operator's "carrier-grade NAT"), which no forward on the router can get through.
Standard library only, blocking.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
import time

MAGIC = 0x2112A442
BINDING_REQUEST, BINDING_SUCCESS = 0x0001, 0x0101
MAPPED_ADDRESS, XOR_MAPPED_ADDRESS = 0x0001, 0x0020
SERVERS = ("stun.l.google.com:19302", "stun.cloudflare.com:3478")


def request(transaction: bytes) -> bytes:
    return struct.pack(">HHI", BINDING_REQUEST, 0, MAGIC) + transaction


def parse_response(data: bytes, transaction: bytes) -> tuple[str, int] | None:
    if len(data) < 20:
        return None
    kind, length, magic = struct.unpack_from(">HHI", data)
    if kind != BINDING_SUCCESS or magic != MAGIC or data[8:20] != transaction:
        return None
    found = None
    pos, end = 20, min(len(data), 20 + length)
    while pos + 4 <= end:
        attr, size = struct.unpack_from(">HH", data, pos)
        value = data[pos + 4:pos + 4 + size]
        pos += 4 + (size + 3) // 4 * 4
        if attr not in (MAPPED_ADDRESS, XOR_MAPPED_ADDRESS) or len(value) < 8 or value[1] != 1:   # IPv4 only
            continue
        port, address = struct.unpack_from(">HI", value, 2)
        if attr == XOR_MAPPED_ADDRESS:
            port ^= MAGIC >> 16
            address ^= MAGIC
            found = (str(ipaddress.IPv4Address(address)), port)
        elif found is None:
            found = (str(ipaddress.IPv4Address(address)), port)
    return found


def public_address(servers=SERVERS, timeout: float = 2.0) -> tuple[str, int] | None:
    """Asks the STUN servers in turn; None when none answers."""
    for server in servers:
        host, _, port = server.rpartition(":")
        try:
            target = (socket.gethostbyname(host), int(port))
        except (OSError, ValueError):
            continue
        transaction = os.urandom(12)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(2):                          # one resend: UDP
                try:
                    s.sendto(request(transaction), target)
                except OSError:
                    break
                until = time.monotonic() + timeout / 2
                while (left := until - time.monotonic()) > 0:
                    s.settimeout(left)
                    try:
                        data, addr = s.recvfrom(2048)
                    except (TimeoutError, socket.timeout, OSError):
                        break
                    if addr == target and (found := parse_response(data, transaction)):
                        return found
    return None
