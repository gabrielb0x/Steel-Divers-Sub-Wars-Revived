#!/usr/bin/env python3
"""Wrap the decompressed code.bin into an ARM ELF so any disassembler loads it
with the right addresses and permissions (Ghidra, IDA, objdump, ...).

Segments come from the exheader: .text (RX), .rodata (R), .data (RW) and a
NOBITS .bss (RW) that follows .data. The entry point is the start of .text.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from ctr import PAGE_SIZE, ExHeader

ROOT = Path(__file__).resolve().parent.parent

EM_ARM = 40
PT_LOAD = 1
PF_X, PF_W, PF_R = 1, 2, 4
SHT_PROGBITS, SHT_STRTAB, SHT_NOBITS = 1, 3, 8
SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 1, 2, 4
EF_ARM_EABI_VER5 = 0x05000000


def align(x: int, a: int) -> int:
    return (x + a - 1) & ~(a - 1)


def build_elf(code: bytes, exh: ExHeader) -> bytes:
    layout = {name: (addr, off, size) for name, addr, off, size in exh.segment_layout()}
    bss_addr = exh.bss_address
    bss_size = align(bss_addr + exh.bss_size, PAGE_SIZE) - bss_addr

    sections = [
        # name, section type, section flags, address, segment flags
        (".text", SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, *layout["text"][:1], PF_R | PF_X),
        (".rodata", SHT_PROGBITS, SHF_ALLOC, *layout["rodata"][:1], PF_R),
        (".data", SHT_PROGBITS, SHF_ALLOC | SHF_WRITE, *layout["data"][:1], PF_R | PF_W),
    ]
    payloads = [code[off:off + size] for _addr, off, size in (layout["text"], layout["rodata"], layout["data"])]

    ehsize, phentsize, shentsize = 52, 32, 40
    nseg = len(sections) + 1  # + bss
    shstrtab = b"\0" + b"\0".join(s[0].encode() for s in sections) + b"\0.bss\0.shstrtab\0"

    # File layout: ELF header, program headers, segment payloads (page aligned), shstrtab, section headers.
    offset = align(ehsize + phentsize * nseg, PAGE_SIZE)
    file_offsets = []
    for payload in payloads:
        file_offsets.append(offset)
        offset = align(offset + len(payload), PAGE_SIZE)
    shstr_off = offset
    sh_off = align(shstr_off + len(shstrtab), 4)
    nsec = 1 + len(sections) + 2  # null, progbits..., .bss, .shstrtab

    out = bytearray(sh_off + shentsize * nsec)
    e_ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + bytes(8)  # ELFCLASS32, little endian, SYSV
    struct.pack_into("<16sHHIIIIIHHHHHH", out, 0, e_ident, 2, EM_ARM, 1, exh.text.address, ehsize, sh_off,
                     EF_ARM_EABI_VER5, ehsize, phentsize, nseg, shentsize, nsec, nsec - 1)

    ph = ehsize
    for (_name, _t, _f, addr, pflags), payload, foff in zip(sections, payloads, file_offsets):
        struct.pack_into("<IIIIIIII", out, ph, PT_LOAD, foff, addr, addr, len(payload), len(payload), pflags, PAGE_SIZE)
        out[foff:foff + len(payload)] = payload
        ph += phentsize
    struct.pack_into("<IIIIIIII", out, ph, PT_LOAD, 0, bss_addr, bss_addr, 0, bss_size, PF_R | PF_W, 4)

    out[shstr_off:shstr_off + len(shstrtab)] = shstrtab
    name_off = 1
    sh = sh_off + shentsize  # index 0 is the null section
    for (name, stype, sflags, addr, _p), payload, foff in zip(sections, payloads, file_offsets):
        struct.pack_into("<IIIIIIIIII", out, sh, name_off, stype, sflags, addr, foff, len(payload), 0, 0, 4, 0)
        name_off += len(name) + 1
        sh += shentsize
    struct.pack_into("<IIIIIIIIII", out, sh, name_off, SHT_NOBITS, SHF_ALLOC | SHF_WRITE, bss_addr, shstr_off,
                     bss_size, 0, 0, 8, 0)
    name_off += len(".bss") + 1
    sh += shentsize
    struct.pack_into("<IIIIIIIIII", out, sh, name_off, SHT_STRTAB, 0, 0, shstr_off, len(shstrtab), 0, 0, 1, 0)
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", type=Path, default=ROOT / "extracted" / "code.bin")
    ap.add_argument("--exheader", type=Path, default=ROOT / "extracted" / "ncch" / "exheader.bin")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "extracted" / "nsub.elf")
    args = ap.parse_args()

    exh = ExHeader.parse(args.exheader.read_bytes())
    elf = build_elf(args.code.read_bytes(), exh)
    args.out.write_bytes(elf)
    print(f"[+] Wrote {args.out} ({len(elf):#x} bytes), entry {exh.text.address:#010x}")


if __name__ == "__main__":
    main()
