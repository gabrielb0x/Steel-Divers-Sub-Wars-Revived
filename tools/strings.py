#!/usr/bin/env python3
"""The game's strings, grouped by the function and original source file that use them.

armcc loads a string's address from a literal pool placed right after the function's code (inside its size in
the map), or computes it from the PC (ADR) when the string follows the function in .text: every such word or ADR
that points at the start of a string is a use of that string by the function holding it (no mark). Two more
passes place the strings nothing points at: in .text, armcc puts a function's literals right after it ("~": the
function before them); in .rodata/.data, the linker keeps each object file's data together ("?", "(by
position)": the function of the string used before them, often one whose log was compiled out).

    python3 tools/strings.py [--all] [--grep REGEX] [--lines]

writes decomp/raw/strings.txt (generated from the game: never committed), the game's own files (source/), and
the libraries' with --all; --grep prints the matching strings with their file and function instead. --lines
prints the logs whose call was compiled out but whose arguments stayed: __FILE__, __LINE__ and the message, so
the line of the original source each one was on (docs/developer-traces.md).
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


def adr_target(word: int, address: int) -> int | None:
    """The address an ADR (ADD/SUB Rd, PC, #imm) computes, or None."""
    if word & 0x0FEF0000 not in (0x028F0000, 0x024F0000) or word >> 28 == 0xF:
        return None
    rotate, imm = (word >> 8 & 0xF) * 2, word & 0xFF
    imm = (imm >> rotate | imm << (32 - rotate)) & 0xFFFFFFFF if rotate else imm
    return address + 8 + (imm if word & 0x00800000 else -imm)


def rotated(word: int) -> int:
    rotate, imm = (word >> 8 & 0xF) * 2, word & 0xFF
    return (imm >> rotate | imm << (32 - rotate)) & 0xFFFFFFFF if rotate else imm


def track_constant(code: bytes, regs: dict[int, int], word: int, address: int) -> None:
    """Follow the constants put in r0..r3 (MOV #imm, MOVW, LDR from a literal pool, ADD Rd, Rn, #imm)."""
    rd = word >> 12 & 0xF
    if word >> 28 != 0xE or rd > 3:
        return
    if word & 0x0FF00000 == 0x03A00000:
        regs[rd] = rotated(word)
    elif word & 0x0FF00000 == 0x03000000:
        regs[rd] = (word >> 4 & 0xF000) | word & 0xFFF
    elif word & 0x0F7F0000 == 0x051F0000:
        literal = address + 8 + (word & 0xFFF if word & 0x00800000 else -(word & 0xFFF))
        regs[rd] = struct.unpack_from("<I", code, literal - BASE)[0]
    elif word & 0x0FE00000 == 0x02800000 and (word >> 16 & 0xF) in regs:
        regs[rd] = regs[word >> 16 & 0xF] + rotated(word)
    else:
        regs.pop(rd, None)


def log_lines(code: bytes, starts: list[int], functions: list[tuple[int, int, str, str]]) -> None:
    """The compiled-out logs: their call became a NOP (MOV r0, r0) after the arguments, or a branch to a NOP
    shared by several logs; __FILE__ in r0 (an ADR to "source/..."), __LINE__ in r1, the format in r3 or r2."""
    NOP, BRANCH = 0xE1A00000, 0xEA000000
    words = struct.unpack_from(f"<{(TEXT_END - BASE) // 4}I", code)
    logs: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for i, word in enumerate(words):
        target = adr_target(word, BASE + 4 * i)
        source = string_at(code, target) if target else None
        if not source or not source.startswith("source/"):
            continue
        end = next((j for j in range(i, min(i + 8, len(words)))
                    if words[j] == NOP or words[j] & 0xFF000000 == BRANCH), None)
        if end is None:
            continue
        regs: dict[int, int] = {}
        message = ""
        for j in range(max(0, i - 8), end):
            track_constant(code, regs, words[j], BASE + 4 * j)
            other = adr_target(words[j], BASE + 4 * j) if j != i else None
            text = string_at(code, other) if other else None
            if text and not text.startswith("source/"):
                message = text
        line = regs.get(1)
        if line is None or line > 100000:
            continue
        k = bisect.bisect_right(starts, BASE + 4 * i) - 1
        logs[source].append((line, functions[k][2] if k >= 0 else "?", message))
    for source in sorted(logs):
        entries = sorted(logs[source])
        print(f"== {source}: {len(entries)} logs, the last at line {entries[-1][0]}")
        for line, name, message in entries:
            print(f"  {line:5} {name}  {message.strip()!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="the libraries' strings too")
    ap.add_argument("--grep", help="only print the lines matching this regular expression")
    ap.add_argument("--lines", action="store_true", help="the compiled-out logs with their source line")
    args = ap.parse_args()
    code = CODE.read_bytes()
    strings: dict[int, str] = {}
    starts, functions = load_functions()
    if args.lines:
        log_lines(code, starts, functions)
        return
    uses: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))   # file -> function -> addresses
    used, nearby, guessed = set(), set(), set()
    text = code[:TEXT_END - BASE]
    for offset in range(0, len(text) - 3, 4):
        value = word = struct.unpack_from("<I", text, offset)[0]
        value = adr_target(word, BASE + offset) or value
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
