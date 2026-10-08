"""Minimal parsers for the 3DS (CTR) container formats used by this project.

Only what the tooling needs is implemented. Field layouts follow 3dbrew:
  https://www.3dbrew.org/wiki/CIA
  https://www.3dbrew.org/wiki/Title_metadata
  https://www.3dbrew.org/wiki/NCCH/Extended_Header
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

PAGE_SIZE = 0x1000
GAME_TITLE_ID = 0x00040000000D7E00     # Steel Diver: Sub Wars, Europe (the version this project targets)
UPDATE_TITLE_ID = 0x0004000E000D7E00   # its update (title version 5200, tools/versions.py)

# Size of signature + padding for each signature type (Ticket/TMD/certificates).
_SIG_SIZES = {
    0x010000: 0x200 + 0x3C,  # RSA-4096 SHA-1
    0x010001: 0x100 + 0x3C,  # RSA-2048 SHA-1
    0x010002: 0x3C + 0x40,   # ECDSA SHA-1
    0x010003: 0x200 + 0x3C,  # RSA-4096 SHA-256
    0x010004: 0x100 + 0x3C,  # RSA-2048 SHA-256
    0x010005: 0x3C + 0x40,   # ECDSA SHA-256
}


def _align(x: int, a: int) -> int:
    return (x + a - 1) & ~(a - 1)


def _sig_body(blob: bytes) -> bytes:
    sig_type = struct.unpack_from(">I", blob, 0)[0]
    return blob[4 + _SIG_SIZES[sig_type]:]


@dataclass
class ContentChunk:
    id: int
    index: int
    type: int
    size: int
    sha256: bytes

    @property
    def encrypted(self) -> bool:
        return bool(self.type & 1)


@dataclass
class CIA:
    header_size: int
    cert_offset: int
    cert_size: int
    ticket_offset: int
    ticket_size: int
    tmd_offset: int
    tmd_size: int
    content_offset: int
    content_size: int
    meta_offset: int
    meta_size: int
    title_id: int = 0
    title_version: int = 0
    contents: list[ContentChunk] = field(default_factory=list)

    @classmethod
    def parse(cls, fp) -> "CIA":
        fp.seek(0)
        hdr = fp.read(0x20)
        hsize, _type, _ver, csize, tsize, tmdsize, msize, consize = struct.unpack("<IHHIIIIQ", hdr)
        cert_off = _align(hsize, 64)
        tik_off = _align(cert_off + csize, 64)
        tmd_off = _align(tik_off + tsize, 64)
        con_off = _align(tmd_off + tmdsize, 64)
        meta_off = _align(con_off + consize, 64)
        cia = cls(hsize, cert_off, csize, tik_off, tsize, tmd_off, tmdsize, con_off, consize, meta_off, msize)

        fp.seek(tmd_off)
        tmd = _sig_body(fp.read(tmdsize))
        cia.title_id = struct.unpack_from(">Q", tmd, 0x4C)[0]
        cia.title_version = struct.unpack_from(">H", tmd, 0x9C)[0]
        count = struct.unpack_from(">H", tmd, 0x9E)[0]
        chunk_base = 0xC4 + 64 * 0x24
        for i in range(count):
            off = chunk_base + i * 0x30
            cid, cidx, ctype, size = struct.unpack_from(">IHHQ", tmd, off)
            cia.contents.append(ContentChunk(cid, cidx, ctype, size, tmd[off + 0x10:off + 0x30]))
        return cia

    def content_offsets(self):
        """Yield (chunk, absolute offset) for each content, in TMD order."""
        off = self.content_offset
        for chunk in self.contents:
            yield chunk, off
            off += _align(chunk.size, 64)


@dataclass
class CodeSegment:
    address: int
    num_pages: int
    size: int


@dataclass
class ExHeader:
    title: str
    flags: int
    remaster_version: int
    text: CodeSegment
    stack_size: int
    rodata: CodeSegment
    data: CodeSegment
    bss_size: int
    dependencies: list[int]
    save_data_size: int
    jump_id: int
    program_id: int
    core_version: int
    priority: int
    resource_limit_category: int
    extdata_id: int
    system_save_ids: int
    storage_unique_ids: int
    fs_access: int
    services: list[str]
    kernel_caps: list[int]

    @property
    def code_compressed(self) -> bool:
        return bool(self.flags & 1)

    @property
    def sd_application(self) -> bool:
        return bool(self.flags & 2)

    @classmethod
    def parse(cls, data: bytes) -> "ExHeader":
        def seg(off: int) -> CodeSegment:
            return CodeSegment(*struct.unpack_from("<III", data, off))

        deps = [d for d in struct.unpack_from("<48Q", data, 0x40) if d]
        save_size, jump_id = struct.unpack_from("<QQ", data, 0x1C0)

        aci = 0x200
        program_id, core_version = struct.unpack_from("<QI", data, aci)
        priority = data[aci + 0xF]
        extdata_id, sys_save, unique_ids = struct.unpack_from("<QQQ", data, aci + 0x30)
        fs_access = int.from_bytes(data[aci + 0x48:aci + 0x4F], "little")
        services = []
        for i in range(34):  # 32 regular + 2 extended slots
            raw = data[aci + 0x50 + i * 8:aci + 0x58 + i * 8].rstrip(b"\0")
            if raw:
                services.append(raw.decode("ascii"))
        kernel_caps = [c for c in struct.unpack_from("<28I", data, aci + 0x170) if c != 0xFFFFFFFF]

        return cls(
            title=data[0:8].rstrip(b"\0").decode("ascii"),
            flags=data[0xD],
            remaster_version=struct.unpack_from("<H", data, 0xE)[0],
            text=seg(0x10),
            stack_size=struct.unpack_from("<I", data, 0x1C)[0],
            rodata=seg(0x20),
            data=seg(0x30),
            bss_size=struct.unpack_from("<I", data, 0x3C)[0],
            dependencies=deps,
            save_data_size=save_size,
            jump_id=jump_id,
            program_id=program_id,
            core_version=core_version,
            priority=priority,
            resource_limit_category=data[aci + 0x16F],
            extdata_id=extdata_id,
            system_save_ids=sys_save,
            storage_unique_ids=unique_ids,
            fs_access=fs_access,
            services=services,
            kernel_caps=kernel_caps,
        )

    def segment_layout(self):
        """Yield (name, vaddr, file offset in code.bin, size) for the loaded segments.

        In the decompressed .code, each segment starts on a page boundary, in the
        order text, rodata, data. BSS directly follows data in memory.
        """
        off = 0
        for name, s in (("text", self.text), ("rodata", self.rodata), ("data", self.data)):
            yield name, s.address, off, s.size
            off += s.num_pages * PAGE_SIZE

    @property
    def bss_address(self) -> int:
        return self.data.address + self.data.size


def tmd_title_version(tmd: bytes) -> int:
    """Title version of a TMD (signature included), e.g. 5200 for the game's update."""
    return struct.unpack_from(">H", _sig_body(tmd), 0x9C)[0]


