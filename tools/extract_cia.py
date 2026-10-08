#!/usr/bin/env python3
"""Extracts the player's decrypted Steel Diver: Sub Wars into extracted/, with the standard library only.

The game can be:
  a .cia (the eShop download)         content 0, the game CXI, is extracted
  a .cxi (Azahar > Load File)         the game NCCH itself
  a .3ds / .cci (cartridge dump)      its partition 0
  the game installed in the emulator  sdmc/Nintendo 3DS/.../title/00040000/000d7e00/content/
By default it is looked for in cia/, chosen by its title id (the folder may hold other titles), then in the
emulator. The game must be decrypted (Azahar needs it decrypted too). Only the game is read: the title id is
checked from the headers before anything else.

Its update (title 0004000E000D7E00, version 5200: tools/versions.py) is extracted the same way, into
extracted/v<version>/, from its decrypted .cia in cia/ or from the emulator where it is installed. By default
both are extracted, the update when there is one.

Layout produced:
  extracted/cia/        certchain.bin, ticket.bin, tmd.bin, meta.bin (from a CIA)
  extracted/ncch/       header.bin, exheader.bin (incl. access descriptor), logo.bin
  extracted/exefs/      raw ExeFS entries (.code is kept compressed as code.lz)
  extracted/code.bin    decompressed .code (text | rodata | data, page aligned)
  extracted/romfs/      RomFS tree
  extracted/manifest.json
  extracted/v5200/      the same for the update (its RomFS only holds the files it changes or adds)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import azahar
import versions
from ctr import CIA, GAME_TITLE_ID, UPDATE_TITLE_ID, ExHeader, find_game_cia, title_id_of, tmd_title_version
from ncch import NCCH, NCCHError, decompress_code

ROOT = Path(__file__).resolve().parent.parent
GAME_SUFFIXES = (".cia", ".cxi", ".3ds", ".cci", ".app")
TITLES = {GAME_TITLE_ID: "Steel Diver: Sub Wars", UPDATE_TITLE_ID: "the update of Steel Diver: Sub Wars"}


class ExtractError(Exception):
    pass


def ncch_offset(fp, path: Path) -> tuple[int, CIA | None]:
    """Offset of the game's (or its update's) NCCH in a file, and the CIA when it is one. Refuses any
    other title."""
    if path.suffix.lower() == ".cia":
        try:
            cia = CIA.parse(fp)
        except (struct.error, KeyError) as e:
            raise ExtractError(f"{path.name}: not a readable CIA") from e
        if cia.title_id not in TITLES:
            raise ExtractError(f"{path.name} is the title {cia.title_id:016X}, not Steel Diver: Sub Wars "
                               f"(Europe, {GAME_TITLE_ID:016X}) or its update ({UPDATE_TITLE_ID:016X})")
        chunk, offset = next(cia.content_offsets())
        if chunk.encrypted:
            what = "the update" if cia.title_id == UPDATE_TITLE_ID else "the game"
            raise ExtractError(f"{path.name}: {what} is encrypted in this CIA. The launcher decrypts it (Game tab, "
                               "\"Set everything up\"), or: python3 tools/decrypt.py <file>")
        return offset, cia
    fp.seek(0x100)
    magic = fp.read(4)
    if magic == b"NCSD":                          # .3ds / .cci: partition table at 0x120
        fp.seek(0x120)
        offset, _ = struct.unpack("<II", fp.read(8))
        return offset * 0x200, None
    if magic == b"NCCH":
        return 0, None
    raise ExtractError(f"{path.name}: neither a CIA, a CCI nor a CXI")


def program_id(path: Path) -> int | None:
    """Title id of a game file, read from its headers only."""
    try:
        with path.open("rb") as fp:
            if path.suffix.lower() == ".cia":
                return CIA.parse(fp).title_id
            offset, _ = ncch_offset(fp, path)
            return NCCH(fp, offset).program_id
    except (OSError, ExtractError, NCCHError, struct.error, KeyError):
        return None


def installed_game() -> Path | None:
    """The game's NCCH as installed in the emulator: content 0 of title/00040000/000d7e00/content/."""
    high, low = f"{GAME_TITLE_ID:016x}"[:8], f"{GAME_TITLE_ID:016x}"[8:]
    for base in azahar.azahar_dirs():
        for folder in (base / "sdmc" / "Nintendo 3DS").glob(f"*/*/title/{high}/{low}/content"):
            for app in sorted(folder.glob("*.app")):
                if program_id(app) == GAME_TITLE_ID:
                    return app
    return None


