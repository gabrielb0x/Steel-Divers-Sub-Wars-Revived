"""A small ARM (A32) assembler in pure Python, for the code patches of the mod recipes (tools/mod.py), so that
players do not need keystone. It covers what patches need, with the encodings keystone (LLVM) produces:

  data processing   and eor sub rsb add adc sbc rsc tst teq cmp cmn orr mov bic mvn [s][cond]
                    operand: #imm, register, register with shift (lsl lsr asr ror #n or by register, rrx)
                    mov/mvn and cmp/cmn swap when only the opposite immediate can be encoded
  multiply          mul mla [s][cond]
  load / store      ldr str ldrb strb [cond]: [rn], [rn, #±imm], [rn, ±rm{, shift #n}], with ! or post-index;
                    ldr rd, label (pc-relative)
                    ldrh strh ldrsh ldrsb [cond]: [rn, #±imm] or [rn, ±rm], ! and post-index
  stack             push pop {reglist} (a single register: str/ldr with writeback, as LLVM does),
                    ldm/stm with ia ib da db (fd ed fa ea), ! and reglists with ranges
  branches          b bl [cond] label or absolute address, bx blx rm
  hint              nop (the ARMv6K hint E320F000, as in the game)
  adr               adr rd, label (add/sub rd, pc, #offset)
  directives        .word .long .short .hword .byte .ascii .asciz .string .align n .balign n .space n
  syntax            labels (name:), comments (@ or //), several statements per line separated by ";"
                    numbers in decimal, 0x hexadecimal, 0b binary, 'c', labels and + - between them
"""

from __future__ import annotations

import re

CONDITIONS = {"eq": 0, "ne": 1, "cs": 2, "hs": 2, "cc": 3, "lo": 3, "mi": 4, "pl": 5, "vs": 6, "vc": 7,
              "hi": 8, "ls": 9, "ge": 10, "lt": 11, "gt": 12, "le": 13, "al": 14}
DATA_OPS = {"and": 0, "eor": 1, "sub": 2, "rsb": 3, "add": 4, "adc": 5, "sbc": 6, "rsc": 7, "tst": 8,
            "teq": 9, "cmp": 10, "cmn": 11, "orr": 12, "mov": 13, "bic": 14, "mvn": 15}
COMPARE = {"tst", "teq", "cmp", "cmn"}
SHIFTS = {"lsl": 0, "asl": 0, "lsr": 1, "asr": 2, "ror": 3}
REGISTERS = {f"r{n}": n for n in range(16)} | {"sb": 9, "sl": 10, "fp": 11, "ip": 12, "sp": 13, "lr": 14,
                                                 "pc": 15}
LDM_MODES = {"ia": (0, 1), "ib": (1, 1), "da": (0, 0), "db": (1, 0)}       # P, U
LDM_STACK = {"ldm": {"fd": "ia", "ed": "ib", "fa": "da", "ea": "db"},
             "stm": {"fd": "db", "ed": "da", "fa": "ib", "ea": "ia"}}


class AsmError(Exception):
    pass


def assemble(source: str, address: int) -> bytes:
    """Assembles source for an image loaded at address."""
    statements = []
    for number, line in enumerate(source.splitlines(), 1):
        line = re.split(r"@|//", _mask_strings(line), maxsplit=1)[0]
        line = _restore(source.splitlines()[number - 1], line)
        for part in _split_statements(line):
            statements.append((number, part.strip()))
    # Pass 1: sizes and labels; pass 2: encodings.
    labels: dict[str, int] = {}
    for final in (False, True):
        out = bytearray()
        for number, text in statements:
            try:
                while True:
                    m = re.match(r"^([A-Za-z_.$][\w.$]*)\s*:\s*", text)
                    if not m:
                        break
                    if not final:
                        if m[1] in labels:
                            raise AsmError(f"label {m[1]} defined twice")
                        labels[m[1]] = address + len(out)
                    text = text[m.end():]
                if text:
                    out += _statement(text, address + len(out), labels, final)
            except AsmError as e:
                raise AsmError(f"line {number}: {e}: {text}") from None
    return bytes(out)


