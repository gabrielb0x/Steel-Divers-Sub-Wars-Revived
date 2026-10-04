#!/usr/bin/env python3
"""Infers the parameter types of the Pawn natives from their C++ implementation.

Reads the pseudo-code exported by Ghidra (decomp/raw/, natives typed as
`cell f(AMX *amx, cell *params)`) and classifies each params[N]:
  s  input string   (loader->getString, or amx_GetAddr + amx_GetString/StrLen/printstring)
  S  output string  (loader->setString, or amx_GetAddr + amx_SetString)
  a  array / by-reference variable (other amx_GetAddr / loader->getAddr uses)
  f  Float          ((float)params[N])
  i  plain cell
Natives reading *params (the argument byte count) are variadic.
Writes extracted/native_types.json, used by tools/amxdec.py.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "decomp" / "raw"

STRING_READERS = ("amx_GetString", "amx_StrLen", "amx_printstring", "amx_StrPack", "amx_StrUnpack", "strlen",
                  "amx_UTF8Len")


def function_bodies() -> dict[str, str]:
    """Native name -> decompiled C, from the per-object files listed in functions.csv."""
    wanted = {}
    with (RAW / "functions.csv").open() as f:
        for row in csv.DictReader(f):
            wanted.setdefault(row["file"], []).append((row["address"][2:].upper(), row["name"]))
    bodies = {}
    for file, functions in wanted.items():
        path = RAW / file
        if not path.exists():
            continue
        text = path.read_text()
        for addr, name in functions:
            m = re.search(rf"^// {addr}\b.*?\n(.*?)(?=^// [0-9A-F]{{8}}\b|\Z)", text, re.S | re.M)
            if m and "AMX *amx,cell *params" in m[1]:
                bodies[name] = m[1]
    return bodies


def classify(body: str) -> dict:
    # `x = params[N];` aliases and function pointers read from the loader vtable.
    alias = {v: int(n) for v, n in re.findall(r"\b(\w+) = params\[(\d+)\];", body)}
    methods = dict(re.findall(r"\b(\w+) = \w+->vtbl->(getString|setString|getAddr);", body))

    def param_index(arg: str) -> int | None:
        arg = arg.strip()
        m = re.fullmatch(r"params\[(\d+)\]", arg)
        return int(m[1]) if m else alias.get(arg)

    used = {int(n) for n in re.findall(r"params\[(\d+)\]", body)}
    types = {n: "i" for n in used if n > 0}
    for n in re.findall(r"\(float\)params\[(\d+)\]", body):
        types[int(n)] = "f"

    # Loader methods: getString(self, dest, amx_addr), setString(self, src, amx_addr), getAddr(self, amx_addr, i).
    calls = [(m, a) for m, a in re.findall(r"vtbl->(getString|setString|getAddr)\)\(([^;]*)\);", body)]
    calls += [(methods[p], a) for p, a in re.findall(r"\(\*(\w+)\)\(([^;]*)\);", body) if p in methods]
    for method, args in calls:
        parts = [x for x in re.split(r",(?![^(]*\))", args)]
        position = 1 if method == "getAddr" else 2
        if len(parts) > position and (n := param_index(re.sub(r"^\([^)]*\)", "", parts[position]))) is not None:
            types[n] = {"getString": "s", "setString": "S", "getAddr": "a"}[method]

    # amx_GetAddr(amx, params[N], &ptr): look at what ptr is used for until it is reassigned.
    getaddr = list(re.finditer(r"amx_GetAddr\([^,]+,([^,]+),\s*(?:\([^)]*\))?\s*&(\w+)\)", body))
    for k, m in enumerate(getaddr):
        n = param_index(m[1])
        if n is None:
            continue
        ptr = m[2]
        stop = next((x.start() for x in getaddr[k + 1:] if x[2] == ptr), len(body))
        segment = body[m.end():stop]
        if re.search(rf"amx_SetString\(\s*(?:\([^)]*\))?\s*{ptr}\b", segment):
            types[n] = "S"
        elif any(re.search(rf"{reader}\([^;]*\b{ptr}\b", segment) for reader in STRING_READERS):
            types[n] = "s"
        elif types.get(n, "i") == "i":
            types[n] = "a"
    count = max(types) if types else 0
    variadic = bool(re.search(r"\(uint\)\*params|\*params >>|params\[0\]", body))
    return {"params": "".join(types.get(n, "?") for n in range(1, count + 1)), "variadic": variadic}


def main() -> None:
    bodies = function_bodies()
    from amx import read_linker_map, find_native_tables   # noqa: E402 (tools/ on sys.path when run as a script)
    symbols = read_linker_map(ROOT / "extracted" / "romfs" / "map")
    amx_register = next(addr for addr, (name, _) in symbols.items() if name == "amx_Register")
    natives = find_native_tables((ROOT / "extracted" / "code.bin").read_bytes(), amx_register)
    result = {}
    for name, addr in sorted(natives.items()):
        impl = symbols.get(addr, (None,))[0]
        body = bodies.get(impl) if impl else None
        if body is not None:
            result[name] = {"impl": impl, **classify(body)}
    out = ROOT / "extracted" / "native_types.json"
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"[+] {len(result)}/{len(natives)} natives typed -> {out}")


if __name__ == "__main__":
    main()
