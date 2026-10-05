#!/usr/bin/env python3
"""Pawn AMX (file version 10, Pawn 3.3) reader and disassembler.

The game's scripts (romfs:/amx/*.amx) are compiled Pawn: this module expands
the compact encoding, decodes the tables (publics, natives, public variables)
and disassembles the P-code with labels, native names and string literals.
Native functions are resolved to their C++ implementation by following the
amx_Register() calls in code.bin (see find_native_tables).

Reference: amx.c / amx.h of Pawn 3.3 (CompuPhase), the version that produced
these files (CUR_FILE_VERSION 10).
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AMX_MAGIC = 0xF1E0
FLAG_COMPACT = 0x04

OPCODES = """NONE LOAD_PRI LOAD_ALT LOAD_S_PRI LOAD_S_ALT LREF_PRI LREF_ALT LREF_S_PRI LREF_S_ALT LOAD_I
LODB_I CONST_PRI CONST_ALT ADDR_PRI ADDR_ALT STOR_PRI STOR_ALT STOR_S_PRI STOR_S_ALT SREF_PRI SREF_ALT
SREF_S_PRI SREF_S_ALT STOR_I STRB_I LIDX LIDX_B IDXADDR IDXADDR_B ALIGN_PRI ALIGN_ALT LCTRL SCTRL MOVE_PRI
MOVE_ALT XCHG PUSH_PRI PUSH_ALT PICK PUSH_C PUSH PUSH_S POP_PRI POP_ALT STACK HEAP PROC RET RETN CALL CALL_PRI
JUMP JREL JZER JNZ JEQ JNEQ JLESS JLEQ JGRTR JGEQ JSLESS JSLEQ JSGRTR JSGEQ SHL SHR SSHR SHL_C_PRI SHL_C_ALT
SHR_C_PRI SHR_C_ALT SMUL SDIV SDIV_ALT UMUL UDIV UDIV_ALT ADD SUB SUB_ALT AND OR XOR NOT NEG INVERT ADD_C SMUL_C
ZERO_PRI ZERO_ALT ZERO ZERO_S SIGN_PRI SIGN_ALT EQ NEQ LESS LEQ GRTR GEQ SLESS SLEQ SGRTR SGEQ EQ_C_PRI EQ_C_ALT
INC_PRI INC_ALT INC INC_S INC_I DEC_PRI DEC_ALT DEC DEC_S DEC_I MOVS CMPS FILL HALT BOUNDS SYSREQ_PRI SYSREQ_C
FILE LINE SYMBOL SRANGE JUMP_PRI SWITCH CASETBL SWAP_PRI SWAP_ALT PUSH_ADR NOP SYSREQ_N SYMTAG BREAK PUSH2_C
PUSH2 PUSH2_S PUSH2_ADR PUSH3_C PUSH3 PUSH3_S PUSH3_ADR PUSH4_C PUSH4 PUSH4_S PUSH4_ADR PUSH5_C PUSH5 PUSH5_S
PUSH5_ADR LOAD_BOTH LOAD_S_BOTH CONST CONST_S ICALL IRETN ISWITCH ICASETBL LOAD_P_PRI LOAD_P_ALT LOAD_P_S_PRI
LOAD_P_S_ALT LREF_P_PRI LREF_P_ALT LREF_P_S_PRI LREF_P_S_ALT LODB_P_I CONST_P_PRI CONST_P_ALT ADDR_P_PRI
ADDR_P_ALT STOR_P_PRI STOR_P_ALT STOR_P_S_PRI STOR_P_S_ALT SREF_P_PRI SREF_P_ALT SREF_P_S_PRI SREF_P_S_ALT
STRB_P_I LIDX_P_B IDXADDR_P_B ALIGN_P_PRI ALIGN_P_ALT PUSH_P_C PUSH_P PUSH_P_S STACK_P HEAP_P SHL_P_C_PRI
SHL_P_C_ALT SHR_P_C_PRI SHR_P_C_ALT ADD_P_C SMUL_P_C ZERO_P ZERO_P_S EQ_P_C_PRI EQ_P_C_ALT INC_P INC_P_S DEC_P
DEC_P_S MOVS_P CMPS_P FILL_P HALT_P BOUNDS_P PUSH_P_ADR SYSREQ_D SYSREQ_ND""".split()
OP = {name: i for i, name in enumerate(OPCODES)}

# Number of operand cells after the opcode (amx.c, VerifyPcode). Packed opcodes
# (*_P_*, 162..212) carry their operand in the upper 16 bits of the opcode cell.
_ONE = """LODB_I CONST_PRI CONST_ALT ADDR_PRI ADDR_ALT STRB_I LIDX_B IDXADDR_B ALIGN_PRI ALIGN_ALT LCTRL SCTRL PICK
PUSH_C PUSH PUSH_S STACK HEAP JREL SHL_C_PRI SHL_C_ALT SHR_C_PRI SHR_C_ALT ADD_C SMUL_C ZERO ZERO_S EQ_C_PRI
EQ_C_ALT MOVS CMPS FILL HALT BOUNDS PUSH_ADR LOAD_PRI LOAD_ALT LREF_PRI LREF_ALT STOR_PRI STOR_ALT SREF_PRI
SREF_ALT INC DEC LOAD_S_PRI LOAD_S_ALT LREF_S_PRI LREF_S_ALT STOR_S_PRI STOR_S_ALT SREF_S_PRI SREF_S_ALT INC_S
DEC_S SYSREQ_C CALL JUMP JZER JNZ JEQ JNEQ JLESS JLEQ JGRTR JGEQ JSLESS JSLEQ JSGRTR JSGEQ SWITCH ICALL
ISWITCH""".split()
NPARAMS = {name: 0 for name in OPCODES}
NPARAMS.update({name: 1 for name in _ONE})
NPARAMS.update({f"PUSH{n}{s}": n for n in (2, 3, 4, 5) for s in ("_C", "", "_S", "_ADR")})
NPARAMS.update({"CONST": 2, "CONST_S": 2, "LOAD_BOTH": 2, "LOAD_S_BOTH": 2, "SYSREQ_N": 2})
PACKED_FIRST, PACKED_LAST = OP["LOAD_P_PRI"], OP["PUSH_P_ADR"]
# Removed from Pawn 3.3 (security fix) or never emitted in files.
INVALID = {OP[n] for n in ("NONE", "CALL_PRI", "JUMP_PRI", "FILE", "LINE", "SYMBOL", "SRANGE", "SYMTAG",
                           "SYSREQ_D", "SYSREQ_ND")}
# Operand is a code address relative to the opcode itself.
BRANCHES = {OP[n] for n in ("CALL", "JUMP", "JZER", "JNZ", "JEQ", "JNEQ", "JLESS", "JLEQ", "JGRTR", "JGEQ",
                            "JSLESS", "JSLEQ", "JSGRTR", "JSGEQ", "SWITCH")}
# Operands that are data-segment addresses (globals).
DATA_OPERANDS = {OP[n] for n in ("LOAD_PRI", "LOAD_ALT", "LREF_PRI", "LREF_ALT", "STOR_PRI", "STOR_ALT",
                                 "SREF_PRI", "SREF_ALT", "INC", "DEC", "LOAD_P_PRI", "LOAD_P_ALT", "LREF_P_PRI",
                                 "LREF_P_ALT", "STOR_P_PRI", "STOR_P_ALT", "SREF_P_PRI", "SREF_P_ALT", "INC_P",
                                 "DEC_P", "LOAD_BOTH", "ZERO", "ZERO_P")}
# Constants that may be addresses of string literals in the data segment.
CONSTANTS = {OP[n] for n in ("CONST_PRI", "CONST_ALT", "PUSH_C", "PUSH_P_C", "CONST_P_PRI", "CONST_P_ALT",
                             "PUSH2_C", "PUSH3_C", "PUSH4_C", "PUSH5_C")}


def s32(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


@dataclass
class Instruction:
    addr: int            # offset in the code segment
    op: int
    args: list[int]
    size: int            # in bytes
    cases: list[tuple[int, int]] = field(default_factory=list)  # CASETBL: (value, target); first is default

    @property
    def name(self) -> str:
        return OPCODES[self.op]


@dataclass
class AmxFile:
    name: str
    header: dict
    code: bytes
    data: bytes
    publics: list[tuple[int, str]]
    natives: list[str]
    pubvars: list[tuple[int, str]]
    tags: list[tuple[int, str]]
    libraries: list[str]

    @classmethod
    def load(cls, path: Path) -> "AmxFile":
        raw = path.read_bytes()
        fields = struct.unpack_from("<iHBBhh12i", raw, 0)
        keys = ("size magic file_version amx_version flags defsize cod dat hea stp cip publics natives "
                "libraries pubvars tags nametable overlays").split()
        h = dict(zip(keys, fields))
        if h["magic"] != AMX_MAGIC:
            raise ValueError(f"{path}: not a 32-bit AMX file (magic {h['magic']:#x})")
        if h["file_version"] != 10:
            raise ValueError(f"{path}: file version {h['file_version']} (only 10 is supported)")

        image = raw[h["cod"]:h["size"]]
        if h["flags"] & FLAG_COMPACT:
            image = expand(image, h["hea"] - h["cod"])
        code, data = image[:h["dat"] - h["cod"]], image[h["dat"] - h["cod"]:]

        def name_at(offset: int) -> str:
            return raw[offset:raw.index(b"\0", offset)].decode("latin-1")

        def table(start: int, end: int) -> list[tuple[int, str]]:
            return [(struct.unpack_from("<I", raw, o)[0], name_at(struct.unpack_from("<I", raw, o + 4)[0]))
                    for o in range(start, end, h["defsize"])]

        return cls(
            name=path.stem,
            header=h,
            code=code,
            data=data,
            publics=table(h["publics"], h["natives"]),
            natives=[n for _, n in table(h["natives"], h["libraries"])],
            libraries=[n for _, n in table(h["libraries"], h["pubvars"])],
            pubvars=table(h["pubvars"], h["tags"]),
            tags=table(h["tags"], h["nametable"]),
        )

    def cell(self, offset: int) -> int:
        return struct.unpack_from("<I", self.code, offset)[0]

    def instructions(self):
        """Decodes the code segment linearly (Pawn emits no data inside code)."""
        try:
            yield from decode(self.code)
        except ValueError as e:
            raise ValueError(f"{self.name}: {e}") from e

    def string_at(self, addr: int, strict: bool = True) -> str | None:
        """Returns the string literal stored at a data address, packed or unpacked. Not strict (the
        address is known to be a string): may follow another value, may be a single character."""
        if addr < 0 or addr % 4 or addr + 4 > len(self.data):
            return None
        if addr >= 4 and strict:
            before = struct.unpack_from("<I", self.data, addr - 4)[0]
            if before != 0 and before & 0xFF != 0:   # inside another string, not at its start
                return None
        cells = []
        for o in range(addr, min(len(self.data), addr + 4 * 256), 4):
            c = struct.unpack_from("<I", self.data, o)[0]
            cells.append(c)
            if c == 0 or (c & 0xFF) == 0:
                break
        if not cells or cells[0] == 0:
            return None
        if all(c < 0x100 for c in cells) and cells[-1] == 0:      # unpacked: one character per cell
            chars = bytes(cells[:-1])
        elif cells[0] > 0xFFFFFF:                                  # packed: big-endian bytes in each cell
            chars = b"".join(struct.pack(">I", c) for c in cells).split(b"\0")[0]
        else:
            return None
        if len(chars) < (2 if strict else 1) or not all(0x20 <= b < 0x7F or b in (9, 10, 13) for b in chars):
            return None
        return chars.decode("latin-1")


def decode(code: bytes, start: int = 0, end: int | None = None):
    """Instructions of a code segment (expanded), from start to end. Branch operands are relative to
    the opcode; CASETBL targets are given as absolute code addresses in Instruction.cases."""
    def cell(offset: int) -> int:
        return struct.unpack_from("<I", code, offset)[0]

    cip = start
    end = len(code) if end is None else end
    while cip < end:
        raw = cell(cip)
        op = raw & 0xFFFF
        if op >= len(OPCODES) or op in INVALID:
            raise ValueError(f"invalid opcode {op} at {cip:#x}")
        if PACKED_FIRST <= op <= PACKED_LAST:
            yield Instruction(cip, op, [s32(raw) >> 16], 4)
            cip += 4
        elif op in (OP["CASETBL"], OP["ICASETBL"]):
            num = cell(cip + 4)
            cases = [(0, cip + 4 + 4 + s32(cell(cip + 8)) - 4)]
            for i in range(num):
                entry = cip + 12 + 8 * i
                cases.append((s32(cell(entry)), entry + 4 + s32(cell(entry + 4)) - 4))
            size = 4 + 4 * (2 * num + 2)
            yield Instruction(cip, op, [num], size, cases)
            cip += size
        else:
            n = NPARAMS[OPCODES[op]]
            yield Instruction(cip, op, [s32(cell(cip + 4 + 4 * i)) for i in range(n)], 4 + 4 * n)
            cip += 4 + 4 * n


def expand(compact: bytes, memsize: int) -> bytes:
    """Decodes the compact encoding: each cell is a big-endian run of 7-bit groups
    (bit 7 = continuation), sign-extended from bit 6 of its first byte."""
    out = bytearray()
    i = 0
    while i < len(compact):
        value = -1 if compact[i] & 0x40 else 0
        while True:
            b = compact[i]
            i += 1
            value = (value << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        out += struct.pack("<I", value & 0xFFFFFFFF)
    if len(out) != memsize:
        raise ValueError(f"compact code expands to {len(out):#x} bytes, header says {memsize:#x}")
    return bytes(out)


def compress(image: bytes) -> bytes:
    """Compact encoding, the inverse of expand(), byte for byte as the Pawn 3.3 compiler wrote the game's
    files: the fewest 7-bit groups that sign-extend back to the cell, except that a cell needing all five
    groups gets its top group unsigned (cell >> 28)."""
    out = bytearray()
    for (value,) in struct.iter_unpack("<i", image):
        groups = []
        v = value
        while True:
            groups.append(v & 0x7F)
            v >>= 7
            if (v == 0 and not groups[-1] & 0x40) or (v == -1 and groups[-1] & 0x40):
                break
        if len(groups) == 5:
            groups[4] = (value & 0xFFFFFFFF) >> 28
        groups.reverse()
        out += bytes(g | 0x80 for g in groups[:-1]) + bytes([groups[-1]])
    return bytes(out)


class AmxPatcher:
    """Edits a script in place: string literals of the data segment and instruction operands, then
    writes the file back (compact encoding included). Addresses are those of the disassembly
    (decomp/scripts/asm/*.asm): code addresses for instructions, data addresses for literals."""

    def __init__(self, raw: bytes) -> None:
        fields = struct.unpack_from("<iHBBhhiiii", raw, 0)
        self.size, magic, version, _, self.flags, _, self.cod, self.dat, self.hea, _ = fields
        if magic != AMX_MAGIC or version != 10:
            raise ValueError("not a Pawn 3.3 AMX file")
        self.prefix = bytearray(raw[:self.cod])
        image = raw[self.cod:self.size]
        if self.flags & FLAG_COMPACT:
            image = expand(image, self.hea - self.cod)
        self.image = bytearray(image)

    @property
    def data_base(self) -> int:
        return self.dat - self.cod

    def _cell(self, offset: int) -> int:
        return struct.unpack_from("<i", self.image, offset)[0]

    def _string(self, addr: int) -> tuple[str, bool, int] | None:
        """(text, packed, cells) of the literal at a data address, or None."""
        base = self.data_base + addr
        cells = []
        while base + 4 * len(cells) + 4 <= len(self.image) and len(cells) < 256:
            c = self._cell(base + 4 * len(cells)) & 0xFFFFFFFF
            cells.append(c)
            if c == 0 or c & 0xFF == 0:
                break
        if not cells or cells[0] == 0:
            return None
        if all(c < 0x100 for c in cells) and cells[-1] == 0:
            return bytes(cells[:-1]).decode("latin-1"), False, len(cells)
        if cells[0] > 0xFFFFFF:
            text = b"".join(struct.pack(">I", c) for c in cells).split(b"\0")[0]
            return text.decode("latin-1"), True, len(cells)
        return None

    def find_string(self, text: str) -> list[int]:
        found = []
        for addr in range(0, len(self.image) - self.data_base, 4):
            if addr >= 4 and self._string(addr - 4) and self._string(addr - 4)[0].endswith(text) \
                    and self._string(addr - 4)[0] != text:
                continue                                          # tail of a longer literal
            s = self._string(addr)
            if s and s[0] == text:
                found.append(addr)
        return found

    def replace_string(self, addr: int, old: str, new: str) -> None:
        current = self._string(addr)
        if current is None or current[0] != old:
            raise ValueError(f"no literal {old!r} at data address {addr:#x}")
        _, packed, cells = current
        if packed:
            raw = new.encode("latin-1") + b"\0"
            raw += bytes(-len(raw) % 4)
            values = [struct.unpack(">I", raw[i:i + 4])[0] for i in range(0, len(raw), 4)]
        else:
            values = list(new.encode("latin-1")) + [0]
        if len(values) > cells:
            raise ValueError(f"{new!r} is longer than {old!r}")
        values += [0] * (cells - len(values))
        for n, v in enumerate(values):
            struct.pack_into("<I", self.image, self.data_base + addr + 4 * n, v)

    def set_operand(self, cip: int, index: int, value: int, expect: int | None = None) -> None:
        op = self._cell(cip) & 0xFFFF
        if op >= len(OPCODES) or index >= NPARAMS[OPCODES[op]]:
            raise ValueError(f"no operand {index} at code address {cip:#x}")
        offset = cip + 4 + 4 * index
        if expect is not None and self._cell(offset) != expect:
            raise ValueError(f"operand {index} at {cip:#x} is {self._cell(offset):#x}, not {expect:#x}")
        struct.pack_into("<i", self.image, offset, value)

    def write(self) -> bytes:
        image = compress(bytes(self.image)) if self.flags & FLAG_COMPACT else bytes(self.image)
        struct.pack_into("<i", self.prefix, 0, len(self.prefix) + len(image))
        return bytes(self.prefix) + image


# --------------------------------------------------------------------------------------------
# Native functions implemented by the game (code.bin)

_SEGMENTS = ((0x00100000, 0x000000, 0x251408), (0x00352000, 0x252000, 0x0332D0), (0x00386000, 0x286000, 0x02EAE4))


def _vaddr_to_offset(addr: int) -> int | None:
    for base, offset, size in _SEGMENTS:
        if base <= addr < base + size:
            return offset + addr - base
    return None


def read_linker_map(path: Path) -> dict[int, tuple[str, str]]:
    symbols = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"^0x([0-9a-fA-F]+)\s+(\d+)\s+(.+)\s+(\S+)$", line.strip())
        if m:
            symbols[int(m[1], 16)] = (m[3], m[4])
    return symbols


def find_native_tables(code_bin: bytes, amx_register: int) -> dict[str, int]:
    """Native name -> implementation address, from every `ldr r1, =table; ...; b(l) amx_Register`.

    AMX_NATIVE_INFO is declared packed, so the tables are not necessarily aligned.
    """
    import capstone

    def word(addr: int) -> int:
        return struct.unpack_from("<I", code_bin, _vaddr_to_offset(addr))[0]

    def cstr(addr: int) -> str | None:
        o = _vaddr_to_offset(addr)
        end = code_bin.find(b"\0", o, o + 96) if o is not None else -1
        name = code_bin[o:end] if end > 0 else b""
        return name.decode() if re.fullmatch(rb"[A-Za-z_@][\w@.]*", name) else None

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    md.skipdata = True
    text_base, _, text_size = _SEGMENTS[0]
    insns = list(md.disasm(code_bin[:text_size], text_base))
    natives = {}
    for k, insn in enumerate(insns):
        if insn.mnemonic not in ("b", "bl") or insn.op_str != f"#{amx_register:#x}":
            continue
        for prev in reversed(insns[max(0, k - 12):k]):
            m = re.match(r"r1, \[pc, #(-?0x[0-9a-f]+|-?\d+)\]", prev.op_str)
            if prev.mnemonic == "ldr" and m:
                entry = word(prev.address + 8 + int(m[1], 0))
                while word(entry) or word(entry + 4):
                    name = cstr(word(entry))
                    if name is None:
                        break
                    natives[name] = word(entry + 4)
                    entry += 8
                break
    return natives


# --------------------------------------------------------------------------------------------
# Disassembly listing

_LOG_TAG = re.compile(r"^\[([\w.]+)::(\w+)(?:<\w+>)?\]")   # update<Dialog>: implementation for a state
_LOG_FUNCTION = re.compile(r"^\[([a-z]\w*[A-Z]\w*)\]")   # "[btnsupActivateButton] ...": camelCase, no file


def function_names(amx: AmxFile, insns: list[Instruction]) -> dict[int, tuple[str, str]]:
    """Names functions after the "[file.inc::function]" (or "[function]") prefix of the log strings
    they print. Returns {address: (file, function)}, file is "" when the prefix has none."""
    names = {}
    start, tags = None, []
    for i in insns + [Instruction(len(amx.code), OP["PROC"], [], 0)]:
        if i.op == OP["PROC"]:
            if start is not None and tags:
                names[start] = max(set(tags), key=tags.count)
            start, tags = i.addr, []
        elif i.op in CONSTANTS:
            for a in i.args:
                text = amx.string_at(a) or ""
                if m := _LOG_TAG.match(text):
                    tags.append((m[1], m[2]))
                elif m := _LOG_FUNCTION.match(text):
                    tags.append(("", m[1]))
    publics = {addr for addr, _ in amx.publics}
    return {addr: tag for addr, tag in names.items() if addr not in publics}


def disassemble(amx: AmxFile, natives: dict[str, tuple[int, str]] | None = None) -> str:
    natives = natives or {}
    insns = list(amx.instructions())
    publics = {addr: name for addr, name in amx.publics}
    pubvars = {addr: name for addr, name in amx.pubvars}

    calls = {i.addr + i.args[0] for i in insns if i.op == OP["CALL"]}
    names = function_names(amx, insns)
    jumps = {i.addr + i.args[0] for i in insns if i.op in BRANCHES and i.op != OP["CALL"]}
    for i in insns:
        jumps.update(target for _, target in i.cases)

    def code_label(addr: int) -> str:
        if addr in publics:
            return publics[addr]
        if addr in names:
            return names[addr][1]
        return f"func_{addr:04x}" if addr in calls else f"L_{addr:04x}"

    def data_ref(addr: int) -> str:
        return pubvars.get(addr, f"g_{addr:04x}")

    h = amx.header
    out = [
        f"; {amx.name}.amx - Pawn AMX file version {h['file_version']}, flags {h['flags']:#x}",
        f"; code {len(amx.code):#x} bytes, data {len(amx.data):#x} bytes, stack+heap {h['stp'] - h['hea']:#x}",
        f"; entry point (main): {code_label(h['cip']) if h['cip'] >= 0 else 'none'}",
        f"; {len(amx.publics)} publics, {len(amx.natives)} natives, {len(amx.pubvars)} public variables",
    ]
    if amx.pubvars:
        out.append(";")
        out += [f"; public variable {name} = data[{addr:#x}]" for addr, name in amx.pubvars]
    out.append(";")
    for index, name in enumerate(amx.natives):
        impl = natives.get(name)
        out.append(f"; native {index:3d} {name}" + (f"  -> {impl[1]} @ {impl[0]:#010x}" if impl else ""))

    for k, i in enumerate(insns):
        if i.op == OP["PROC"]:
            kind = "public" if i.addr in publics else "function"
            source = f" ({names[i.addr][0]})" if i.addr in names and names[i.addr][0] else ""
            out += ["", f"; ---- {kind} {code_label(i.addr)}{source}"]
        if i.addr in publics or i.addr in calls or i.addr in jumps:
            out.append(f"{code_label(i.addr)}:")

        text = i.name.lower().replace("_", ".")
        comment = ""
        if i.op in BRANCHES:
            operands = code_label(i.addr + i.args[0])
        elif i.op == OP["SYSREQ_C"] or i.op == OP["SYSREQ_N"]:
            index = i.args[0]
            name = amx.natives[index] if index < len(amx.natives) else f"native_{index}"
            operands = name + (f", {i.args[1] // 4} arg(s)" if i.op == OP["SYSREQ_N"] else "")
        elif i.cases:
            operands = f"{i.args[0]} case(s)"
            out.append(f"    {i.addr:05x}  {text:14s} {operands}")
            out.append(f"                   default -> {code_label(i.cases[0][1])}")
            out += [f"                   {value:#x} -> {code_label(target)}" for value, target in i.cases[1:]]
            continue
        elif i.op in DATA_OPERANDS:
            operands = ", ".join(data_ref(a) for a in i.args)
        else:
            operands = ", ".join(f"{a:#x}" if abs(a) > 9 else str(a) for a in i.args)
            arg_count = i.op == OP["PUSH_C"] and k + 1 < len(insns) and insns[k + 1].op == OP["CALL"]
            if i.op in CONSTANTS and not arg_count:
                strings = [s for s in (amx.string_at(a) for a in i.args) if s]
                if strings:
                    comment = "  ; " + ", ".join(repr(s) for s in strings)
        out.append(f"    {i.addr:05x}  {text:14s} {operands}{comment}".rstrip())
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help=".amx files (default: every romfs:/amx script)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "decomp" / "scripts" / "asm")
    args = ap.parse_args()

    symbols = read_linker_map(ROOT / "extracted" / "romfs" / "map")
    amx_register = next(addr for addr, (name, _) in symbols.items() if name == "amx_Register")
    native_impl = find_native_tables((ROOT / "extracted" / "code.bin").read_bytes(), amx_register)
    natives = {name: (addr, symbols.get(addr, (f"FUN_{addr:08x}", ""))[0]) for name, addr in native_impl.items()}
    print(f"[+] {len(natives)} native functions found in code.bin")

    files = args.files or sorted((ROOT / "extracted" / "romfs" / "amx").glob("*.amx"))
    args.out.mkdir(parents=True, exist_ok=True)
    missing: dict[str, list[str]] = {}
    for path in files:
        amx = AmxFile.load(path)
        (args.out / f"{amx.name}.asm").write_text(disassemble(amx, natives))
        for name in amx.natives:
            if name not in natives:
                missing.setdefault(name, []).append(amx.name)
    print(f"[+] {len(files)} scripts disassembled into {args.out}")
    if missing:
        print(f"[!] natives without a C implementation: {sorted(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