def title_id_of(path) -> int | None:
    """Title id of a CIA (from its TMD), or None if the file is not a readable CIA."""
    try:
        with open(path, "rb") as f:
            return CIA.parse(f).title_id
    except (OSError, struct.error, KeyError, ValueError):
        return None


def program_encrypted(path) -> bool:
    """Whether the program of a game file is still encrypted: content 0 of a CIA under the title key, or its NCCH
    (content 0 of a CIA, partition 0 of a .3ds/.cci, a .cxi) without the NoCrypto flag (flags[7] bit 2)."""
    from pathlib import Path
    path = Path(path)
    with path.open("rb") as f:
        offset = 0
        if path.suffix.lower() == ".cia":
            chunk, offset = next(CIA.parse(f).content_offsets())
            if chunk.encrypted:
                return True
        else:
            f.seek(0x100)
            if f.read(4) == b"NCSD":
                f.seek(0x120)
                offset = struct.unpack("<I", f.read(4))[0] * 0x200
        f.seek(offset + 0x100)
        if f.read(4) != b"NCCH":
            raise ValueError(f"{path.name}: not a game file (no NCCH)")
        f.seek(offset + 0x18F)
        return not f.read(1)[0] & 0x04


def find_game_cia(folder, title_id: int = GAME_TITLE_ID):
    """The CIA of the game in a folder, chosen by title id: the folder may also hold the add-on content
    (0004008C...), an update or other regions, in any alphabetical order."""
    from pathlib import Path
    found = [path for path in sorted(Path(folder).glob("*.cia")) if title_id_of(path) == title_id]
    for path in found:                  # a decrypted copy first (the encrypted one may still lie next to it)
        try:
            if not program_encrypted(path):
                return path
        except (OSError, ValueError, struct.error, KeyError, StopIteration):
            continue
    return found[0] if found else None