def find_game(folder: Path = ROOT / "cia") -> Path | None:
    cia = find_game_cia(folder)
    if cia:
        return cia
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() in GAME_SUFFIXES[1:] and program_id(path) == GAME_TITLE_ID:
            return path
    return installed_game()


def find_update(folder: Path = ROOT / "cia") -> Path | None:
    """The update: its CIA in cia/ (the decrypted one when there are several, the highest version first),
    or the update installed in an emulator."""
    found = []
    for path in sorted(folder.glob("*.cia")):
        if title_id_of(path) == UPDATE_TITLE_ID:
            with path.open("rb") as fp:
                cia = CIA.parse(fp)
            found.append((not next(cia.content_offsets())[0].encrypted, cia.title_version, path))
    if found:
        return max(found, key=lambda f: (f[0], f[1]))[2]
    for base in azahar.azahar_dirs():
        update = versions.installed_update(base)
        if update:
            return update[1]
    return None


def update_version(source: Path, cia: CIA | None) -> int:
    """Title version of an update file: its CIA's TMD, or the TMD installed next to its .app."""
    if cia is not None:
        return cia.title_version
    for tmd in sorted(source.parent.glob("*.tmd")):
        try:
            return tmd_title_version(tmd.read_bytes())
        except (OSError, struct.error, KeyError):
            continue
    raise ExtractError(f"{source.name}: the version of this update is unknown (no TMD next to it); "
                       "give its .cia instead")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump_romfs(ncch: NCCH, out: Path, progress=None) -> tuple[int, int]:
    files = total = 0
    for path, offset, size in ncch.romfs_files():
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(ncch.read(offset, size))
        files += 1
        total += size
        if progress and files % 200 == 0:
            progress(f"    {files} files...")
    return files, total


