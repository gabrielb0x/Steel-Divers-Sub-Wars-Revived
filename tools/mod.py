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
  text = "My text"                  # \\n for a new line
  languages = ["EU_French"]         # optional: only these files

  [[bxml]]                          # any BXML file, edited as the XML of `make data`
  file = "worlds/scope00_online_stage01.bxml"
  select = "actor[@name='mode_settings']"   # ElementTree path from the root element
  set = { timeLimit = "2400.0" }    # values written as in the XML (2400.0 is a f32, 60 a s32)

  [[code]]                          # code patch, at a virtual address of code.bin
  address = 0x0010C7FC
  arm = "bx lr"                     # ARM assembly (keystone), or: bytes = "1eff2fe1"
  expect = "f0412de9"               # optional: bytes that must be there (guards the version)

Usage:  tools/mod.py build <name> [--install]     tools/mod.py list
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import azahar
from bxml import Bxml, escape_string, from_xml

ROOT = Path(__file__).resolve().parent.parent
MODS = ROOT / "mods"
ROMFS = ROOT / "extracted" / "romfs"
CODE_BIN = ROOT / "extracted" / "code.bin"
CODE_BASE = 0x00100000      # code.bin offset = address - CODE_BASE (text, rodata, data are contiguous)


class ModError(Exception):
    pass


# ---- data -----------------------------------------------------------------------------------

def edit_bxml(files: dict[str, ET.Element], file: str, select: str, values: dict[str, str]) -> int:
    if file not in files:
        path = ROMFS / file
        if not path.exists():
            raise ModError(f"{file}: not in extracted/romfs (run make extract)")
        files[file] = ET.fromstring(Bxml(path.read_bytes()).to_xml())
    root = files[file]
    nodes = [root] if select in (".", "") else root.findall(select)
    if not nodes:
        raise ModError(f"{file}: nothing matches {select!r}")
    for node in nodes:
        for name, value in values.items():
            node.set(name, str(value))
    return len(nodes)


def apply_texts(files: dict[str, ET.Element], entry: dict) -> int:
    languages = entry.get("languages") or sorted(p.stem for p in (ROMFS / "text").glob("*.bxml"))
    count = 0
    for language in languages:
        count += edit_bxml(files, f"text/{language}.bxml", f"string[@key='{entry['key']}']",
                           {"text": escape_string(entry["text"])})
    return count


# ---- code -----------------------------------------------------------------------------------

def assemble(source: str, address: int) -> bytes:
    try:
        import keystone
    except ImportError as e:
        raise ModError("ARM assembly needs keystone-engine (pip install keystone-engine)") from e
    ks = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
    encoding, _ = ks.asm(source, address)
    return bytes(encoding)


def code_patches(entries: list[dict]) -> dict[int, bytes]:
    code = CODE_BIN.read_bytes()
    patches: dict[int, bytes] = {}
    for entry in entries:
        address = entry["address"]
        data = assemble(entry["arm"], address) if "arm" in entry else bytes.fromhex(entry["bytes"].replace(" ", ""))
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


# ---- build ----------------------------------------------------------------------------------

def build(name: str, out_root: Path) -> Path:
    recipe = MODS / name / "mod.toml"
    if not recipe.exists():
        raise ModError(f"no recipe {recipe}")
    mod = tomllib.loads(recipe.read_text(encoding="utf-8"))
    out = out_root / name / azahar.TITLE_ID
    if out.exists():
        shutil.rmtree(out)

    files: dict[str, ET.Element] = {}
    for entry in mod.get("text", []):
        apply_texts(files, entry)
    for entry in mod.get("bxml", []):
        edit_bxml(files, entry["file"], entry.get("select", "."), entry.get("set", {}))
    for file, root in files.items():
        dest = out / "romfs" / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(from_xml(ET.tostring(root, encoding="unicode")))

    if mod.get("code"):
        dest = out / "exefs" / "code.ips"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(ips(code_patches(mod["code"])))
    print(f"[+] {mod.get('name', name)}: {len(files)} file(s), {len(mod.get('code', []))} code patch(es) -> {out}")
    return out_root / name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="build mods/<name> into build/mods/<name>")
    p.add_argument("name")
    p.add_argument("--install", action="store_true", help="then install it into Azahar")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "build" / "mods")
    sub.add_parser("list", help="list the mods of mods/")
    args = ap.parse_args()

    if args.command == "list":
        for recipe in sorted(MODS.glob("*/mod.toml")):
            mod = tomllib.loads(recipe.read_text(encoding="utf-8"))
            print(f"{recipe.parent.name:24s} {mod.get('description', '')}")
        return
    try:
        built = build(args.name, args.out)
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
