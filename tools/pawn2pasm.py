#!/usr/bin/env python3
"""Compile Pawn source into Pawn assembly for tools/amxasm.py: new code for a script of the game, written
in Pawn instead of assembly (mods/*/src/*.p -> mods/*/*.pasm).

    tools/pawn2pasm.py mods/online/src/bots_pilot.p        # writes mods/online/bots_pilot.pasm

A tool of the developers, not of the players: the .pasm it writes is committed, and tools/mod.py assembles it
with Python alone. It needs the Pawn 3.3 compiler (`make pawncc`, build/pawncc) and the dump (the game's script,
for the size of its data).

The source is ordinary Pawn, compiled by pawncc, with three additions read by this tool:

    // @target amx/surface_sub.amx                        the script the code goes into
    // @game Float:g_1ca0[3]                              a global of that script (decomp/scripts/<name>.p)
    // @call 0x2ea0 spawnActor(const name[], const Float:position[3])   a function of that script

Globals of the game: the tool puts in front of the source a declaration of the script's whole data segment,
the named globals at their addresses and fillers between them, so the compiled code reads and writes them at
their real addresses, and everything the source adds (globals, strings) comes after the end of the script's
data, where tools/amxasm.py appends new data: the .pasm starts with `.data_at <size>`, which checks it. No
address of the compiled code has to be translated.

The constant SDSW_VERSION is the version compiled for (0, 5200): `#if SDSW_VERSION >= 5200` for what the update
changed (its texts, for one).

Room for the stack: the compiled code gets at least 16 KB of heap and stack (`.heapstack`), what the game's
scripts have; the update v5200's have only 8 KB, which the mods' deeper calls overflowed (the abstract machine
then aborts the public function midway). `// @heapstack 0` keeps the script's own, for scripts loaded many
times at once (a torpedo each), where memory counts.

Functions of the game: a stub of that name is compiled and its calls become `call <address>`.

Addresses are those of the game's scripts as sold (v0). With --version v5200, the same source is compiled for
the update's recompiled script: tools/amxport.py translates the globals, the functions and the hooks' addresses
(<stem>-v5200.pasm), and the ones it cannot pair are written by hand in the section <stem> of v5200.toml next
to the mod's recipe.

Assembly that stays hand-written (the hooks into the game's code) goes in comments `/* asm ... */` of the
source, copied as they are after the compiled code; it calls the Pawn functions by their names (`call @name`;
`call @name` of a Pawn function pushes its arguments and their size in bytes first, as Pawn does).
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import amxport  # noqa: E402
import versions  # noqa: E402
from amxasm import AmxImage  # noqa: E402

PAWNCC = Path(os.environ.get("PAWNCC", ROOT / "build" / "pawncc"))
INCLUDES = [ROOT / "decomp" / "pawn"]

_GAME = re.compile(r"^\s*//\s*@game\s+(?:(\w+):)?(g_([0-9a-fA-F]+))(?:\[(\w+)\])?(?:\s.*)?$")
_CALL = re.compile(r"^\s*//\s*@call\s+(0x[0-9a-fA-F]+)\s+((?:\w+:)?(\w+)\s*\(([^)]*)\))(?:\s.*)?$")
_TARGET = re.compile(r"^\s*//\s*@target\s+(\S+)\s*$")
_HEAPSTACK = re.compile(r"^\s*//\s*@heapstack\s+(\S+)(?:\s.*)?$")
HEAPSTACK = 0x4000                  # the game's scripts have 16 KB of heap and stack, v5200's only 8 KB
_ASM = re.compile(r"/\*\s*asm\b(.*?)\*/", re.S)
_HEX = re.compile(r"^-?[0-9a-fA-F]{8}$")

BRANCH = {"jump", "jzer", "jnz", "jeq", "jneq", "jless", "jleq", "jgrtr", "jgeq", "jsless", "jsleq",
          "jsgrtr", "jsgeq", "jrel"}


class Pawn2PasmError(Exception):
    pass


def _cells(n: str) -> int:
    return int(n, 0)


def _params(prototype: str) -> list[str]:
    """Names of the parameters of a prototype's parameter list."""
    names = []
    for p in filter(None, (x.strip() for x in prototype.split(","))):
        if p == "...":
            continue
        m = re.search(r"(\w+)\s*(?:\[[^\]]*\])*\s*(?:=.*)?$", p.lstrip("&"))
        if m:
            names.append(m[1])
    return names