# ---- syntax helpers -----------------------------------------------------------------------------

def _mask_strings(line: str) -> str:
    """The line with the inside of string and character literals blanked (to find comments)."""
    return re.sub(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])\'', lambda m: "_" * len(m[0]), line)


def _restore(original: str, cut: str) -> str:
    return original[:len(cut)]


def _split_statements(line: str) -> list[str]:
    parts, current, quoted = [], "", None
    i = 0
    while i < len(line):
        c = line[i]
        if quoted:
            current += c
            if c == "\\" and i + 1 < len(line):
                current += line[i + 1]
                i += 1
            elif c == quoted:
                quoted = None
        elif c in "\"'":
            quoted = c
            current += c
        elif c == ";":
            parts.append(current)
            current = ""
        else:
            current += c
        i += 1
    parts.append(current)
    return [p for p in parts if p.strip()]


def _operands(text: str) -> list[str]:
    """Splits operands on commas outside brackets, braces and strings."""
    out, depth, current, quoted = [], 0, "", None
    for c in text:
        if quoted:
            current += c
            if c == quoted:
                quoted = None
            continue
        if c in "\"'":
            quoted = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(current.strip())
            current = ""
            continue
        current += c
    if current.strip():
        out.append(current.strip())
    return out


def _value(text: str, labels: dict[str, int], final: bool) -> int:
    text = text.strip().lstrip("#").strip()
    if not text:
        raise AsmError("missing value")
    total, sign, pos, first = 0, 1, 0, True
    for m in re.finditer(r"\s*([+-])?\s*('(?:\\.|[^'\\])'|0x[0-9a-fA-F]+|0b[01]+|\d+|[A-Za-z_.$][\w.$]*)\s*", text):
        if m.start() != pos:
            raise AsmError(f"cannot read {text!r}")
        pos = m.end()
        if m[1]:
            sign = -1 if m[1] == "-" else 1
        elif not first:
            raise AsmError(f"cannot read {text!r}")
        first = False
        token = m[2]
        if token.startswith("'"):
            value = ord(_unescape(token[1:-1]))
        elif token[0].isdigit():
            value = int(token, 0)
        elif token in labels:
            value = labels[token]
        elif not final:
            value = 0
        else:
            raise AsmError(f"unknown label {token}")
        total += sign * value
        sign = 1
    if pos != len(text):
        raise AsmError(f"cannot read {text!r}")
    return total


def _unescape(text: str) -> str:
    return re.sub(r"\\(x[0-9a-fA-F]{1,2}|[0-7]{1,3}|.)", lambda m: _escape(m[1]), text)


def _escape(code: str) -> str:
    simple = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'", "a": "\a",
              "b": "\b", "f": "\f", "v": "\v"}
    if code[0] == "x":
        return chr(int(code[1:], 16))
    if code[0] in "01234567" and len(code) > 1 or code[0] in "1234567":
        return chr(int(code, 8))
    return simple.get(code, code)


def _register(text: str) -> int:
    reg = REGISTERS.get(text.strip().lower())
    if reg is None:
        raise AsmError(f"not a register: {text!r}")
    return reg


def _reglist(text: str) -> int:
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise AsmError(f"expected a register list: {text!r}")
    mask = 0
    for part in text[1:-1].split(","):
        if "-" in part:
            low, high = (_register(p) for p in part.split("-"))
            for r in range(low, high + 1):
                mask |= 1 << r
        elif part.strip():
            mask |= 1 << _register(part)
    if not mask:
        raise AsmError("empty register list")
    return mask


def encode_immediate(value: int) -> int | None:
    """The 12-bit rotated form of a data-processing immediate, or None."""
    value &= 0xFFFFFFFF
    for rot in range(16):
        unrotated = (value << 2 * rot | value >> (32 - 2 * rot)) & 0xFFFFFFFF if rot else value
        if unrotated < 0x100:
            return rot << 8 | unrotated
    return None


