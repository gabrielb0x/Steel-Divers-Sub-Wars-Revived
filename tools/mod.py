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
  like = "internet_mode_warning"    # optional: a new key (key the game lacks), a copy of that text
  # or append = " text": added to the end of the text, after every text = of the build (mods share a line)

  [[bxml]]                          # any BXML file, edited as the XML of `make data`
  file = "worlds/scope00_online_stage01.bxml"     # or files = "bxml/pscope_ply??_stats.bxml" (glob)
  select = "actor[@name='mode_settings']"   # ElementTree path from the root element
  set = { timeLimit = "2400.0" }    # values written as in the XML (2400.0 is a f32, 60 a s32)
  rename = { old = "new" }          # optional: renames attributes, keeping their place (applied before set)
  scale = "${factor}"               # optional: multiplies every number of the selected nodes (after set)
  remove = true                     # optional: removes the selected nodes instead
  from = "bxml/surface_sub_npc_blue.bxml"   # optional: file is a new file, a copy of this one
  copy = { file = "bxml/pscope_ply01.bxml", select = "collshape" }   # optional: set the attributes of
                                    # that node (before set)

  [[subs]]                          # the characteristics of the submarines from a player's file
  file = "${fichier}"               # (tools/subs.py; "auto": sous-marins.toml of the settings folder)

  [[amx]]                           # a Pawn script (amx/*.amx), addresses of decomp/scripts/asm/*.asm
  file = "amx/periscope_move.amx"
  at = 0x5D4C                       # a string literal of the data segment (or every one: no "at")
  string = "player.muteki"
  replace = "mode.ready"            # not longer than the original
  # or an instruction operand: address = 0x130D0, operand = 0, value = 1, expect = 0
  # or Pawn assembly added to the script (tools/amxasm.py): asm = "..." or asm_file = "x.pasm" (in the
  # mod's folder), with .hook <address> to run it in place of existing instructions; ${param} allowed

  [[shader]]                        # an instruction of a PICA200 shader (shaders/*.shbin, DVLB)
  file = "shaders/metaball.shbin"
  instruction = 0x061               # index in the shared code (DVLP), as tools/shbin.py lists it
  expect = 0xA441BC00               # optional: the original instruction
  value = 0x84000000                # nop

  [[code]]                          # code patch, at a virtual address of code.bin
  address = 0x0010C7FC
  arm = "bx lr"                     # ARM assembly (tools/armasm.py), or: bytes = "1eff2fe1",
                                    # (the labels of an arm block: ${arm_<label>} in the entries after it)
                                    # ascii = "text" / utf16 = "text" (NUL-terminated), words = ["0x1234"]
  expect = "f0412de9"               # optional: bytes that must be there (guards the version)
  max_size = 116                    # optional: the patch must not be longer (end of the function)

  [params.server]                   # optional: values given on the command line (--set server=...),
  help = "..."                      # used as ${server} in the [[code]] texts
  default = "127.0.0.1"
  max_length = 31                   # or choices = ["2", "3"]: the only values accepted

  [identity]                        # optional: a player identity for an online server, generated once
  scope = "${server}:${port}"       # per scope and kept in ~/.config/sub-wars-open-sourced/identites.json;
                                    # gives ${pid}, ${password} and ${token}
  token_flags = ["triche"]          # optional, top level: told to the online server in the token
  always = true                     # optional, top level: part of every build (fixes of the game)

Every recipe also gets ${sdsw_version}, the version of Sub Wars Open Sourced (VERSION, and the git commit).

Any entry may have if = "${param}": it is applied only when the parameter is yes (oui, 1, true...),
or unless = "${param}": only when it is no.

Usage:  tools/mod.py build <name> [<name>...] [--set key=value ...] [--install] [--cxi] [--no-fixes]
        tools/mod.py list
Several mods are built together into build/mods/<name>+<name>/ (Azahar loads a single mod folder).
The recipes marked always = true (mods/correctifs) are added to every build, unless --no-fixes.

--cxi also writes build/azahar/SteelDiverSubWars_<name>[_<server>].cxi, the game with the code patch already
applied, to open in Azahar next to the original (RomFS changes stay in the mod folder only).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import string
import struct
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import armasm
import azahar
import shbin
from amxasm import AmxImage, AsmError
from bxml import TYPE_FLOATS, TYPE_INTS, Bxml, escape_string, float_text, from_xml, infer_type
from ctr import find_game_cia