def extract(source: Path, out: Path | None = None, skip_romfs: bool = False, log=print) -> dict:
    """Extracts the game, or its update, into out (by default extracted/ for the game and
    extracted/v<version>/ for the update)."""
    with source.open("rb") as fp:
        offset, cia = ncch_offset(fp, source)
        try:
            ncch = NCCH(fp, offset)
        except NCCHError as e:
            raise ExtractError(f"{source.name}: {e}") from e
        if ncch.program_id not in TITLES:
            raise ExtractError(f"{source.name} is the title {ncch.program_id:016X}, not Steel Diver: Sub Wars "
                               f"(Europe, {GAME_TITLE_ID:016X}) or its update ({UPDATE_TITLE_ID:016X})")
        if ncch.encrypted:
            raise ExtractError(f"{source.name}: its NCCH is encrypted; decrypt it first (Azahar needs it decrypted "
                               "too): python3 tools/decrypt.py <file>, or the launcher's Game tab")
        update = ncch.program_id == UPDATE_TITLE_ID
        version = versions.name(update_version(source, cia)) if update else versions.BASE
        if out is None:
            out = versions.folder(version)
        log(f"[+] NCCH {ncch.product_code}, program {ncch.program_id:016x}"
            + (f" (update {version})" if update else ""))
        if cia:
            log(f"[+] CIA: version {cia.title_version}, {len(cia.contents)} content(s)")
            (out / "cia").mkdir(parents=True, exist_ok=True)
            for name, off, size in (("certchain", cia.cert_offset, cia.cert_size),
                                    ("ticket", cia.ticket_offset, cia.ticket_size),
                                    ("tmd", cia.tmd_offset, cia.tmd_size),
                                    ("meta", cia.meta_offset, cia.meta_size)):
                if size:
                    fp.seek(off)
                    (out / "cia" / f"{name}.bin").write_bytes(fp.read(size))

        ncch_out = out / "ncch"
        ncch_out.mkdir(parents=True, exist_ok=True)
        (ncch_out / "header.bin").write_bytes(ncch.header)
        (ncch_out / "exheader.bin").write_bytes(ncch.exheader())
        for region, name in ((ncch.logo, "logo.bin"), (ncch.plain, "plain.bin")):
            if region:
                (ncch_out / name).write_bytes(ncch.read(region.offset, region.size))
        exheader = ExHeader.parse((ncch_out / "exheader.bin").read_bytes())

        exefs_out = out / "exefs"
        exefs_out.mkdir(parents=True, exist_ok=True)
        code_raw = None
        for name, data in ncch.exefs_files().items():
            if name == ".code":
                code_raw = data
                name = "code.lz" if exheader.code_compressed else "code.raw"
            (exefs_out / name.lstrip(".")).write_bytes(data)
        if code_raw is None:
            raise ExtractError("no .code in the ExeFS")
        code = decompress_code(code_raw) if exheader.code_compressed else code_raw
        (out / "code.bin").write_bytes(code)
        log(f"[+] code.bin: {len(code):#x} bytes ({'decompressed' if exheader.code_compressed else 'raw'})")

        romfs_stats = None
        if not skip_romfs and ncch.romfs is not None:
            log("[+] Extracting RomFS...")
            romfs_stats = dump_romfs(ncch, out / "romfs", log)
            log(f"[+] RomFS: {romfs_stats[0]} files, {romfs_stats[1] / 1e6:.1f} MB")

    manifest = {
        "source": {"file": source.name, "sha256": sha256_file(source)},
        "title_id": f"{cia.title_id if cia else ncch.program_id:016X}",
        "title_version": cia.title_version if cia else (int(version[1:]) if update else None),
        "version": version,
        "product_code": ncch.product_code,
        "contents": [{"index": c.index, "id": f"{c.id:08x}", "type": c.type, "size": c.size,
                      "encrypted_cia_layer": c.encrypted} for c in cia.contents] if cia else [],
        "exheader": {
            "title": exheader.title,
            "code_compressed": exheader.code_compressed,
            "sd_application": exheader.sd_application,
            "remaster_version": exheader.remaster_version,
            "segments": {name: {"address": f"{addr:#010x}", "file_offset": f"{off:#x}", "size": f"{size:#x}"}
                         for name, addr, off, size in exheader.segment_layout()},
            "bss": {"address": f"{exheader.bss_address:#010x}", "size": f"{exheader.bss_size:#x}"},
            "stack_size": f"{exheader.stack_size:#x}",
            "save_data_size": f"{exheader.save_data_size:#x}",
            "dependencies": [f"{d:016X}" for d in exheader.dependencies],
            "core_version": exheader.core_version,
            "priority": exheader.priority,
            "extdata_id": f"{exheader.extdata_id:#x}",
            "fs_access": f"{exheader.fs_access:#x}",
            "services": exheader.services,
            "kernel_caps": [f"{c:08x}" for c in exheader.kernel_caps],
        },
        "code_bin_sha256": hashlib.sha256(code).hexdigest(),
        "romfs": {"files": romfs_stats[0], "bytes": romfs_stats[1]} if romfs_stats else None,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"[+] Wrote {out / 'manifest.json'}")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="?", type=Path,
                    help="the game or its update: .cia, .cxi, .3ds/.cci (default: both, found in cia/, then in "
                         "the emulator)")
    ap.add_argument("-o", "--out", type=Path, help="default: extracted/ (the update: extracted/v<version>/)")
    ap.add_argument("--skip-romfs", action="store_true", help="do not extract the RomFS tree")
    ap.add_argument("--no-update", action="store_true", help="only the game, not its update")
    args = ap.parse_args()

    sources = [args.game] if args.game else [find_game()]
    if sources[0] is None:
        sys.exit(f"The game ({GAME_TITLE_ID:016X}) was found neither in cia/ nor in the emulator: "
                 "pass its path (.cia, .cxi, .3ds).")
    if not args.game and not args.no_update and not args.out:        # -o: one folder, the game only
        update = find_update()
        if update:
            sources.append(update)
    for source in sources:
        print(f"[+] {source}")
        try:
            extract(source, args.out, args.skip_romfs)
        except (ExtractError, OSError) as e:
            sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
