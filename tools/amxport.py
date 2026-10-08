#!/usr/bin/env python3
"""Addresses of a Pawn script of the game (v0) in the same script of the update v5200, and back.

The update recompiled the 123 scripts: most functions are the same, at other addresses, and the globals
moved. The mods' Pawn code (mods/*/src/*.p, *.pasm) names the game's code and globals by their addresses in
one version; this tool finds them in the other:

    tools/amxport.py surface_sub 0xcf80 g_1ca0 0x8668      v0 -> v5200: each address, with the instruction
    tools/amxport.py --reverse mode_title 0x10358          v5200 -> v0
    tools/amxport.py --show mode_lobby 0xebf8              the code around it, both versions aligned
    tools/amxport.py mode_lobby --pasm a.pasm a-v5200.pasm --overrides v5200.toml   a .pasm file
    tools/amxport.py --stats                               how much of each script is matched

How: both scripts are decoded and each instruction becomes a token that does not depend on where things are
(branch targets and globals masked, natives by name, string literals by their text); the two token sequences
are aligned (difflib), function by function once the functions are paired by their log names, their callers
and their code. An aligned instruction is the same in both versions: its address maps, and its global operands
pair the globals of the two versions (majority vote over every use). A developer tool (the RE pipeline): the
results go into the mods' sources (tools/pawn2pasm.py --version), which the players' tools then only read.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import versions  # noqa: E402
from amx import BRANCHES, CONSTANTS, DATA_OPERANDS, OP, OPCODES, AmxFile, Instruction  # noqa: E402

# Opcodes whose operand is a global, besides amx.DATA_OPERANDS (as tools/amxsym.py counts them).
GLOBAL_OPERANDS = {OP[n] for n in ("PUSH", "PUSH2", "PUSH3", "PUSH4", "PUSH5", "PUSH_P", "LOAD_BOTH",
                                   "ZERO", "ZERO_P")} | DATA_OPERANDS
_LOG = re.compile(r"\[([\w.]+::[\w<>]+)\]")


def base_name(op: int) -> str:
    name = OPCODES[op]
    return name.replace("_P_", "_").removesuffix("_P") if "_P_" in name or name.endswith("_P") else name


@dataclass
class Function:
    start: int
    insns: list[Instruction] = field(default_factory=list)
    log: str | None = None                  # "file.inc::name" of its log strings


class Script:
    """One script decoded, its instructions as version-free tokens, split into functions."""

    def __init__(self, path: Path) -> None:
        self.amx = AmxFile.load(path)
        self.insns = list(self.amx.instructions())
        self.at = {i.addr: k for k, i in enumerate(self.insns)}
        self.functions: list[Function] = []
        for i in self.insns:
            if i.op == OP["PROC"] or not self.functions:
                self.functions.append(Function(i.addr))
            self.functions[-1].insns.append(i)
        self.tokens = [self.token(i) for i in self.insns]
        for f in self.functions:
            for i in f.insns:
                for a in self.strings(i):
                    m = _LOG.search(a)
                    if m and f.log is None:
                        f.log = m[1]

    def is_data_address(self, value: int) -> bool:
        return 0x100 <= value < len(self.amx.data) and value % 4 == 0

    def strings(self, i: Instruction) -> list[str]:
        if i.op not in CONSTANTS:
            return []
        out = []
        for v in i.args:
            s = self.amx.string_at(v)
            if s is not None:
                out.append(s)
        return out

    def token(self, i: Instruction) -> tuple:
        name = base_name(i.op)
        if i.op in BRANCHES:
            if i.op == OP["CALL"]:
                return name, "call"
            return name, "@"
        if name in ("SYSREQ_C", "SYSREQ_N"):
            return name, self.amx.natives[i.args[0]], *i.args[1:]
        if i.op in GLOBAL_OPERANDS and name not in ("PUSH", "PUSH2", "PUSH3", "PUSH4", "PUSH5"):
            return name, *("g" for _ in i.args)
        args = []
        for v in i.args:
            if (i.op in CONSTANTS or name.startswith("PUSH")) and v >= 0x40:     # not a byte count
                s = self.amx.string_at(v)
                if s is not None:
                    args.append(("s", s))
                    continue
                if self.is_data_address(v):
                    args.append("d")
                    continue
            args.append(v)
        if i.op in (OP["CASETBL"], OP["ICASETBL"]):
            args.append(tuple(v for v, _ in i.cases[1:]))
        return name, *args

    def function_at(self, addr: int) -> Function | None:
        best = None
        for f in self.functions:
            if f.start <= addr:
                best = f
            else:
                break
        return best

    def callees(self, f: Function) -> list[int]:
        return [i.addr + i.args[0] for i in f.insns if i.op == OP["CALL"]]

    def data_operands(self, i: Instruction) -> list[int]:
        """Operands of an instruction that are addresses in the data segment (globals, arrays)."""
        name = base_name(i.op)
        if i.op in GLOBAL_OPERANDS and name not in ("PUSH", "PUSH2", "PUSH3", "PUSH4", "PUSH5"):
            return list(i.args)
        if i.op in CONSTANTS or name.startswith("PUSH") and not name.endswith(("_S", "_ADR")):
            return [v for v in i.args if self.is_data_address(v) and self.amx.string_at(v) is None]
        return []


class Port:
    """The pairing of two versions of a script: code addresses and globals."""

    def __init__(self, a: Script, b: Script) -> None:
        self.a, self.b = a, b
        self.code: dict[int, int] = {}          # address in a -> address in b, aligned instructions
        self.functions: dict[int, int] = {}     # function start in a -> in b
        self.similarity: dict[int, float] = {}  # function start in a -> how alike the pair is (1: the same code)
        votes: dict[int, Counter] = defaultdict(Counter)
        for fa, fb in self._pair_functions():
            self.functions[fa.start] = fb.start
            ta = [a.tokens[a.at[i.addr]] for i in fa.insns]
            tb = [b.tokens[b.at[i.addr]] for i in fb.insns]
            sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
            self.similarity[fa.start] = sm.ratio()
            for block in sm.get_matching_blocks():
                for k in range(block.size):
                    ia, ib = fa.insns[block.a + k], fb.insns[block.b + k]
                    self.code[ia.addr] = ib.addr
                    for va, vb in zip(a.data_operands(ia), b.data_operands(ib)):
                        votes[va][vb] += 1
        self.globals = {va: c.most_common(1)[0][0] for va, c in votes.items()}
        self.global_votes = votes

    def _pair_functions(self) -> list[tuple[Function, Function]]:
        a, b = self.a, self.b
        pairs: dict[int, Function] = {}
        used: set[int] = set()

        def pair(fa: Function, fb: Function) -> None:
            if fa.start not in pairs and fb.start not in used:
                pairs[fa.start] = fb
                used.add(fb.start)

        # 1. identical code (unique on both sides), 2. the same log name
        def key(s: Script, f: Function) -> tuple:
            return tuple(s.tokens[s.at[i.addr]] for i in f.insns)

        ka = Counter(key(a, f) for f in a.functions)
        kb: dict[tuple, list[Function]] = defaultdict(list)
        for f in b.functions:
            kb[key(b, f)].append(f)
        for f in a.functions:
            k = key(a, f)
            if ka[k] == 1 and len(kb.get(k, [])) == 1:
                pair(f, kb[k][0])
        # same log name: the copies in the same order (a state's implementations share their stub's name)
        logs_a: dict[str, list[Function]] = defaultdict(list)
        logs_b: dict[str, list[Function]] = defaultdict(list)
        for f in a.functions:
            if f.log:
                logs_a[f.log].append(f)
        for f in b.functions:
            if f.log:
                logs_b[f.log].append(f)
        for log, fs in logs_a.items():
            if len(fs) == len(logs_b.get(log, ())):
                for fa, fb in zip(fs, logs_b[log]):
                    pair(fa, fb)
        # 3. what the paired functions call, in the same order, when the callees look alike
        for _ in range(4):
            for fa_start, fb in list(pairs.items()):
                fa = a.function_at(fa_start)
                ca, cb = a.callees(fa), b.callees(fb)
                if len(ca) == len(cb):
                    for x, y in zip(ca, cb):
                        xa, yb = a.function_at(x), b.function_at(y)
                        if (xa and yb and xa.start == x and yb.start == y and xa.start not in pairs
                                and similarity(key(a, xa), key(b, yb)) > 0.5):
                            pair(xa, yb)
        # 4. the rest by similarity, the largest first (an update may also move whole .inc files)
        keys_b = {g.start: key(b, g) for g in b.functions}
        for f in sorted(a.functions, key=lambda f: -len(f.insns)):
            if f.start in pairs or len(f.insns) < 4:
                continue
            ta = key(a, f)
            best, ratio = None, 0.6
            for g in b.functions:
                if g.start in used or not 0.5 <= len(g.insns) / len(f.insns) <= 2:
                    continue
                sm = difflib.SequenceMatcher(None, ta, keys_b[g.start], autojunk=False)
                if sm.real_quick_ratio() <= ratio or sm.quick_ratio() <= ratio:
                    continue
                r = sm.ratio()
                if r > ratio:
                    best, ratio = g, r
            if best:
                pair(f, best)
        return [(a.function_at(s), fb) for s, fb in sorted(pairs.items())]

    def same(self, addr: int) -> bool:
        """The instruction at addr (in a) is aligned with an instruction of b."""
        return addr in self.code

    def code_address(self, addr: int) -> int | None:
        return self.code.get(addr)

    def describe(self, text: str) -> str:
        m = re.fullmatch(r"g_([0-9a-fA-F]+)|(0x[0-9a-fA-F]+|\d+)", text)
        if not m:
            return f"{text}: ?"
        if m[1]:
            va = int(m[1], 16)
            if va not in self.globals:
                return f"g_{va:04x}: not found"
            votes = self.global_votes[va]
            vb = self.globals[va]
            other = "" if len(votes) == 1 else f"  (votes {dict((f'g_{k:04x}', n) for k, n in votes.items())})"
            return f"g_{va:04x} -> g_{vb:04x}{other}"
        addr = int(m[2], 0)
        f = self.a.function_at(addr)
        where = f" (in func_{f.start:x}" + (f" {f.log}" if f and f.log else "") + ")" if f else ""
        if addr in self.code:
            ia = self.a.insns[self.a.at[addr]]
            return f"{addr:#x} -> {self.code[addr]:#x}  {OPCODES[ia.op].lower()}{where}"
        if f and f.start in self.functions:
            return f"{addr:#x}: changed, function -> {self.functions[f.start]:#x}{where}"
        return f"{addr:#x}: not found{where}"


def similarity(x: tuple, y: tuple) -> float:
    return difflib.SequenceMatcher(None, x, y, autojunk=False).ratio()


def listing(port: Port, addr: int, context: int = 12) -> str:
    """The function around addr in both versions, aligned, with the addresses of each."""
    a, b = port.a, port.b
    fa = a.function_at(addr)
    if fa is None or fa.start not in port.functions:
        return f"{addr:#x}: no matching function"
    fb = b.function_at(port.functions[fa.start])
    ta = [a.tokens[a.at[i.addr]] for i in fa.insns]
    tb = [b.tokens[b.at[i.addr]] for i in fb.insns]
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        for k in range(max(i2 - i1, j2 - j1)):
            ia = fa.insns[i1 + k] if i1 + k < i2 else None
            ib = fb.insns[j1 + k] if j1 + k < j2 else None
            rows.append((ia, ib, " " if tag == "equal" else "*"))
    at = next((n for n, (ia, _, _) in enumerate(rows) if ia and ia.addr >= addr), 0)
    out = [f"func_{fa.start:x} -> func_{fb.start:x}" + (f"  {fa.log}" if fa.log else "")]
    for ia, ib, mark in rows[max(0, at - context):at + context + 1]:
        left = f"{ia.addr:6x}  {text(a, ia)}" if ia else ""
        right = f"{ib.addr:6x}  {text(b, ib)}" if ib else ""
        out.append(f"{'>' if ia and ia.addr == addr else ' '}{mark} {left:52} | {right}")
    return "\n".join(out)


def text(s: Script, i: Instruction) -> str:
    name = OPCODES[i.op].lower()
    if i.op in BRANCHES:
        return f"{name} {i.addr + i.args[0]:#x}"
    if name in ("sysreq_c", "sysreq_n"):
        return f"{name} {s.amx.natives[i.args[0]]}" + (f", {i.args[1]}" if len(i.args) > 1 else "")
    args = []
    for v in i.args:
        string = s.amx.string_at(v) if i.op in CONSTANTS else None
        args.append(f"'{string[:16]}'" if string else (f"{v:#x}" if v >= 0 else str(v)))
    return f"{name} {', '.join(args)}".rstrip()


class PortError(ValueError):
    pass


_BRANCH_MNEMONICS = {OPCODES[op].lower().replace("_", ".") for op in BRANCHES}
_CODE_LINE = re.compile(r"^(\s*(?:[@$\w.]+:\s*)?)(\S+)(\s+)(.*)$")
_GLOBAL = re.compile(r"\bg_([0-9a-fA-F]+)\b")


def overrides_of(path: Path | None, section: str) -> dict[str, str]:
    """The addresses written by hand for one script (a section of a TOML file): "0xebf8" = "0x140d4",
    "g_b094" = "g_10aa0"; keys and values as text."""
    if path is None or not path.exists():
        return {}
    import tomllib
    table = tomllib.loads(path.read_text(encoding="utf-8")).get(section, {})
    out = {}
    for k, v in table.items():
        out[k.lower()] = f"{v:#x}" if isinstance(v, int) else str(v).lower()
    return out


class Translator:
    """Addresses of a script's code and globals from one version to the other, with the hand-written ones
    (overrides) first; an address that is not the same instruction in both, or a global used ambiguously,
    is an error unless written by hand."""

    def __init__(self, port: Port, overrides: dict[str, str]) -> None:
        self.port = port
        self.overrides = overrides
        self.errors: list[str] = []

    def code(self, addr: int, function: bool = False) -> int:
        text = f"{addr:#x}"
        if text in self.overrides:
            return int(self.overrides[text], 0)
        if function and addr in self.port.functions:
            return self.port.functions[addr]
        if addr in self.port.code:
            return self.port.code[addr]
        self.errors.append(self.port.describe(text) + "\n" + listing(self.port, addr, 6))
        return addr

    def global_(self, addr: int) -> int:
        text = f"g_{addr:04x}"
        for key in (text, f"g_{addr:x}"):
            if key in self.overrides:
                return int(self.overrides[key].removeprefix("g_"), 16)
        votes = self.port.global_votes.get(addr)
        if not votes:
            self.errors.append(f"{text}: never used by an instruction of both versions")
            return addr
        if len(votes) > 1:
            self.errors.append(self.port.describe(text) + ": ambiguous, write it by hand")
        return self.port.globals[addr]

    def asm(self, source: str) -> str:
        """Pawn assembly (tools/amxasm.py) for one version -> for the other: .hook addresses, branches and
        calls into the script's code, and g_<hex> globals; comments are kept as they are."""
        out = []
        for line in source.splitlines():
            code, sep, comment = line.partition(";")
            m = _CODE_LINE.match(code)
            if m:
                head, mnemonic, space, rest = m.groups()
                operand = rest.strip()
                if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", operand):
                    if mnemonic == ".hook":
                        rest = f"{self.code(int(operand, 0)):#x}" + rest[len(operand):]
                    elif mnemonic == "call":
                        rest = f"{self.code(int(operand, 0), function=True):#x}" + rest[len(operand):]
                    elif mnemonic in _BRANCH_MNEMONICS:
                        rest = f"{self.code(int(operand, 0)):#x}" + rest[len(operand):]
                code = head + mnemonic + space + rest
            code = _GLOBAL.sub(lambda g: f"g_{self.global_(int(g[1], 16)):04x}", code)
            out.append(code + sep + comment)
        return "\n".join(out) + ("\n" if source.endswith("\n") else "")

    def check(self, what: str) -> None:
        if self.errors:
            raise PortError(f"{what}: {len(self.errors)} address(es) to write by hand\n\n" + "\n\n".join(self.errors))