ROOT = Path(__file__).resolve().parent.parent
MODS = ROOT / "mods"
ROMFS = ROOT / "extracted" / "romfs"
CODE_BIN = ROOT / "extracted" / "code.bin"
CODE_BASE = 0x00100000      # code.bin offset = address - CODE_BASE (text, rodata, data are contiguous)


class ModError(Exception):
    pass


# ---- data -----------------------------------------------------------------------------------

def load_bxml(files: dict[str, ET.Element], file: str) -> ET.Element:
    """The tree of a BXML file of the game, as edited so far by this build."""
    if file not in files:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        files[file] = ET.fromstring(Bxml(path.read_bytes()).to_xml())
    return files[file]


def new_bxml(files: dict[str, ET.Element], file: str, source: str) -> None:
    """A new file of the mod, a copy of a file of the game (then edited by the entries that follow)."""
    if file in files or (ROMFS / file).exists():
        raise ModError(f"{file}: the game already has this file")
    files[file] = copy.deepcopy(load_bxml(files, source))


def copied_attributes(files: dict[str, ET.Element], spec: dict) -> dict[str, str]:
    """copy = {file = ..., select = ...}: the attributes of a node of another file."""
    root = load_bxml(files, spec["file"])
    select = spec.get("select", ".")
    node = root if select in (".", "") else root.find(select)
    if node is None:
        raise ModError(f"{spec['file']}: nothing matches {select!r}")
    return dict(node.attrib)


def edit_bxml(files: dict[str, ET.Element], file: str, select: str, values: dict[str, str],
              rename: dict[str, str] | None = None, remove: bool = False, scale: float | None = None) -> int:
    root = load_bxml(files, file)
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
        if scale is not None:
            for name, value in list(node.attrib.items()):
                node.set(name, scaled(value, scale))
    return len(nodes)


def scaled(text: str, factor: float) -> str:
    """An attribute of numbers multiplied by factor, of the same type (other attributes unchanged)."""
    kind = infer_type(text)
    if kind == TYPE_INTS:
        return " ".join(str(round(int(t) * factor)) for t in text.split())
    if kind == TYPE_FLOATS:
        return " ".join(float_text(float(t) * factor) for t in text.split())
    return text


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


def edit_amx(scripts: dict[str, AmxImage], entry: dict, params: dict[str, str] | None = None,
             folder: Path | None = None) -> None:
    file = entry["file"]
    if file not in scripts:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        scripts[file] = AmxImage.parse(path.read_bytes())
    script = scripts[file]
    try:
        if "asm" in entry or "asm_file" in entry:
            source = entry.get("asm") or (folder / entry["asm_file"]).read_text(encoding="utf-8")
            script.assemble(fill_braces(source, params or {}))
        elif "string" in entry:
            places = [entry["at"]] if "at" in entry else script.find_string(entry["string"])
            if not places:
                raise ModError(f"{file}: no literal {entry['string']!r}")
            if "count" in entry and len(places) != entry["count"]:
                raise ModError(f"{file}: {len(places)} literal(s) {entry['string']!r}, expected {entry['count']}")
            for addr in places:
                script.replace_string(addr, entry["string"], entry["replace"])
        else:
            script.set_operand(entry["address"], entry.get("operand", 0), entry["value"], entry.get("expect"))
    except (ValueError, AsmError) as e:
        where = f" ({entry['asm_file']})" if "asm_file" in entry else ""
        raise ModError(f"{file}{where}: {e} (not the EUR v0 scripts?)") from e


def edit_shader(shaders: dict[str, bytearray], entry: dict) -> None:
    """Replaces an instruction of a PICA200 shader binary (DVLB), by its index in the shared code."""
    file = entry["file"]
    if file not in shaders:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        shaders[file] = bytearray(path.read_bytes())
    data = shaders[file]
    try:
        code, size = shbin.code_location(data)
    except ValueError as e:
        raise ModError(f"{file}: {e}") from e
    index = entry["instruction"]
    if not 0 <= index < size:
        raise ModError(f"{file}: no instruction {index:#x} ({size} in the shader)")
    offset = code + 4 * index
    found = struct.unpack_from("<I", data, offset)[0]
    if "expect" in entry and found != entry["expect"]:
        raise ModError(f"{file}: instruction {index:#x} is {found:#010x}, not {entry['expect']:#010x} "
                       "(not the EUR v0 files?)")
    struct.pack_into("<I", data, offset, entry["value"])


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


