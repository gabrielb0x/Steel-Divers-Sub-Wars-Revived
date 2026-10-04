#!/usr/bin/env python3
"""Pawn AMX decompiler: turns the game's compiled scripts into pseudo-Pawn.

Works per function on the P-code decoded by tools/amx.py:
  1. split into basic blocks (jump targets, CASETBL entries),
  2. symbolic execution of each block over the PRI/ALT registers and the
     stack, rebuilding expressions, calls, assignments and local declarations
     (the compiler emits a BREAK at each statement, which delimits them),
  3. structuring of the control flow into if/else, while, do/while, switch,
     break/continue, with && / || conditions; anything else stays a goto.

The output is meant to be read, not recompiled: names of locals, globals and
unnamed functions are synthetic (local_14, g_01c8, func_02c0).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from amx import BRANCHES, OP, AmxFile, Instruction, function_names

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------------------------
# Expressions

PREC = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "<": 7, "<=": 7, ">": 7, ">=": 7,
        "<<": 8, ">>": 8, ">>>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}
NEGATE = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
FLOAT_OPS = {"floatadd": "+", "floatsub": "-", "floatmul": "*", "floatdiv": "/"}
# Float parameters of the float natives (float.inc of Pawn 3.3, plus the game's own float* natives).
FLOAT_PARAMS = {"floatmul": (0, 1), "floatdiv": (0, 1), "floatadd": (0, 1), "floatsub": (0, 1), "floatcmp": (0, 1),
                "floatpower": (0, 1), "floatlog": (0, 1), "floatclamp": (0, 1, 2), "floatatan2": (0, 1),
                "floatsin": (0,), "floatcos": (0,), "floattan": (0,), "floatasin": (0,), "floatacos": (0,),
                "floatatan": (0,), "floatabs": (0,), "floatsqroot": (0,), "floatfract": (0,), "floatround": (0,)}


class Expr:
    side_effects = False

    def render(self, prec: int = 0) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.render()


@dataclass
class Const(Expr):
    value: int
    as_float: bool = False

    def render(self, prec: int = 0) -> str:
        if self.as_float:
            return float_literal(self.value)
        v = self.value
        bitmask = v >= 0x100 and v & (v - 1) == 0
        text = str(v) if -100000 < v < 100000 and not bitmask else (f"{v:#x}" if v > 0 else f"-{-v:#x}")
        return f"({text})" if v < 0 and prec > 11 else text


@dataclass
class Str(Expr):
    text: str

    def render(self, prec: int = 0) -> str:
        escaped = self.text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'


@dataclass
class Lit(Const):
    """Constant that is also the data address of a string literal."""
    text: str = ""

    def render(self, prec: int = 0) -> str:
        return Str(self.text).render()


@dataclass
class Var(Expr):
    name: str

    def render(self, prec: int = 0) -> str:
        return self.name


@dataclass
class AddrOf(Expr):
    """Address of a variable or array: Pawn passes these by reference, so it reads as the name."""
    target: Expr

    def render(self, prec: int = 0) -> str:
        return self.target.render(prec)


@dataclass
class Deref(Expr):
    address: Expr

    def render(self, prec: int = 0) -> str:
        if isinstance(self.address, AddrOf):
            return self.address.target.render(prec)
        return f"[{self.address.render()}]"


@dataclass
class Index(Expr):
    base: Expr
    index: Expr
    shift: int = 2   # byte shift of the element size (2 = cells)

    def render(self, prec: int = 0) -> str:
        idx = self.index.render() if self.shift == 2 else f"{self.index.render(8)} << {self.shift}"
        return f"{self.base.render(12)}[{idx}]"


@dataclass(eq=False)
class HeapCell(Expr):
    """Heap cell holding a value passed by reference (Pawn passes variadic arguments by address)."""
    value: Expr | None = None

    @property
    def side_effects(self) -> bool:
        return self.value is not None and self.value.side_effects

    def render(self, prec: int = 0) -> str:
        return self.value.render(prec) if self.value is not None else "heap_tmp"


@dataclass
class Row(Expr):
    """Row of a two-dimensional array (Pawn indirection vector): renders as base[index]."""
    base: Expr
    index: Expr

    def render(self, prec: int = 0) -> str:
        return f"{self.base.render(12)}[{self.index.render()}]"


@dataclass
class Unary(Expr):
    op: str
    operand: Expr

    def render(self, prec: int = 0) -> str:
        text = f"{self.op}{self.operand.render(11)}"
        return f"({text})" if prec > 11 else text


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr

    def render(self, prec: int = 0) -> str:
        p = PREC[self.op]
        text = f"{self.left.render(p)} {self.op} {self.right.render(p + 1)}"
        return f"({text})" if prec > p else text


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]
    side_effects = True

    def render(self, prec: int = 0) -> str:
        return f"{self.name}({', '.join(a.render() for a in self.args)})"


@dataclass
class Assign(Expr):
    """Assignment used as a value (x = y in an expression, x++ ...)."""
    target: Expr
    value: Expr
    op: str = "="
    side_effects = True

    def render(self, prec: int = 0) -> str:
        if self.op in ("++", "--"):
            return f"{self.target.render(12)}{self.op}"
        text = f"{self.target.render()} {self.op} {self.value.render()}"
        return f"({text})" if prec > 0 else text


class NotPure(Exception):
    """The region being evaluated as an expression contains a statement."""


@dataclass
class Ternary(Expr):
    cond: Expr
    then: Expr
    other: Expr

    @property
    def side_effects(self) -> bool:
        return any(e.side_effects for e in (self.cond, self.then, self.other))

    def render(self, prec: int = 0) -> str:
        text = f"{self.cond.render(1)} ? {self.then.render(1)} : {self.other.render(1)}"
        return f"({text})" if prec > 0 else text


@dataclass
class Boolean(Expr):
    """An expression the compiler reduced to 0/1 (renders unchanged)."""
    inner: Expr

    @property
    def side_effects(self) -> bool:
        return self.inner.side_effects

    def render(self, prec: int = 0) -> str:
        return self.inner.render(prec)


def is_boolean(e: Expr) -> bool:
    return (isinstance(e, Boolean) or isinstance(e, Binary) and e.op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||")
            or isinstance(e, Unary) and e.op == "!" or type(e) is Const and e.value in (0, 1))


def select(cond: Expr, then: Expr, other: Expr) -> Expr:
    """cond ? then : other, folded back into && / || when the compiler materialised a boolean."""
    def is_const(e: Expr, v: int) -> bool:
        return type(e) is Const and e.value == v
    if is_const(then, 1) and is_const(other, 0):
        return cond if is_boolean(cond) else Boolean(cond)
    if is_const(then, 0) and is_const(other, 1):
        result = negate(cond)
        return result if is_boolean(result) else Boolean(result)
    if is_const(other, 0) and is_boolean(then):
        return Binary("&&", cond, then)
    if is_const(then, 1) and is_boolean(other):
        return Binary("||", cond, other)
    if is_const(then, 0) and is_boolean(other):
        return Binary("&&", negate(cond), other)
    if is_const(other, 1) and is_boolean(then):
        return Binary("||", negate(cond), then)
    return Ternary(cond, then, other)


def float_literal(bits: int) -> str:
    raw = struct.pack("<I", bits & 0xFFFFFFFF)
    value = struct.unpack("<f", raw)[0]
    if value != value or value in (float("inf"), float("-inf")):
        return f"Float:{bits:#x}"
    if value == 0 or 1e-4 <= abs(value) < 1e7:
        for decimals in range(1, 10):
            text = f"{value:.{decimals}f}"
            if struct.pack("<f", float(text)) == raw:
                return text
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if struct.pack("<f", float(text)) == raw:
            return text
    return repr(value)


def looks_like_float(bits: int) -> bool:
    """Integer constants that are much more plausible as IEEE floats (1.0, 0.5, -90.0, 1000.0 ...)."""
    if bits == 0 or not 0x3A000000 <= (bits & 0x7FFFFFFF) <= 0x4C000000:
        return False
    return (bits & 0x7FF) == 0   # few significant mantissa bits


def negate(cond: Expr) -> Expr:
    if isinstance(cond, Boolean):
        cond = cond.inner
    if isinstance(cond, Binary) and cond.op in NEGATE:
        return Binary(NEGATE[cond.op], cond.left, cond.right)
    if isinstance(cond, Binary) and cond.op in ("&&", "||"):
        return Binary("||" if cond.op == "&&" else "&&", negate(cond.left), negate(cond.right))
    if isinstance(cond, Unary) and cond.op == "!":
        return cond.operand
    return Unary("!", cond)


def truth(expr: Expr) -> Expr:
    """`x != 0` -> `x` for readability of conditions."""
    if isinstance(expr, Binary) and expr.op == "!=" and isinstance(expr.right, Const) and expr.right.value == 0:
        return expr.left
    return expr


# --------------------------------------------------------------------------------------------
# Statements and blocks

CONDITIONAL = {OP[n] for n in ("JZER", "JNZ", "JEQ", "JNEQ", "JLESS", "JLEQ", "JGRTR", "JGEQ",
                               "JSLESS", "JSLEQ", "JSGRTR", "JSGEQ")}
STATEMENT_ONLY = {OP[n] for n in ("BREAK", "RET", "RETN", "SWITCH", "CASETBL", "PROC", "HALT")}
AMX_ERR_SLEEP = 12   # HALT code of the `sleep` statement

@dataclass
class Stmt:
    text: str


@dataclass
class Block:
    start: int
    insns: list[Instruction]
    end: int = 0
    stmts: list[Stmt] = field(default_factory=list)
    kind: str = "fall"          # fall | jump | cond | return | switch | halt
    target: int | None = None   # jump/cond target
    cond: Expr | None = None    # cond: taken when true
    value: Expr | None = None   # return value
    cases: list[tuple[int, int]] = field(default_factory=list)  # switch: (value, target), first = default


class FunctionDecompiler:
    def __init__(self, ctx: "ScriptDecompiler", start: int, end: int, insns: list[Instruction]):
        self.ctx = ctx
        self.start = start
        self.end = end
        self.insns = insns
        self.locals: dict[int, str] = {}       # frame offset -> declared name
        self.arrays: dict[int, tuple[str, int]] = {}   # frame offset -> (name, cells)
        self.max_param = -1
        self.blocks: dict[int, Block] = {}

    # ---- naming
    def frame_var(self, offset: int) -> Expr:
        if offset >= 12:
            index = (offset - 12) // 4
            self.max_param = max(self.max_param, index)
            return Var(f"arg{index}")
        for start, (name, size) in self.arrays.items():
            if start <= offset < start + 4 * size:
                return Index(Var(name), Const((offset - start) // 4))
        return Var(self.locals.get(offset, f"local_{-offset:x}"))

    def frame_addr(self, offset: int) -> Expr:
        """Address of a frame slot: an array passed by reference reads as its name."""
        if offset in self.arrays:
            return AddrOf(Var(self.arrays[offset][0]))
        return AddrOf(self.frame_var(offset))

    def global_var(self, addr: int) -> Var:
        return Var(self.ctx.global_name(addr))

    # ---- block construction
    def split_blocks(self) -> list[Block]:
        leaders = {self.start}
        by_addr = {i.addr: k for k, i in enumerate(self.insns)}
        for k, i in enumerate(self.insns):
            nxt = self.insns[k + 1].addr if k + 1 < len(self.insns) else self.end
            if i.op in BRANCHES and i.op != OP["CALL"]:
                leaders.add(i.addr + i.args[0])
                leaders.add(nxt)
            elif i.op in (OP["RETN"], OP["RET"]) or i.op in (OP["HALT"], OP["HALT_P"]) and i.args[0] != AMX_ERR_SLEEP:
                leaders.add(nxt)
            for _, target in i.cases:
                leaders.add(target)
        leaders = sorted(a for a in leaders if a in by_addr)
        blocks = []
        for n, addr in enumerate(leaders):
            stop = leaders[n + 1] if n + 1 < len(leaders) else self.end
            blocks.append(Block(addr, [i for i in self.insns if addr <= i.addr < stop], stop))
        return blocks

    # ---- expression regions
    def block_at(self, addr: int) -> Block:
        return self.by_start[addr]

    def blocks_in(self, start: int, end: int) -> list[Block]:
        return [b for b in self.all_blocks if start <= b.start < end]

    def expression_merge(self, jump: Instruction) -> int | None:
        """Where the two branches of a conditional jump meet again, if everything in between is
        part of one expression: forward jumps only, no statement boundary (BREAK) on the way."""
        k = self.index[jump.addr] + 1
        merge = jump.addr + jump.args[0]
        if merge <= jump.addr:
            return None
        while k < len(self.insns) and self.insns[k].addr < merge:
            i = self.insns[k]
            if i.op in STATEMENT_ONLY:
                return None
            if i.op in BRANCHES and i.op != OP["CALL"]:
                target = i.addr + i.args[0]
                if target <= i.addr:
                    return None
                merge = max(merge, target)
            k += 1
        return merge if merge in self.by_start else None

    def eval_conditional(self, interp: "BlockInterpreter", jump: Instruction, merge: int) -> Expr | None:
        try:
            state = interp.clone()
            cond = state.condition(jump.name)
            taken = self.eval_path(state.clone(), jump.addr + jump.args[0], merge)
            fall = self.eval_path(state.clone(), jump.addr + jump.size, merge)
        except NotPure:
            return None
        if taken[1] != fall[1]:
            return None   # the branches leave the stack in different states
        interp.use_pri()
        return select(cond, taken[0], fall[0])

    def eval_path(self, state: "BlockInterpreter", addr: int, merge: int) -> tuple[Expr, int]:
        while addr != merge:
            k = self.index.get(addr)
            if k is None or addr > merge:
                raise NotPure()
            i = self.insns[k]
            if i.op in CONDITIONAL:
                cond = state.condition(i.name)
                taken = self.eval_path(state.clone(), i.addr + i.args[0], merge)
                fall = self.eval_path(state.clone(), i.addr + i.size, merge)
                if taken[1] != fall[1]:
                    raise NotPure()
                return select(cond, taken[0], fall[0]), taken[1]
            if i.op == OP["JUMP"]:
                addr = i.addr + i.args[0]
                continue
            if i.op in STATEMENT_ONLY:
                raise NotPure()
            state.step(i)
            addr = i.addr + i.size
        state.use_pri()
        if state.pending is not None:
            raise NotPure()
        return state.pri, state.sp

    # ---- symbolic execution
    def run(self) -> list[Block]:
        blocks = self.split_blocks()
        self.all_blocks = blocks
        self.by_start = {b.start: b for b in blocks}
        self.index = {i.addr: k for k, i in enumerate(self.insns)}
        entry_sp = {self.start: 0}
        previous_end = 0
        absorbed: set[int] = set()
        for b in blocks:
            if b.start in absorbed:
                continue
            interp = BlockInterpreter(self, b, entry_sp.get(b.start, previous_end))
            interp.execute()
            absorbed |= interp.absorbed
            self.blocks[b.start] = b
            successors = [b.target] if b.kind in ("jump", "cond") else []
            successors += [t for _, t in b.cases]
            if b.kind in ("fall", "cond", "switch"):
                successors.append(b.end)
            for succ in successors:
                entry_sp.setdefault(succ, interp.sp)
            previous_end = interp.sp
        return [b for b in blocks if b.start not in absorbed]


class BlockInterpreter:
    """Symbolic execution of one basic block."""

    def __init__(self, fn: FunctionDecompiler, block: Block, sp: int, pure: bool = False):
        self.fn = fn
        self.block = block
        self.pri: Expr = Var("pri")
        self.alt: Expr = Var("alt")
        self.temps: list[tuple[int, Expr]] = []   # values pushed in the current statement (offset, value)
        self.sp = sp                              # STK relative to FRM
        self.pending: Expr | None = None          # PRI value with side effects not consumed yet
        self.pure = pure                          # evaluating an expression region: no statement allowed
        self.absorbed: set[int] = set()

    def clone(self) -> "BlockInterpreter":
        other = BlockInterpreter(self.fn, Block(self.block.start, []), self.sp, pure=True)
        other.pri, other.alt, other.temps, other.pending = self.pri, self.alt, list(self.temps), self.pending
        return other

    # PRI bookkeeping: a call whose result is dropped still has to be emitted.
    def set_pri(self, value: Expr) -> None:
        self.flush_pending()
        self.pri = value
        if value.side_effects:
            self.pending = value

    def use_pri(self) -> Expr:
        if self.pending is self.pri:
            self.pending = None
        return self.pri

    def flush_pending(self) -> None:
        if self.pending is not None:
            self.emit(f"{self.pending.render()};")
            self.pending = None

    def emit(self, text: str) -> None:
        if self.pure:
            raise NotPure()
        self.block.stmts.append(Stmt(text))

    def assign(self, target: Expr, value: Expr, op: str = "=") -> None:
        self.flush_pending()
        self.emit(f"{target.render()} {op} {value.render()};")

    def push(self, value: Expr) -> None:
        self.sp -= 4
        self.temps.append((self.sp, value))

    def pop(self) -> Expr:
        self.sp += 4
        if self.temps:
            return self.temps.pop()[1]
        return Var(f"pop_{-self.sp + 4:x}")

    def end_statement(self) -> None:
        """Values still pushed at a statement boundary are new local variables."""
        self.flush_pending()
        for offset, value in self.temps:
            name = f"local_{-offset:x}"
            self.fn.locals[offset] = name
            init = "" if isinstance(value, Var) and value.name.startswith("uninit") else f" = {value.render()}"
            self.emit(f"new {name}{init};")
        self.temps.clear()

    def call_args(self, count: int) -> list[Expr]:
        args = []
        for _ in range(count):
            args.append(self.pop())
        return args

    def typed_args(self, sig: dict, args: list[Expr]) -> list[Expr]:
        """Applies the parameter types inferred from the native's C++ implementation."""
        kinds = list(sig["params"])
        if sig.get("variadic") and "s" in kinds:
            fmt = args[kinds.index("s")] if kinds.index("s") < len(args) else None
            if isinstance(fmt, Lit):
                conversions = re.findall(r"%[-+ 0#]*\d*(?:\.\d+)?([a-zA-Z%])", fmt.text)
                kinds += ["f" if c in "fFeEgG" else "s" if c == "s" else "i" for c in conversions if c != "%"]
        typed = []
        for n, arg in enumerate(args):
            kind = kinds[n] if n < len(kinds) else None
            value = arg.value if isinstance(arg, HeapCell) and arg.value is not None else arg
            if kind == "f" and type(value) in (Const, Lit):
                value = Const(value.value, True)
            elif kind == "i" and type(value) is Lit:
                value = Const(value.value)
            elif kind in ("a", "S") and type(value) is Lit:
                value = self.fn.global_var(value.value)
            typed.append(value if isinstance(arg, HeapCell) else value if value is not arg else arg)
        return typed

    def native(self, index: int) -> str:
        natives = self.fn.ctx.amx.natives
        return natives[index] if index < len(natives) else f"native_{index}"

    def make_native_call(self, name: str, args: list[Expr]) -> Expr:
        sig = self.fn.ctx.native_types.get(name)
        if sig is not None:
            args = self.typed_args(sig, args)
        if name in FLOAT_OPS and len(args) == 2:
            a, b = (Const(x.value, True) if type(x) is Const else x for x in args)
            return Binary(FLOAT_OPS[name], a, b)
        if name in FLOAT_PARAMS:
            args = [Const(x.value, True) if n in FLOAT_PARAMS[name] and type(x) is Const else x
                    for n, x in enumerate(args)]
        elif name.startswith("float"):
            args = [Const(x.value, True) if type(x) is Const and looks_like_float(x.value) else x for x in args]
        return Call(name, args)

    def execute(self) -> None:
        """Runs the block; a conditional jump that only computes a value (no BREAK before the
        branches meet again) is folded into a ternary / boolean expression and the blocks of
        that region are absorbed into this one."""
        insns = list(self.block.insns)
        k = 0
        while k < len(insns):
            i = insns[k]
            merge = self.fn.expression_merge(i) if i.op in CONDITIONAL else None
            if merge is not None:
                value = self.fn.eval_conditional(self, i, merge)
                if value is not None:
                    self.set_pri(value)
                    merged = self.fn.block_at(merge)
                    for blk in self.fn.blocks_in(i.addr + i.size, merge):
                        self.absorbed.add(blk.start)
                    self.absorbed.add(merged.start)
                    self.block.end = merged.end
                    insns, k = list(merged.insns), 0
                    continue
            self.step(i)
            k += 1
        if self.block.kind == "fall":
            self.end_statement()

    def step(self, i: Instruction) -> None:
        name = i.name
        a = i.args
        # Packed opcodes behave exactly like their unpacked counterpart.
        if "_P_" in name or name.endswith("_P"):
            name = name.replace("_P_", "_").removesuffix("_P")

        if name == "BREAK":
            if self.pure:
                raise NotPure()
            self.end_statement()
        elif name in ("PROC", "NOP", "BOUNDS"):
            return
        elif name == "LOAD_PRI":
            self.set_pri(self.fn.global_var(a[0]))
        elif name == "LOAD_ALT":
            self.alt = self.fn.global_var(a[0])
        elif name == "LOAD_S_PRI":
            self.set_pri(self.fn.frame_var(a[0]))
        elif name == "LOAD_S_ALT":
            self.alt = self.fn.frame_var(a[0])
        elif name == "LREF_PRI":
            self.set_pri(Deref(self.fn.global_var(a[0])))
        elif name == "LREF_ALT":
            self.alt = Deref(self.fn.global_var(a[0]))
        elif name == "LREF_S_PRI":
            self.set_pri(self.fn.frame_var(a[0]))   # by-reference parameter: reads as the name
        elif name == "LREF_S_ALT":
            self.alt = self.fn.frame_var(a[0])
        elif name == "LOAD_BOTH":
            self.set_pri(self.fn.global_var(a[0]))
            self.alt = self.fn.global_var(a[1])
        elif name == "LOAD_S_BOTH":
            self.set_pri(self.fn.frame_var(a[0]))
            self.alt = self.fn.frame_var(a[1])
        elif name == "LOAD_I":
            self.set_pri(self.deref(self.use_pri()))
        elif name == "LODB_I":
            self.set_pri(Call(f"load_byte{a[0] * 8}", [self.use_pri()]))
        elif name == "CONST_PRI":
            self.set_pri(self.constant(a[0]))
        elif name == "CONST_ALT":
            self.alt = self.constant(a[0])
        elif name == "ADDR_PRI":
            self.set_pri(self.fn.frame_addr(a[0]))
        elif name == "ADDR_ALT":
            self.alt = self.fn.frame_addr(a[0])
        elif name == "STOR_PRI":
            self.store(self.fn.global_var(a[0]))
        elif name == "STOR_ALT":
            self.flush_pending()
            self.emit(f"{self.fn.global_var(a[0]).render()} = {self.alt.render()};")
        elif name == "STOR_S_PRI":
            if not self.initialise(a[0], self.pri):
                self.store(self.fn.frame_var(a[0]))
        elif name == "STOR_S_ALT":
            self.flush_pending()
            self.emit(f"{self.fn.frame_var(a[0]).render()} = {self.alt.render()};")
        elif name in ("SREF_PRI", "SREF_S_PRI"):
            var = self.fn.global_var(a[0]) if name == "SREF_PRI" else self.fn.frame_var(a[0])
            self.store(var)
        elif name in ("SREF_ALT", "SREF_S_ALT"):
            var = self.fn.global_var(a[0]) if name == "SREF_ALT" else self.fn.frame_var(a[0])
            self.flush_pending()
            self.emit(f"{var.render()} = {self.alt.render()};")
        elif name == "STOR_I" and isinstance(self.alt, HeapCell):
            self.alt.value = self.use_pri()
        elif name == "STOR_I":
            self.store(self.deref(self.alt))
        elif name == "STRB_I":
            value = self.use_pri()
            self.flush_pending()
            self.emit(f"store_byte{a[0] * 8}({self.alt.render()}, {value.render()});")
        elif name == "LIDX":
            self.set_pri(Index(self.array_base(self.alt), self.use_pri()))
        elif name == "LIDX_B":
            self.set_pri(Index(self.array_base(self.alt), self.use_pri(), a[0]))
        elif name == "IDXADDR":
            self.set_pri(AddrOf(Index(self.array_base(self.alt), self.use_pri())))
        elif name == "IDXADDR_B":
            self.set_pri(AddrOf(Index(self.array_base(self.alt), self.use_pri(), a[0])))
        elif name in ("ALIGN_PRI", "ALIGN_ALT"):
            return   # byte addressing inside packed strings: no effect on readability
        elif name == "LCTRL":
            self.set_pri(Var(["COD", "DAT", "HEA", "STP", "STK", "FRM", "CIP"][a[0]] if a[0] < 7 else f"ctrl{a[0]}"))
        elif name == "SCTRL":
            self.flush_pending()
            self.emit(f"/* sctrl {a[0]}, {self.use_pri().render()} */")
        elif name == "MOVE_PRI":
            self.set_pri(self.alt)
        elif name == "MOVE_ALT":
            self.alt = self.use_pri()
        elif name == "XCHG":
            pri = self.use_pri()
            self.pri, self.alt = self.alt, pri
        elif name == "PUSH_PRI":
            self.push(self.use_pri())
        elif name == "PUSH_ALT":
            self.push(self.alt)
        elif name in ("PUSH_C", "PUSH2_C", "PUSH3_C", "PUSH4_C", "PUSH5_C"):
            for v in a:
                self.push(self.constant(v))
        elif name in ("PUSH", "PUSH2", "PUSH3", "PUSH4", "PUSH5"):
            for v in a:
                self.push(self.fn.global_var(v))
        elif name in ("PUSH_S", "PUSH2_S", "PUSH3_S", "PUSH4_S", "PUSH5_S"):
            for v in a:
                self.push(self.fn.frame_var(v))
        elif name in ("PUSH_ADR", "PUSH2_ADR", "PUSH3_ADR", "PUSH4_ADR", "PUSH5_ADR"):
            for v in a:
                self.push(self.fn.frame_addr(v))
        elif name == "PICK":
            self.set_pri(Var(f"stack[{a[0]}]"))
        elif name == "POP_PRI":
            self.set_pri(self.pop())
        elif name == "POP_ALT":
            self.alt = self.pop()
        elif name == "STACK":
            self.stack(a[0])
        elif name == "HEAP":
            if a[0] > 0:
                self.alt = HeapCell()
        elif name in ("RET", "RETN"):
            self.block.kind = "return"
            self.block.value = self.use_pri()
            self.pending = None
        elif name == "CALL":
            target = i.addr + a[0]
            count = self.pop()
            n = count.value // 4 if isinstance(count, Const) else 0
            args = self.call_args(n)
            inline = self.fn.ctx.inline.get(target)
            if inline is not None:
                self.set_pri(substitute(inline[1], args))
            else:
                self.set_pri(Call(self.fn.ctx.function_label(target), args))
        elif name == "SYSREQ_N":
            self.set_pri(self.make_native_call(self.native(a[0]), self.call_args(a[1] // 4)))
        elif name == "SYSREQ_C":
            count = self.temps[-1][1] if self.temps else None
            n = count.value // 4 if isinstance(count, Const) else 0
            self.pop()
            args = self.call_args(n)
            self.sp -= 4 * (n + 1)   # the caller's following STACK instruction releases them
            self.set_pri(self.make_native_call(self.native(a[0]), args))
        elif name == "SYSREQ_PRI":
            self.set_pri(Call(f"native[{self.use_pri().render()}]", []))
        elif name in ("JUMP", "JZER", "JNZ", "JEQ", "JNEQ", "JLESS", "JLEQ", "JGRTR", "JGEQ",
                      "JSLESS", "JSLEQ", "JSGRTR", "JSGEQ"):
            self.branch(name, i.addr + a[0])
        elif name == "SWITCH":
            self.block.kind = "switch"
            self.block.value = self.use_pri()
            table = self.fn.ctx.casetbl.get(i.addr + a[0])
            self.block.cases = table.cases if table else []
            self.flush_pending()
        elif name in ("CASETBL", "ICASETBL"):
            return
        elif name == "HALT" and a[0] == AMX_ERR_SLEEP:
            # `sleep [value]`: the script yields to the engine until the next frame.
            value = self.use_pri()
            self.flush_pending()
            shown = "" if isinstance(value, Var) and value.name in ("pri", "alt") else f" {value.render()}"
            self.emit(f"sleep{shown};")
        elif name == "HALT":
            self.flush_pending()
            self.emit("exit;" if a[0] == 0 else f"halt({a[0]});")
            self.block.kind = "halt"
        elif name == "ADD" and (self.is_row(self.pri, self.alt) or self.is_row(self.alt, self.pri)):
            index = self.alt if isinstance(self.alt, Index) else self.use_pri()
            self.use_pri()
            self.set_pri(Row(index.base, index.index))
        elif name in ("SHL", "SHR", "SSHR", "SMUL", "SDIV", "UMUL", "UDIV", "ADD", "SUB", "AND", "OR", "XOR",
                      "EQ", "NEQ", "LESS", "LEQ", "GRTR", "GEQ", "SLESS", "SLEQ", "SGRTR", "SGEQ"):
            ops = {"SHL": "<<", "SHR": ">>>", "SSHR": ">>", "SMUL": "*", "SDIV": "/", "UMUL": "*", "UDIV": "/",
                   "ADD": "+", "SUB": "-", "AND": "&", "OR": "|", "XOR": "^", "EQ": "==", "NEQ": "!=",
                   "LESS": "<", "LEQ": "<=", "GRTR": ">", "GEQ": ">=", "SLESS": "<", "SLEQ": "<=",
                   "SGRTR": ">", "SGEQ": ">="}
            self.set_pri(Binary(ops[name], self.use_pri(), self.alt))
        elif name in ("SUB_ALT", "SDIV_ALT", "UDIV_ALT"):
            self.set_pri(Binary({"SUB_ALT": "-", "SDIV_ALT": "/", "UDIV_ALT": "/"}[name], self.alt, self.use_pri()))
        elif name in ("SHL_C_PRI", "SHR_C_PRI"):
            self.set_pri(Binary("<<" if name == "SHL_C_PRI" else ">>>", self.use_pri(), Const(a[0])))
        elif name in ("SHL_C_ALT", "SHR_C_ALT"):
            self.alt = Binary("<<" if name == "SHL_C_ALT" else ">>>", self.alt, Const(a[0]))
        elif name == "ADD_C":
            self.set_pri(self.add_const(self.use_pri(), a[0]))
        elif name == "SMUL_C":
            self.set_pri(Binary("*", self.use_pri(), Const(a[0])))
        elif name == "NOT":
            self.set_pri(negate(self.use_pri()))
        elif name == "NEG":
            self.set_pri(Unary("-", self.use_pri()))
        elif name == "INVERT":
            self.set_pri(Unary("~", self.use_pri()))
        elif name == "ZERO_PRI":
            self.set_pri(Const(0))
        elif name == "ZERO_ALT":
            self.alt = Const(0)
        elif name == "ZERO":
            self.assign(self.fn.global_var(a[0]), Const(0))
        elif name == "ZERO_S":
            self.assign(self.fn.frame_var(a[0]), Const(0))
        elif name in ("SIGN_PRI", "SIGN_ALT"):
            return
        elif name == "EQ_C_PRI":
            self.set_pri(Binary("==", self.use_pri(), self.constant(a[0])))
        elif name == "EQ_C_ALT":
            self.set_pri(Binary("==", self.alt, self.constant(a[0])))
        elif name in ("INC_PRI", "DEC_PRI"):
            self.set_pri(self.add_const(self.use_pri(), 1 if name == "INC_PRI" else -1))
        elif name in ("INC_ALT", "DEC_ALT"):
            self.alt = self.add_const(self.alt, 1 if name == "INC_ALT" else -1)
        elif name in ("INC", "DEC", "INC_S", "DEC_S", "INC_I", "DEC_I"):
            var = (self.fn.global_var(a[0]) if name in ("INC", "DEC") else
                   self.fn.frame_var(a[0]) if name in ("INC_S", "DEC_S") else self.deref(self.use_pri()))
            self.flush_pending()
            self.emit(f"{var.render()}{'++' if name.startswith('INC') else '--'};")
        elif name == "MOVS" and isinstance(self.alt, HeapCell):
            self.alt.value = self.use_pri()   # constant array copied to the heap to be passed
        elif name == "MOVS":
            self.flush_pending()
            self.emit(f"memcpy({self.alt.render()}, {self.use_pri().render()}, {a[0] // 4});   // {a[0]:#x} bytes")
        elif name == "CMPS":
            self.set_pri(Call("memcmp", [self.alt, self.use_pri(), Const(a[0])]))
        elif name == "FILL":
            self.fill(a[0])
        elif name in ("SWAP_PRI", "SWAP_ALT"):
            top = self.pop()
            if name == "SWAP_PRI":
                self.push(self.use_pri())
                self.set_pri(top)
            else:
                self.push(self.alt)
                self.alt = top
        elif name == "CONST":
            self.assign(self.fn.global_var(a[0]), self.constant(a[1]))
        elif name == "CONST_S":
            if not self.initialise(a[0], self.constant(a[1])):
                self.assign(self.fn.frame_var(a[0]), self.constant(a[1]))
        elif name == "JREL":
            self.emit(f"/* jrel {a[0]} */")
        else:
            self.emit(f"/* unhandled {i.name} {a} */")

    # ---- helpers
    def constant(self, value: int) -> Expr:
        # 0 is zero/false/NULL, and round decimal numbers (100, 10000 ...) are far more likely
        # values than string addresses.
        if value <= 0 or value >= 100 and value % 100 == 0:
            return Const(value)
        text = self.fn.ctx.amx.string_at(value)
        return Lit(value, text=text) if text is not None else Const(value)

    def initialise(self, offset: int, value: Expr) -> bool:
        """`stack -4` followed by a store: the store is the initialiser of the new local."""
        for n, (temp_offset, temp) in enumerate(self.temps):
            if temp_offset == offset and isinstance(temp, Var) and temp.name == "uninit":
                if value is self.pri:
                    value = self.use_pri()
                    self.pri = Var(f"local_{-offset:x}")
                self.temps[n] = (offset, value)
                return True
        return False

    def add_const(self, expr: Expr, value: int) -> Expr:
        if isinstance(expr, AddrOf) and value % 4 == 0 and isinstance(expr.target, Var):
            return AddrOf(Index(expr.target, Const(value // 4)))
        if value < 0:
            return Binary("-", expr, Const(-value))
        return Binary("+", expr, Const(value))

    def deref(self, address: Expr) -> Expr:
        if isinstance(address, AddrOf):
            return address.target
        if type(address) in (Const, Lit):
            return self.fn.global_var(address.value)
        # Two-dimensional arrays: a row is &a[i] + a[i] (indirection vector of relative offsets).
        if isinstance(address, Binary) and address.op == "+" and isinstance(address.right, Const) \
                and address.right.value % 4 == 0 and isinstance(address.left, Row):
            return Index(address.left, Const(address.right.value // 4))
        if isinstance(address, Row):
            return Index(address, Const(0))
        if (isinstance(address, Binary) and address.op == "+" and type(address.left) in (Const, Lit)
                and type(address.right) is Const and address.right.value % 4 == 0):
            return Index(self.fn.global_var(address.left.value), Const(address.right.value // 4))
        # Array parameters hold an address: arg + 8 is &arg[2].
        if isinstance(address, Var) and address.name.startswith("arg"):
            return Index(address, Const(0))
        if (isinstance(address, Binary) and address.op == "+" and isinstance(address.left, Var)
                and address.left.name.startswith("arg") and type(address.right) is Const
                and address.right.value % 4 == 0):
            return Index(address.left, Const(address.right.value // 4))
        if (isinstance(address, Binary) and address.op == "+" and isinstance(address.right, Const)
                and address.right.value % 4 == 0 and isinstance(address.left, AddrOf)):
            return Index(address.left.target, Const(address.right.value // 4))
        return Deref(address)

    @staticmethod
    def is_row(a: Expr, b: Expr) -> bool:
        """&arr[i] + arr[i]: address of row i of a two-dimensional array."""
        return (isinstance(a, AddrOf) and isinstance(a.target, Index) and isinstance(b, Index)
                and a.target.base == b.base and a.target.index == b.index)

    def array_base(self, expr: Expr) -> Expr:
        if isinstance(expr, AddrOf):
            return expr.target
        if type(expr) in (Const, Lit):
            return self.fn.global_var(expr.value)
        return expr

    def store(self, target: Expr) -> None:
        value = self.use_pri()
        self.flush_pending()
        self.emit(f"{target.render()} = {value.render()};")
        self.pri = target   # later uses of PRI read the variable, not a second evaluation

    def stack(self, delta: int) -> None:
        self.alt = Var("STK")
        if delta < 0:
            # Allocation of uninitialised locals; an array is filled right after.
            start = self.sp + delta
            if delta == -4:
                self.push(Var("uninit"))
            else:
                self.end_statement()
                name = f"local_{-start:x}"
                self.fn.locals[start] = name
                self.fn.arrays[start] = (name, -delta // 4)
                self.emit(f"new {name}[{-delta // 4}];")
                self.sp = start
        else:
            target = self.sp + delta
            while self.temps and self.temps[-1][0] < target:
                self.temps.pop()
            # Leaving a scope: its arrays are freed, later locals may reuse the slots.
            for start in [x for x in self.fn.arrays if x < target]:
                del self.fn.arrays[start]
            self.sp = target

    def fill(self, size: int) -> None:
        value = self.use_pri()
        if isinstance(value, Const) and value.value == 0 and isinstance(self.alt, AddrOf):
            return   # zero-initialisation of a new array: implied by the declaration
        self.flush_pending()
        self.emit(f"fill({self.alt.render()}, {value.render()}, {size // 4});")

    def branch(self, name: str, target: int) -> None:
        b = self.block
        b.target = target
        if name == "JUMP":
            self.end_statement()
            b.kind = "jump"
            return
        cond = self.condition(name)
        self.end_statement()
        b.kind = "cond"
        b.cond = cond

    def condition(self, name: str) -> Expr:
        """Condition under which a conditional jump is taken."""
        pri = self.use_pri()
        if name == "JZER":
            return negate(truth(pri))
        if name == "JNZ":
            return truth(pri)
        op = {"JEQ": "==", "JNEQ": "!=", "JLESS": "<", "JLEQ": "<=", "JGRTR": ">", "JGEQ": ">=",
              "JSLESS": "<", "JSLEQ": "<=", "JSGRTR": ">", "JSGEQ": ">="}[name]
        return Binary(op, pri, self.alt)


# --------------------------------------------------------------------------------------------
# Control-flow structuring

class Structurer:
    """Rebuilds if/else, loops and switches from the linear block layout of the Pawn compiler."""

    def __init__(self, fn: FunctionDecompiler, blocks: list[Block]):
        self.fn = fn
        self.blocks = blocks
        self.index = {b.start: n for n, b in enumerate(blocks)}
        self.labels_needed: set[int] = set()
        self.casetbl_blocks = {b.start for b in blocks if b.insns and b.insns[0].op == OP["CASETBL"]}

    def block_at(self, addr: int) -> Block | None:
        n = self.index.get(addr)
        return self.blocks[n] if n is not None else None

    def emit(self) -> list[str]:
        lines = self.region(self.fn.start, self.fn.end, None, 1)
        # Labels that are still jumped to with goto.
        out = []
        for line in lines:
            out.append(line)
        return out

    def region(self, start: int, end: int, loop: tuple[int, int] | None, depth: int) -> list[str]:
        pad = "    " * depth
        out: list[str] = []
        addr = start
        while addr < end:
            b = self.block_at(addr)
            if b is None:
                break
            if b.start in self.casetbl_blocks:
                addr = b.end
                continue
            if b.start in self.labels_needed or b.start in self.fn.ctx.goto_targets.get(self.fn.start, set()):
                out.append(f"{'    ' * (depth - 1)}  L_{b.start:04x}:")

            # Loop: a later block in this region jumps back here.
            back = [x for x in self.blocks if b.start <= x.start < end
                    and x.kind in ("jump", "cond") and x.target == b.start]
            if back and (loop is None or loop[0] != b.start):
                tail = max(back, key=lambda x: x.start)
                exit_addr = tail.end
                lines = self.loop(b, tail, exit_addr, depth)
                if lines is not None:
                    out += lines
                    addr = exit_addr
                    continue

            if b.kind == "jump" and (result := self.for_loop(b, end, depth)) is not None:
                lines, addr = result
                out += lines
                continue
            out += [pad + s.text for s in b.stmts]
            nxt = b.end
            if b.kind == "return":
                last_in_function = b.end >= self.fn.end or all(
                    x.start in self.casetbl_blocks for x in self.blocks if x.start >= b.end)
                v = b.value
                if not (last_in_function and isinstance(v, Const) and v.value == 0):
                    out.append(pad + ("return;" if v is None else f"return {v.render()};"))
                addr = nxt
            elif b.kind == "halt":
                addr = nxt
            elif b.kind == "jump":
                out.append(pad + self.jump_text(b.target, loop))
                addr = nxt
            elif b.kind == "cond":
                lines, addr = self.conditional(b, end, loop, depth)
                out += lines
            elif b.kind == "switch":
                lines, addr = self.switch(b, end, loop, depth)
                out += lines
            else:
                addr = nxt
        return out

    def jump_text(self, target: int, loop: tuple[int, int] | None) -> str:
        if loop and target == loop[1]:
            return "break;"
        if loop and target == loop[0]:
            return "continue;"
        self.labels_needed.add(target)
        self.fn.ctx.goto_targets.setdefault(self.fn.start, set()).add(target)
        return f"goto L_{target:04x};"

    def condition_chain(self, b: Block, region_end: int) -> tuple[Expr, int, int]:
        """Merges consecutive condition-only blocks into && / || chains.

        Returns (condition for entering the then-part, then start, else target)."""
        cond = negate(b.cond)          # the jump skips the then-part
        else_target = b.target
        nxt = self.block_at(b.end)
        while (nxt is not None and nxt.kind == "cond" and not nxt.stmts and nxt.start < else_target
               and nxt.target == else_target and nxt.start not in self.fn.ctx.goto_targets.get(self.fn.start, set())
               and self.single_entry(nxt)):
            cond = Binary("&&", cond, negate(nxt.cond))
            nxt = self.block_at(nxt.end)
        return cond, (nxt.start if nxt else b.end), else_target

    def single_entry(self, b: Block) -> bool:
        return not any(x.kind in ("jump", "cond") and x.target == b.start for x in self.blocks) and \
            not any(t == b.start for x in self.blocks for _, t in x.cases)

    def conditional(self, b: Block, end: int, loop, depth: int) -> tuple[list[str], int]:
        pad = "    " * depth
        out = list()
        # `a || b`: cond1 jumps into the then-part, cond2 jumps over it.
        nxt = self.block_at(b.end)
        if (b.target > b.start and nxt is not None and nxt.kind == "cond" and not nxt.stmts
                and b.target == nxt.end and nxt.target > nxt.end and self.single_entry(nxt)):
            cond = Binary("||", b.cond, negate(nxt.cond))
            fake = Block(b.start, [], nxt.end, kind="cond", target=nxt.target, cond=negate(cond))
            return self.if_else(fake, cond, nxt.end, nxt.target, end, loop, depth)

        if loop and b.target == loop[1]:
            out.append(pad + f"if ({b.cond.render()}) break;")
            return out, b.end
        if loop and b.target == loop[0]:
            out.append(pad + f"if ({b.cond.render()}) continue;")
            return out, b.end
        if not (b.start < b.target <= end):
            out.append(pad + f"if ({b.cond.render()}) {self.jump_text(b.target, loop)}")
            return out, b.end
        cond, then_start, else_target = self.condition_chain(b, end)
        return self.if_else(b, cond, then_start, else_target, end, loop, depth)

    def if_else(self, b: Block, cond: Expr, then_start: int, else_target: int, end: int, loop, depth: int):
        pad = "    " * depth
        out = []
        # Last block of the then-part: an unconditional forward jump means there is an else.
        last = self.last_block_before(else_target)
        else_end = None
        if (last is not None and last.kind == "jump" and last.target is not None
                and else_target < last.target <= end and not (loop and last.target in loop)):
            else_end = last.target
        out.append(pad + f"if ({cond.render()}) {{")
        if else_end is not None:
            then_lines = self.region_without_final_jump(then_start, else_target, last, loop, depth + 1)
            out += then_lines
            out.append(pad + "} else {")
            out += self.region(else_target, else_end, loop, depth + 1)
            out.append(pad + "}")
            return out, else_end
        out += self.region(then_start, else_target, loop, depth + 1)
        out.append(pad + "}")
        return out, else_target

    def last_block_before(self, addr: int) -> Block | None:
        candidates = [x for x in self.blocks if x.end == addr]
        return candidates[0] if candidates else None

    def region_without_final_jump(self, start: int, end: int, last: Block, loop, depth: int) -> list[str]:
        kind = last.kind
        last.kind = "fall"
        try:
            return self.region(start, end, loop, depth)
        finally:
            last.kind = kind

    def loop(self, head: Block, tail: Block, exit_addr: int, depth: int) -> list[str] | None:
        pad = "    " * depth
        loop = (head.start, exit_addr)
        if tail.kind == "cond":
            # do { body } while (cond): the condition evaluation is the tail block itself.
            kind = tail.kind
            tail.kind = "fall"
            try:
                body = self.region(head.start, tail.end, loop, depth + 1)
            finally:
                tail.kind = kind
            return [pad + "do {"] + body + [pad + f"}} while ({tail.cond.render()});"]
        # while (cond) / for(;;): head tests the condition and jumps to the exit.
        if head.kind == "cond" and head.target == exit_addr and not head.stmts:
            cond = negate(head.cond)
            kind = tail.kind
            tail.kind = "fall"
            try:
                body = self.region(head.end, tail.end, loop, depth + 1)
            finally:
                tail.kind = kind
            return [pad + f"while ({cond.render()}) {{"] + body + [pad + "}"]
        kind = tail.kind
        tail.kind = "fall"
        try:
            body = self.region(head.start, tail.end, loop, depth + 1) if head is not tail else \
                [pad + "    " + s.text for s in head.stmts]
        finally:
            tail.kind = kind
        return [pad + "for (;;) {"] + body + [pad + "}"]

    def for_loop(self, b: Block, end: int, depth: int) -> tuple[list[str], int] | None:
        """Pawn's `for`: the init jumps forward over the increment to the condition test."""
        top = b.end
        cond_block = self.block_at(b.target) if b.target is not None else None
        if cond_block is None or not (top < b.target < end) or cond_block.kind != "cond" or cond_block.stmts:
            return None
        tails = [x for x in self.blocks if x.kind == "jump" and x.target == top and x.start >= cond_block.end]
        if not tails:
            return None
        tail = max(tails, key=lambda x: x.start)
        exit_addr = tail.end
        if cond_block.target != exit_addr or exit_addr > end:
            return None
        increment = [s.text.rstrip(";") for x in self.blocks if top <= x.start < b.target for s in x.stmts]
        if any(x.kind != "fall" for x in self.blocks if top <= x.start < b.target):
            return None
        pad = "    " * depth
        init = ""
        if b.stmts:
            init = b.stmts[-1].text.rstrip(";")
            b.stmts = b.stmts[:-1]
        head = [pad + s.text for s in b.stmts]
        loop = (top, exit_addr)
        kind = tail.kind
        tail.kind = "fall"
        try:
            body = self.region(cond_block.end, tail.end, loop, depth + 1)
        finally:
            tail.kind = kind
        cond = negate(cond_block.cond).render()
        head.append(pad + f"for ({init}; {cond}; {', '.join(increment)}) {{")
        return head + body + [pad + "}"], exit_addr

    def switch(self, b: Block, end: int, loop, depth: int) -> tuple[list[str], int]:
        pad = "    " * depth
        out = [pad + f"switch ({b.value.render()}) {{"]
        if not b.cases:
            return out + [pad + "}"], b.end
        # The exit is the address after the CASETBL; every case jumps there.
        table = next((x for x in self.blocks if x.start in self.casetbl_blocks and x.start >= b.end), None)
        exit_addr = table.end if table else end
        targets = sorted({t for _, t in b.cases[1:]} | {b.cases[0][1]})
        bodies = [t for t in targets if t < (table.start if table else exit_addr)]
        bounds = bodies + [table.start if table else exit_addr]
        inner_loop = (loop[0] if loop else -1, exit_addr)
        for n, t in enumerate(bodies):
            values = [v for v, target in b.cases[1:] if target == t]
            label = ", ".join(str(Const(v)) for v in values)
            header = f"case {label}:" if values else ""
            if t == b.cases[0][1]:
                header = (header + " " if header else "") + "default:"
            out.append(pad + "    " + header)
            body = self.region(t, bounds[n + 1], inner_loop, depth + 2)
            if body and body[-1].strip() == "break;":
                body = body[:-1]
            out += body
        out.append(pad + "}")
        return out, exit_addr


# --------------------------------------------------------------------------------------------
# Script

COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


def substitute(expr: Expr, args: list[Expr]) -> Expr:
    """Copy of a template expression with argN replaced by the call arguments."""
    if isinstance(expr, Var) and expr.name.startswith("arg") and expr.name[3:].isdigit():
        return args[int(expr.name[3:])]
    if not dataclasses.is_dataclass(expr):
        return expr
    changes = {}
    for f in dataclasses.fields(expr):
        value = getattr(expr, f.name)
        if isinstance(value, Expr):
            changes[f.name] = substitute(value, args)
        elif isinstance(value, list):
            changes[f.name] = [substitute(v, args) if isinstance(v, Expr) else v for v in value]
    return dataclasses.replace(expr, **changes)


def as_float_operand(e: Expr) -> Expr:
    """Operand of a Float operator: int conversions are implicit, constants are float literals."""
    if isinstance(e, Call) and e.name == "float" and len(e.args) == 1:
        return e.args[0]
    if type(e) is Const:
        return Const(e.value, True)
    return e


def operator_template(expr: Expr | None) -> tuple[str, Expr] | None:
    """Recognises the float.inc stocks: floatcmp(a, b) <op> 0, a ^ cellmin (negation), a op b."""
    def is_arg(e: Expr) -> bool:
        e = e.args[0] if isinstance(e, Call) and e.name == "float" and len(e.args) == 1 else e
        return isinstance(e, Var) and e.name in ("arg0", "arg1")
    if (isinstance(expr, Binary) and expr.op in COMPARISONS and isinstance(expr.left, Call)
            and expr.left.name == "floatcmp" and type(expr.right) is Const and expr.right.value == 0
            and len(expr.left.args) == 2 and all(is_arg(a) for a in expr.left.args)):
        a, b = expr.left.args
        return expr.op, Binary(expr.op, as_float_operand(a), as_float_operand(b))
    if (isinstance(expr, Binary) and expr.op == "^" and isinstance(expr.left, Var) and expr.left.name == "arg0"
            and type(expr.right) is Const and expr.right.value == -0x80000000):
        return "-", Unary("-", Var("arg0"))
    if isinstance(expr, Binary) and expr.op in ("+", "-", "*", "/") and is_arg(expr.left) and is_arg(expr.right):
        return expr.op, Binary(expr.op, as_float_operand(expr.left), as_float_operand(expr.right))
    return None


class ScriptDecompiler:
    def __init__(self, amx: AmxFile, native_impl: dict[str, tuple[int, str]] | None = None):
        self.amx = amx
        self.native_impl = native_impl or {}
        self.insns = list(amx.instructions())
        self.publics = {addr: name for addr, name in amx.publics}
        self.names = function_names(amx, self.insns)
        self.pubvars = {addr: name for addr, name in amx.pubvars}
        self.casetbl = {i.addr: i for i in self.insns if i.cases}
        self.inline: dict[int, tuple[str, Expr]] = {}   # function -> (operator, template)
        path = ROOT / "extracted" / "native_types.json"
        self.native_types = json.loads(path.read_text()) if path.exists() else {}
        self.goto_targets: dict[int, set[int]] = {}
        self.globals_used: set[int] = set()

    def function_label(self, addr: int) -> str:
        if addr in self.publics:
            return self.publics[addr]
        if addr in self.names:
            return self.names[addr][1]
        if addr == self.amx.header["cip"]:
            return "main"
        return f"func_{addr:04x}"

    def global_name(self, addr: int) -> str:
        self.globals_used.add(addr)
        return self.pubvars.get(addr, f"g_{addr:04x}")

    def functions(self):
        starts = [i.addr for i in self.insns if i.op == OP["PROC"]]
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(self.amx.code)
            yield start, end, [i for i in self.insns if start <= i.addr < end]

    def find_operators(self) -> None:
        """First pass: functions that are only `return <operator on the arguments>;`."""
        for start, end, insns in self.functions():
            if start in self.publics:
                continue
            fn = FunctionDecompiler(self, start, end, insns)
            blocks = fn.run()
            if any(b.stmts for b in blocks):
                continue
            returns = [b for b in blocks if b.kind == "return"]
            if len(returns) == 1 and returns[0] is blocks[0]:
                template = operator_template(returns[0].value)
                if template is not None:
                    self.inline[start] = template
        self.globals_used.clear()

    def decompile(self) -> str:
        self.find_operators()
        h = self.amx.header
        out = [f"// {self.amx.name}.amx — pseudo-Pawn decompiled from the game's compiled script.",
               "// Synthetic names: argN (parameters), local_X (frame offset), g_X (data offset), func_X (code offset).",
               ""]
        used_natives = sorted(set(self.amx.natives))
        out.append(f"// natives used: {len(used_natives)}")
        bodies = []
        for start, end, insns in self.functions():
            fn = FunctionDecompiler(self, start, end, insns)
            blocks = fn.run()
            lines = Structurer(fn, blocks).emit()
            name = self.function_label(start)
            source = f"  // {self.names[start][0]}" if start in self.names else ""
            if start in self.inline:
                name = f"operator{self.inline[start][0]}"
                source = "  // Float operator (float.inc), inlined at call sites"
            params = ", ".join(f"arg{n}" for n in range(fn.max_param + 1))
            prefix = "public " if start in self.publics else ""
            entry = "  // entry point" if start == h["cip"] else ""
            bodies.append("")
            bodies.append(f"// {start:#06x}{source}{entry}")
            bodies.append(f"{prefix}{name}({params})")
            bodies.append("{")
            bodies += lines
            bodies.append("}")
        if self.globals_used:
            out.append("")
            for addr in sorted(self.globals_used):
                init = struct.unpack_from("<i", self.amx.data, addr)[0] if addr + 4 <= len(self.amx.data) else 0
                name = self.pubvars.get(addr, f"g_{addr:04x}")
                public = "public " if addr in self.pubvars else ""
                out.append(f"{public}new {name} = {init};" if init else f"{public}new {name};")
        return "\n".join(out + bodies) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help=".amx files (default: every romfs:/amx script)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "decomp" / "scripts")
    args = ap.parse_args()

    files = args.files or sorted((ROOT / "extracted" / "romfs" / "amx").glob("*.amx"))
    args.out.mkdir(parents=True, exist_ok=True)
    for path in files:
        amx = AmxFile.load(path)
        (args.out / f"{amx.name}.p").write_text(ScriptDecompiler(amx).decompile())
    print(f"[+] {len(files)} scripts decompiled into {args.out}")


if __name__ == "__main__":
    main()
