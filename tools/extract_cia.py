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

Layout produced:
  extracted/cia/        certchain.bin, ticket.bin, tmd.bin, meta.bin (from a CIA)
  extracted/ncch/       header.bin, exheader.bin (incl. access descriptor), logo.bin
  extracted/exefs/      raw ExeFS entries (.code is kept compressed as code.lz)
  extracted/code.bin    decompressed .code (text | rodata | data, page aligned)
  extracted/romfs/      RomFS tree
  extracted/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import azahar
from ctr import CIA, GAME_TITLE_ID, ExHeader, find_game_cia
from ncch import NCCH, NCCHError, decompress_code

ROOT = Path(__file__).resolve().parent.parent
GAME_SUFFIXES = (".cia", ".cxi", ".3ds", ".cci", ".app")


class ExtractError(Exception):
    pass


def ncch_offset(fp, path: Path) -> tuple[int, CIA | None]:
    """Offset of the game's NCCH in a file, and the CIA when it is one. Refuses any other title."""
    if path.suffix.lower() == ".cia":
        try:
            cia = CIA.parse(fp)
        except (struct.error, KeyError) as e:
            raise ExtractError(f"{path.name}: not a readable CIA") from e
        if cia.title_id != GAME_TITLE_ID:
            raise ExtractError(f"{path.name} is the title {cia.title_id:016X}, not Steel Diver: Sub Wars "
                               f"(Europe, {GAME_TITLE_ID:016X})")
        chunk, offset = next(cia.content_offsets())
        if chunk.encrypted:
            raise ExtractError("the game is encrypted in this CIA (title key): use a decrypted dump")
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


def extract(source: Path, out: Path, skip_romfs: bool = False, log=print) -> dict:
    with source.open("rb") as fp:
        offset, cia = ncch_offset(fp, source)
        try:
            ncch = NCCH(fp, offset)
        except NCCHError as e:
            raise ExtractError(f"{source.name}: {e}") from e
        if ncch.program_id != GAME_TITLE_ID:
            raise ExtractError(f"{source.name} is the title {ncch.program_id:016X}, not Steel Diver: Sub Wars "
                               f"(Europe, {GAME_TITLE_ID:016X})")
        if ncch.encrypted:
            raise ExtractError("the game NCCH is encrypted; decrypt it first (Azahar needs it decrypted too)")
        log(f"[+] NCCH {ncch.product_code}, program {ncch.program_id:016x}")
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
        "title_version": cia.title_version if cia else None,
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
                    help="the game: .cia, .cxi, .3ds/.cci (default: found in cia/, then in the emulator)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "extracted")
    ap.add_argument("--skip-romfs", action="store_true", help="do not extract the RomFS tree")
    args = ap.parse_args()

    source = args.game or find_game()
    if source is None:
        sys.exit(f"The game ({GAME_TITLE_ID:016X}) was found neither in cia/ nor in the emulator: "
                 "pass its path (.cia, .cxi, .3ds).")
    print(f"[+] {source}")
    try:
        extract(source, args.out, args.skip_romfs)
    except (ExtractError, OSError) as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