def text_languages(entry: dict) -> list[str]:
    return entry.get("languages") or sorted(p.stem for p in (ROMFS / "text").glob("*.bxml"))


def apply_texts(files: dict[str, ET.Element], entry: dict, params: dict[str, str] | None = None) -> int:
    """[[text]]: text replaces the text of the key, append adds to its end (after every replacement of the
    build); like = "<key>" creates the key when the game has none, as a copy of that one (font, spacing)."""
    languages = text_languages(entry)
    appended = "append" in entry
    text = fill(entry["append" if appended else "text"], params or {})
    count = 0
    for language in languages:
        file = f"text/{language}.bxml"
        select = f"string[@key='{entry['key']}']"
        root = load_bxml(files, file)
        if root.find(select) is None and "like" in entry:
            model = root.find(f"string[@key='{entry['like']}']")
            if model is None:
                raise ModError(f"{file}: no text {entry['like']!r}")
            node = copy.deepcopy(model)
            node.set("key", entry["key"])
            root.insert(list(root).index(model) + 1, node)
        node = root.find(select)
        new = (node.get("text", "") if node is not None else "") + escape_string(text) if appended \
            else escape_string(text)
        count += edit_bxml(files, file, select, {"text": new})
        chars = font_characters(node.get("typeface", "")) if node is not None else None
        missing = sorted({c for c in text if c not in "\n" and chars is not None and ord(c) not in chars})
        if missing and language == languages[0]:
            print(f"[!] {entry['key']} : la police {node.get('typeface')} n'a pas {' '.join(missing)} "
                  "(ces caractères ne s'afficheront pas)")
    return count


# ---- code -----------------------------------------------------------------------------------

def assemble(source: str, address: int, symbols: dict[str, int] | None = None) -> bytes:
    try:
        return armasm.assemble(source, address, symbols)
    except armasm.AsmError as e:
        raise ModError(f"ARM code at {address:#x}: {e}") from e


def fill_braces(text: str, params: dict[str, str]) -> str:
    """${name} only (Pawn assembly uses $name for its own data)."""
    def value(m: re.Match) -> str:
        if m[1] not in params:
            raise ModError(f"unknown parameter ${{{m[1]}}} in the recipe")
        return params[m[1]]
    return re.sub(r"\$\{(\w+)\}", value, text)


def fill(text: str, params: dict[str, str]) -> str:
    try:
        return string.Template(text).substitute(params)
    except KeyError as e:
        raise ModError(f"unknown parameter {e} in the recipe") from e


def patch_data(entry: dict, params: dict[str, str]) -> bytes:
    """The bytes of a [[code]] entry. The labels of its ARM code become parameters of the entries after it:
    ${arm_<label>} is the address of <label>, as 0x..."""
    address = entry["address"]
    if "arm" in entry:
        symbols: dict[str, int] = {}
        data = assemble(fill(entry["arm"], params), address, symbols)
        params.update({f"arm_{name}": f"{value:#010x}" for name, value in symbols.items()})
        return data
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
    params = dict(params or {})
    for entry in entries:
        address = entry["address"]
        data = patch_data(entry, params)
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


