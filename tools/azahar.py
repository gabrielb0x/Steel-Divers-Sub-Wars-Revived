#!/usr/bin/env python3
"""The game and its mods in the Azahar emulator.

  prepare     cia/*.cia -> build/azahar/SteelDiverSubWars.cia and .cxi, from the player's own dump.
              The eShop CIA also holds the electronic manual (content 1), still NCCH-encrypted, and
              Azahar then refuses the whole installation ("Blocked unauthorized encrypted CIA
              installation"). The game itself (content 0) is not encrypted: the CIA written here
              holds it alone (TMD reduced to one content, its hashes recomputed), and the .cxi can
              also be opened directly (File > Load File).
  install     copies a mod built by tools/mod.py into Azahar's load/mods/<title id>/
  uninstall   removes the mod files of the game from Azahar
  where       prints the Azahar folders found

Nothing is sent anywhere: the files are written on this computer, from the player's own dump.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import sys
from pathlib import Path

from ctr import CIA, _SIG_SIZES

ROOT = Path(__file__).resolve().parent.parent
TITLE_ID = "00040000000D7E00"   # Steel Diver: Sub Wars, Europe
TMD_HEADER, INFO_RECORDS, CHUNK = 0xC4, 64 * 0x24, 0x30


def azahar_dirs() -> list[Path]:
    """User folders of Azahar: AZAHAR_DIR, the Flatpak one, the native one."""
    candidates = []
    if os.environ.get("AZAHAR_DIR"):
        candidates.append(Path(os.environ["AZAHAR_DIR"]))
    home = Path.home()
    candidates += [home / ".var/app/org.azahar_emu.Azahar/data/azahar-emu",
                   home / ".local/share/azahar-emu"]
    if os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "Azahar")
    return [c for c in candidates if c.is_dir()]


def mods_dir(base: Path | None) -> Path:
    if base is None:
        found = azahar_dirs()
        if not found:
            sys.exit("Azahar's user folder was not found (set AZAHAR_DIR or pass --azahar-dir).")
        base = found[0]
    return base / "load" / "mods" / TITLE_ID


def align(x: int, a: int = 64) -> int:
    return (x + a - 1) & ~(a - 1)


def game_only_cia(src: Path, dest: Path) -> None:
    """Copy of a CIA keeping content 0 only."""
    with src.open("rb") as f:
        cia = CIA.parse(f)
        f.seek(0)
        header = bytearray(f.read(cia.header_size))
        f.seek(cia.cert_offset)
        certs = f.read(cia.cert_size)
        f.seek(cia.ticket_offset)
        ticket = f.read(cia.ticket_size)
        f.seek(cia.tmd_offset)
        tmd = bytearray(f.read(cia.tmd_size))
        f.seek(cia.meta_offset)
        meta = f.read(cia.meta_size)
        game, offset = next((c, o) for c, o in cia.content_offsets() if c.index == 0)
        if game.encrypted:
            sys.exit("Content 0 is encrypted in this CIA: use a decrypted dump.")

        # TMD: one content chunk record, info record 0 covering it, hashes recomputed. The signature
        # no longer matches, which the emulator does not check.
        body = 4 + _SIG_SIZES[struct.unpack_from(">I", tmd, 0)[0]]
        chunks = body + TMD_HEADER + INFO_RECORDS
        chunk0 = next(tmd[chunks + n * CHUNK:chunks + (n + 1) * CHUNK] for n in range(len(cia.contents))
                      if struct.unpack_from(">H", tmd, chunks + n * CHUNK + 4)[0] == 0)
        info = bytearray(INFO_RECORDS)
        struct.pack_into(">HH", info, 0, 0, 1)
        info[4:0x24] = hashlib.sha256(chunk0).digest()
        new_tmd = bytearray(tmd[:body + TMD_HEADER])
        struct.pack_into(">H", new_tmd, body + 0x9E, 1)
        new_tmd[body + 0xA4:body + 0xC4] = hashlib.sha256(info).digest()
        new_tmd += info + chunk0

        # Header: sizes, and the content index bitmap with content 0 only.
        struct.pack_into("<I", header, 0x10, len(new_tmd))
        struct.pack_into("<Q", header, 0x18, game.size)
        header[0x20:0x2020] = bytes(0x2000)
        header[0x20] = 0x80

        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            for blob in (bytes(header), certs, ticket, bytes(new_tmd)):
                out.write(blob)
                out.write(bytes(align(out.tell()) - out.tell()))
            f.seek(offset)
            copy_range(f, out, game.size)
            out.write(bytes(align(out.tell()) - out.tell()))
            out.write(meta)


def copy_range(src, dst, size: int) -> None:
    while size > 0:
        block = src.read(min(size, 1 << 20))
        if not block:
            raise EOFError("truncated CIA")
        dst.write(block)
        size -= len(block)


def game_cxi(src: Path, dest: Path) -> None:
    with src.open("rb") as f:
        cia = CIA.parse(f)
        game, offset = next((c, o) for c, o in cia.content_offsets() if c.index == 0)
        f.seek(offset)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            copy_range(f, out, game.size)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--azahar-dir", type=Path, help="Azahar's user folder (default: found automatically)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="build the CIA and CXI that Azahar accepts")
    p.add_argument("cia", nargs="?", type=Path, help="the dump (default: first .cia in cia/)")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "build" / "azahar")
    p = sub.add_parser("install", help="install a mod built by tools/mod.py")
    p.add_argument("mod", type=Path, help="build/mods/<name> (or its <title id> folder)")
    sub.add_parser("uninstall", help="remove the game's mod files from Azahar")
    sub.add_parser("where", help="print Azahar's folders")
    args = ap.parse_args()

    if args.command == "prepare":
        src = args.cia or next(iter(sorted((ROOT / "cia").glob("*.cia"))), None)
        if src is None:
            sys.exit("No .cia found in cia/.")
        game_only_cia(src, args.out / "SteelDiverSubWars.cia")
        game_cxi(src, args.out / "SteelDiverSubWars.cxi")
        print(f"[+] {args.out / 'SteelDiverSubWars.cia'}: Azahar > File > Install CIA")
        print(f"[+] {args.out / 'SteelDiverSubWars.cxi'}: or Azahar > File > Load File, without installing")
    elif args.command == "install":
        src = args.mod / TITLE_ID if (args.mod / TITLE_ID).is_dir() else args.mod
        dest = mods_dir(args.azahar_dir)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        print(f"[+] installed into {dest}")
    elif args.command == "uninstall":
        dest = mods_dir(args.azahar_dir)
        if dest.exists():
            shutil.rmtree(dest)
            print(f"[+] removed {dest}")
    else:
        found = azahar_dirs()
        for d in found:
            print(f"{d}\n  mods: {d / 'load' / 'mods' / TITLE_ID}")
        if not found:
            print("Azahar's user folder was not found (set AZAHAR_DIR).")


if __name__ == "__main__":
    main()