def _shift(text: str) -> int:
    """Shift of a register operand: bits 11-4 (immediate amount or register)."""
    text = text.strip().lower()
    if text == "rrx":
        return 3 << 5
    m = re.match(r"^(lsl|asl|lsr|asr|ror)\s+(.+)$", text)
    if not m:
        raise AsmError(f"bad shift {text!r}")
    kind = SHIFTS[m[1]]
    amount = m[2].strip()
    if amount.startswith("#"):
        n = int(amount[1:].strip(), 0)
        if n == 0:
            return 0                                    # no shift
        if kind in (1, 2) and n == 32:
            n = 0                                       # lsr #32 and asr #32 are encoded as #0
        elif not 1 <= n <= 31:
            raise AsmError(f"bad shift amount {n}")
        return n << 7 | kind << 5
    return _register(amount) << 8 | kind << 5 | 1 << 4


# ---- statements ---------------------------------------------------------------------------------

def _statement(text: str, pc: int, labels: dict[str, int], final: bool) -> bytes:
    m = re.match(r"^(\.?[A-Za-z][\w.]*)\s*(.*)$", text)
    if not m:
        raise AsmError("cannot read the statement")
    name, rest = m[1].lower(), m[2].strip()
    if name.startswith("."):
        return _directive(name, rest, pc, labels, final)
    if not final:
        return bytes(4)                                 # first pass: only the size counts (labels unknown)
    word = _instruction(name, _operands(rest), pc, labels, final)
    return (word & 0xFFFFFFFF).to_bytes(4, "little")


def _directive(name: str, rest: str, pc: int, labels: dict[str, int], final: bool) -> bytes:
    if name in (".word", ".long", ".int"):
        return b"".join((_value(v, labels, final) & 0xFFFFFFFF).to_bytes(4, "little") for v in _operands(rest))
    if name in (".short", ".hword", ".half"):
        return b"".join((_value(v, labels, final) & 0xFFFF).to_bytes(2, "little") for v in _operands(rest))
    if name == ".byte":
        return bytes(_value(v, labels, final) & 0xFF for v in _operands(rest))
    if name in (".ascii", ".asciz", ".string"):
        out = b""
        for part in _operands(rest):
            if not (len(part) >= 2 and part[0] == part[-1] == '"'):
                raise AsmError(f"expected a string: {part}")
            out += _unescape(part[1:-1]).encode("latin-1") + (b"\0" if name != ".ascii" else b"")
        return out
    if name in (".align", ".p2align", ".balign"):
        n = _value(rest or "2", labels, True)
        size = n if name == ".balign" else 1 << n
        return bytes(-pc % size)
    if name in (".space", ".skip", ".zero"):
        return bytes(_value(rest, labels, True))
    if name in (".arm", ".code", ".text", ".syntax", ".global", ".globl", ".type", ".size"):
        return b""
    raise AsmError(f"unknown directive {name}")


def _split_mnemonic(name: str, bases: list[str], allow_s: bool, middles: tuple[str, ...] = ("",)):
    """name -> (base, middle, s flag, condition) or None. Bases are tried longest first."""
    for base in sorted(bases, key=len, reverse=True):
        if not name.startswith(base):
            continue
        rest = name[len(base):]
        for middle in middles:
            if not rest.startswith(middle):
                continue
            tail = rest[len(middle):]
            for s in ((True, False) if allow_s else (False,)):
                t = tail
                if s:
                    if not t.startswith("s"):
                        continue
                    t = t[1:]
                if t == "":
                    return base, middle, s, 14
                if t in CONDITIONS:
                    return base, middle, s, CONDITIONS[t]
    return None