def project_version() -> str:
    """The version of Sub Wars Open Sourced: VERSION, and the commit when this is a git checkout
    ("+": with changes not committed), e.g. "v0.1 (3566be7+)"."""
    version = "v" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if (ROOT / ".git").exists():
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            git = ["git", "-C", str(ROOT)]
            commit = subprocess.run(git + ["rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                    timeout=10, check=True).stdout.strip()
            changed = subprocess.run(git + ["status", "--porcelain", "--untracked-files=no"], capture_output=True,
                                     text=True, timeout=10, check=True).stdout.strip()
            version += f" ({commit}{'+' if changed else ''})"
    return version


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
        choices = [str(c) for c in spec.get("choices", [])]
        if choices and value not in choices:
            raise ModError(f"{key}: {value!r} is not one of {', '.join(choices)}")
        params[key] = value
    params["sdsw_version"] = project_version()
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

def fixes() -> list[str]:
    """The recipes marked always = true: fixes of the game, part of every build."""
    return sorted(recipe.parent.name for recipe in MODS.glob("*/mod.toml")
                  if tomllib.loads(recipe.read_text(encoding="utf-8")).get("always"))


def build(names: list[str], out_root: Path, overrides: dict[str, str] | None = None,
          with_fixes: bool = True) -> Path:
    label = "+".join(names) or "+".join(fixes())
    if with_fixes:
        names = [name for name in fixes() if name not in names] + list(names)
    if not names:
        raise ModError("no mod to build")
    mods = [load_recipe(name) for name in names]
    params = recipe_params(mods, overrides or {})
    out = out_root / label / azahar.TITLE_ID
    if out.exists():
        shutil.rmtree(out)

    files: dict[str, ET.Element] = {}
    edited: set[str] = set()                           # files of the mod (others are only read)
    scripts: dict[str, AmxImage] = {}
    shaders: dict[str, bytearray] = {}
    code: list[dict] = []
    for mod, name in zip(mods, names):
        for entry in mod.get("text", []):
            if enabled(entry, params) and "append" not in entry:
                apply_texts(files, entry, params)
                edited.update(f"text/{language}.bxml" for language in text_languages(entry))
        for entry in mod.get("bxml", []):
            if enabled(entry, params):
                scale = None
                if "scale" in entry:
                    try:
                        scale = float(fill(str(entry["scale"]), params))
                    except ValueError as e:
                        raise ModError(f"scale = {entry['scale']!r}: not a number") from e
                if "from" in entry:
                    new_bxml(files, entry["file"], entry["from"])
                values = copied_attributes(files, entry["copy"]) if "copy" in entry else {}
                values |= {k: fill(str(v), params) for k, v in entry.get("set", {}).items()}
                for file in bxml_files(entry):
                    edit_bxml(files, file, entry.get("select", "."), values,
                              entry.get("rename"), entry.get("remove", False), scale)
                    edited.add(file)
        for entry in mod.get("subs", []):
            if enabled(entry, params):
                import subs
                try:
                    edits = subs.changes(fill(entry["file"], params))
                except subs.SubsError as e:
                    raise ModError(str(e)) from e
                for file, values in edits.items():
                    edit_bxml(files, file, ".", values)
                    edited.add(file)
                print(f"[+] caractéristiques de {len(edits)} sous-marin(s) modifiées")
        for entry in mod.get("amx", []):
            if enabled(entry, params):
                edit_amx(scripts, entry, params, MODS / name)
        for entry in mod.get("shader", []):
            if enabled(entry, params):
                edit_shader(shaders, entry)
        code += [entry for entry in mod.get("code", []) if enabled(entry, params)]
    for mod in mods:                                   # after every replacement: mods add to the same line
        for entry in mod.get("text", []):
            if enabled(entry, params) and "append" in entry:
                apply_texts(files, entry, params)
                edited.update(f"text/{language}.bxml" for language in text_languages(entry))
    for file, root in files.items():
        if file not in edited:
            continue
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(from_xml(ET.tostring(root, encoding="unicode")))
    for file, script in scripts.items():
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(script.write())
    for file, shader in shaders.items():
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(shader))

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
    print(f"[+] {title}: {len(edited) + len(scripts) + len(shaders)} file(s), {len(code)} code patch(es) -> {out}")
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
    p.add_argument("--install", action="store_true",
                   help="then install it into the emulators found (Azahar, Lime3DS, Citra, Borked3DS)")
    p.add_argument("--cxi", action="store_true", help="also write the game with this code patch applied")
    p.add_argument("--no-fixes", action="store_true", help="without the fixes of the game (mods/correctifs)")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "build" / "mods")
    sub.add_parser("list", help="list the mods of mods/")
    args = ap.parse_args()

    if args.command == "list":
        for recipe in sorted(MODS.glob("*/mod.toml")):
            mod = tomllib.loads(recipe.read_text(encoding="utf-8"))
            always = " (toujours inclus)" if mod.get("always") else ""
            print(f"{recipe.parent.name:24s} {mod.get('description', '')}{always}")
        return
    try:
        overrides = dict(item.split("=", 1) for item in args.set)
    except ValueError:
        sys.exit("[!] --set expects KEY=VALUE")
    try:
        built = build(args.names, args.out, overrides, with_fixes=not args.no_fixes)
        if args.cxi:
            print(f"[+] {write_cxi('+'.join(args.names), built, build.params)}: Azahar > File > Load File")
    except (ModError, KeyError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"[!] {e}")
    if args.install:
        for dest in azahar.install(built):              # every emulator found (Azahar, Citra family)
            print(f"[+] installed into {dest}")


if __name__ == "__main__":
    main()
