#!/usr/bin/env python3
"""Bot sandbox: runs the pilot of the online bots (mods/en-ligne/bots_ia.pasm, assembled into the game's
surface_sub.amx) in a small world of our own, to check it without the emulator.

    tools/botsim.py                      # every scenario, at every level
    tools/botsim.py duel --level 3 -v    # one scenario, with a trace

A tool of the developers (it needs the dump: extracted/romfs, extracted/xml). The world: the sea floor, boxes
for rocks and walls, subs (the bots, each running its own copy of the script, and scripted players), the
torpedoes (the game's physics: surface_torpedo.p, func_1778 and func_2ef4). It is not the game: what it checks
is that the script runs without a fault of the abstract machine, and how the pilot behaves (hits, misses,
time stuck in walls, distance kept, depth matched).

The AMX interpreter follows amx.c of Pawn 3.3 for the opcodes the compiler emits.
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amx import BRANCHES, NPARAMS, OP, OPCODES, decode  # noqa: E402
from amxasm import AmxImage  # noqa: E402

ROMFS = ROOT / "extracted" / "romfs"
BXML = ROOT / "extracted" / "xml" / "bxml"
PASM = ROOT / "mods" / "en-ligne"

MASK = 0xFFFFFFFF


def s32(v: int) -> int:
    v &= MASK
    return v - (1 << 32) if v & 0x80000000 else v


def f2c(f: float) -> int:
    return struct.unpack("<i", struct.pack("<f", f))[0]


def c2f(c: int) -> float:
    return struct.unpack("<f", struct.pack("<i", s32(c)))[0]


class AmxFault(Exception):
    pass


# ---- the abstract machine --------------------------------------------------------------------------

class Amx:
    """One script instance: code shared, its own data, heap and stack."""

    def __init__(self, image: AmxImage, natives) -> None:
        self.image = image
        self.code = bytes(image.code)
        self.ncells = (len(image.data) + image.heapstack) // 4
        self.mem = list(struct.unpack(f"<{len(image.data) // 4}i", bytes(image.data))) + \
            [0] * (image.heapstack // 4)
        self.hea = len(image.data)
        self.stp = self.ncells * 4
        self.stk = self.stp
        self.frm = 0
        self.native_names = [name for _, name, _ in image.natives]
        self.natives = natives
        self.insns = {i.addr: i for i in decode(self.code)}
        self.steps = 0

    # memory, by byte address (cells only)
    def rd(self, addr: int) -> int:
        if addr % 4 or not 0 <= addr < self.stp:
            raise AmxFault(f"read at {addr:#x}")
        return self.mem[addr // 4]

    def wr(self, addr: int, value: int) -> None:
        if addr % 4 or not 0 <= addr < self.stp:
            raise AmxFault(f"write at {addr:#x}")
        self.mem[addr // 4] = s32(value)

    def push(self, v: int) -> None:
        self.stk -= 4
        if self.stk < self.hea:
            raise AmxFault("stack overflow")
        self.mem[self.stk // 4] = s32(v)

    def pop(self) -> int:
        v = self.mem[self.stk // 4]
        self.stk += 4
        return v

    def string(self, addr: int) -> str:
        out = []
        while True:
            c = self.rd(addr)
            if not c:
                return "".join(out)
            if c > 0xFF:                                  # packed: four characters per cell, big end first
                for shift in (24, 16, 8, 0):
                    ch = (c >> shift) & 0xFF
                    if not ch:
                        return "".join(out)
                    out.append(chr(ch))
            else:
                out.append(chr(c))
            addr += 4

    def put_string(self, addr: int, text: str, size: int) -> None:
        for i, ch in enumerate(text[:size - 1]):
            self.wr(addr + 4 * i, ord(ch))
        self.wr(addr + 4 * min(len(text), size - 1), 0)

    def vec(self, addr: int) -> list[float]:
        return [c2f(self.rd(addr + 4 * i)) for i in range(3)]

    def put_vec(self, addr: int, v) -> None:
        for i in range(3):
            self.wr(addr + 4 * i, f2c(v[i]))

    def call(self, address: int, *args: int, limit: int = 3_000_000) -> int:
        """Calls a Pawn function (PROC at address) with these cell arguments; returns pri."""
        for a in reversed(args):
            self.push(a)
        self.push(4 * len(args))
        self.push(-1)                                     # return address: stop
        return self.run(address, limit)

    def run(self, cip: int, limit: int) -> int:
        pri = alt = 0
        mem = self.mem
        insns = self.insns
        steps = 0
        while True:
            if cip == -1:
                self.steps += steps
                return pri
            steps += 1
            if steps > limit:
                raise AmxFault(f"more than {limit} instructions (endless loop?) at {cip:#x}")
            i = insns.get(cip)
            if i is None:
                raise AmxFault(f"no instruction at {cip:#x}")
            n = OPCODES[i.op]
            a = i.args
            nxt = cip + i.size
            if n == "BREAK" or n == "NOP":
                pass
            elif n == "LOAD_PRI":
                pri = self.rd(a[0])
            elif n == "LOAD_ALT":
                alt = self.rd(a[0])
            elif n == "LOAD_S_PRI":
                pri = self.rd(self.frm + a[0])
            elif n == "LOAD_S_ALT":
                alt = self.rd(self.frm + a[0])
            elif n == "LREF_PRI":
                pri = self.rd(self.rd(a[0]))
            elif n == "LREF_ALT":
                alt = self.rd(self.rd(a[0]))
            elif n == "LREF_S_PRI":
                pri = self.rd(self.rd(self.frm + a[0]))
            elif n == "LREF_S_ALT":
                alt = self.rd(self.rd(self.frm + a[0]))
            elif n == "LOAD_I":
                pri = self.rd(pri)
            elif n == "CONST_PRI":
                pri = a[0]
            elif n == "CONST_ALT":
                alt = a[0]
            elif n == "ADDR_PRI":
                pri = self.frm + a[0]
            elif n == "ADDR_ALT":
                alt = self.frm + a[0]
            elif n == "STOR_PRI":
                self.wr(a[0], pri)
            elif n == "STOR_ALT":
                self.wr(a[0], alt)
            elif n == "STOR_S_PRI":
                self.wr(self.frm + a[0], pri)
            elif n == "STOR_S_ALT":
                self.wr(self.frm + a[0], alt)
            elif n == "SREF_PRI":
                self.wr(self.rd(a[0]), pri)
            elif n == "SREF_ALT":
                self.wr(self.rd(a[0]), alt)
            elif n == "SREF_S_PRI":
                self.wr(self.rd(self.frm + a[0]), pri)
            elif n == "SREF_S_ALT":
                self.wr(self.rd(self.frm + a[0]), alt)
            elif n == "STOR_I":
                self.wr(alt, pri)
            elif n == "LIDX":
                pri = self.rd(alt + pri * 4)
            elif n == "LIDX_B":
                pri = self.rd(alt + (pri << a[0]))
            elif n == "IDXADDR":
                pri = alt + pri * 4
            elif n == "IDXADDR_B":
                pri = alt + (pri << a[0])
            elif n == "LCTRL":
                pri = {0: 0, 1: 0, 2: self.hea, 3: self.stp, 4: self.stk, 5: self.frm, 6: cip}[a[0]]
            elif n == "SCTRL":
                if a[0] == 2:
                    self.hea = pri
                elif a[0] == 4:
                    self.stk = pri
                elif a[0] == 5:
                    self.frm = pri
                elif a[0] == 6:
                    nxt = pri
            elif n == "MOVE_PRI":
                pri = alt
            elif n == "MOVE_ALT":
                alt = pri
            elif n == "XCHG":
                pri, alt = alt, pri
            elif n == "PUSH_PRI":
                self.push(pri)
            elif n == "PUSH_ALT":
                self.push(alt)
            elif n == "PUSH_C":
                self.push(a[0])
            elif n == "PUSH":
                self.push(self.rd(a[0]))
            elif n == "PUSH_S":
                self.push(self.rd(self.frm + a[0]))
            elif n == "PUSH_ADR":
                self.push(self.frm + a[0])
            elif n.startswith("PUSH") and n[4].isdigit():
                kind = n[6:]
                for v in a:
                    self.push(v if kind == "C" else self.frm + v if kind == "ADR" else
                              self.rd(self.frm + v) if kind == "S" else self.rd(v))
            elif n == "POP_PRI":
                pri = self.pop()
            elif n == "POP_ALT":
                alt = self.pop()
            elif n == "PICK":
                pri = self.rd(self.stk + a[0])
            elif n == "STACK":
                self.stk += a[0]
                alt = self.stk
                if self.stk < self.hea or self.stk > self.stp:
                    raise AmxFault("stack out of bounds")
            elif n == "HEAP":
                alt = self.hea
                self.hea += a[0]
                if self.hea > self.stk or self.hea < len(self.image.data):
                    raise AmxFault("heap out of bounds")
            elif n == "PROC":
                self.push(self.frm)
                self.frm = self.stk
            elif n == "RET":
                self.frm = self.pop()
                nxt = self.pop()
            elif n == "RETN":
                self.frm = self.pop()
                nxt = self.pop()
                nbytes = self.pop()
                self.stk += nbytes
                if nxt != -1 and nxt not in insns:
                    raise AmxFault(f"return to {nxt:#x}")
            elif n == "CALL":
                self.push(nxt)
                nxt = cip + a[0]
            elif n == "SWITCH":                           # the case table that follows (CASETBL)
                table = insns[cip + a[0]]
                nxt = table.cases[0][1]
                for value, target in table.cases[1:]:
                    if pri == value:
                        nxt = target
                        break
            elif i.op in BRANCHES:
                target = cip + a[0]
                take = {"JUMP": True, "JZER": pri == 0, "JNZ": pri != 0, "JEQ": pri == alt,
                        "JNEQ": pri != alt, "JLESS": (pri & MASK) < (alt & MASK),
                        "JLEQ": (pri & MASK) <= (alt & MASK), "JGRTR": (pri & MASK) > (alt & MASK),
                        "JGEQ": (pri & MASK) >= (alt & MASK), "JSLESS": pri < alt, "JSLEQ": pri <= alt,
                        "JSGRTR": pri > alt, "JSGEQ": pri >= alt}[n]
                if take:
                    nxt = target
            elif n == "SHL":
                pri = s32(pri << (alt & 31))
            elif n == "SHR":
                pri = s32((pri & MASK) >> (alt & 31))
            elif n == "SSHR":
                pri = pri >> (alt & 31)
            elif n == "SHL_C_PRI":
                pri = s32(pri << a[0])
            elif n == "SHL_C_ALT":
                alt = s32(alt << a[0])
            elif n == "SHR_C_PRI":
                pri = s32((pri & MASK) >> a[0])
            elif n == "SHR_C_ALT":
                alt = s32((alt & MASK) >> a[0])
            elif n == "SMUL":
                pri = s32(pri * alt)
            elif n in ("SDIV", "SDIV_ALT"):
                num, den = (pri, alt) if n == "SDIV" else (alt, pri)
                if den == 0:
                    raise AmxFault("division by zero")
                q = num // den                            # Pawn: floored division
                pri, alt = s32(q), s32(num - q * den)
            elif n == "ADD":
                pri = s32(pri + alt)
            elif n == "SUB":
                pri = s32(pri - alt)
            elif n == "SUB_ALT":
                pri = s32(alt - pri)
            elif n == "AND":
                pri &= alt
            elif n == "OR":
                pri |= alt
            elif n == "XOR":
                pri = s32(pri ^ alt)
            elif n == "NOT":
                pri = int(pri == 0)
            elif n == "NEG":
                pri = s32(-pri)
            elif n == "INVERT":
                pri = s32(~pri)
            elif n == "ADD_C":
                pri = s32(pri + a[0])
            elif n == "SMUL_C":
                pri = s32(pri * a[0])
            elif n == "ZERO_PRI":
                pri = 0
            elif n == "ZERO_ALT":
                alt = 0
            elif n == "ZERO":
                self.wr(a[0], 0)
            elif n == "ZERO_S":
                self.wr(self.frm + a[0], 0)
            elif n in ("EQ", "NEQ", "LESS", "LEQ", "GRTR", "GEQ", "SLESS", "SLEQ", "SGRTR", "SGEQ"):
                up, ua = pri & MASK, alt & MASK
                pri = int({"EQ": pri == alt, "NEQ": pri != alt, "LESS": up < ua, "LEQ": up <= ua,
                           "GRTR": up > ua, "GEQ": up >= ua, "SLESS": pri < alt, "SLEQ": pri <= alt,
                           "SGRTR": pri > alt, "SGEQ": pri >= alt}[n])
            elif n == "EQ_C_PRI":
                pri = int(pri == a[0])
            elif n == "EQ_C_ALT":
                pri = int(alt == a[0])
            elif n == "INC_PRI":
                pri = s32(pri + 1)
            elif n == "INC_ALT":
                alt = s32(alt + 1)
            elif n == "INC":
                self.wr(a[0], self.rd(a[0]) + 1)
            elif n == "INC_S":
                self.wr(self.frm + a[0], self.rd(self.frm + a[0]) + 1)
            elif n == "INC_I":
                self.wr(pri, self.rd(pri) + 1)
            elif n == "DEC_PRI":
                pri = s32(pri - 1)
            elif n == "DEC_ALT":
                alt = s32(alt - 1)
            elif n == "DEC":
                self.wr(a[0], self.rd(a[0]) - 1)
            elif n == "DEC_S":
                self.wr(self.frm + a[0], self.rd(self.frm + a[0]) - 1)
            elif n == "DEC_I":
                self.wr(pri, self.rd(pri) - 1)
            elif n == "MOVS":
                for k in range(0, a[0], 4):
                    self.wr(alt + k, self.rd(pri + k))
            elif n == "CMPS":
                pri = 0
                for k in range(0, a[0], 4):
                    d = self.rd(alt + k) - self.rd(pri + k)
                    if d:
                        pri = d
                        break
            elif n == "FILL":
                for k in range(0, a[0], 4):
                    self.wr(alt + k, pri)
            elif n == "HALT":
                raise AmxFault(f"halt {a[0]} at {cip:#x}")
            elif n == "BOUNDS":
                if (pri & MASK) > a[0]:
                    raise AmxFault(f"index {pri} out of bounds {a[0]} at {cip:#x}")
            elif n == "SWAP_PRI":
                v = self.rd(self.stk)
                self.wr(self.stk, pri)
                pri = v
            elif n == "SWAP_ALT":
                v = self.rd(self.stk)
                self.wr(self.stk, alt)
                alt = v
            elif n in ("SYSREQ_C", "SYSREQ_N"):
                if n == "SYSREQ_N":
                    self.push(a[1])
                name = self.native_names[a[0]]
                fn = self.natives.get(name)
                if fn is None:
                    raise AmxFault(f"native {name} not simulated")
                params = self.stk
                nargs = self.rd(params) // 4
                pri = s32(fn(self, [self.rd(params + 4 * (k + 1)) for k in range(nargs)]) or 0)
                if n == "SYSREQ_N":
                    self.stk += a[1] + 4
            elif n == "CONST":
                self.wr(a[0], a[1])
            elif n == "CONST_S":
                self.wr(self.frm + a[0], a[1])
            elif n == "LOAD_BOTH":
                pri, alt = self.rd(a[0]), self.rd(a[1])
            elif n == "LOAD_S_BOTH":
                pri, alt = self.rd(self.frm + a[0]), self.rd(self.frm + a[1])
            elif n == "SIGN_PRI":
                pri = s32(pri & 0xFF) if not pri & 0x80 else s32(pri | ~0xFF)
            else:
                raise AmxFault(f"opcode {n} not simulated (at {cip:#x})")
            cip = nxt


# ---- the world ---------------------------------------------------------------------------------------

def props_of(name: str) -> dict[str, str]:
    path = BXML / f"{name}.xml"
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    out = {}
    if "properties" in root.attrib:
        out.update(props_of(root.attrib["properties"]))
    out.update(root.attrib)
    return out


class Box:
    def __init__(self, lo, hi) -> None:
        self.lo, self.hi = lo, hi

    def ray(self, o, d, length) -> float:
        t0, t1 = 0.0, length
        for k in range(3):
            if abs(d[k]) < 1e-9:
                if not self.lo[k] <= o[k] <= self.hi[k]:
                    return length
                continue
            a, b = (self.lo[k] - o[k]) / d[k], (self.hi[k] - o[k]) / d[k]
            if a > b:
                a, b = b, a
            t0, t1 = max(t0, a), min(t1, b)
            if t0 > t1:
                return length
        return t0

    def push_out(self, p, radius):
        """Normal and depth if a sphere at p of this radius touches the box."""
        q = [min(max(p[k], self.lo[k]), self.hi[k]) for k in range(3)]
        d = [p[k] - q[k] for k in range(3)]
        dist = math.sqrt(sum(x * x for x in d))
        if dist >= radius:
            return None
        if dist < 1e-6:                                   # center inside: the nearest face
            faces = [(p[k] - self.lo[k], k, -1) for k in range(3)] + [(self.hi[k] - p[k], k, 1) for k in range(3)]
            _, k, s = min(faces)
            n = [0.0, 0.0, 0.0]
            n[k] = float(s)
            return n, q
        return [x / dist for x in d], q


class Actor:
    def __init__(self, world, kind: str, pos, yaw=0.0) -> None:
        self.id = world.next_id
        world.next_id += 1
        world.actors[self.id] = self
        self.world = world
        self.kind = kind
        self.pos = list(pos)
        self.rot = [0.0, yaw, 0.0]                        # pitch, yaw, roll
        self.vel = [0.0, 0.0, 0.0]
        self.props: dict[str, str] = {}
        self.type = 0
        self.check = 0
        self.visible = True
        self.alive = True
        self.amx: Amx | None = None
        self.age = 0

    def axis(self, k):
        pitch, yaw, _ = self.rot
        sgn = self.world.pitch_sign
        fwd = [math.sin(yaw) * math.cos(pitch), -sgn * math.sin(pitch), math.cos(yaw) * math.cos(pitch)]
        right = [math.cos(yaw), 0.0, -math.sin(yaw)]
        up = [fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2],
              fwd[0] * right[1] - fwd[1] * right[0]]
        if up[1] < 0:
            up = [-x for x in up]
        return [right, up, fwd][k]

    def local_to_world(self, v, point=True):
        r, u, f = self.axis(0), self.axis(1), self.axis(2)
        out = [r[k] * v[0] + u[k] * v[1] + f[k] * v[2] for k in range(3)]
        return [out[k] + self.pos[k] for k in range(3)] if point else out


class World:
    def __init__(self, seed=1, pitch_sign=1.0) -> None:
        self.actors: dict[int, Actor] = {}
        self.next_id = 2                                  # 1: the map
        self.boxes: list[Box] = []
        self.floor = -2000.0
        self.globals: dict[str, int] = {"network.online": 1}
        self.frame = 0
        self.rng = random.Random(seed)
        self.pitch_sign = pitch_sign
        self.log: list[str] = []
        self.hits: list[tuple[int, int, int, float]] = []      # (frame, shooter, target, damage)
        self.shots: list[tuple[int, int, str]] = []
        self.net: list[tuple] = []
        self.wall_frames: dict[int, int] = {}
        self.off_axis: list[float] = []

    # rays and contacts against the map
    def clip(self, o, d, length) -> float:
        best = length
        for b in self.boxes:
            best = min(best, b.ray(o, d, best))
        if d[1] < -1e-9:
            t = (self.floor - o[1]) / d[1]
            if 0 <= t < best:
                best = t
        return best


class Sim:
    """Natives of the game, for the scripts of the world's actors."""

    def __init__(self, world: World, image: AmxImage) -> None:
        self.world = world
        self.image = image
        self.natives = self._natives()

    def actor_of(self, amx: Amx, a: int) -> Actor:
        if a == 0:
            return amx.owner
        actor = self.world.actors.get(a)
        if actor is None:
            raise AmxFault(f"no actor {a}")
        return actor

    def _natives(self):
        w = self.world
        f = c2f
        sim = self

        def prop_get(kind):
            def fn(amx, p):
                actor = w.actors.get(p[2]) if p[2] else amx.owner
                if actor is None:
                    return 0
                name = amx.string(p[0])
                if name not in actor.props:
                    return 0
                value = actor.props[name]
                if kind == "int":
                    amx.wr(p[1], int(float(value)))
                elif kind == "real":
                    amx.wr(p[1], f2c(float(value)))
                elif kind == "vector":
                    amx.put_vec(p[1], [float(x) for x in str(value).split()])
                elif kind == "string":
                    amx.put_string(p[1], str(value), 96)
                elif kind == "rgb":
                    for k, x in enumerate(str(value).split()[:4]):
                        amx.wr(p[1] + 4 * k, int(x))
                return 1
            return fn

        def prop_set(kind):
            def fn(amx, p):
                actor = sim.actor_of(amx, p[2])
                name = amx.string(p[0])
                actor.props[name] = (str(s32(p[1])) if kind == "int" else repr(f(p[1])) if kind == "real" else
                                     " ".join(map(str, amx.vec(p[1]))) if kind == "vector" else amx.string(p[1]))
                return 1
            return fn

        def fmt(amx, p):
            text = amx.string(p[3])
            args = p[4:]
            out, k, i = [], 0, 0
            while i < len(text):
                ch = text[i]
                if ch == "%" and i + 1 < len(text):
                    j = i + 1
                    while text[j] in "0123456789.-":
                        j += 1
                    spec, conv = text[i:j], text[j]
                    value = amx.rd(args[k])
                    k += 1
                    if conv == "d":
                        out.append(("%" + spec[1:] + "d") % value)
                    elif conv == "s":
                        out.append(amx.string(args[k - 1]))
                    elif conv == "f":
                        out.append(("%" + spec[1:] + "f") % c2f(value))
                    elif conv == "x":
                        out.append("%x" % (value & MASK))
                    i = j + 1
                    continue
                out.append(ch)
                i += 1
            amx.put_string(p[0], "".join(out), p[1])
            return 1

        def fa(op):
            return lambda amx, p: f2c(op(f(p[0]), f(p[1])))

        def vec_fn(op):
            return op

        def new_actor(amx, p):
            return Actor(w, "new", [0, 0, 0]).id

        def read_props(amx, p):
            actor = sim.actor_of(amx, p[1])
            name = amx.string(p[0])
            actor.props.update(props_of(name))
            if "torpedo" in name:
                actor.kind = "torpedo"
                actor.props["_name"] = name
                actor.type = 8
            return 1

        def find(amx, p):
            center = amx.vec(p[1])
            radius = f(p[2])
            out = []
            for a in w.actors.values():
                if a.alive and a.visible and a.type & p[3]:
                    if math.dist(a.pos, center) < radius:
                        out.append(a.id)
            out = out[:p[4]]
            for k, a in enumerate(out):
                amx.wr(p[0] + 4 * k, a)
            return len(out)

        def get_pos(amx, p):
            actor = w.actors.get(p[1]) if p[1] else amx.owner
            if actor is None or not actor.alive:
                return 0
            amx.put_vec(p[0], actor.pos)
            return 1

        def set_pos(amx, p):
            sim.actor_of(amx, p[1]).pos = amx.vec(p[0])
            return 1

        def clip(amx, p):
            o, d, length = amx.vec(p[0]), amx.vec(p[1]), f(p[2])
            return f2c(w.clip(o, d, length) if p[3] & 1 else length)

        def call_public(amx, p):
            target, name = p[0], amx.string(p[1])
            args = [amx.rd(x) for x in p[2:]]
            w.net.append(("sys", target, name, args))
            if name == "@lockOnTarget":
                actor = w.actors.get(target)
                if actor:
                    actor.lock = args[0]
            return 0

        def net_call(amx, p):
            name = amx.string(p[1])
            args = [amx.rd(x) for x in p[2:]]
            w.net.append(("net", p[0], name, args))
            if name == "@torpedoHitOnNpcToOwner":
                target = args[2]
                w.hits.append((w.frame, amx.owner.props.get("actor_id", "?"), target, c2f(args[6])))
                victim = w.actors.get(target)
                if victim:
                    victim.life -= c2f(args[6])
            elif name == "@eventMessageWeaponHitTorp":
                node = args[1]
                for a in w.actors.values():
                    if a.kind == "player" and a.props.get("nodeid") == str(node):
                        a.life -= c2f(args[2])
                        w.hits.append((w.frame, amx.owner.props.get("actor_id", "?"), a.id, c2f(args[2])))
            return 0

        def to_local(amx, p, point=True):
            actor = sim.actor_of(amx, p[2])
            v = amx.vec(p[1])
            if point:
                v = [v[k] - actor.pos[k] for k in range(3)]
            r, u, fw = actor.axis(0), actor.axis(1), actor.axis(2)
            amx.put_vec(p[0], [sum(v[k] * ax[k] for k in range(3)) for ax in (r, u, fw)])
            return 1

        def vec_sub(amx, p):
            a, b = amx.vec(p[1]), amx.vec(p[2])
            amx.put_vec(p[0], [a[k] - b[k] for k in range(3)])

        def vec_normalize(amx, p):
            v = amx.vec(p[1])
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            amx.put_vec(p[0], [x / n for x in v])

        def vec_addscale(amx, p):
            v, a = amx.vec(p[0]), amx.vec(p[1])
            amx.put_vec(p[0], [v[k] + a[k] * f(p[2]) for k in range(3)])

        def vec_copyscale(amx, p):
            a = amx.vec(p[1])
            amx.put_vec(p[0], [x * f(p[2]) for x in a])

        def set_rot(amx, p):
            actor = sim.actor_of(amx, p[1])
            actor.rot = amx.vec(p[0])
            if actor.kind == "torpedo" and actor is not amx.owner:
                actor.launcher_axis = amx.owner.axis(2)       # its shooter's axis when it fired

        def set_angle(k):
            def fn(amx, p):
                sim.actor_of(amx, p[1]).rot[k] = f(p[0])
            return fn

        n = {
            "floatmul": fa(lambda x, y: x * y), "floatadd": fa(lambda x, y: x + y),
            "floatsub": fa(lambda x, y: x - y),
            "floatdiv": fa(lambda x, y: x / y if y else (math.copysign(math.inf, x) if x else math.nan)),
            "floatcmp": lambda amx, p: (f(p[0]) > f(p[1])) - (f(p[0]) < f(p[1])),
            "float": lambda amx, p: f2c(float(s32(p[0]))),
            "floatsqroot": lambda amx, p: f2c(math.sqrt(max(f(p[0]), 0.0))),
            "floatsin": lambda amx, p: f2c(math.sin(f(p[0]))),
            "floatcos": lambda amx, p: f2c(math.cos(f(p[0]))),
            "floatatan2": lambda amx, p: f2c(math.atan2(f(p[0]), f(p[1]))),
            "floatpower": lambda amx, p: f2c(math.pow(f(p[0]), f(p[1]))),
            "floatround": lambda amx, p: {0: round, 1: math.floor, 2: math.ceil, 3: int}[p[1]](f(p[0])),
            "floatrnd": lambda amx, p: f2c(w.rng.randrange(10000) / 10000.0),
            "random": lambda amx, p: w.rng.randrange(max(p[0], 1)),
            "min": lambda amx, p: min(s32(p[0]), s32(p[1])), "max": lambda amx, p: max(s32(p[0]), s32(p[1])),
            "floatvecsubto": vec_sub,
            "floatvecsub": lambda amx, p: amx.put_vec(p[0], [a - b for a, b in zip(amx.vec(p[0]), amx.vec(p[1]))]),
            "floatveclength": lambda amx, p: f2c(math.sqrt(sum(x * x for x in amx.vec(p[0])))),
            "floatvecset": lambda amx, p: amx.put_vec(p[0], [f(p[1]), f(p[2]), f(p[3])]),
            "floatvecaddscale": vec_addscale,
            "floatveccopyscale": vec_copyscale,
            "floatveczero": lambda amx, p: amx.put_vec(p[0], [0.0, 0.0, 0.0]),
            "floatvecdot": lambda amx, p: f2c(sum(a * b for a, b in zip(amx.vec(p[0]), amx.vec(p[1])))),
            "floatvecscale": lambda amx, p: amx.put_vec(p[0], [x * f(p[1]) for x in amx.vec(p[0])]),
            "floatvecadd": lambda amx, p: amx.put_vec(p[0], [a + b for a, b in zip(amx.vec(p[0]), amx.vec(p[1]))]),
            "floatvecnormalize": vec_normalize,
            "actorGetPropInt": prop_get("int"), "actorGetPropReal": prop_get("real"),
            "actorGetPropVector": prop_get("vector"), "actorGetPropString": prop_get("string"),
            "actorGetPropRGB": prop_get("rgb"),
            "actorSetPropInt": prop_set("int"), "actorSetPropReal": prop_set("real"),
            "actorSetPropVector": prop_set("vector"), "actorSetPropString": prop_set("string"),
            "strformat": fmt,
            "sysGetGlobal": lambda amx, p: w.globals.get(amx.string(p[0]), 0),
            "sysGetGlobalArray": lambda amx, p: amx.put_string(p[1], "Bot", 96) or 1,
            "sysGetString": lambda amx, p: amx.put_string(p[0], "Lv %d", 96) or 1,
            "actorReadProperties": read_props,
            "worldNewActor": new_actor,
            "actorKill": lambda amx, p: setattr(sim.actor_of(amx, p[0]), "alive", False),
            "worldClipLine": clip,
            "worldFindActors": find,
            "actorGetPosition": get_pos,
            "actorSetPosition": set_pos,
            "actorGetID": lambda amx, p: amx.owner.id,
            "actorGetCollisionType": lambda amx, p: sim.actor_of(amx, p[0]).type if p[0] in w.actors or p[0] == 0 else 0,
            "actorSetCollisionCheck": lambda amx, p: setattr(sim.actor_of(amx, p[1]), "check", p[0]),
            "actorGetVelocity": lambda amx, p: amx.put_vec(p[0], sim.actor_of(amx, p[1]).vel) or 1,
            "actorSetVelocity": lambda amx, p: setattr(sim.actor_of(amx, p[1]), "vel", amx.vec(p[0])),
            "actorSetTorque": lambda amx, p: 0,
            "actorGetRotation": lambda amx, p: amx.put_vec(p[0], sim.actor_of(amx, p[1]).rot) or 1,
            "actorSetRotation": set_rot,
            "actorSetYaw": set_angle(1), "actorSetPitch": set_angle(0), "actorSetRoll": set_angle(2),
            "actorUpdateMatrix": lambda amx, p: 0,
            "actorGetAxis": lambda amx, p: amx.put_vec(p[1], sim.actor_of(amx, p[2]).axis(p[0])) or 1,
            "actorLocalPosToWorld": lambda amx, p: amx.put_vec(p[0], sim.actor_of(amx, p[2]).local_to_world(amx.vec(p[1]))) or 1,
            "actorLocalVectorToWorld": lambda amx, p: amx.put_vec(p[0], sim.actor_of(amx, p[2]).local_to_world(amx.vec(p[1]), False)) or 1,
            "actorWorldPosToLocal": lambda amx, p: to_local(amx, p),
            "actorSetParent": lambda amx, p: setattr(sim.actor_of(amx, p[1]), "parent", p[0]),
            "actorSetIdleDistance": lambda amx, p: 0,
            "actorGetSyncController": lambda amx, p: 1,
            "actorGetSyncID": lambda amx, p: (w.actors.get(p[0]) or amx.owner).id + 100,
            "netGetNodeId": lambda amx, p: 1,
            "sysCallPublic": call_public,
            "netCallPublic": net_call,
            "actorSetModel": lambda amx, p: 1, "actorSetModelColor": lambda amx, p: 1,
        }
        return n