def prelude(source: str, data_size: int, tr=None) -> tuple[str, dict[str, int], int]:
    """Pawn declarations of the script's data segment, the game functions' stubs (name -> address), and the
    number of lines of the declarations (for the line numbers of the compiler's messages). tr: an
    amxport.Translator, for another version of the script (the names stay those of v0)."""
    globals_: list[tuple[int, str, int, str]] = []
    for line in source.splitlines():
        m = _GAME.match(line)
        if m:
            address, size = int(m[3], 16), _cells(m[4]) if m[4] else 1
            if tr is not None:
                address = tr.global_(address)
            if address % 4:
                raise Pawn2PasmError(f"{m[2]}: unaligned")
            globals_.append((address, m[2], size, m[1] or ""))
    globals_.sort()
    lines = ["#pragma rational Float", "// data segment of the game's script (tools/pawn2pasm.py)"]
    declared: list[tuple[str, int, str]] = []                  # (name, cells, tag)
    at = 0
    for n, (address, name, size, tag) in enumerate(globals_):
        if address < at:
            raise Pawn2PasmError(f"{name} overlaps the global before it")
        if address > at:
            declared.append((f"__game{n}", (address - at) // 4, ""))
        declared.append((name, size, tag))
        at = address + 4 * size
    if at > data_size:
        raise Pawn2PasmError(f"globals beyond the script's data ({data_size:#x} bytes)")
    if at < data_size:
        declared.append(("__game_end", (data_size - at) // 4, ""))
    for name, size, tag in declared:
        lines.append(f"new {tag + ':' if tag else ''}{name}{f'[{size}]' if size > 1 else ''};")
    # Pawn leaves out the globals nothing uses: one function (not output) uses them all, in order
    lines.append("forward __touch_game();\npublic __touch_game() {\n" + "".join(
        f"    {name}{'[0]' if size > 1 else ''} = {tag + ':' if tag else ''}0;\n" for name, size, tag in declared)
        + "}")
    calls: dict[str, int] = {}
    for line in source.splitlines():
        m = _CALL.match(line)
        if m:
            calls[m[3]] = tr.code(int(m[1], 16), function=True) if tr is not None else int(m[1], 16)
            unused = _params(m[4])
            body = (f"#pragma unused {', '.join(unused)}\n" if unused else "")
            lines.append(f"stock {m[2]} {{\n{body}    return 0;\n}}")
    text = "\n".join(lines) + "\n"
    return text, calls, text.count("\n")


def natives_of(amx: bytes) -> tuple[list[str], list[str]]:
    """Native and public names of a compiled script."""
    img = AmxImage.parse(amx)
    return [name for _, name, _ in img.natives], [name for _, name, _ in img.publics]


def _label(name: str) -> str:
    """A label of amxasm for a Pawn function name (operators included)."""
    ops = {"*": "mul", "/": "div", "+": "add", "-": "sub", "%": "mod", "<": "lt", ">": "gt", "=": "eq",
           "!": "not", "(": "_", ")": "", ":": "", ",": "_", "&": "and", "|": "or", "^": "xor", "~": "inv",
           "@": "at_"}
    out = "".join(ops.get(c, c) for c in name)
    out = re.sub(r"\W", "_", out)
    return "pw_" + out


def convert(listing: str, natives: list[str], publics: list[str], calls: dict[str, int], data_size: int,
            module: str) -> tuple[list[str], list[str]]:
    """The compiler's assembly listing -> amxasm code lines and data cells."""
    code: list[str] = []
    data: dict[int, int] = {}
    section, at = None, 0
    skip = False                      # inside a proc that is not output (game stubs, main)
    for raw in listing.splitlines():
        line = raw.split(";", 1)
        text, comment = line[0].strip(), (line[1].strip() if len(line) > 1 else "")
        if not text:
            continue
        words = text.split()
        if words[0] in ("CODE", "DATA"):
            section = words[0]
            at = int(comment, 16) if section == "DATA" else 0
            continue
        if words[0] == "STKSIZE":
            continue
        if section == "DATA":
            if words[0] != "dump":
                raise Pawn2PasmError(f"unexpected data line: {raw}")
            for w in words[1:]:
                data[at] = s32(int(w, 16))
                at += 4
            continue
        mnemonic = words[0]
        if mnemonic == "halt" and not code:
            continue                                           # the program's exit point
        if mnemonic == "proc":
            name = comment.split()[0] if comment else ""
            skip = name in calls or name in ("main", "__touch_game")
            if not skip:
                if name in publics and name.startswith("@"):
                    code.append(f".public {name}")       # other publics: only kept by the compiler
                code.append(f"{_label(name)}:")
                code.append("    proc")
            continue
        if skip:
            continue
        if re.fullmatch(r"l\.[0-9a-fA-F]+", mnemonic):
            code.append(f"{module}_l{int(mnemonic[2:], 16)}:")
            continue
        if mnemonic in ("switch", "casetbl", "case", "icasetbl", "icase"):
            raise Pawn2PasmError("switch statements are not supported: use if/else")
        if mnemonic in ("break", "line", "file", "symbol", "srange", "symtag"):
            continue
        operands = words[1:]
        if mnemonic == "sysreq.c":
            index = int(operands[0], 16)
            code.append(f"    sysreq.c {natives[index]}")
            continue
        if mnemonic == "call":
            target = comment if comment else operands[0]
            target = target.split()[0] if target else ""
            if not target or _HEX.match(target.split(">")[0]):
                raise Pawn2PasmError(f"call without a name: {raw}")
            if target in calls:
                code.append(f"    call {calls[target]:#x}")
            else:
                code.append(f"    call @{_label(target)}")
            continue
        if mnemonic in BRANCH:
            code.append(f"    {mnemonic} @{module}_l{int(operands[0], 16)}")
            continue
        out = []
        for o in operands:
            if _HEX.match(o):
                value = s32(int(o, 16))
                out.append(f"{value:#x}" if value >= 0 else str(value))
            else:
                raise Pawn2PasmError(f"unexpected operand {o!r}: {raw}")
        code.append(f"    {mnemonic} {', '.join(out)}".rstrip())

    # push.c <bytes>, sysreq.c <native>, stack <bytes + 4> -> sysreq.n <native>, <arguments>: the form the
    # game's scripts use (the compiler's macro instruction)
    folded: list[str] = []
    k = 0
    while k < len(code):
        if (k + 2 < len(code) and code[k].startswith("    push.c ") and code[k + 1].startswith("    sysreq.c ")
                and code[k + 2].startswith("    stack ")):
            nbytes = int(code[k].split()[1], 0)
            if int(code[k + 2].split()[1], 0) == nbytes + 4 and nbytes % 4 == 0:
                folded.append(f"    sysreq.n {code[k + 1].split()[1]}, {nbytes // 4}")
                k += 3
                continue
        folded.append(code[k])
        k += 1
    code = folded

    # data: the game's own (zeros of the declarations of the prelude), then ours
    own = sorted(a for a in data if a >= data_size)
    if own and own[0] != data_size:
        raise Pawn2PasmError(f"the new data starts at {own[0]:#x}, not at the end of the script's ({data_size:#x})")
    for a, b in zip(own, own[1:]):
        if b != a + 4:
            raise Pawn2PasmError(f"hole in the new data at {a:#x}")
    if any(data[a] for a in data if a < data_size):
        raise Pawn2PasmError("a global of the game has an initial value: declare it without one")
    return code, [f"{data[a]:#x}" if data[a] >= 0 else str(data[a]) for a in own]


def s32(value: int) -> int:
    return struct.unpack("<i", struct.pack("<I", value & 0xFFFFFFFF))[0]


def build(path: Path, out: Path | None = None, version: str = versions.BASE) -> Path:
    source = path.read_text(encoding="utf-8")
    m = next((m for m in map(_TARGET.match, source.splitlines()) if m), None)
    if m is None:
        raise Pawn2PasmError(f"{path}: no // @target line")
    target = m[1]
    game = AmxImage.parse(versions.game_files(version).path(target).read_bytes())
    data_size = len(game.data)
    tr = None
    if version != versions.BASE:
        script = Path(target).stem
        port = amxport.Port(amxport.load(script, versions.BASE), amxport.load(script, version))
        tr = amxport.Translator(port, amxport.overrides_of(path.parent.parent / f"{version}.toml", path.stem))
    head, calls, head_lines = prelude(source, data_size, tr)
    module = re.sub(r"\W", "_", path.stem)
    suffix = "" if version == versions.BASE else f"-{version}"
    pasm = out or path.parent.parent / f"{path.stem}{suffix}.pasm"
    if not PAWNCC.exists():
        raise Pawn2PasmError(f"no Pawn compiler at {PAWNCC} (make pawncc)")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{module}.p"
        src.write_text(head + f'#line 1\n#file "{path.name}"\n' + source, encoding="utf-8")
        includes = [f"-i{p}" for p in [path.parent, *INCLUDES]]
        number = int(version[1:]) if version[1:].isdigit() else 0
        common = [str(PAWNCC), str(src), "-d0", "-O1", "-;+", *includes, f"SDSW_VERSION={number}"]
        result = subprocess.run(common + [f"-o{Path(tmp) / module}"], capture_output=True, text=True)
        messages = [l for l in (result.stdout + result.stderr).splitlines()
                    if re.search(r"\b(error|warning)\b", l)]
        # warnings about the declarations of the prelude (unused fillers) are expected
        from_asm = set(re.findall(r"@pw_(\w+)", "\n".join(_ASM.findall(source))))
        messages = [l for l in messages if not re.search(r"__game|__touch_game|symbol is (never used|assigned a value that is never used): \"g_", l)
                    and not any(f'symbol is never used: "{name}"' in l for name in from_asm)]
        if result.returncode or messages:
            raise Pawn2PasmError("\n".join(messages) or result.stdout)
        natives, publics = natives_of((Path(tmp) / f"{module}.amx").read_bytes())
        subprocess.run(common + ["-a", f"-o{Path(tmp) / module}"], capture_output=True, text=True, check=True)
        listing = (Path(tmp) / f"{module}.asm").read_text(encoding="latin-1")
    code, cells = convert(listing, natives, publics, calls, data_size, module)
    hooks = [block.strip("\n") for block in _ASM.findall(source)]
    if tr is not None:
        hooks = [tr.asm(block) for block in hooks]
        try:
            tr.check(f"{path} ({version})")
        except amxport.PortError as e:
            raise Pawn2PasmError(str(e)) from None
    option = f"--version {version} " if suffix else ""
    lines = [f"; Generated by tools/pawn2pasm.py from src/{path.name}: edit the source, then run",
             f";   tools/pawn2pasm.py {option}mods/{path.parent.parent.name}/src/{path.name}",
             f"; Target: {target}" + (f" of the update {version} (addresses of v0 translated by tools/amxport.py; "
                                     f"the names g_<hex> of the source are those of v0)" if suffix else "") + ".", "",
             f".data_at {data_size:#x}"]
    hs = next((int(m[1], 0) for m in map(_HEAPSTACK.match, source.splitlines()) if m), HEAPSTACK)
    if hs:
        lines.append(f".heapstack {hs:#x}                ; room for the stack of the code below (// @heapstack)")
    if cells:
        for k in range(0, len(cells), 16):
            lines.append((f".cells $pawn_data {', '.join(cells[k:k + 16])}" if k == 0
                          else f".cells $pawn_data{k // 16} {', '.join(cells[k:k + 16])}"))
    lines += ["", "; ---- hand-written: hooks into the game's code ----", *hooks,
              "", "; ---- compiled ----", *code, ""]
    pasm.write_text("\n".join(lines), encoding="utf-8")
    return pasm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--version", default=versions.BASE, help="the game's version: v0 (default) or v5200")
    args = parser.parse_args()
    for path in args.sources:
        try:
            print(build(path, version=args.version))
        except Pawn2PasmError as e:
            print(f"{path}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
