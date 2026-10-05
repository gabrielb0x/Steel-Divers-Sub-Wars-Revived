#!/usr/bin/env python3
"""BXML (the game's binary XML, source/sys/binxml.cpp) <-> XML.

Layout (little endian, offsets from the start of the file):
  header     "BXML" magic (LMXB on disk), u32 version (1), u32 root node offset
  node       u32 parent, u32 next sibling, u32 first child, u32 attribute count, u32 attributes offset
  attribute  u32 type, u32 name hash (generateCRC = CRC-32), u32 name offset, u32 name length (with
             the NUL), u32 data offset, u32 data size
The first attribute of a node is its name (BXML::Node::getName). Attribute types
(BXML::Attribute::set*Data): 1 name, 2 bytes, 3 string (with its NUL), 4 s16[], 5 s32[], 7 f32[].

The writer reproduces the layout of the game's own converter, so that an unmodified file comes
back byte for byte (488 of the 490 files; textures/decal_22 and decal_28 were made by an older
version that did not align texture data, see --no-align):
  - the header, the nodes in pre-order, the attribute tables in node order, then a pool holding,
    attribute after attribute, its name and its data, each padded to 4 bytes;
  - texture data (type 2) aligned to 128 bytes, and in such files the pool too;
  - a blob whose size is a multiple of 4 reuses the latest identical entry of the pool (other
    sizes never do: the original seems to compare padded blobs, padding included);
  - attributes without data point to the start of the pool, with size 0.

XML representation: one element per node, one attribute per BXML attribute. Types are inferred
from the values: integers -> s32, numbers written with a decimal point or an exponent -> f32,
anything else -> string. A prefix gives the type when the inference would be wrong: "s:31308"
is a string, "s16:1 2", "hex:00ff..." raw bytes (textures). Strings escape their control
characters as \\n and \\xHH (the game's text uses 0x0E and 0x0C as formatting codes), and the
backslash as \\\\.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
MAGIC = b"LMXB"

TYPE_NAME, TYPE_BYTES, TYPE_STRING, TYPE_SHORTS, TYPE_INTS, TYPE_FLOATS = 1, 2, 3, 4, 5, 7
PREFIXES = {"s": TYPE_STRING, "s32": TYPE_INTS, "f32": TYPE_FLOATS, "s16": TYPE_SHORTS, "hex": TYPE_BYTES,
            "u8": TYPE_BYTES}
_PREFIX = re.compile(r"^(s|s32|f32|s16|hex|u8):")
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+(\.\d*)?[eE][-+]?\d+|inf|nan)$")


def float_text(value: float) -> str:
    """Shortest text giving back the same f32, always with a decimal point (so it reads as f32)."""
    raw = struct.pack("<f", value)
    if value != value or value in (float("inf"), float("-inf")):
        return repr(value)
    for decimals in range(1, 10):
        text = f"{value:.{decimals}f}"
        if struct.pack("<f", float(text)) == raw:
            return text
    return repr(value)


def escape_string(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)


def unescape_string(text: str) -> str:
    return re.sub(r"\\(\\|n|x[0-9a-fA-F]{2})",
                  lambda m: "\\" if m[1] == "\\" else "\n" if m[1] == "n" else chr(int(m[1][1:], 16)), text)


def infer_type(text: str) -> int:
    tokens = text.split()
    if tokens and all(_INT.match(t) for t in tokens):
        return TYPE_INTS
    if tokens and all(_INT.match(t) or _FLOAT.match(t) for t in tokens):
        return TYPE_FLOATS
    return TYPE_STRING


def encode_value(kind: int, raw: bytes) -> str:
    """BXML attribute data -> XML attribute text (see the module docstring)."""
    if kind == TYPE_STRING:
        text = escape_string(raw[:-1].decode("utf-8"))
        return f"s:{text}" if infer_type(text) != TYPE_STRING or _PREFIX.match(text) else text
    if kind == TYPE_INTS:
        return " ".join(str(v) for v in struct.unpack(f"<{len(raw) // 4}i", raw))
    if kind == TYPE_FLOATS:
        return " ".join(float_text(v) for v in struct.unpack(f"<{len(raw) // 4}f", raw))
    if kind == TYPE_SHORTS:
        return "s16:" + " ".join(str(v) for v in struct.unpack(f"<{len(raw) // 2}h", raw))
    if kind == TYPE_BYTES:
        return "hex:" + raw.hex()
    raise ValueError(f"unknown attribute type {kind}")


def decode_value(text: str) -> tuple[int, bytes]:
    """XML attribute text -> (BXML type, data)."""
    m = _PREFIX.match(text)
    kind = PREFIXES[m[1]] if m else infer_type(text)
    body = text[m.end():] if m else text
    if kind == TYPE_STRING:
        return kind, unescape_string(body).encode("utf-8") + b"\0"
    if kind == TYPE_INTS:
        return kind, b"".join(struct.pack("<i", int(t)) for t in body.split())
    if kind == TYPE_FLOATS:
        return kind, b"".join(struct.pack("<f", float(t)) for t in body.split())
    if kind == TYPE_SHORTS:
        return kind, b"".join(struct.pack("<h", int(t)) for t in body.split())
    if m and m[1] == "u8":
        return kind, bytes(int(t) for t in body.split())
    return kind, bytes.fromhex(body)


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
            attrs.append((kind, name, self.data[data_off:data_off + size] if size else b""))
        return attrs

    def to_xml(self) -> str:
        out = ['<?xml version="1.0" encoding="utf-8"?>']

        def walk(offset: int, depth: int) -> None:
            pad = "  " * depth
            attrs = self.attributes(offset)
            if not attrs or attrs[0][0] != TYPE_NAME or attrs[0][2]:
                raise ValueError(f"node at {offset:#x}: no name attribute, or one with data")
            name = attrs[0][1]
            fields = "".join(f" {n}={quoteattr(encode_value(k, raw))}" for k, n, raw in attrs[1:])
            child = self.node(offset)[2]
            if not child:
                out.append(f"{pad}<{name}{fields}/>")
                return
            out.append(f"{pad}<{name}{fields}>")
            while child:
                walk(child, depth + 1)
                child = self.node(child)[1]
            out.append(f"{pad}</{name}>")

        # The root is an unnamed document node; every file has a single top-level element.
        top = self.node(self.root)[2]
        while top:
            walk(top, 0)
            top = self.node(top)[1]
        return "\n".join(out) + "\n"


def from_xml(text: str, align: bool = True, version: int = 1) -> bytes:
    """XML -> BXML, laid out like the game's converter (see the module docstring)."""
    element = ET.fromstring(text)
    nodes: list[tuple[list[tuple[int, str, bytes]], int, list[int]]] = []   # (attributes, parent, children)

    def add(attrs: list[tuple[int, str, bytes]], parent: int) -> int:
        nodes.append((attrs, parent, []))
        if parent >= 0:
            nodes[parent][2].append(len(nodes) - 1)
        return len(nodes) - 1

    def walk(e: ET.Element, parent: int) -> None:
        if e.text and e.text.strip():
            raise ValueError(f"<{e.tag}>: text content is not supported")
        attrs = [(TYPE_NAME, e.tag, b"")]
        for name, value in e.attrib.items():
            kind, data = decode_value(value)
            attrs.append((kind, name, data))
        index = add(attrs, parent)
        for child in e:
            walk(child, index)

    walk(element, add([(TYPE_NAME, "", b"")], -1))

    node_base = 12
    tables, offset = [], node_base + 20 * len(nodes)
    for attrs, _, _ in nodes:
        tables.append(offset)
        offset += 24 * len(attrs)
    align = align and any(kind == TYPE_BYTES and data for attrs, _, _ in nodes for kind, _, data in attrs)
    pool_base = (offset + 127) & ~127 if align else offset
    out = bytearray(pool_base)
    latest: dict[bytes, int] = {}

    def put(blob: bytes, alignment: int = 4) -> int:
        if len(blob) % 4 == 0 and blob in latest:
            return latest[blob]
        out.extend(bytes(-len(out) % alignment))
        position = len(out)
        padded = blob + bytes(-len(blob) % 4)
        out.extend(padded)
        latest[padded] = position
        return position

    rows = []
    for attrs, _, _ in nodes:
        for kind, name, data in attrs:
            raw_name = name.encode("latin-1") + b"\0" if name else b"\0"
            name_off = put(raw_name)
            data_off = put(data, 128 if kind == TYPE_BYTES and align else 4) if data else pool_base
            rows.append(struct.pack("<6I", kind, zlib.crc32(raw_name[:-1]), name_off, len(raw_name), data_off,
                                    len(data)))
    head = bytearray(MAGIC + struct.pack("<II", version, node_base))
    for k, (attrs, parent, _) in enumerate(nodes):
        siblings = nodes[parent][2] if parent >= 0 else [k]
        position = siblings.index(k)
        sibling = node_base + 20 * siblings[position + 1] if position + 1 < len(siblings) else 0
        child = node_base + 20 * nodes[k][2][0] if nodes[k][2] else 0
        head += struct.pack("<5I", node_base + 20 * parent if parent >= 0 else 0, sibling, child, len(attrs),
                            tables[k])
    head += b"".join(rows)
    out[:len(head)] = head
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help=".bxml files, or .xml with --to-bxml (default: every RomFS .bxml)")
    ap.add_argument("-o", "--out", type=Path, help="output directory (default: extracted/xml), or file with --to-bxml")
    ap.add_argument("--to-bxml", action="store_true", help="convert XML files back to BXML")
    ap.add_argument("--no-align", action="store_true", help="do not align texture data (older converter)")
    ap.add_argument("--check", action="store_true", help="BXML -> XML -> BXML on every file, compare the bytes")
    args = ap.parse_args()

    romfs = ROOT / "extracted" / "romfs"
    if args.to_bxml:
        if not args.files:
            ap.error("--to-bxml needs XML files")
        for path in args.files:
            dest = args.out if args.out and len(args.files) == 1 and args.out.suffix else \
                (args.out or path.parent) / path.with_suffix(".bxml").name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(from_xml(path.read_text(encoding="utf-8"), align=not args.no_align))
            print(f"[+] {path} -> {dest}")
        return

    files = args.files or sorted(romfs.rglob("*.bxml"))
    if args.check:
        identical = []
        for path in files:
            data = path.read_bytes()
            xml = Bxml(data).to_xml()
            if from_xml(xml) == data or from_xml(xml, align=False) == data:
                identical.append(path)
            else:
                print(f"[!] {path}: differs after a round trip", file=sys.stderr)
        print(f"[+] {len(identical)}/{len(files)} files identical after BXML -> XML -> BXML")
        sys.exit(0 if len(identical) == len(files) else 1)

    out_dir = args.out or ROOT / "extracted" / "xml"
    failures = 0
    for path in files:
        try:
            xml = Bxml(path.read_bytes()).to_xml()
        except (ValueError, struct.error, IndexError, UnicodeDecodeError) as e:
            failures += 1
            print(f"[!] {path}: {e}", file=sys.stderr)
            continue
        rel = path.relative_to(romfs) if path.is_relative_to(romfs) else Path(path.name)
        dest = (out_dir / rel).with_suffix(".xml")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(xml, encoding="utf-8")
    print(f"[+] {len(files) - failures}/{len(files)} BXML files converted into {out_dir}")


if __name__ == "__main__":
    main()
