"""Reading a decrypted NCCH (the game's CXI) with the standard library only: header, ExeFS, compressed .code,
RomFS. Players' tools use it, so that they only need Python. Layouts follow 3dbrew:
  https://www.3dbrew.org/wiki/NCCH  https://www.3dbrew.org/wiki/ExeFS  https://www.3dbrew.org/wiki/RomFS
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Iterator

MEDIA_UNIT = 0x200
NO_CRYPTO = 0x04                     # NCCH flags[7]


class NCCHError(Exception):
    pass


@dataclass
class Region:
    offset: int                       # bytes, from the start of the NCCH
    size: int


class NCCH:
    """A NCCH inside a file, at a given offset (content 0 of a CIA, or a .cxi)."""

    def __init__(self, fp: BinaryIO, base: int = 0) -> None:
        self.fp, self.base = fp, base
        fp.seek(base)
        header = fp.read(0x200)
        if header[0x100:0x104] != b"NCCH":
            raise NCCHError("not a NCCH (decrypted CXI expected)")
        self.header = header
        self.program_id, = struct.unpack_from("<Q", header, 0x118)
        self.product_code = header[0x150:0x160].rstrip(b"\0").decode("ascii", "replace")
        self.flags = header[0x188:0x190]
        unit = MEDIA_UNIT << self.flags[6]
        self.exheader_size, = struct.unpack_from("<I", header, 0x180)

        def region(at: int) -> Region | None:
            offset, size = struct.unpack_from("<II", header, at)
            return Region(offset * unit, size * unit) if size else None
        self.plain = region(0x190)
        self.logo = region(0x198)
        self.exefs = region(0x1A0)
        self.romfs = region(0x1B0)

    @property
    def encrypted(self) -> bool:
        return not self.flags[7] & NO_CRYPTO

    def read(self, offset: int, size: int) -> bytes:
        self.fp.seek(self.base + offset)
        data = self.fp.read(size)
        if len(data) != size:
            raise NCCHError("truncated NCCH")
        return data

    def exheader(self) -> bytes:
        """Extended header and access descriptor (0x800 bytes), right after the NCCH header."""
        return self.read(0x200, 0x800) if self.exheader_size else b""

    def exefs_files(self) -> dict[str, bytes]:
        if self.exefs is None:
            return {}
        table = self.read(self.exefs.offset, 0x200)
        files = {}
        for n in range(10):
            name, offset, size = struct.unpack_from("<8sII", table, n * 16)
            name = name.rstrip(b"\0").decode("ascii")
            if name:
                files[name] = self.read(self.exefs.offset + 0x200 + offset, size)
        return files

    def romfs_files(self) -> Iterator[tuple[str, int, int]]:
        """(path, offset from the NCCH start, size) of each RomFS file (IVFC level 3)."""
        if self.romfs is None:
            return
        ivfc = self.read(self.romfs.offset, 0x5C)
        if ivfc[:4] != b"IVFC":
            raise NCCHError("RomFS without its IVFC header")
        master_hash_size, = struct.unpack_from("<I", ivfc, 0x8)
        level3_block = 1 << struct.unpack_from("<I", ivfc, 0x4C)[0]
        level3 = self.romfs.offset + align(0x60 + master_hash_size, level3_block)
        header = self.read(level3, 0x28)
        (_, _, _, dir_meta_off, dir_meta_size, _, _,
         file_meta_off, file_meta_size, data_off) = struct.unpack("<10I", header)
        dirs = self.read(level3 + dir_meta_off, dir_meta_size)
        files = self.read(level3 + file_meta_off, file_meta_size)

        def name(table: bytes, at: int) -> str:
            length, = struct.unpack_from("<I", table, at)
            return table[at + 4:at + 4 + length].decode("utf-16-le")

        stack = [(0, "")]                                  # the root directory, at offset 0
        while stack:
            entry, path = stack.pop()
            _, _, child, file, _ = struct.unpack_from("<5I", dirs, entry)
            while file != 0xFFFFFFFF:
                _, sibling, offset, size, _ = struct.unpack_from("<IIQQI", files, file)
                yield f"{path}/{name(files, file + 0x1C)}".lstrip("/"), level3 + data_off + offset, size
                file = sibling
            while child != 0xFFFFFFFF:
                stack.append((child, f"{path}/{name(dirs, child + 0x14)}"))
                child, = struct.unpack_from("<I", dirs, child + 4)


def align(x: int, a: int) -> int:
    return (x + a - 1) & ~(a - 1)


def decompress_code(data: bytes) -> bytes:
    """The ExeFS .code compression ("backwards LZ77"): read from the end, written from the end.
    Footer: u32 (bits 0-23: compressed size, 24-31: header size), u32 size increase."""
    top, increase = struct.unpack_from("<II", data, len(data) - 8)
    out = bytearray(data) + bytearray(increase)
    src = len(data) - (top >> 24)
    stop = len(data) - (top & 0xFFFFFF)
    dst = len(out)
    while src > stop:
        src -= 1
        flags = data[src]
        for _ in range(8):
            if src <= stop:
                break
            if flags & 0x80:
                src -= 2
                pair = data[src] | data[src + 1] << 8
                length = (pair >> 12) + 3
                distance = (pair & 0xFFF) + 3
                for _ in range(length):
                    dst -= 1
                    out[dst] = out[dst + distance]
            else:
                src -= 1
                dst -= 1
                out[dst] = data[src]
            flags = flags << 1 & 0xFF
    return bytes(out)