def load(name: str, version: str) -> Script:
    return Script(versions.game_files(version).path(f"amx/{name}.amx"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", help="name of the script (surface_sub, mode_lobby...)")
    ap.add_argument("addresses", nargs="*", help="code addresses (0x...) and globals (g_...)")
    ap.add_argument("--from", dest="source", default="v0")
    ap.add_argument("--to", dest="target", default="v5200")
    ap.add_argument("--reverse", action="store_true", help="from v5200 to v0")
    ap.add_argument("--stats", action="store_true", help="matched share of every script")
    ap.add_argument("--show", action="store_true", help="the code around each address, in both versions")
    ap.add_argument("--pasm", nargs=2, metavar=("IN", "OUT"), type=Path,
                    help="translate a Pawn assembly file (.pasm) of the script")
    ap.add_argument("--overrides", type=Path, help="TOML file of the addresses written by hand, one section "
                    "per .pasm file (its name without extension)")
    args = ap.parse_args()
    source, target = (args.target, args.source) if args.reverse else (args.source, args.target)
    if args.stats:
        files = versions.game_files(source)
        for name in sorted(Path(f).stem for f in files.glob("amx/*.amx")):
            if not versions.game_files(target).exists(f"amx/{name}.amx"):
                continue
            port = Port(load(name, source), load(name, target))
            n = len(port.a.insns)
            print(f"{name:32} {100 * len(port.code) / n:5.1f} % of {n} instructions, "
                  f"{len(port.functions)}/{len(port.a.functions)} functions, {len(port.globals)} globals")
        return 0
    if not args.script:
        ap.error("a script name, or --stats")
    port = Port(load(args.script, source), load(args.script, target))
    if args.pasm:
        src, dst = args.pasm
        tr = Translator(port, overrides_of(args.overrides, src.stem))
        text = tr.asm(src.read_text(encoding="utf-8"))
        try:
            tr.check(str(src))
        except PortError as e:
            print(e, file=sys.stderr)
            return 1
        header = (f"; Generated by tools/amxport.py from {src.name} ({source}) for {target}: edit {src.name}"
                  f"{f' or {args.overrides.name}' if args.overrides else ''}, then run\n"
                  f";   tools/amxport.py {args.script} --pasm {src} {dst}"
                  f"{f' --overrides {args.overrides}' if args.overrides else ''}\n")
        dst.write_text(header + text, encoding="utf-8")
        print(dst)
        return 0
    for item in args.addresses:
        print(port.describe(item))
        if args.show and not item.startswith("g_"):
            print(listing(port, int(item, 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