def _instruction(name: str, ops: list[str], pc: int, labels: dict[str, int], final: bool) -> int:
    if name == "nop" or name[3:] in CONDITIONS and name.startswith("nop"):
        if ops:
            raise AsmError("nop takes no operand")
        return CONDITIONS.get(name[3:], 14) << 28 | 0x0320F000
    # Branches first: "blt" is b + lt, "bls" b + ls, "bleq" bl + eq.
    for base in ("bx", "blx"):
        if name == base or name[len(base):] in CONDITIONS and name.startswith(base):
            cond = CONDITIONS.get(name[len(base):], 14)
            if len(ops) != 1:
                raise AsmError(f"{base} takes one register")
            return cond << 28 | (0x012FFF10 if base == "bx" else 0x012FFF30) | _register(ops[0])
    for base, link in (("bl", 1), ("b", 0)):
        rest = name[len(base):] if name.startswith(base) else None
        if rest is not None and (rest == "" or rest in CONDITIONS):
            cond = CONDITIONS.get(rest, 14)
            if len(ops) != 1:
                raise AsmError("a branch takes one target")
            offset = _value(ops[0], labels, final) - (pc + 8)
            if offset & 3 or not -(1 << 25) <= offset < 1 << 25:
                raise AsmError("branch target out of range or misaligned")
            return cond << 28 | 0x0A000000 | link << 24 | (offset >> 2) & 0xFFFFFF

    if name in ("push", "pop") or re.match(r"^(push|pop)(" + "|".join(CONDITIONS) + ")$", name):
        base = name[:4] if name.startswith("push") else name[:3]
        cond = CONDITIONS.get(name[len(base):], 14)
        mask = _reglist(",".join(ops))
        if mask & (mask - 1) == 0:                          # one register: str/ldr with writeback
            reg = mask.bit_length() - 1
            return (cond << 28 | 0x052D0004 | reg << 12) if base == "push" else (cond << 28 | 0x049D0004 | reg << 12)
        return cond << 28 | (0x092D0000 if base == "push" else 0x08BD0000) | mask

    parsed = _split_mnemonic(name, ["ldm", "stm"], False, tuple(LDM_MODES) + tuple(LDM_STACK["ldm"]) + ("",))
    if parsed and not name.startswith(("ldr", "str")):
        base, mode, _, cond = parsed
        mode = mode or "ia"
        mode = LDM_STACK[base].get(mode, mode)
        p, u = LDM_MODES[mode]
        rn_text = ops[0].strip()
        writeback = rn_text.endswith("!")
        rn = _register(rn_text.rstrip("!"))
        mask = _reglist(",".join(ops[1:]))
        return (cond << 28 | 0x08000000 | p << 24 | u << 23 | writeback << 21 | (base == "ldm") << 20
                | rn << 16 | mask)

    if name == "adr" or name[3:] in CONDITIONS and name.startswith("adr"):
        cond = CONDITIONS.get(name[3:], 14)
        rd = _register(ops[0])
        offset = _value(ops[1], labels, final) - (pc + 8)
        op, magnitude = (4, offset) if offset >= 0 else (2, -offset)
        imm = encode_immediate(magnitude)
        if imm is None:
            raise AsmError("adr target too far")
        return cond << 28 | 1 << 25 | op << 21 | 15 << 16 | rd << 12 | imm

    parsed = _split_mnemonic(name, ["mul", "mla"], True)
    if parsed:
        base, _, s, cond = parsed
        rd, rm, rs = (_register(o) for o in ops[:3])
        word = cond << 28 | s << 20 | rd << 16 | rs << 8 | 0x90 | rm
        if base == "mla":
            word |= 1 << 21 | _register(ops[3]) << 12
        return word

    parsed = _split_mnemonic(name, ["ldr", "str"], False, ("sb", "sh", "b", "h", ""))
    if parsed:
        base, size, _, cond = parsed
        return _load_store(base == "ldr", size, cond, ops, pc, labels, final)

    parsed = _split_mnemonic(name, list(DATA_OPS), True)
    if parsed:
        base, _, s, cond = parsed
        return _data_processing(base, s, cond, ops, labels, final)
    raise AsmError(f"unknown instruction {name}")


