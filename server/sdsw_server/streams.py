"""NEX serialization, as the game's NEX 3.7 library writes and reads it (little endian).

Verified in the executable:
  String      u16 byte count (UTF-8 + terminating NUL), UTF-8 bytes, NUL  (ByteStream::AppendString)
  Buffer      u32 size + bytes; qBuffer: u16 size + bytes
  List<T>     u32 count + items
  StationURL  a String ("prudp:/address=...;port=...")
  Structure   u8 version + u32 content size, then the fields: every DDL class of the hierarchy
              writes its own header (_DDL_Gathering::Add, then _DDL_MatchmakeSession::Add)
  AnyDataHolder (Gathering adapter): String class name, u32 size + 4, u32 size, object
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field


class StreamError(Exception):
    pass


class StreamOut:
    def __init__(self) -> None:
        self.data = bytearray()

    def get(self) -> bytes:
        return bytes(self.data)

    def write(self, data: bytes) -> None:
        self.data += data

    def u8(self, v: int) -> None: self.data += struct.pack("<B", v & 0xFF)
    def u16(self, v: int) -> None: self.data += struct.pack("<H", v & 0xFFFF)
    def u32(self, v: int) -> None: self.data += struct.pack("<I", v & 0xFFFFFFFF)
    def u64(self, v: int) -> None: self.data += struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)
    def s32(self, v: int) -> None: self.data += struct.pack("<i", v)
    def bool(self, v: bool) -> None: self.u8(1 if v else 0)
    def pid(self, v: int) -> None: self.u32(v)          # PIDs are 32-bit on the 3DS
    def result(self, v: int) -> None: self.u32(v)

    def string(self, s: str) -> None:
        raw = s.encode("utf-8") + b"\0"
        self.u16(len(raw))
        self.data += raw

    def buffer(self, b: bytes) -> None:
        self.u32(len(b))
        self.data += b

    def qbuffer(self, b: bytes) -> None:
        self.u16(len(b))
        self.data += b

    def list(self, items, writer) -> None:
        items = list(items)
        self.u32(len(items))
        for item in items:
            writer(self, item)

    def url(self, url: "StationURL | str") -> None:
        self.string(str(url))

    def datetime(self, v: int) -> None:
        self.u64(v)

    def structure(self, obj) -> None:
        """Writes obj (with a NEX structure hierarchy: obj.encode_parts() -> [(version, writer)])."""
        for version, writer in obj.encode_parts():
            sub = StreamOut()
            writer(sub)
            self.u8(version)
            self.u32(len(sub.data))
            self.data += sub.data

    def anydata(self, name: str, obj) -> None:
        sub = StreamOut()
        sub.structure(obj)
        self.string(name)
        self.u32(len(sub.data) + 4)
        self.u32(len(sub.data))
        self.data += sub.data


class StreamIn:
    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise StreamError(f"read past end ({n} bytes at {self.pos}, size {len(self.data)})")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int: return self.read(1)[0]
    def u16(self) -> int: return struct.unpack("<H", self.read(2))[0]
    def u32(self) -> int: return struct.unpack("<I", self.read(4))[0]
    def u64(self) -> int: return struct.unpack("<Q", self.read(8))[0]
    def s32(self) -> int: return struct.unpack("<i", self.read(4))[0]
    def bool(self) -> bool: return self.u8() != 0
    def pid(self) -> int: return self.u32()

    def string(self) -> str:
        n = self.u16()
        raw = self.read(n)
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")

    def buffer(self) -> bytes:
        return self.read(self.u32())

    def qbuffer(self) -> bytes:
        return self.read(self.u16())

    def list(self, reader) -> list:
        return [reader(self) for _ in range(self.u32())]

    def url(self) -> "StationURL":
        return StationURL.parse(self.string())

    def datetime(self) -> int:
        return self.u64()

    def structure_header(self) -> tuple[int, "StreamIn"]:
        """Reads one structure header and returns (version, substream of its content)."""
        version = self.u8()
        size = self.u32()
        return version, StreamIn(self.read(size))

    def anydata(self) -> tuple[str, "StreamIn"]:
        name = self.string()
        self.u32()                       # size + 4
        return name, StreamIn(self.buffer())


# ---- NEX DateTime --------------------------------------------------------------------------

def datetime_now() -> int:
    t = time.gmtime()
    return make_datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def make_datetime(year: int, month: int, day: int, hour: int, minute: int, second: int) -> int:
    return second | (minute << 6) | (hour << 12) | (day << 17) | (month << 22) | (year << 26)


# ---- Station URL ---------------------------------------------------------------------------

@dataclass
class StationURL:
    """prudp:/address=1.2.3.4;port=60000;... (keys are kept in insertion order)."""
    scheme: str = "prudp"
    fields: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "StationURL":
        if not text:
            return cls("", {})
        scheme, _, rest = text.partition(":/")
        fields = {}
        for part in rest.split(";"):
            if "=" in part:
                k, _, v = part.partition("=")
                fields[k] = v
        return cls(scheme, fields)

    def __str__(self) -> str:
        if not self.scheme:
            return ""
        return f"{self.scheme}:/" + ";".join(f"{k}={v}" for k, v in self.fields.items())

    def copy(self) -> "StationURL":
        return StationURL(self.scheme, dict(self.fields))

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.fields.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.fields.get(key, default))
        except ValueError:
            return default

    def __setitem__(self, key: str, value) -> None:
        self.fields[key] = str(value)

    def __getitem__(self, key: str) -> str:
        return self.fields[key]
