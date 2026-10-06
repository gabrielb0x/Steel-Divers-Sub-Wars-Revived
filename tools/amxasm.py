#!/usr/bin/env python3
"""Pawn AMX assembler: adds code, data, natives and public functions to a script of the game, and
hooks its existing instructions. Used by tools/mod.py ([[amx]] entries with asm = "...").

A script (romfs:/amx/*.amx, Pawn 3.3, file version 10, compact encoding) is read whole: header,
tables (publics, natives, libraries, public variables, tags), name table, code and data. New code and
data are appended at the end of their segment, so nothing that exists moves: data addresses are
relative to the data segment, branch operands relative to the instruction. A new native goes at the
end of the native table (indexes of the others unchanged); a new public is inserted in name order
(amx_FindPublic searches the table by bisection). write() rebuilds the file; an unchanged script is
written back byte for byte.

Assembly, one instruction per line, with the mnemonics of the disassembly (decomp/scripts/asm/):

    label:                          a label of the new code (referenced as @label)
        const.pri 1                 numbers: 12, -0x28, float(1.5) for a Float
        push.c "server.bots"        a string: stored once in the new data, unpacked (one char per cell)
        sysreq.n sysGetGlobal, 1    a native by name, and its number of arguments (added if missing)
        stor.pri g_504c             an existing global by its address (g_<hex>), or a new one ($name)
        jzer @skip                  a branch to a new label, or 0x1234: an address of the original code
        call 0x6150                 a function of the original script (address of its PROC)

    .hook 0x143f4                   the instruction(s) at this address (at least 8 bytes of whole
                                    instructions) become a jump to the code that follows
    .original                       the instructions the hook replaced, as they were
    .return                         jump back after them
    .public @serverEvent            the next label is also a public function of that name
    .var $name [count]              a new global (zeroed), count cells (default 1)
    .cells $name 1, 2, 3            a new global array with these values
    .string $name "text"            a new string
    .data_at 0x4524                 the new data must start there (code compiled by tools/pawn2pasm.py)

Comments start with ';'. Pawn functions: PROC, arguments at frame offsets 12, 16..., RETN;
`push.c <bytes>` + `call` to call one (see decomp/scripts/asm for the game's own code).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from amx import AMX_MAGIC, BRANCHES, FLAG_COMPACT, INVALID, NPARAMS, OP, OPCODES, compress, decode, expand, s32

HEADER = struct.Struct("<iHBBhh12i")
NOP = OP["NOP"]
JUMP = OP["JUMP"]


class AsmError(ValueError):
    pass


@dataclass
class AmxImage:
    """A whole script, editable and growable."""
    version: tuple[int, int, int]          # file_version, amx_version, flags
    defsize: int
    cip: int
    # tables: (value, name, offset of the name in the name table, None for a new entry); the value of a
    # public is its address, a native's is filled in at run time by amx_Register
    publics: list[tuple[int, str, int | None]]
    natives: list[tuple[int, str, int | None]]
    libraries: list[tuple[int, str, int | None]]
    pubvars: list[tuple[int, str, int | None]]
    tags: list[tuple[int, str, int | None]]
    names: bytearray                       # the name table: u16 longest name, then the names
    code: bytearray
    data: bytearray
    heapstack: int                         # stp - hea: room for the heap and the stack
    prefix_pad: bytes = b""                # bytes between the end of the names and the code
    labels: dict[str, int] = field(default_factory=dict)          # new code labels -> address
    data_labels: dict[str, int] = field(default_factory=dict)     # new data labels -> address
    strings: dict[str, int] = field(default_factory=dict)         # new strings -> address
    hooked: dict[int, int] = field(default_factory=dict)          # hook address -> replaced bytes

    # ---- reading and writing -----------------------------------------------------------------

    @classmethod
    def parse(cls, raw: bytes) -> "AmxImage":
        f = HEADER.unpack_from(raw, 0)
        size, magic, file_version, amx_version, flags, defsize = f[:6]
        cod, dat, hea, stp, cip, publics, natives, libraries, pubvars, tags, nametable, overlays = f[6:]
        if magic != AMX_MAGIC or file_version != 10:
            raise AsmError("not a Pawn 3.3 AMX file")
        if overlays != nametable or publics != HEADER.size:
            raise AsmError("unexpected AMX layout (overlays)")

        def table(start: int, end: int) -> list[tuple[int, str, int]]:
            """(value, name, offset of the name in the name table)"""
            out = []
            for o in range(start, end, defsize):
                value, offset = struct.unpack_from("<II", raw, o)
                out.append((value, raw[offset:raw.index(b"\0", offset)].decode("latin-1"), offset - nametable))
            return out

        names_end = nametable + 2
        while names_end < cod and raw[names_end]:
            names_end = raw.index(b"\0", names_end) + 1
        image = raw[cod:size]
        if flags & FLAG_COMPACT:
            image = expand(image, hea - cod)
        return cls(version=(file_version, amx_version, flags), defsize=defsize, cip=cip,
                   publics=table(publics, natives), natives=table(natives, libraries),
                   libraries=table(libraries, pubvars), pubvars=table(pubvars, tags), tags=table(tags, nametable),
                   names=bytearray(raw[nametable:names_end]), code=bytearray(image[:dat - cod]),
                   data=bytearray(image[dat - cod:]), heapstack=stp - hea, prefix_pad=raw[names_end:cod])

    def write(self) -> bytes:
        tables = [self.publics, self.natives, self.libraries, self.pubvars, self.tags]
        offsets, at = [], HEADER.size
        for t in tables:
            offsets.append(at)
            at += len(t) * self.defsize
        nametable = at
        names = bytearray(self.names)
        for t in tables:                                   # names of the new entries, after the others
            for n, (value, name, offset) in enumerate(t):
                if offset is None:
                    t[n] = (value, name, len(names))
                    names += name.encode("latin-1") + b"\0"
        longest = max([len(name) for t in tables for _, name, _ in t] + [0])
        if longest > struct.unpack_from("<H", names, 0)[0]:
            struct.pack_into("<H", names, 0, longest)       # Pawn sizes its name buffers with it
        pad = self.prefix_pad if len(names) == len(self.names) else bytes(-(nametable + len(names)) % 4)
        cod = nametable + len(names) + len(pad)
        prefix = bytearray(HEADER.size)
        for t in tables:
            for value, name, offset in t:
                prefix += struct.pack("<II", value & 0xFFFFFFFF, nametable + offset) + bytes(self.defsize - 8)
        prefix += names + pad
        image = bytes(self.code) + bytes(self.data)
        body = compress(image) if self.version[2] & FLAG_COMPACT else image
        dat = cod + len(self.code)
        hea = dat + len(self.data)
        HEADER.pack_into(prefix, 0, len(prefix) + len(body), AMX_MAGIC, self.version[0], self.version[1],
                         self.version[2], self.defsize, cod, dat, hea, hea + self.heapstack, self.cip,
                         *offsets, nametable, nametable)
        return bytes(prefix) + body

    # ---- in-place edits (strings of the data segment, operands) ---------------------------------

    def cell(self, address: int, data: bool = False) -> int:
        return struct.unpack_from("<i", self.data if data else self.code, address)[0]

    def string(self, address: int) -> tuple[str, bool, int] | None:
        """(text, packed, cells) of the literal at a data address, or None."""
        cells = []
        while address + 4 * len(cells) + 4 <= len(self.data) and len(cells) < 256:
            c = self.cell(address + 4 * len(cells), True) & 0xFFFFFFFF
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
        for addr in range(0, len(self.data), 4):
            before = self.string(addr - 4) if addr >= 4 else None
            if before and before[0].endswith(text) and before[0] != text:
                continue                                          # tail of a longer literal
            s = self.string(addr)
            if s and s[0] == text:
                found.append(addr)
        return found

    def replace_string(self, address: int, old: str, new: str) -> None:
        current = self.string(address)
        if current is None or current[0] != old:
            raise AsmError(f"no literal {old!r} at data address {address:#x}")
        _, packed, cells = current
        if packed:
            raw = new.encode("latin-1") + b"\0"
            raw += bytes(-len(raw) % 4)
            values = [struct.unpack(">I", raw[i:i + 4])[0] for i in range(0, len(raw), 4)]
        else:
            values = list(new.encode("latin-1")) + [0]
        if len(values) > cells:
            raise AsmError(f"{new!r} is longer than {old!r}")
        values += [0] * (cells - len(values))
        for n, v in enumerate(values):
            struct.pack_into("<I", self.data, address + 4 * n, v)

    def set_operand(self, cip: int, index: int, value: int, expect: int | None = None) -> None:
        op = self.cell(cip) & 0xFFFF
        if op >= len(OPCODES) or index >= NPARAMS[OPCODES[op]]:
            raise AsmError(f"no operand {index} at code address {cip:#x}")
        offset = cip + 4 + 4 * index
        if expect is not None and self.cell(offset) != expect:
            raise AsmError(f"operand {index} at {cip:#x} is {self.cell(offset):#x}, not {expect:#x}")
        struct.pack_into("<i", self.code, offset, value)

    # ---- growing ---------------------------------------------------------------------------------

    def native(self, name: str) -> int:
        for index, (_, n, _) in enumerate(self.natives):
            if n == name:
                return index
        self.natives.append((0, name, None))
        return len(self.natives) - 1

    def add_public(self, name: str, address: int) -> None:
        if any(n == name for _, n, _ in self.publics):
            raise AsmError(f"public {name} already exists")
        self.publics.append((address, name, None))
        self.publics.sort(key=lambda p: p[1].encode("latin-1"))

    def add_data(self, cells: list[int]) -> int:
        address = len(self.data)
        for c in cells:
            self.data += struct.pack("<I", c & 0xFFFFFFFF)
        return address

    def add_string(self, text: str) -> int:
        if text not in self.strings:
            self.strings[text] = self.add_data(list(text.encode("latin-1")) + [0])
        return self.strings[text]

    def branch_targets(self) -> set[int]:
        """Every address the original code can reach other than by falling through."""
        targets = {addr for addr, _, _ in self.publics} | {self.cip}
        for i in decode(self.code):
            if i.op in BRANCHES:
                targets.add(i.addr + i.args[0])
            targets.update(t for _, t in i.cases)
        return targets

    def assemble(self, source: str) -> None:
        Assembler(self).run(source)


# ---- the assembler -------------------------------------------------------------------------------

_LINE = re.compile(r'^(?:(?P<label>[@\w.$]+):)?\s*(?P<body>.*?)\s*$')


def _split_operands(text: str) -> list[str]:
    out, current, quoted = [], "", False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == "," and not quoted:
            out.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        out.append(current.strip())
    return out


def _strip_comment(line: str) -> str:
    quoted = False
    for n, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ";" and not quoted:
            return line[:n]
    return line


@dataclass
class _Insn:
    op: int
    operands: list[str]
    line: str
    address: int = 0
    raw: list[int] | None = None           # .original: cells copied from the script
    raw_branch: int | None = None          # their branch target, if any


class Assembler:
    def __init__(self, image: AmxImage) -> None:
        self.image = image
        self.targets: set[int] | None = None
        self.pending: list[tuple[int, int]] = []           # hooks of this source: (address, size)

    def _hook(self, address: int) -> tuple[int, list[int], tuple | None]:
        """Whole instructions from address covering at least 8 bytes: (size, cells)."""
        if self.targets is None:
            self.targets = self.image.branch_targets()
        size, cells, branch = 0, [], None
        for i in decode(self.image.code, address):
            if size and i.addr in self.targets:
                raise AsmError(f"hook at {address:#x}: {i.addr:#x} is a branch target, cannot be replaced")
            if i.op in (OP["CASETBL"], OP["ICASETBL"], OP["PROC"]) or (i.op in BRANCHES and branch is not None):
                raise AsmError(f"hook at {address:#x}: {OPCODES[i.op].lower()} at {i.addr:#x} cannot be moved")
            if i.op in BRANCHES:
                branch = (len(cells), i.addr + i.args[0], i.addr - address)
            cells += [self.image.cell(i.addr + 4 * k) for k in range(i.size // 4)]
            size += i.size
            if size >= 8:
                break
        if size < 8:
            raise AsmError(f"hook at {address:#x}: not enough instructions")
        for start, length in list(self.image.hooked.items()) + self.pending:
            if start < address + size and address < start + length:
                raise AsmError(f"hook at {address:#x}: overlaps the hook at {start:#x}")
        self.pending.append((address, size))
        return size, cells, branch

    def run(self, source: str) -> None:
        img = self.image
        items: list[_Insn | tuple] = []
        hooks: list[tuple[int, int, str]] = []                       # (address, size, label)
        pending_public: list[str] = []
        current_hook: tuple[int, int, list[int], tuple | None] | None = None
        hook_count = 0
        for number, line in enumerate(source.splitlines(), 1):
            text = _strip_comment(line).strip()
            if not text:
                continue
            m = _LINE.match(text)
            label, body = m["label"], m["body"]
            where = f"line {number}: {line.strip()}"
            if label:
                items.append(("label", label.lstrip("@"), where))
                for name in pending_public:
                    items.append(("public", name, label.lstrip("@")))
                pending_public = []
            if not body:
                continue
            words = body.split(None, 1)
            mnemonic, rest = words[0].lower(), (words[1] if len(words) > 1 else "")
            operands = _split_operands(rest)
            if mnemonic == ".hook":
                address = int(operands[0], 0)
                size, cells, branch = self._hook(address)
                hook_label = f".hook{hook_count}"
                hook_count += 1
                hooks.append((address, size, hook_label))
                current_hook = (address, size, cells, branch)
                items.append(("label", hook_label, where))
            elif mnemonic == ".original":
                if current_hook is None:
                    raise AsmError(f"{where}: .original outside a .hook")
                address, size, cells, branch = current_hook
                items.append(_Insn(-1, [], where, raw=cells,
                                   raw_branch=branch))
            elif mnemonic == ".return":
                if current_hook is None:
                    raise AsmError(f"{where}: .return outside a .hook")
                items.append(_Insn(JUMP, [f"{current_hook[0] + current_hook[1]:#x}"], where))
            elif mnemonic == ".public":
                pending_public.append(operands[0])
            elif mnemonic == ".data_at":
                if len(img.data) != self._number(operands[0], where):
                    raise AsmError(f"{where}: the new data would start at {len(img.data):#x}: this code, "
                                   "compiled by tools/pawn2pasm.py, must be the first to add data to the script")
            elif mnemonic in (".var", ".cells", ".string"):
                name = operands[0].split()[0]
                if not name.startswith("$"):
                    raise AsmError(f"{where}: data names start with $")
                if name in img.data_labels:
                    raise AsmError(f"{where}: {name} defined twice")
                if mnemonic == ".var":
                    count = int(operands[0].split()[1], 0) if len(operands[0].split()) > 1 else 1
                    img.data_labels[name] = img.add_data([0] * count)
                elif mnemonic == ".cells":
                    first = operands[0].split(None, 1)
                    values = ([first[1]] if len(first) > 1 else []) + operands[1:]
                    img.data_labels[name] = img.add_data([self._number(v, where) for v in values])
                else:
                    literal = rest.split(None, 1)[1].strip()
                    if not (literal.startswith('"') and literal.endswith('"')):
                        raise AsmError(f"{where}: .string $name \"text\"")
                    img.data_labels[name] = img.add_data(list(_unescape(literal[1:-1]).encode("latin-1")) + [0])
            elif mnemonic.startswith("."):
                raise AsmError(f"{where}: unknown directive {mnemonic}")
            else:
                name = mnemonic.replace(".", "_").upper()
                if name not in OP or OP[name] in INVALID or name in ("CASETBL", "ICASETBL"):
                    raise AsmError(f"{where}: unknown instruction {mnemonic}")
                items.append(_Insn(OP[name], operands, where))
        if pending_public:
            raise AsmError(f".public {pending_public[0]} is not followed by a label")

        # Layout: the new code goes at the end of the code segment.
        address = len(img.code)
        local: dict[str, int] = {}
        for item in items:
            if isinstance(item, tuple):
                if item[0] == "label":
                    if item[1] in local or item[1] in img.labels:
                        raise AsmError(f"{item[2]}: label {item[1]} defined twice")
                    local[item[1]] = address
                continue
            item.address = address
            if item.raw is not None:
                address += 4 * len(item.raw)
            else:
                n = NPARAMS[OPCODES[item.op]]
                if item.op == OP["SYSREQ_N"]:
                    n = 2
                if len(item.operands) != n:
                    raise AsmError(f"{item.line}: {OPCODES[item.op].lower()} takes {n} operand(s)")
                address += 4 + 4 * n
        img.labels.update(local)

        # Encoding.
        out = bytearray()
        for item in items:
            if isinstance(item, tuple):
                if item[0] == "public":
                    img.add_public(item[1], img.labels[item[2]])
                continue
            if item.raw is not None:
                cells = list(item.raw)
                if item.raw_branch is not None:
                    index, target, offset = item.raw_branch
                    cells[index + 1] = target - (item.address + offset)
                out += b"".join(struct.pack("<i", s32(c & 0xFFFFFFFF)) for c in cells)
                continue
            cells = [item.op]
            for k, operand in enumerate(item.operands):
                cells.append(self._operand(item, k, operand))
            out += b"".join(struct.pack("<i", c) for c in cells)
        img.code += out

        # The hooks: a jump to their code, then NOPs over the rest of the replaced instructions.
        for address, size, label in hooks:
            jump = struct.pack("<ii", JUMP, img.labels[label] - address)
            struct.pack_into(f"<{size}s", img.code, address, jump + struct.pack("<i", NOP) * ((size - 8) // 4))
            img.hooked[address] = size
        list(decode(img.code))                                       # every instruction must decode

    def _number(self, text: str, where: str) -> int:
        text = text.strip()
        m = re.fullmatch(r"float\((.+)\)", text)
        if m:
            return struct.unpack("<i", struct.pack("<f", float(m[1])))[0]
        try:
            value = int(text, 0)
        except ValueError:
            raise AsmError(f"{where}: {text!r} is not a number") from None
        if not -(1 << 31) <= value < (1 << 32):
            raise AsmError(f"{where}: {text} does not fit in a cell")
        return s32(value & 0xFFFFFFFF)

    def _operand(self, item: _Insn, k: int, text: str) -> int:
        img = self.image
        op = item.op
        if op in (OP["SYSREQ_C"], OP["SYSREQ_N"]) and k == 0:
            if re.fullmatch(r"[A-Za-z_]\w*", text):
                return img.native(text)
            return self._number(text, item.line)
        if op == OP["SYSREQ_N"] and k == 1:
            return 4 * self._number(text, item.line)                 # arguments -> bytes
        if op in BRANCHES:
            if text.startswith("@"):
                name = text[1:]
                if name not in img.labels:
                    raise AsmError(f"{item.line}: no label {text}")
                target = img.labels[name]
            else:
                target = self._number(text, item.line)
                if not 0 <= target < len(img.code) or target in img.hooked:
                    raise AsmError(f"{item.line}: {text} is not an address of the script's code")
            return target - item.address
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            return img.add_string(_unescape(text[1:-1]))
        if text.startswith("$"):
            if text not in img.data_labels:
                raise AsmError(f"{item.line}: no data {text}")
            return img.data_labels[text]
        m = re.fullmatch(r"g_([0-9a-fA-F]+)", text)
        if m:
            return int(m[1], 16)
        if text.startswith("@"):                                     # address of new code (as a value)
            if text[1:] not in img.labels:
                raise AsmError(f"{item.line}: no label {text}")
            return img.labels[text[1:]]
        return self._number(text, item.line)


def _unescape(text: str) -> str:
    return text.encode("latin-1").decode("unicode_escape")
