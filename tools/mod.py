#!/usr/bin/env python3
"""Builds a mod for the Azahar emulator from a recipe: mods/<name>/mod.toml.

A mod is a list of changes applied to the player's own files (extracted/ by `make extract`), so the
repository never holds game data. The result has the layout Azahar loads, for this game only:

  build/mods/<name>/00040000000D7E00/romfs/...      files replacing those of the RomFS
  build/mods/<name>/00040000000D7E00/exefs/code.ips patch of the code (decompressed code.bin)

mod.toml:

  name = "..."
  description = "..."

  [[text]]                          # a text of the game, in every language (text/*.bxml)
  key = "title_version"             # <string key=...> of extracted/xml/text/*.xml
  text = "My text"                  # \\n for a new line; ${param} for a value given at build time
  languages = ["EU_French"]         # optional: only these files

  [[bxml]]                          # any BXML file, edited as the XML of `make data`
  file = "worlds/scope00_online_stage01.bxml"     # or files = "bxml/pscope_ply??_stats.bxml" (glob)
  select = "actor[@name='mode_settings']"   # ElementTree path from the root element
  set = { timeLimit = "2400.0" }    # values written as in the XML (2400.0 is a f32, 60 a s32)
  rename = { old = "new" }          # optional: renames attributes, keeping their place (applied before set)
  remove = true                     # optional: removes the selected nodes instead

  [[subs]]                          # the characteristics of the submarines from a player's file
  file = "${fichier}"               # (tools/subs.py; "auto": sous-marins.toml of the settings folder)

  [[amx]]                           # a Pawn script (amx/*.amx), addresses of decomp/scripts/asm/*.asm
  file = "amx/periscope_move.amx"
  at = 0x5D4C                       # a string literal of the data segment (or every one: no "at")
  string = "player.muteki"
  replace = "mode.ready"            # not longer than the original
  # or an instruction operand: address = 0x130D0, operand = 0, value = 1, expect = 0

  [[code]]                          # code patch, at a virtual address of code.bin
  address = 0x0010C7FC
  arm = "bx lr"                     # ARM assembly (tools/armasm.py), or: bytes = "1eff2fe1",
                                    # ascii = "text" / utf16 = "text" (NUL-terminated), words = ["0x1234"]
  expect = "f0412de9"               # optional: bytes that must be there (guards the version)
  max_size = 116                    # optional: the patch must not be longer (end of the function)

  [params.server]                   # optional: values given on the command line (--set server=...),
  help = "..."                      # used as ${server} in the [[code]] texts
  default = "127.0.0.1"
  max_length = 31

  [identity]                        # optional: a player identity for an online server, generated once
  scope = "${server}:${port}"       # per scope and kept in ~/.config/sub-wars-open-sourced/identites.json;
                                    # gives ${pid}, ${password} and ${token}
  token_flags = ["triche"]          # optional, top level: told to the online server in the token

Any entry may have if = "${param}": it is applied only when the parameter is yes (oui, 1, true...),
or unless = "${param}": only when it is no.

Usage:  tools/mod.py build <name> [<name>...] [--set key=value ...] [--install] [--cxi]
        tools/mod.py list
Several mods are built together into build/mods/<name>+<name>/ (Azahar loads a single mod folder).

--cxi also writes build/azahar/SteelDiverSubWars_<name>[_<server>].cxi, the game with the code patch already
applied, to open in Azahar next to the original (RomFS changes stay in the mod folder only).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import string
import struct
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import armasm
import azahar
from amx import AmxPatcher
from bxml import Bxml, escape_string, from_xml
from ctr import find_game_cia

ROOT = Path(__file__).resolve().parent.parent
MODS = ROOT / "mods"
ROMFS = ROOT / "extracted" / "romfs"
CODE_BIN = ROOT / "extracted" / "code.bin"
CODE_BASE = 0x00100000      # code.bin offset = address - CODE_BASE (text, rodata, data are contiguous)


class ModError(Exception):
    pass


# ---- data -----------------------------------------------------------------------------------

def edit_bxml(files: dict[str, ET.Element], file: str, select: str, values: dict[str, str],
              rename: dict[str, str] | None = None, remove: bool = False) -> int:
    if file not in files:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        files[file] = ET.fromstring(Bxml(path.read_bytes()).to_xml())
    root = files[file]
    nodes = [root] if select in (".", "") else root.findall(select)
    if not nodes:
        raise ModError(f"{file}: nothing matches {select!r}")
    if remove:
        parents = {child: parent for parent in root.iter() for child in parent}
        for node in nodes:
            if node is root:
                raise ModError(f"{file}: cannot remove the root node")
            parents[node].remove(node)
        return len(nodes)
    for node in nodes:
        if rename:
            missing = set(rename) - set(node.attrib)
            if missing:
                raise ModError(f"{file}: {select!r} has no attribute {', '.join(sorted(missing))}")
            # The game applies the attributes in order (Actor::readProperties): keep their place.
            items = [(rename.get(k, k), v) for k, v in node.attrib.items()]
            node.attrib.clear()
            node.attrib.update(items)
        for name, value in values.items():
            node.set(name, str(value))
    return len(nodes)


YES = {"1", "oui", "o", "yes", "y", "true", "vrai", "on"}
NO = {"0", "non", "n", "no", "false", "faux", "off"}


def enabled(entry: dict, params: dict[str, str]) -> bool:
    for key, wanted in (("if", True), ("unless", False)):
        if key in entry:
            value = fill(entry[key], params).strip().lower()
            if value not in YES | NO:
                raise ModError(f"{entry[key]} = {value!r}: expected oui/non")
            if (value in YES) != wanted:
                return False
    return True


def bxml_files(entry: dict) -> list[str]:
    if "files" in entry:
        found = sorted(str(p.relative_to(ROMFS)) for p in ROMFS.glob(entry["files"]))
        if not found:
            raise ModError(f"{entry['files']}: no file in extracted/romfs (run make extract)")
        return found
    return [entry["file"]]


def edit_amx(scripts: dict[str, AmxPatcher], entry: dict) -> None:
    file = entry["file"]
    if file not in scripts:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        scripts[file] = AmxPatcher(path.read_bytes())
    script = scripts[file]
    try:
        if "string" in entry:
            places = [entry["at"]] if "at" in entry else script.find_string(entry["string"])
            if not places:
                raise ModError(f"{file}: no literal {entry['string']!r}")
            if "count" in entry and len(places) != entry["count"]:
                raise ModError(f"{file}: {len(places)} literal(s) {entry['string']!r}, expected {entry['count']}")
            for addr in places:
                script.replace_string(addr, entry["string"], entry["replace"])
        else:
            script.set_operand(entry["address"], entry.get("operand", 0), entry["value"], entry.get("expect"))
    except ValueError as e:
        raise ModError(f"{file}: {e} (not the EUR v0 scripts?)") from e


def font_characters(typeface: str, cache: dict[str, set[int] | None] = {}) -> set[int] | None:
    """Characters of fonts/<typeface>.bcfnt (its CMAP sections), or None if it cannot be read."""
    if typeface not in cache:
        cache[typeface] = None
        path = ROMFS / "fonts" / f"{typeface}.bcfnt"
        with contextlib.suppress(OSError, struct.error, ValueError):
            data = path.read_bytes()
            if data[:4] != b"CFNT":
                return None
            end = "<" if data[4:6] == b"\xff\xfe" else ">"
            finf = struct.unpack_from(end + "H", data, 6)[0]
            chars: set[int] = set()
            section = struct.unpack_from(end + "I", data, finf + 0x18)[0]       # FINF: first CMAP
            while section:
                begin, last, method, _, following = struct.unpack_from(end + "HHHHI", data, section)
                body = section + 12
                if method == 0:                                                 # direct
                    chars.update(range(begin, last + 1))
                elif method == 1:                                               # table
                    chars.update(code for i, code in enumerate(range(begin, last + 1))
                                 if struct.unpack_from(end + "H", data, body + 2 * i)[0] != 0xFFFF)
                else:                                                           # scan
                    count = struct.unpack_from(end + "H", data, body)[0]
                    chars.update(struct.unpack_from(end + "H", data, body + 2 + 4 * i)[0] for i in range(count))
                section = following
            cache[typeface] = chars
    return cache[typeface]


def apply_texts(files: dict[str, ET.Element], entry: dict, params: dict[str, str] | None = None) -> int:
    languages = entry.get("languages") or sorted(p.stem for p in (ROMFS / "text").glob("*.bxml"))
    text = fill(entry["text"], params or {})
    count = 0
    for language in languages:
        count += edit_bxml(files, f"text/{language}.bxml", f"string[@key='{entry['key']}']",
                           {"text": escape_string(text)})
        node = files[f"text/{language}.bxml"].find(f"string[@key='{entry['key']}']")
        chars = font_characters(node.get("typeface", "")) if node is not None else None
        missing = sorted({c for c in text if c not in "\n" and chars is not None and ord(c) not in chars})
        if missing and language == languages[0]:
            print(f"[!] {entry['key']} : la police {node.get('typeface')} n'a pas {' '.join(missing)} "
                  "(ces caractères ne s'afficheront pas)")
    return count


# ---- code -----------------------------------------------------------------------------------

def assemble(source: str, address: int) -> bytes:
    try:
        return armasm.assemble(source, address)
    except armasm.AsmError as e:
        raise ModError(f"ARM code at {address:#x}: {e}") from e


def fill(text: str, params: dict[str, str]) -> str:
    try:
        return string.Template(text).substitute(params)
    except KeyError as e:
        raise ModError(f"unknown parameter {e} in the recipe") from e


def patch_data(entry: dict, params: dict[str, str]) -> bytes:
    address = entry["address"]
    if "arm" in entry:
        return assemble(fill(entry["arm"], params), address)
    if "ascii" in entry:
        return fill(entry["ascii"], params).encode("ascii") + b"\0"
    if "utf16" in entry:
        return fill(entry["utf16"], params).encode("utf-16-le") + b"\0\0"
    if "words" in entry:
        return b"".join(int(fill(w, params), 0).to_bytes(4, "little") for w in entry["words"])
    return bytes.fromhex(fill(entry["bytes"], params).replace(" ", ""))


def code_patches(entries: list[dict], params: dict[str, str] | None = None) -> dict[int, bytes]:
    code = CODE_BIN.read_bytes()
    patches: dict[int, bytes] = {}
    for entry in entries:
        address = entry["address"]
        data = patch_data(entry, params or {})
        if "max_size" in entry and len(data) > entry["max_size"]:
            raise ModError(f"code patch at {address:#x}: {len(data)} bytes, more than {entry['max_size']}")
        offset = address - CODE_BASE
        if not 0 <= offset <= len(code) - len(data):
            raise ModError(f"code patch at {address:#x}: outside code.bin")
        if "expect" in entry:
            expected = bytes.fromhex(entry["expect"].replace(" ", ""))
            if code[offset:offset + len(expected)] != expected:
                raise ModError(f"code patch at {address:#x}: unexpected bytes, not the EUR v0 executable?")
        patches[offset] = data
    return patches


def ips(patches: dict[int, bytes]) -> bytes:
    """IPS file: "PATCH", records (u24 offset, u16 size, data), "EOF"."""
    out = bytearray(b"PATCH")
    for offset in sorted(patches):
        data = patches[offset]
        for k in range(0, len(data), 0xFFFF):
            chunk, at = data[k:k + 0xFFFF], offset + k
            if at == 0x454F46:     # the bytes "EOF": IPS cannot start a record there
                raise ModError("a patch starts at offset 0x454F46, which IPS cannot express")
            out += at.to_bytes(3, "big") + len(chunk).to_bytes(2, "big") + chunk
    return bytes(out + b"EOF")


# ---- parameters and identity ----------------------------------------------------------------

IDENTITY_FILE = azahar.config_dir() / "identites.json"


def user_key(pid: int, password: str) -> str:
    """Kerberos key of a NEX account: MD5 applied 65000 + pid % 1024 times (MD5KeyDerivation)."""
    data = password.encode("ascii")
    for _ in range(65000 + pid % 1024):
        data = hashlib.md5(data).digest()
    return data.hex()


def identity(scope: str, flags: list[str] | None = None) -> dict[str, str]:
    known = json.loads(IDENTITY_FILE.read_text(encoding="utf-8")) if IDENTITY_FILE.exists() else {}
    if scope not in known:
        alphabet = string.ascii_letters + string.digits
        known[scope] = {"pid": 0x10000000 + secrets.randbelow(0x70000000),
                        "password": "".join(secrets.choice(alphabet) for _ in range(16))}
        IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        IDENTITY_FILE.write_text(json.dumps(known, indent=2) + "\n", encoding="utf-8")
        os.chmod(IDENTITY_FILE, 0o600)
        print(f"[+] new player identity for {scope}: pid {known[scope]['pid']} (kept in {IDENTITY_FILE})")
    pid, password = known[scope]["pid"], known[scope]["password"]
    token = "sdsw1:" + user_key(pid, password) + (":" + ",".join(sorted(flags)) if flags else "")
    return {"pid": str(pid), "password": password, "token": token}


def recipe_params(mods: list[dict], overrides: dict[str, str]) -> dict[str, str]:
    specs: dict[str, dict] = {}
    for mod in mods:
        for key, spec in mod.get("params", {}).items():
            if key in specs and specs[key] != spec:
                raise ModError(f"parameter {key} is declared differently by two of these mods")
            specs[key] = spec
    unknown = set(overrides) - set(specs)
    if unknown:
        raise ModError(f"unknown parameter(s) {', '.join(sorted(unknown))}; these mods take: {', '.join(specs) or 'none'}")
    params = {}
    for key, spec in specs.items():
        value = str(overrides.get(key, spec.get("default", "")))
        if not value:
            raise ModError(f"--set {key}=... is required: {spec.get('help', '')}")
        if len(value) > spec.get("max_length", 1 << 30):
            raise ModError(f"{key}: at most {spec['max_length']} characters")
        params[key] = value
    flags = sorted({f for mod in mods for f in mod.get("token_flags", [])})
    scopes = {fill(mod["identity"]["scope"], params) for mod in mods if "identity" in mod}
    if len(scopes) > 1:
        raise ModError("two identities requested")
    if scopes:
        params.update(identity(scopes.pop(), flags))
    return params


def load_recipe(name: str) -> dict:
    recipe = MODS / name / "mod.toml"
    if not recipe.exists():
        raise ModError(f"no recipe {recipe}")
    return tomllib.loads(recipe.read_text(encoding="utf-8"))


# ---- build ----------------------------------------------------------------------------------

def build(names: list[str], out_root: Path, overrides: dict[str, str] | None = None) -> Path:
    mods = [load_recipe(name) for name in names]
    params = recipe_params(mods, overrides or {})
    label = "+".join(names)
    out = out_root / label / azahar.TITLE_ID
    if out.exists():
        shutil.rmtree(out)

    files: dict[str, ET.Element] = {}
    scripts: dict[str, AmxPatcher] = {}
    code: list[dict] = []
    for mod in mods:
        for entry in mod.get("text", []):
            if enabled(entry, params):
                apply_texts(files, entry, params)
        for entry in mod.get("bxml", []):
            if enabled(entry, params):
                for file in bxml_files(entry):
                    edit_bxml(files, file, entry.get("select", "."),
                              {k: fill(str(v), params) for k, v in entry.get("set", {}).items()},
                              entry.get("rename"), entry.get("remove", False))
        for entry in mod.get("subs", []):
            if enabled(entry, params):
                import subs
                try:
                    edits = subs.changes(fill(entry["file"], params))
                except subs.SubsError as e:
                    raise ModError(str(e)) from e
                for file, values in edits.items():
                    edit_bxml(files, file, ".", values)
                print(f"[+] caractéristiques de {len(edits)} sous-marin(s) modifiées")
        for entry in mod.get("amx", []):
            if enabled(entry, params):
                edit_amx(scripts, entry)
        code += [entry for entry in mod.get("code", []) if enabled(entry, params)]
    for file, root in files.items():
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(from_xml(ET.tostring(root, encoding="unicode")))
    for file, script in scripts.items():
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(script.write())

    if code:
        patches = code_patches(code, params)
        ranges = sorted((o, o + len(d)) for o, d in patches.items())
        for (_, end), (start, _) in zip(ranges, ranges[1:]):
            if start < end:
                raise ModError(f"two code patches overlap at {start + CODE_BASE:#x}")
        dest = out / "exefs" / "code.ips"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(ips(patches))
    title = " + ".join(mod.get("name", name) for mod, name in zip(mods, names))
    print(f"[+] {title}: {len(files) + len(scripts)} file(s), {len(code)} code patch(es) -> {out}")
    build.params = params
    return out_root / label


def write_cxi(name: str, built: Path, params: dict[str, str]) -> Path:
    patch = built / azahar.TITLE_ID / "exefs" / "code.ips"
    if not patch.exists():
        raise ModError("this mod has no code patch: nothing to put in a CXI")
    if (built / azahar.TITLE_ID / "romfs").exists():
        print("[!] the CXI only holds the code patch; the RomFS changes need the mod folder (--install)")
    cia = find_game_cia(ROOT / "cia")
    if cia is None:
        raise ModError(f"no CIA of the game ({azahar.TITLE_ID}) in cia/")
    code = bytearray(CODE_BIN.read_bytes())
    azahar.apply_ips(code, patch.read_bytes())
    label = name + (f"_{params['server']}" if "server" in params else "")
    label = "".join(c if c.isalnum() or c in "._-" else "-" for c in label)
    dest = ROOT / "build" / "azahar" / f"SteelDiverSubWars_{label}.cxi"
    azahar.patched_cxi(cia, bytes(code), dest)
    azahar.write_readme(dest.parent)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="build mods/<name> (several: together) into build/mods/")
    p.add_argument("names", nargs="+", metavar="name")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a parameter of the recipe")
    p.add_argument("--install", action="store_true", help="then install it into Azahar")
    p.add_argument("--cxi", action="store_true", help="also write the game with this code patch applied")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "build" / "mods")
    sub.add_parser("list", help="list the mods of mods/")
    args = ap.parse_args()

    if args.command == "list":
        for recipe in sorted(MODS.glob("*/mod.toml")):
            mod = tomllib.loads(recipe.read_text(encoding="utf-8"))
            print(f"{recipe.parent.name:24s} {mod.get('description', '')}")
        return
    try:
        overrides = dict(item.split("=", 1) for item in args.set)
    except ValueError:
        sys.exit("[!] --set expects KEY=VALUE")
    try:
        built = build(args.names, args.out, overrides)
        if args.cxi:
            print(f"[+] {write_cxi('+'.join(args.names), built, build.params)}: Azahar > File > Load File")
    except (ModError, KeyError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"[!] {e}")
    if args.install:
        dest = azahar.mods_dir(None)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(built / azahar.TITLE_ID, dest)
        print(f"[+] installed into {dest}")


if __name__ == "__main__":
    main()
