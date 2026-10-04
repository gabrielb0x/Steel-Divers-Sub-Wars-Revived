#!/usr/bin/env python3
"""BXML (the game's binary XML, source/sys/binxml.cpp) to XML converter.

Layout (little endian, offsets from the start of the file):
  header     "BXML" magic (LMXB on disk), u32 version (1), u32 root node offset
  node       u32 parent, u32 next sibling, u32 first child, u32 attribute count, u32 attributes offset
  attribute  u32 type, u32 name hash (generateCRC), u32 name offset, u32 name length,
             u32 data offset, u32 data size
The first attribute of a node is its name (BXML::Node::getName). Attribute
types (BXML::Attribute::set*Data): 1 name, 2 bytes, 3 string, 4 s16[], 5 s32[], 7 f32[].
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr, escape

ROOT = Path(__file__).resolve().parent.parent
MAGIC = b"LMXB"

TYPE_NAME, TYPE_BYTES, TYPE_STRING, TYPE_SHORTS, TYPE_INTS, TYPE_FLOATS = 1, 2, 3, 4, 5, 7


def _float(value: float) -> str:
    raw = struct.pack("<f", value)
    for decimals in range(0, 9):
        text = f"{value:.{decimals}f}"
        if struct.pack("<f", float(text)) == raw:
            return text
    return repr(value)


class Bxml:
    def __init__(self, data: bytes):
        if data[:4] != MAGIC:
            raise ValueError("not a BXML file")
        self.data = data
        self.version, self.root = struct.unpack_from("<II", data, 4)

    def node(self, offset: int) -> tuple[int, int, int, int, int]:
        return struct.unpack_from("<5I", self.data, offset)

    def attributes(self, node_offset: int) -> list[tuple[int, str, bytes]]:
        _, _, _, count, table = self.node(node_offset)
        attrs = []
        for n in range(count):
            kind, _hash, name_off, _name_len, data_off, size = struct.unpack_from("<6I", self.data, table + 24 * n)
            name = self.data[name_off:self.data.index(b"\0", name_off)].decode("latin-1") if name_off else ""
            attrs.append((kind, name, self.data[data_off:data_off + size] if data_off else b""))
        return attrs

    @staticmethod
    def value(kind: int, raw: bytes, typed: bool) -> str:
        if kind == TYPE_STRING:
            text = raw.split(b"\0")[0].decode("utf-8", errors="replace")
        elif kind == TYPE_FLOATS:
            text = " ".join(_float(v) for v in struct.unpack(f"<{len(raw) // 4}f", raw[:len(raw) // 4 * 4]))
        elif kind == TYPE_INTS:
            text = " ".join(str(v) for v in struct.unpack(f"<{len(raw) // 4}i", raw[:len(raw) // 4 * 4]))
        elif kind == TYPE_SHORTS:
            text = " ".join(str(v) for v in struct.unpack(f"<{len(raw) // 2}h", raw[:len(raw) // 2 * 2]))
        elif kind == TYPE_BYTES:
            text = " ".join(str(b) for b in raw)
        else:
            text = raw.hex()
        if typed:
            prefix = {TYPE_BYTES: "u8", TYPE_STRING: "s", TYPE_SHORTS: "s16", TYPE_INTS: "s32",
                      TYPE_FLOATS: "f32"}.get(kind, f"t{kind}")
            text = f"{prefix}:{text}"
        return text

    def to_xml(self, typed: bool = False) -> str:
        out = ['<?xml version="1.0" encoding="utf-8"?>']

        def walk(offset: int, depth: int) -> None:
            pad = "  " * depth
            attrs = self.attributes(offset)
            name = attrs[0][1] if attrs else "node"
            text = self.value(attrs[0][0], attrs[0][2], False) if attrs and attrs[0][2].strip(b"\0") else ""
            fields = "".join(f" {n}={quoteattr(self.value(k, raw, typed))}" for k, n, raw in attrs[1:])
            child = self.node(offset)[2]
            if not child and not text:
                out.append(f"{pad}<{name}{fields}/>")
                return
            if not child:
                out.append(f"{pad}<{name}{fields}>{escape(text)}</{name}>")
                return
            out.append(f"{pad}<{name}{fields}>" + (escape(text) if text else ""))
            while child:
                walk(child, depth + 1)
                child = self.node(child)[1]
            out.append(f"{pad}</{name}>")

        # The root is an unnamed document node: print its children.
        top = self.node(self.root)[2]
        while top:
            walk(top, 0)
            top = self.node(top)[1]
        return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help=".bxml files (default: every RomFS .bxml)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "extracted" / "xml")
    ap.add_argument("--typed", action="store_true", help="prefix values with their BXML type (u8, s, s16, s32, f32)")
    args = ap.parse_args()

    romfs = ROOT / "extracted" / "romfs"
    files = args.files or sorted(romfs.rglob("*.bxml"))
    failures = 0
    for path in files:
        try:
            xml = Bxml(path.read_bytes()).to_xml(args.typed)
        except (ValueError, struct.error, IndexError) as e:
            failures += 1
            print(f"[!] {path}: {e}", file=sys.stderr)
            continue
        rel = path.relative_to(romfs) if path.is_relative_to(romfs) else Path(path.name)
        dest = (args.out / rel).with_suffix(".xml")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(xml)
    print(f"[+] {len(files) - failures}/{len(files)} BXML files converted into {args.out}")


if __name__ == "__main__":
    main()