# ---- scenarios ---------------------------------------------------------------------------------------

def build_image() -> AmxImage:
    img = AmxImage.parse((ROMFS / "amx" / "surface_sub.amx").read_bytes())
    img.assemble((PASM / "bots_ia.pasm").read_text(encoding="utf-8"))
    return img


G = {"life": 0x1c68, "afloat": 0x1c90, "pos": 0x1ca0, "yaw": 0x1cc8, "online": 0x1f28, "roll_speed": 0x1c74}


class Bot:
    def __init__(self, world: World, sim: Sim, image: AmxImage, pos, yaw, team: int, k: int, sub: int) -> None:
        self.actor = a = Actor(world, "bot", pos, yaw)
        a.type = 0x40004
        a.life = 150.0
        a.props.update({"npc": "1", "teamColor": str(team), "botIndex": str(k), "life": "150.0", "npcActorId": str(a.id)})
        world.globals[f"server.bots.sub{k}"] = sub
        self.sub = sub
        a.amx = Amx(image, sim.natives)
        a.amx.owner = a
        self.amx = a.amx
        self.image = image
        m = self.amx
        m.wr(G["online"], 1)
        m.wr(G["afloat"], 1)
        m.wr(G["life"], f2c(150.0))
        m.put_vec(G["pos"], pos)
        m.wr(G["yaw"], f2c(yaw))
        self.call("pw_botInit")

    def call(self, label: str, *args) -> int:
        return self.amx.call(self.image.labels[label], *args)

    def debug(self) -> dict[str, float]:
        """botDebug of bots_ia.p."""
        m = self.amx
        buf = m.hea
        m.hea += 64
        m.call(self.image.labels["pw_botDebug"], buf)
        m.hea = buf
        values = [c2f(m.rd(buf + 4 * k)) for k in range(16)]
        keys = ("target tx ty tz tvx tvy tvz omega yawWant throttle depthWant torpedoes elevation yawSteer "
                "visible floorY").split()
        return dict(zip(keys, values))

    def frame(self) -> None:
        a = self.actor
        m = self.amx
        m.wr(G["life"], f2c(a.life))
        a.props["life"] = repr(max(a.life, 0.0))
        if a.life <= 0.01:
            m.wr(G["afloat"], 0)
            a.alive = False
            return
        before_yaw, before = a.rot[1], list(a.pos)
        if not self.call("pw_botPilot"):
            raise AmxFault("the pilot gave the sub back to the game while afloat")
        a.pos = m.vec(G["pos"])
        # what a player's sub can do (pscope_player.p func_12184): turn rate <= 0.4 * maxTurn of the sub,
        # forward speed <= accel / linDrag, backwards at half power
        turn = abs((a.rot[1] - before_yaw + math.pi) % (2 * math.pi) - math.pi)
        speed = math.hypot(a.pos[0] - before[0], a.pos[2] - before[2])
        self.max_turn = max(getattr(self, "max_turn", 0.0), turn)
        self.max_speed = max(getattr(self, "max_speed", 0.0), speed)


