#!/usr/bin/env python3
"""The game's strings, grouped by the function and original source file that use them.

armcc loads a string's address from a literal pool placed right after the function's code (inside its size in
the map), or computes it from the PC (ADR) when the string follows the function in .text: every such word or ADR
that points at the start of a string is a use of that string by the function holding it (no mark). Two more
passes place the strings nothing points at: in .text, armcc puts a function's literals right after it ("~": the
function before them); in .rodata/.data, the linker keeps each object file's data together ("?", "(by
position)": the function of the string used before them, often one whose log was compiled out).

    python3 tools/strings.py [--all] [--grep REGEX]

writes decomp/raw/strings.txt (generated from the game: never committed), the game's own files (source/), and
the libraries' with --all; --grep prints the matching strings with their file and function instead.
Needs extracted/code.bin and decomp/raw/functions.csv (make export).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import re
import struct
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "extracted" / "code.bin"
FUNCTIONS = ROOT / "decomp" / "raw" / "functions.csv"
OUT = ROOT / "decomp" / "raw" / "strings.txt"
BASE = 0x00100000
TEXT_END = 0x00352000
PRINTABLE = re.compile(rb"[\t\n\r\x20-\x7e\x80-\xff]{4,}\x00")


def string_at(code: bytes, address: int, ascii_only: bool = False) -> str | None:
    """The string starting at address (UTF-8 or Shift-JIS text of 4 characters or more, NUL-terminated, mostly
    letters, digits and punctuation)."""
    offset = address - BASE
    if not 0 <= offset < len(code):
        return None
    end = code.find(b"\0", offset, offset + 4096)
    raw = code[offset:end]
    if end < 0 or len(raw) < 4 or not PRINTABLE.fullmatch(raw + b"\0"):
        return None
    if ascii_only and max(raw) > 0x7E:
        return None
    for encoding in ("utf-8", "shift_jis"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    letters = sum(c.isalnum() or c in " _%:./[]()-',\n" or ord(c) > 0x7f for c in text)
    if letters < 0.8 * len(text) or (text[0] == " " and len(text) <= 12):
        return None
    return text


def load_functions() -> tuple[list[int], list[tuple[int, int, str, str]]]:
    rows = []
    with FUNCTIONS.open(newline="") as f:
        for row in csv.DictReader(f):
            start = int(row["address"], 16)
            size = int(row["map_size"] or row["ghidra_size"] or 0)
            rows.append((start, size, row["name"], row["file"]))
    rows.sort()
    return [r[0] for r in rows], rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="the libraries' strings too")
    ap.add_argument("--grep", help="only print the lines matching this regular expression")
    args = ap.parse_args()
    code = CODE.read_bytes()
    strings: dict[int, str] = {}
    starts, functions = load_functions()
    uses: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))   # file -> function -> addresses
    used, nearby, guessed = set(), set(), set()
    text = code[:TEXT_END - BASE]
    for offset in range(0, len(text) - 3, 4):
        value = word = struct.unpack_from("<I", text, offset)[0]
        if word & 0x0FEF0000 in (0x028F0000, 0x024F0000) and word >> 28 != 0xF:      # ADR: ADD/SUB Rd, PC, #imm
            rotate, imm = (word >> 8 & 0xF) * 2, word & 0xFF
            imm = (imm >> rotate | imm << (32 - rotate)) & 0xFFFFFFFF if rotate else imm
            value = BASE + offset + 8 + (imm if word & 0x00800000 else -imm)
        if value not in strings:
            found = string_at(code, value) if BASE <= value < BASE + len(code) else None
            if found is None:
                continue
            strings[value] = found
        address = BASE + offset
        i = bisect.bisect_right(starts, address) - 1
        if i < 0:
            continue
        start, size, name, file = functions[i]
        if size and address >= start + size + 64:                   # a pool may trail a little
            continue
        uses[file or "unmapped"][name].add(value)
        used.add(value)
    # Strings of .text nothing points at directly (an address computed from another): armcc places them right
    # after the functions using them, so they go to the function before them, marked "~".
    for i, (start, size, name, file) in enumerate(functions):
        end = functions[i + 1][0] if i + 1 < len(functions) else TEXT_END
        address = (start + size + 3) & ~3 if size else end
        while address < min(end, TEXT_END):
            found = strings[address] if address in used else string_at(code, address)
            if found is None:
                address += 4
                continue
            if address not in used:
                strings[address] = found
                uses[file or "unmapped"][name].add(address)
                nearby.add(address)
            address = (address + len(found.encode("utf-8", "replace")) + 4) & ~3
    # Strings of .rodata/.data nothing points at directly: the linker keeps each object file's data together,
    # so they go to the function of the string used before them, marked "?" (ASCII only: .data holds binary
    # tables that read as Shift-JIS).
    owner = {}
    for file, names in uses.items():
        for name, values in names.items():
            for value in values:
                owner[value] = (file, name)
    address, last = TEXT_END, None
    while address < BASE + len(code):
        if address in owner:
            last = owner[address]
        found = strings.get(address) or string_at(code, address, ascii_only=True)
        if found is None:
            address += 1
            continue
        if address not in used and address not in nearby and last:
            strings[address] = found
            uses[last[0]][last[1] + " (by position)"].add(address)
            guessed.add(address)
        address += len(found.encode("utf-8", "replace")) + 1
    lines = []
    for file in sorted(uses, key=lambda f: (not f.startswith("source/"), f)):
        if not args.all and not file.startswith("source/"):
            continue
        lines.append(f"== {file}")
        for name in sorted(uses[file], key=lambda n: min(uses[file][n])):
            lines.append(f"  {name}")
            for value in sorted(uses[file][name]):
                lines.append(f"  {'~' if value in nearby else '?' if value in guessed else ' '} 0x{value:08x} {strings[value]!r}")
    if args.grep:
        pattern = re.compile(args.grep, re.I)
        header, function, shown = "", "", set()
        for line in lines:
            if line.startswith("=="):
                header = line
            elif not re.match(r"  [ ~?] 0x", line):
                function = line
            elif pattern.search(line):
                for context in (header, function):
                    if context not in shown:
                        print(context)
                        shown.add(context)
                print(line)
        return
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[+] {OUT.relative_to(ROOT)}: {len(used)} strings used by {sum(len(u) for u in uses.values())} functions")


if __name__ == "__main__":
    main()
