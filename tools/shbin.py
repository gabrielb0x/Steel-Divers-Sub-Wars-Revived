#!/usr/bin/env python3
"""PICA200 shader binaries (romfs:/shaders/*.shbin, DVLB) : reader and disassembler.

  shbin.py <file.shbin>            programs, constants, uniforms and the disassembled code
  shbin.py --check <file>...       loops reached from inside another loop (see below)

Layout (little endian; 3dbrew "SHBIN"):
  DVLB   "DVLB", u32 count, u32 offsets of the DVLE (from the start of the file), then the DVLP
  DVLP   "DVLP", u32 version, u32 code offset, u32 code size in words, u32 operand descriptors
         offset, u32 descriptor count (8 bytes each), ...; offsets from the start of the DVLP
  DVLE   one program sharing the code: "DVLE", u16 version, u8 type (0 vertex, 1 geometry), u8,
         u32 main, u32 endmain (in words), u16 input mask, u16 output mask, u8 geometry type,
         u8 start register, u8 vertices, u8 vertices, then (offset, count) of the constants (20
         bytes), labels (16), outputs (8), uniforms (8) and the symbol table (offset, size)

--check lists the loops that the x64 shader JIT of Azahar/Citra runs wrongly: it keeps the
counter of a LOOP in host registers that it saves only for a loop nested in the same block of
code. A loop inside a subroutine called from another loop overwrites the counter of the outer
loop, which ends at 0, then wraps to -1: about four billion more iterations. A geometry shader
emits vertices at each one and the emulator fills its memory until it is killed
(shaders/metaball.shbin, the oil of damaged submarines: mods/fixes).
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

OPS = {0x00: "add", 0x01: "dp3", 0x02: "dp4", 0x03: "dph", 0x04: "dst", 0x05: "ex2", 0x06: "lg2", 0x07: "litp",
       0x08: "mul", 0x09: "sge", 0x0A: "slt", 0x0B: "flr", 0x0C: "max", 0x0D: "min", 0x0E: "rcp", 0x0F: "rsq",
       0x12: "mova", 0x13: "mov", 0x18: "dphi", 0x19: "dsti", 0x1A: "sgei", 0x1B: "slti",
       0x20: "break", 0x21: "nop", 0x22: "end", 0x23: "breakc", 0x24: "call", 0x25: "callc", 0x26: "callu",
       0x27: "ifu", 0x28: "ifc", 0x29: "loop", 0x2A: "emit", 0x2B: "setemit", 0x2C: "jmpc", 0x2D: "jmpu"}
UNARY = {"ex2", "lg2", "litp", "flr", "rcp", "rsq", "mova", "mov"}
INVERTED = {"dphi", "dsti", "sgei", "slti"}             # the 7-bit source is the second one
COMPARE = ["eq", "ne", "lt", "le", "gt", "ge", "?6", "?7"]
CONDITION = ["or", "and", "x", "y"]
INDEX = ["", "[a0.x]", "[a0.y]", "[aL]"]
OUTPUTS = ["position", "normquat", "color", "texcoord0", "texcoord0w", "texcoord1", "texcoord2", "?7", "view"]
NOP = 0x84000000


def f24(v: int) -> float:
    """PICA200 24-bit float: sign, 7-bit exponent (bias 63), 16-bit mantissa."""
    sign, exp, man = (v >> 23) & 1, (v >> 16) & 0x7F, v & 0xFFFF
    if exp == 0:
        value = 0.0
    elif exp == 0x7F:
        value = float("nan") if man else float("inf")
    else:
        value = (1 + man / 65536.0) * 2.0 ** (exp - 63)
    return -value if sign else value


def code_location(data: bytes) -> tuple[int, int]:
    """(offset of the shared code in the file, its size in instructions)."""
    if data[:4] != b"DVLB":
        raise ValueError("not a shader binary (DVLB)")
    dvlp = 8 + 4 * struct.unpack_from("<I", data, 4)[0]
    if data[dvlp:dvlp + 4] != b"DVLP":
        raise ValueError("no DVLP after the DVLB header")
    code, size = struct.unpack_from("<II", data, dvlp + 8)
    return dvlp + code, size


class Shader:
    def __init__(self, data: bytes):
        start, size = code_location(data)
        self.data = data
        self.code = list(struct.unpack_from(f"<{size}I", data, start))
        dvlp = 8 + 4 * struct.unpack_from("<I", data, 4)[0]
        desc_offset, desc_count = struct.unpack_from("<II", data, dvlp + 16)
        self.descriptors = [struct.unpack_from("<I", data, dvlp + desc_offset + 8 * i)[0] for i in range(desc_count)]
        count = struct.unpack_from("<I", data, 4)[0]
        self.programs = [self._program(offset) for offset in struct.unpack_from(f"<{count}I", data, 8)]

    def _program(self, base: int) -> dict:
        (_, _, kind, _, main, endmain, inputs, outputs, gs_type, gs_start, gs_var, gs_fixed,
         c_off, c_count, l_off, l_count, o_off, o_count, u_off, u_count, s_off, s_size) = \
            struct.unpack_from("<4sHBBIIHHBBBBIIIIIIIIII", self.data, base)
        symbols = self.data[base + s_off: base + s_off + s_size]

        def name(offset: int) -> str:
            return symbols[offset:symbols.index(b"\0", offset)].decode("ascii", "replace")

        constants = []
        for i in range(c_count):
            at = base + c_off + 20 * i
            kind_c, reg = struct.unpack_from("<HH", self.data, at)
            if kind_c == 0:
                constants.append(f"b{reg} = {self.data[at + 4]}")
            elif kind_c == 1:
                constants.append(f"i{reg} = {tuple(self.data[at + 4:at + 8])}")
            else:
                values = struct.unpack_from("<4I", self.data, at + 4)
                constants.append(f"c{reg} = ({', '.join(f'{f24(v):g}' for v in values)})")
        labels = {}
        for i in range(l_count):
            _, offset, _, symbol = struct.unpack_from("<IIII", self.data, base + l_off + 16 * i)
            labels[offset] = name(symbol)
        outs = []
        for i in range(o_count):
            kind_o, reg, mask = struct.unpack_from("<HHB", self.data, base + o_off + 8 * i)
            outs.append(f"o{reg}.{_mask(mask)} = {OUTPUTS[kind_o] if kind_o < len(OUTPUTS) else kind_o}")
        uniforms = []
        for i in range(u_count):
            symbol, first, last = struct.unpack_from("<IHH", self.data, base + u_off + 8 * i)
            uniforms.append(f"{name(symbol)}: {_uniform(first)}-{_uniform(last)}")
        return {"kind": "geometry" if kind else "vertex", "main": main, "endmain": endmain,
                "gs_type": gs_type, "constants": constants, "labels": labels, "outputs": outs,
                "uniforms": uniforms}

    def disassemble(self, index: int) -> str:
        return disassemble(self.code[index], self.descriptors)

    def nested_loops(self) -> list[tuple[int, int]]:
        """(outer, inner) LOOP instructions where the inner one runs in a subroutine of the outer body."""
        found = []
        for outer, word in enumerate(self.code):
            if word >> 26 != 0x29:
                continue
            end = (word >> 10) & 0xFFF
            seen: set[int] = set()
            for inner in self._reached(outer + 1, end + 1, seen, depth=0):
                found.append((outer, inner))
        return found

    def _reached(self, start: int, stop: int, seen: set[int], depth: int) -> list[int]:
        """LOOP instructions run by the CALLs of [start, stop) (not those of the range itself)."""
        loops = []
        for pc in range(start, min(stop, len(self.code))):
            word = self.code[pc]
            if word >> 26 in (0x24, 0x25, 0x26) and depth < 8:     # call, callc, callu
                target, count = (word >> 10) & 0xFFF, word & 0xFF
                if (target, count) in seen:
                    continue
                seen.add((target, count))
                for sub in range(target, min(target + count, len(self.code))):
                    if self.code[sub] >> 26 == 0x29:
                        loops.append(sub)
                loops += self._reached(target, target + count, seen, depth + 1)
        return loops


def _mask(m: int) -> str:
    return "".join(c for i, c in enumerate("xyzw") if m & (8 >> i))


def _uniform(r: int) -> str:
    if r < 0x10:
        return f"v{r}"
    if r < 0x70:
        return f"c{r - 0x10}"
    if r < 0x74:
        return f"i{r - 0x70}"
    return f"b{r - 0x78}"


def _source(reg: int) -> str:
    return f"v{reg}" if reg < 0x10 else f"r{reg - 0x10}" if reg < 0x20 else f"c{reg - 0x20}"


def _dest(reg: int) -> str:
    return f"o{reg}" if reg < 0x10 else f"r{reg - 0x10}"


def _operand(reg: int, negate: int, swizzle: int, index: str = "") -> str:
    s = "".join("xyzw"[(swizzle >> (6 - 2 * i)) & 3] for i in range(4))
    return ("-" if negate else "") + _source(reg) + index + ("" if s == "xyzw" else "." + s)


def disassemble(word: int, descriptors: list[int]) -> str:
    op = word >> 26
    if op >= 0x30:                                          # mad, madi: 3-bit opcode
        d = descriptors[word & 0x1F]
        index = INDEX[(word >> 22) & 3]
        src1 = (word >> 17) & 0x1F
        if op >= 0x38:
            name, src2, src3, i2, i3 = "mad", (word >> 10) & 0x7F, (word >> 5) & 0x1F, index, ""
        else:
            name, src2, src3, i2, i3 = "madi", (word >> 12) & 0x1F, (word >> 5) & 0x7F, "", index
        return (f"{name} {_dest((word >> 24) & 0x1F)}.{_mask(d & 0xF)}, {_operand(src1, d >> 4 & 1, d >> 5 & 0xFF)}, "
                f"{_operand(src2, d >> 13 & 1, d >> 14 & 0xFF, i2)}, {_operand(src3, d >> 22 & 1, d >> 23 & 0xFF, i3)}")
    if op in (0x2E, 0x2F):                                  # cmp: 5-bit opcode
        d = descriptors[word & 0x7F]
        return (f"cmp {_operand((word >> 12) & 0x7F, d >> 4 & 1, d >> 5 & 0xFF, INDEX[(word >> 19) & 3])}, "
                f"{COMPARE[(word >> 24) & 7]}, {COMPARE[(word >> 21) & 7]}, "
                f"{_operand((word >> 7) & 0x1F, d >> 13 & 1, d >> 14 & 0xFF)}")
    name = OPS.get(op, f"op{op:02x}")
    if op < 0x20:
        d = descriptors[word & 0x7F]
        index = INDEX[(word >> 19) & 3]
        if name in INVERTED:
            s1, s2, i1, i2 = (word >> 14) & 0x1F, (word >> 7) & 0x7F, "", index
        else:
            s1, s2, i1, i2 = (word >> 12) & 0x7F, (word >> 7) & 0x1F, index, ""
        first = _operand(s1, d >> 4 & 1, d >> 5 & 0xFF, i1)
        if name == "mova":
            return f"mova a0.{_mask(d & 0xC)}, {first}"
        dest = f"{_dest((word >> 21) & 0x1F)}.{_mask(d & 0xF)}"
        if name in UNARY:
            return f"{name} {dest}, {first}"
        return f"{name} {dest}, {first}, {_operand(s2, d >> 13 & 1, d >> 14 & 0xFF, i2)}"
    count, target = word & 0xFF, (word >> 10) & 0xFFF
    condition = f"{CONDITION[(word >> 22) & 3]}(x={(word >> 25) & 1}, y={(word >> 24) & 1})"
    if name in ("break", "nop", "end", "emit"):
        return name
    if name == "setemit":
        return f"setemit {(word >> 24) & 3}" + (", prim" if word >> 23 & 1 else "") + (", inv" if word >> 22 & 1 else "")
    if name == "breakc":
        return f"breakc {condition}"
    if name in ("callc", "ifc", "jmpc"):
        return f"{name} {condition}, {target:03x}, {count}"
    if name in ("callu", "ifu"):
        return f"{name} b{(word >> 22) & 0xF}, {target:03x}, {count}"
    if name == "jmpu":
        return f"jmpu {'!' if count & 1 else ''}b{(word >> 22) & 0xF}, {target:03x}"
    if name == "call":
        return f"call {target:03x}, {count}"
    if name == "loop":
        return f"loop i{(word >> 22) & 3}, {target:03x}"
    return f"{name} {word:08x}"


def show(path: Path) -> None:
    shader = Shader(path.read_bytes())
    labels: dict[int, str] = {}
    for i, program in enumerate(shader.programs):
        print(f"; program {i}: {program['kind']} shader, main {program['main']:03x}, endmain {program['endmain']:03x}"
              + (f", geometry type {program['gs_type']}" if program["kind"] == "geometry" else ""))
        for line in program["constants"] + program["outputs"] + program["uniforms"]:
            print(f";   {line}")
        labels.update(program["labels"])
    for pc in range(len(shader.code)):
        if pc in labels:
            print(f"{labels[pc]}:")
        print(f"  {pc:03x}: {shader.code[pc]:08x}  {shader.disassemble(pc)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true", help="list the loops run from inside another loop")
    args = ap.parse_args()
    for path in args.files:
        if not args.check:
            show(path)
            continue
        try:
            shader = Shader(path.read_bytes())
        except ValueError as e:
            sys.exit(f"[!] {path}: {e}")
        for outer, inner in shader.nested_loops():
            print(f"{path}: loop {inner:03x} runs inside loop {outer:03x} through a call "
                  f"({shader.disassemble(outer)} / {shader.disassemble(inner)})")


if __name__ == "__main__":
    main()