class Player:
    """A scripted player: weaves around a path at a player's speed, changing depth."""

    def __init__(self, world: World, pos, team: int, node: int, speed=9.0, turn=0.02, weave=True) -> None:
        self.actor = a = Actor(world, "player", pos, 0.0)
        a.type = 0x40002
        a.life = 100.0
        a.props.update({"teamColor": str(team), "nodeid": str(node), "life": "100.0"})
        self.speed, self.turn, self.weave = speed, turn, weave
        self.world = world

    def frame(self) -> None:
        a, w = self.actor, self.world
        a.props["life"] = repr(max(a.life, 0.0))
        if a.life <= 0.01:
            a.alive = False
            return
        if self.weave:
            phase = (w.frame // 150) % 4
            a.rot[1] += (self.turn if phase in (0, 1) else -self.turn) * (1 if phase != 3 else 0.3)
            target_y = -400.0 if (w.frame // 300) % 2 else -700.0
            a.vel[1] = max(-2.0, min(2.0, (target_y - a.pos[1]) * 0.01))
        fwd = [math.sin(a.rot[1]), 0.0, math.cos(a.rot[1])]
        a.vel[0], a.vel[2] = fwd[0] * self.speed, fwd[2] * self.speed
        # bounce off the arena's edge
        for k in (0, 2):
            if abs(a.pos[k] + a.vel[k] * 60) > 9000:
                a.rot[1] += 0.06
        a.pos = [a.pos[k] + a.vel[k] for k in range(3)]


def torpedo_step(world: World, t: Actor) -> None:
    """surface_torpedo.p: v -= v*0.01; pos += v; v += forward*1.2 (gravity compensated); range; hits."""
    t.age += 1
    if t.age == 1:
        shooter = world.actors.get(int(t.props.get("actor_id", "0") or 0))
        if shooter is not None and shooter.kind == "bot":
            a, b = t.axis(2), getattr(t, "launcher_axis", shooter.axis(2))
            world.off_axis.append(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))
        t.start = list(t.pos)
        t.vel = list(t.vel)
        homing = "homing" in t.props.get("_name", "")
        t.accel = 0.3 if homing else 1.2
        t.range = float(t.props.get("maxRange", "10000"))
        world.shots.append((world.frame, t.props.get("actor_id"), t.props.get("_name")))
        return
    lock = getattr(t, "lock", None)
    if lock and lock in world.actors and "1" in (world.actors[lock].props.get("masker_on"),
                                                  world.actors[lock].props.get("masker")):
        t.lock = lock = None                             # lost under the masker (func_4800)
    if lock and t.age > 45 and lock in world.actors and world.actors[lock].alive:
        target = world.actors[lock]                      # steers in yaw and pitch, 0.03 rad per frame
        d = [target.pos[k] - t.pos[k] for k in range(3)]
        want = math.atan2(d[0], d[2])
        err = (want - t.rot[1] + math.pi) % (2 * math.pi) - math.pi
        t.rot[1] += max(-0.03, min(0.03, err))
        elevation = math.atan2(d[1], math.hypot(d[0], d[2]))
        pitch = -world.pitch_sign * elevation
        t.rot[0] += max(-0.03, min(0.03, pitch - t.rot[0]))
    fwd = t.axis(2)
    t.vel = [v * 0.99 for v in t.vel]
    new = [t.pos[k] + t.vel[k] for k in range(3)]
    t.vel = [t.vel[k] + fwd[k] * t.accel for k in range(3)]
    # hits: the subs' capsules (550 long, 60 wide), the map
    seg = [new[k] - t.pos[k] for k in range(3)]
    length = math.sqrt(sum(x * x for x in seg)) or 1e-6
    if world.clip(t.pos, [x / length for x in seg], length) < length:
        t.alive = False
        world.log.append(f"{world.frame}: torpedo of {t.props.get('actor_id')} hits the map")
        return
    for a in list(world.actors.values()):
        if not a.alive or a.kind not in ("bot", "player") or str(a.id) == t.props.get("actor_id"):
            continue
        if a.props.get("teamColor") == t.props.get("teamColor"):
            continue
        axis = [math.sin(a.rot[1]), 0.0, math.cos(a.rot[1])]
        r = [new[k] - a.pos[k] for k in range(3)]
        along = max(-275.0, min(275.0, sum(r[k] * axis[k] for k in range(3))))
        q = [a.pos[k] + axis[k] * along for k in range(3)]
        if math.dist(q, new) < 70.0:
            t.alive = False
            damage = float(t.props.get("damage", t.props.get("damageToNpc", "20")))
            a.life -= damage
            world.hits.append((world.frame, t.props.get("actor_id"), a.id, damage))
            world.log.append(f"{world.frame}: torpedo of {t.props.get('actor_id')} hits {a.kind} {a.id}")
            return
    t.pos = new
    if math.dist(t.pos, t.start) > t.range:
        t.alive = False


def contacts(world: World, bots: list[Bot], sim: Sim) -> None:
    """@eventCollide of each bot: the map (boxes, floor) and the other subs."""
    for b in bots:
        a = b.actor
        if not a.alive:
            continue
        events = []
        for box in world.boxes:
            hit = box.push_out(a.pos, 110.0)
            if hit:
                events.append((1, hit[1], hit[0]))
        if a.pos[1] < world.floor + 110.0:
            events.append((1, [a.pos[0], world.floor, a.pos[2]], [0.0, 1.0, 0.0]))
        for o in world.actors.values():
            if o is a or not o.alive or o.kind not in ("bot", "player"):
                continue
            d = [a.pos[k] - o.pos[k] for k in range(3)]
            dist = math.sqrt(sum(x * x for x in d))
            if dist < 220.0:
                n = [x / (dist or 1) for x in d]
                events.append((o.id, o.pos, n))
        if events:
            world.wall_frames[a.id] = world.wall_frames.get(a.id, 0) + any(e[0] == 1 for e in events)
        for other, point, normal in events:
            m = b.amx
            m.hea_save = m.hea
            p_addr = m.hea
            m.put_vec(p_addr, point)
            m.put_vec(p_addr + 12, normal)
            m.hea += 24
            m.call(b.image.labels["pw_at_eventCollide"], other, p_addr, p_addr + 12)
            m.hea = m.hea_save


def scenario(name: str, level: int, seed: int, verbose: bool, pitch_sign: float = 1.0, frames: int = 1800):
    world = World(seed, pitch_sign)
    world.globals["server.bots.level"] = level
    map_actor = Actor(world, "map", [0, 0, 0])
    map_actor.id = 1
    world.actors[1] = map_actor
    map_actor.type = 1
    image = build_image()
    sim = Sim(world, image)
    bots: list[Bot] = []
    players: list[Player] = []
    if name == "duel":                        # one bot against a weaving player, open water
        bots.append(Bot(world, sim, image, [0.0, -500.0, -4000.0], 0.0, 1, 1, 3))
        players.append(Player(world, [0.0, -500.0, 1500.0], 2, 2))
    elif name == "close":                     # the player right next to it, circling
        bots.append(Bot(world, sim, image, [0.0, -500.0, 0.0], 0.0, 1, 1, 1))
        players.append(Player(world, [300.0, -500.0, 400.0], 2, 2, speed=8.0, turn=0.03))
    elif name == "walls":                     # a wall between them, rocks around
        world.boxes.append(Box([-3000.0, -2000.0, -200.0], [3000.0, 0.0, 200.0]))
        world.boxes.append(Box([-6000.0, -2000.0, -5000.0], [-4500.0, -300.0, -3500.0]))
        world.boxes.append(Box([2500.0, -2000.0, -3000.0], [4000.0, -800.0, -1500.0]))
        bots.append(Bot(world, sim, image, [0.0, -600.0, -2500.0], 0.0, 1, 1, 7))
        players.append(Player(world, [0.0, -600.0, 3000.0], 2, 2, speed=6.0, weave=False))
    elif name == "corner":                    # starts facing a wall at full speed
        world.boxes.append(Box([-4000.0, -2000.0, 600.0], [4000.0, 0.0, 1000.0]))
        world.boxes.append(Box([600.0, -2000.0, -4000.0], [1000.0, 0.0, 1000.0]))
        bots.append(Bot(world, sim, image, [0.0, -500.0, 0.0], 0.7, 1, 1, 5))
    elif name == "retreat":                   # hull low, a player coming at it
        bots.append(Bot(world, sim, image, [0.0, -500.0, 0.0], 0.0, 1, 1, 2))
        players.append(Player(world, [0.0, -500.0, 6000.0], 2, 2, speed=8.0, weave=False))
        players[0].actor.rot[1] = math.pi
        world.hurt_at = (5, bots[0], 50.0)
    elif name == "dodge":                     # a player that fires at it every 3 s, from 2500
        bots.append(Bot(world, sim, image, [0.0, -500.0, 0.0], 0.0, 1, 1, 6))
        players.append(Player(world, [2500.0, -500.0, 0.0], 2, 2, speed=0.0, weave=False))
        world.shooter = players[0]
    elif name == "masker":                    # the player hides under its masker from 10 s to 20 s
        bots.append(Bot(world, sim, image, [0.0, -500.0, -3000.0], 0.0, 1, 1, 3))
        players.append(Player(world, [0.0, -500.0, 0.0], 2, 2, speed=7.0))
        world.masker = (300, 600, players[0])
    elif name == "melee":                     # four bots against four bots
        for k in range(4):
            bots.append(Bot(world, sim, image, [k * 900.0 - 1350.0, -500.0, -4000.0], 0.0, 1, k + 1, k * 5 + 1))
            bots.append(Bot(world, sim, image, [k * 900.0 - 1350.0, -600.0, 4000.0], math.pi, 2, k + 5, k * 4 + 3))
    else:
        raise SystemExit(f"no scenario {name}")
    for world.frame in range(frames):
        hurt = getattr(world, "hurt_at", None)
        if hurt and world.frame == hurt[0]:
            hurt[1].actor.life = hurt[2]
        masker = getattr(world, "masker", None)
        if masker:
            on = masker[0] <= world.frame < masker[1]
            masker[2].actor.props["masker_on"] = "1" if on else "0"
            if on:
                world.masked_frames = getattr(world, "masked_frames", 0) + 1
        shooter = getattr(world, "shooter", None)
        if shooter and world.frame % 90 == 45 and shooter.actor.alive:
            target = bots[0].actor
            t = Actor(world, "torpedo", shooter.actor.pos)
            t.type = 16
            d = [target.pos[k] - t.pos[k] for k in range(3)]
            t.rot = [0.0, math.atan2(d[0], d[2]), 0.0]
            t.props.update({"_name": "player_torpedo", "teamColor": "2", "actor_id": str(shooter.actor.id),
                            "damage": "20", "maxRange": "6500"})
        for b in bots:
            b.frame()
        for p in players:
            p.frame()
        contacts(world, bots, sim)
        for a in list(world.actors.values()):
            if a.kind == "torpedo" and a.alive:
                torpedo_step(world, a)
        if verbose and world.frame % 60 == 0:
            for b in bots:
                a = b.actor
                tgt = b.amx.rd(image.labels.get("pw_target", 0)) if False else None
                world.log.append(f"{world.frame}: bot {a.id} at {[round(x) for x in a.pos]} yaw {a.rot[1]:.2f} "
                                 f"life {a.life:.0f}")
        alive_teams = {a.props.get("teamColor") for a in world.actors.values()
                       if a.alive and a.kind in ("bot", "player")}
        if len(alive_teams) < 2 and name != "corner":
            break
    return world, bots, players


def report(name: str, level: int, world: World, bots, players) -> list[str]:
    shots = len(world.shots)
    hits = len(world.hits)
    lines = [f"{name:7} level {level}: {world.frame + 1} frames, {shots} torpedoes, {hits} hits"
             + (f" ({100 * hits / shots:.0f} %)" if shots else "")]
    for b in bots:
        a = b.actor
        stats = props_of(f"pscope_ply{b.sub:02d}_stats")
        turn = float(props_of("table_maxturn")[f"maxTurn_{stats['maxTurn']}"]) * 0.4
        top = float(props_of("table_below_accel")[f"belowAccel_{stats['belowAccel']}"]) / 0.038
        flag = "" if getattr(b, "max_turn", 0) <= turn * 1.02 and getattr(b, "max_speed", 0) <= top * 1.05 + 5.0 \
            else "  NOT A PLAYER'S MOVE"
        lines.append(f"    bot {a.id} team {a.props['teamColor']}: life {max(a.life, 0):.0f}, "
                     f"{world.wall_frames.get(a.id, 0)} frames against the map, steps {b.amx.steps}, "
                     f"turn {getattr(b, 'max_turn', 0):.4f}/{turn:.4f}, speed {getattr(b, 'max_speed', 0):.1f}/"
                     f"{top:.1f}{flag}")
    off = [x for x in world.off_axis if x > 0.002]
    if off:
        lines.append(f"    {len(off)} torpedoes off the sub's axis (up to {max(off):.3f} rad)  NOT A PLAYER'S SHOT")
    for p in players:
        lines.append(f"    player {p.actor.id}: life {max(p.actor.life, 0):.0f}")
    masker = getattr(world, "masker", None)
    if masker:
        start, end, _ = masker
        during = [f for f, _, _ in world.shots if start <= f < end]
        hit = [f for f, *_ in world.hits if start <= f < end + 150]
        lines.append(f"    player masked from frame {start} to {end}: {len(during)} torpedoes fired at a guess, "
                     f"{len(hit)} hits while masked (or by those)")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenarios", nargs="*",
                        default=["duel", "close", "walls", "corner", "retreat", "dodge", "masker", "melee"])
    parser.add_argument("--level", type=int, action="append")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--frames", type=int, default=1800)
    parser.add_argument("--pitch-sign", type=float, default=1.0, help="-1: the other convention for pitch")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    for name in args.scenarios:
        for level in args.level or [1, 2, 3]:
            world, bots, players = scenario(name, level, args.seed, args.verbose, args.pitch_sign, args.frames)
            print("\n".join(report(name, level, world, bots, players)))
            if args.verbose:
                print("\n".join("      " + l for l in world.log[-400:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
