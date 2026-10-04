#!/usr/bin/env python3
"""Names shared by all the Pawn scripts, for tools/amxdec.py.

The game's 123 scripts are compiled from a common set of .inc files, so most functions exist in
several copies at different addresses. They are matched across scripts by a fingerprint of their
normalised code:
  - natives by name, string literals by content, callees by their own fingerprint (refined until
    stable),
  - globals renumbered in their order of first use, constants that the decompiler saw used as the
    address of a global (ScriptDecompiler.usage) likewise.
A name then applies to every copy of a function: the original name from the "[file.inc::function]"
prefix of its log strings, or the one written in decomp/pawn/symbols.txt. Globals that matching
functions use at the same position are the same variable, so a global name applies to every script
that shares it. The .inc file of unnamed functions is inferred from their named neighbours (the
compiler emits functions in source order).

decomp/pawn/symbols.txt:
    <script>:<address> <name>(<parameters>)  [<file.inc>]   function, parameters in Pawn syntax
    <script>:g_<address> <name>                              global variable
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from amx import CONSTANTS, DATA_OPERANDS, OP, OPCODES, AmxFile, Instruction, function_names

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = ROOT / "decomp" / "pawn" / "symbols.txt"
NATIVES = ROOT / "decomp" / "pawn" / "natives.inc"

# Body of an empty function (the retail build compiled the debug output out of its functions).
_EMPTY = {OP[n] for n in ("PROC", "BREAK", "ZERO_PRI", "RETN", "RET")}
# Not counted in the size of a function when deciding whether it is trivial.
_FRAME = _EMPTY | {OP[n] for n in ("STACK", "HEAP")}
# Opcodes whose operands are globals but are missing from amx.DATA_OPERANDS.
_GLOBAL_OPERANDS = {OP[n] for n in ("PUSH", "PUSH2", "PUSH3", "PUSH4", "PUSH5", "PUSH_P", "CONST", "ZERO",
                                    "ZERO_P", "LOAD_BOTH")} | DATA_OPERANDS


def base_opcode(op: int) -> str:
    """Packed opcodes behave exactly like their unpacked counterpart."""
    name = OPCODES[op]
    return name.replace("_P_", "_").removesuffix("_P") if "_P_" in name or name.endswith("_P") else name


@dataclass
class Parameter:
    label: str
    kind: str = ""   # "" value, f Float, s const string, a array, r by reference (amxdec.PARAM_RANK)
    tag: str | None = None


@dataclass
class FunctionSymbol:
    name: str
    params: list[Parameter] | None = None
    variadic: bool = False
    include: str | None = None
    origin: str = "log"     # log: the game's own log strings, hand: symbols.txt, auto: empty function


@dataclass
class ScriptSymbols:
    functions: dict[int, FunctionSymbol] = field(default_factory=dict)
    globals: dict[int, str] = field(default_factory=dict)


@dataclass
class Function:
    script: str
    start: int
    insns: list[Instruction]
    log_name: tuple[str, str] | None = None
    public: str | None = None
    fingerprint: str = ""
    globals: list[int] = field(default_factory=list)   # data addresses, in order of first use


def parse_params(text: str) -> tuple[list[Parameter], bool]:
    """Pawn parameter list -> (parameters, variadic)."""
    params, variadic = [], False
    for part in (p.strip() for p in text.split(",") if p.strip()):
        if part.endswith("..."):
            variadic = True
            continue
        part = re.sub(r"\s*=.*$", "", part)   # default value
        const = part.startswith("const ")
        part = part.removeprefix("const ").strip()
        ref = part.startswith("&")
        part = part.removeprefix("&")
        tag = None
        if m := re.match(r"(\{[^}]*\}|\w+):", part):
            tag, part = m[1], part[m.end():]
        array = bool(re.search(r"\[\w*\]$", part))
        part = re.sub(r"(\[\w*\])+$", "", part)
        if array:
            kind = "s" if const and tag is None else "a"
        else:
            kind = "r" if ref else "f" if tag == "Float" else ""
        params.append(Parameter(part, kind, tag))
    return params, variadic


def read_natives(path: Path) -> tuple[dict[str, tuple[list[Parameter], bool, str | None]], dict[str, dict[int, str]]]:
    """decomp/pawn/natives.inc: native prototypes (name -> (parameters, variadic, return tag)) and
    enumerations (tag -> value -> constant name), used to name the constants passed to parameters
    of that tag or compared with values of that tag."""
    if not path.exists():
        return {}, {}
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(), flags=re.S)
    natives = {}
    for m in re.finditer(r"\bnative\s+(?:(\w+):)?(\w+)\s*\(([^)]*)\)", text):
        natives[m[2]] = (*parse_params(m[3]), m[1])
    enums: dict[str, dict[int, str]] = {}
    for m in re.finditer(r"\benum\s+(\w+)\s*\{([^}]*)\}", text):
        values = enums.setdefault(m[1], {})
        for name, value in re.findall(r"(\w+)\s*=\s*(-?(?:0x[0-9a-fA-F]+|\d+))", m[2]):
            values[int(value, 0)] = name
    return natives, enums


class Program:
    """All the scripts, decompiled once (analysis pass) so that constant usage is known."""

    def __init__(self, decompilers: dict):
        self.decompilers = decompilers   # script name -> amxdec.ScriptDecompiler (analysed)
        self.functions: dict[tuple[str, int], Function] = {}
        for script, dec in decompilers.items():
            names = function_names(dec.amx, dec.insns)
            for start, _, insns in dec.functions():
                self.functions[(script, start)] = Function(script, start, insns, names.get(start),
                                                           dec.publics.get(start))
        self.compute_fingerprints()
        self.groups: dict[str, list[Function]] = defaultdict(list)
        for f in self.functions.values():
            self.groups[f.fingerprint].append(f)
        self.order: dict[tuple[str, int], tuple[Function | None, Function | None]] = {}
        for script in decompilers:
            ordered = sorted((f for f in self.functions.values() if f.script == script), key=lambda f: f.start)
            for k, f in enumerate(ordered):
                self.order[(script, f.start)] = (ordered[k - 1] if k else None,
                                                  ordered[k + 1] if k + 1 < len(ordered) else None)

    # ---- matching
    def normalise(self, f: Function, callee: dict[int, str]) -> tuple[list, list[int]]:
        dec = self.decompilers[f.script]
        amx: AmxFile = dec.amx
        gmap: dict[int, int] = {}

        def glob(addr: int) -> tuple:
            return ("g", gmap.setdefault(addr, len(gmap)))

        out = []
        for i in f.insns:
            name = base_opcode(i.op)
            if name == "CALL":
                args = [callee.get(i.addr + i.args[0], "?")]
            elif name in ("SYSREQ_C", "SYSREQ_N"):
                args = [amx.natives[i.args[0]], *i.args[1:]]
            elif i.cases:
                args = [(v, t - i.addr) for v, t in i.cases]
            elif name == "CONST":
                args = [glob(i.args[0]), self.constant(dec, i, 1, glob)]
            elif i.op in _GLOBAL_OPERANDS:
                args = [glob(v) for v in i.args]
            elif i.op in CONSTANTS or name == "EQ_C_PRI" or name == "EQ_C_ALT" or name == "CONST_S":
                first = 1 if name == "CONST_S" else 0
                args = list(i.args[:first]) + [self.constant(dec, i, n, glob) for n in range(first, len(i.args))]
            else:
                args = list(i.args)
            out.append((name, tuple(args)))
        return out, list(gmap)

    @staticmethod
    def constant(dec, i: Instruction, n: int, glob) -> object:
        """A constant as the decompiler saw it used: global, string literal (by content) or number.
        Never guessed from the data: a number may look like a string in one script only."""
        value = i.args[n]
        usage = dec.usage.get((i.addr, n))
        if usage == "address":
            return glob(value)
        if usage == "string":
            text = dec.amx.string_at(value, strict=False)
            if text is not None:
                return ("s", text)
        return value

    def compute_fingerprints(self) -> None:
        fingerprints: dict[tuple[str, int], str] = {}
        for _ in range(12):
            new = {}
            for key, f in self.functions.items():
                callee = {start: fingerprints.get((f.script, start), "?")
                          for start in (i.addr + i.args[0] for i in f.insns if i.op == OP["CALL"])}
                normalised, f.globals = self.normalise(f, callee)
                new[key] = hashlib.sha1(repr(normalised).encode()).hexdigest()[:16]
            if new == fingerprints:
                break
            fingerprints = new
        for key, f in self.functions.items():
            f.fingerprint = fingerprints[key]

    def group_of(self, script: str, start: int) -> list[Function]:
        f = self.functions.get((script, start))
        return self.members(f) if f is not None else []

    def members(self, f: Function) -> list[Function]:
        """Every copy of a function. Empty functions all look alike, so they are not matched; a
        trivial one (`return g_x;`) only where a neighbour matches too (same place in the .inc)."""
        if self.is_empty(f):
            return [f]
        group = self.groups[f.fingerprint]
        if not self.is_trivial(f):
            return group
        return [m for m in group if m is f or self.same_place(f, m)]

    def same_place(self, a: Function, b: Function) -> bool:
        matches = []
        for side in (0, 1):
            na, nb = self.order[(a.script, a.start)][side], self.order[(b.script, b.start)][side]
            same = na is not None and nb is not None and na.fingerprint == nb.fingerprint
            if same and not self.is_trivial(na):
                return True
            matches.append(same)
        return all(matches)

    @staticmethod
    def is_empty(f: Function) -> bool:
        return all(i.op in _EMPTY for i in f.insns)

    @staticmethod
    def is_trivial(f: Function) -> bool:
        """A few instructions, no call, no native: shared by unrelated functions of every script."""
        body = [i for i in f.insns if i.op not in _FRAME]
        return len(body) <= 6 and not any(i.op in (OP["CALL"], OP["SYSREQ_N"], OP["SYSREQ_C"]) for i in body)

    def debug_stubs(self, script: str) -> dict[int, str]:
        """Empty functions: the debug output compiled out of the retail build. Those that receive a
        format string are named debugPrint (debugPrint2... when a script has several), the others
        stub, stub2..."""
        dec = self.decompilers[script]
        empty = {f.start for f in self.functions.values()
                 if f.script == script and not f.public and self.is_empty(f)}
        prints = set()
        insns = dec.insns
        for k, i in enumerate(insns):
            if i.op != OP["CALL"] or i.addr + i.args[0] not in empty or k < 1:
                continue
            # The argument count is the last operand pushed before the call, the first argument
            # the operand pushed just before it.
            operands = [(j, v) for j in insns[max(0, k - 3):k] for v in j.args] if insns[k - 1].op in CONSTANTS else []
            if len(operands) >= 2 and operands[-2][0].op in CONSTANTS and dec.amx.string_at(operands[-2][1]):
                prints.add(i.addr + i.args[0])
        names, counts = {}, Counter()
        for start in sorted(empty):
            base = "debugPrint" if start in prints else "stub"
            counts[base] += 1
            names[start] = base if counts[base] == 1 else f"{base}{counts[base]}"
        return names

    # ---- names
    def includes(self) -> dict[tuple[str, int], str]:
        """.inc file of each function: its own log tag, or that of both named neighbours."""
        found: dict[tuple[str, int], str] = {}
        for script in self.decompilers:
            ordered = sorted((f for f in self.functions.values() if f.script == script), key=lambda f: f.start)
            tags = [f.log_name[0] if f.log_name and f.log_name[0].endswith(".inc") else None for f in ordered]
            for k, f in enumerate(ordered):
                if tags[k]:
                    found[(script, f.start)] = tags[k]
                    continue
                before = next((t for t in reversed(tags[:k]) if t), None)
                after = next((t for t in tags[k + 1:] if t), None)
                if before and before == after:
                    found[(script, f.start)] = before
        # A copy of the same function gets the include most of its copies agree on.
        for members in self.groups.values():
            votes = Counter(found[(f.script, f.start)] for f in members if (f.script, f.start) in found)
            if votes:
                best = votes.most_common(1)[0][0]
                for f in members:
                    found.setdefault((f.script, f.start), best)
        return found

    def global_classes(self) -> dict[tuple[str, int], tuple[str, int]]:
        """Union-find of the globals used at the same position by matching functions."""
        parent: dict[tuple[str, int], tuple[str, int]] = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for f in self.functions.values():
            for other in self.members(f):
                for a, b in zip(f.globals, other.globals):
                    ra, rb = find((f.script, a)), find((other.script, b))
                    if ra != rb:
                        parent[ra] = rb
        return {x: find(x) for x in list(parent)}

    def resolve(self, path: Path = SYMBOLS) -> tuple[dict[str, ScriptSymbols], list[str]]:
        """Per-script symbols: log names and symbols.txt, propagated to every copy. Returns warnings too."""
        result = {script: ScriptSymbols() for script in self.decompilers}
        warnings: list[str] = []
        includes = self.includes()

        for f in self.functions.values():
            if f.log_name and not f.public:
                result[f.script].functions[f.start] = FunctionSymbol(f.log_name[1], include=includes.get(
                    (f.script, f.start)))
                # An implementation for a state ("[file::update<Top>]") names the stub everybody calls.
                stub = self.decompilers[f.script].state_impl.get(f.start)
                if stub is not None:
                    result[f.script].functions.setdefault(stub[0], FunctionSymbol(f.log_name[1]))

        global_names: dict[tuple[str, int], str] = {}
        classes = self.global_classes()
        for lineno, script, addr, is_global, name, params, include in self.read(path, warnings):
            where = f"{path.name}:{lineno}"
            if script not in self.decompilers:
                warnings.append(f"{where}: unknown script {script}")
                continue
            if is_global:
                root = classes.get((script, addr), (script, addr))
                global_names[root] = name
                continue
            members = self.group_of(script, addr)
            if not members:
                warnings.append(f"{where}: no function at {script}:{addr:#x}")
                continue
            parsed, variadic = parse_params(params) if params is not None else (None, False)
            for f in members:
                old = result[f.script].functions.get(f.start)
                if old and old.origin == "log" and old.name != name:
                    warnings.append(f"{where}: {name} renames {old.name} ({f.script}:{f.start:#x})")
                result[f.script].functions[f.start] = FunctionSymbol(
                    name, parsed, variadic, include or includes.get((f.script, f.start)) or (old.include if old else None),
                    origin="log" if old and old.origin == "log" and old.name == name else "hand")

        for (script, addr), root in classes.items():
            if root in global_names:
                result[script].globals[addr] = global_names[root]
        for (script, addr), name in global_names.items():
            result[script].globals.setdefault(addr, name)

        # Unnamed functions: include file only (shown in the header comment).
        for key, inc in includes.items():
            script, start = key
            if start not in result[script].functions and not self.functions[key].public:
                result[script].functions[start] = FunctionSymbol("", include=inc, origin="")
        for script in self.decompilers:
            for start, name in self.debug_stubs(script).items():
                symbol = result[script].functions.get(start)
                if symbol is None or not symbol.name:
                    params = [Parameter("format", "s")] if name.startswith("debugPrint") else []
                    result[script].functions[start] = FunctionSymbol(
                        name, params, True, symbol.include if symbol else None, origin="auto")
        return result, warnings

    @staticmethod
    def read(path: Path, warnings: list[str]):
        if not path.exists():
            return
        line_re = re.compile(r"^(\w+):(g_)?(0x[0-9a-fA-F]+|[0-9a-fA-F]+)\s+([A-Za-z_@][\w@]*)"
                             r"(?:\(([^)]*)\))?\s*(?:\[([\w.]+)\])?\s*$")
        for lineno, raw in enumerate(path.read_text().splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            m = line_re.match(line)
            if not m:
                warnings.append(f"{path.name}:{lineno}: cannot parse {raw!r}")
                continue
            script, is_global, addr, name, params, include = m.groups()
            yield lineno, script, int(addr, 16), bool(is_global), name, params, include