def _data_processing(base: str, s: bool, cond: int, ops: list[str], labels: dict[str, int], final: bool) -> int:
    op = DATA_OPS[base]
    if base in COMPARE:
        rd, rn, operand = 0, _register(ops[0]), ops[1:]
        s = True
    elif base in ("mov", "mvn"):
        rd, rn, operand = _register(ops[0]), 0, ops[1:]
    else:
        rd = _register(ops[0])
        if len(ops) == 2:                               # "add r0, #1" means "add r0, r0, #1"
            rn, operand = rd, ops[1:]
        else:
            rn, operand = _register(ops[1]), ops[2:]
    if not operand:
        raise AsmError("missing operand")
    if operand[0].startswith("#"):
        value = _value(operand[0], labels, final)
        imm = encode_immediate(value)
        if imm is None:
            swaps = {"mov": ("mvn", ~value), "mvn": ("mov", ~value), "cmp": ("cmn", -value), "cmn": ("cmp", -value),
                     "add": ("sub", -value), "sub": ("add", -value), "and": ("bic", ~value), "bic": ("and", ~value)}
            if base in swaps:
                other, other_value = swaps[base]
                imm = encode_immediate(other_value)
                if imm is not None:
                    op = DATA_OPS[other]
            if imm is None:
                raise AsmError(f"immediate {value:#x} cannot be encoded")
        return cond << 28 | 1 << 25 | op << 21 | s << 20 | rn << 16 | rd << 12 | imm
    rm = _register(operand[0])
    shift = _shift(operand[1]) if len(operand) > 1 else 0
    return cond << 28 | op << 21 | s << 20 | rn << 16 | rd << 12 | shift | rm


def _load_store(load: bool, size: str, cond: int, ops: list[str], pc: int, labels: dict[str, int],
                final: bool) -> int:
    rd = _register(ops[0])
    rest = ops[1:]
    if not rest:
        raise AsmError("missing address")
    if not rest[0].startswith("["):                     # ldr rd, label: pc-relative
        rest = [f"[pc, #{_value(rest[0], labels, final) - (pc + 8)}]"]
    text = ",".join(rest)
    m = re.match(r"^\[\s*([^\],]+?)\s*(?:,\s*(.+?))?\s*\]\s*(!)?\s*(?:,\s*(.+))?$", text)
    if not m:
        raise AsmError("bad address")
    rn = _register(m[1])
    inner, writeback, post = m[2], bool(m[3]), m[4]
    if inner and post:
        raise AsmError("bad address")
    pre = post is None
    offset_text = inner if pre else post
    up, imm_form, offset_bits, value = 1, True, 0, 0
    if offset_text:
        offset_text = offset_text.strip()
        if offset_text.startswith("#"):
            value = _value(offset_text, labels, final)
            up = 0 if value < 0 or offset_text[1:].lstrip().startswith("-") else 1
            value = abs(value)
        else:
            imm_form = False
            parts = [p.strip() for p in offset_text.split(",")]
            reg_text = parts[0]
            if reg_text.startswith("-"):
                up, reg_text = 0, reg_text[1:]
            elif reg_text.startswith("+"):
                reg_text = reg_text[1:]
            rm = _register(reg_text)
            shift = _shift(parts[1]) if len(parts) > 1 else 0
            if shift & 1 << 4:
                raise AsmError("register-shifted register offsets do not exist for loads and stores")
            offset_bits = shift | rm
    p = 1 if pre else 0
    w = 1 if writeback and pre else 0
    if size in ("", "b"):
        if imm_form:
            if value > 0xFFF:
                raise AsmError("offset out of range")
            offset_bits = value
        return (cond << 28 | 1 << 26 | (not imm_form) << 25 | p << 24 | up << 23 | (size == "b") << 22 | w << 21
                | load << 20 | rn << 16 | rd << 12 | offset_bits)
    sh = {"h": 0b01, "sb": 0b10, "sh": 0b11}[size]
    if not load and size != "h":
        raise AsmError("no signed stores")
    if imm_form:
        if value > 0xFF:
            raise AsmError("offset out of range")
        low = value & 0xF | (value >> 4) << 8
        return (cond << 28 | p << 24 | up << 23 | 1 << 22 | w << 21 | load << 20 | rn << 16 | rd << 12 | low
                | 1 << 7 | sh << 5 | 1 << 4)
    if offset_bits & ~0xF:
        raise AsmError("no shifted register offsets for halfwords")
    return (cond << 28 | p << 24 | up << 23 | w << 21 | load << 20 | rn << 16 | rd << 12 | 1 << 7 | sh << 5 | 1 << 4
            | offset_bits)
