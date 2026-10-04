#!/usr/bin/env python3
"""Extract a decrypted Steel Diver: Sub Wars CIA into extracted/.

Layout produced:
  extracted/cia/        certchain.bin, ticket.bin, tmd.bin, meta.bin
  extracted/ncch/       header.bin, exheader.bin (incl. access descriptor), logo.bin
  extracted/exefs/      raw ExeFS entries (.code is kept compressed as code.lz)
  extracted/code.bin    decompressed .code (text | rodata | data, page aligned)
  extracted/romfs/      RomFS tree
  extracted/manifest.json

Only content 0 (the game CXI) is extracted. Content 1 is the electronic manual,
which is still NCCH-encrypted in this dump and is not needed for the project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from pyctr.crypto.engine import CryptoEngine
from pyctr.fileio import SubsectionIO
from pyctr.type.exefs import decompress_code
from pyctr.type.ncch import NCCHReader, NCCHSection

from ctr import CIA, ExHeader

ROOT = Path(__file__).resolve().parent.parent


def find_cia() -> Path:
    found = sorted((ROOT / "cia").glob("*.cia"))
    if not found:
        sys.exit("No .cia found in cia/ (pass a path explicitly).")
    return found[0]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump_romfs(romfs, out: Path) -> tuple[int, int]:
    files = size = 0
    stack = ["/"]
    while stack:
        path = stack.pop()
        info = romfs.get_info_from_path(path)
        for name in info.contents:
            child = path.rstrip("/") + "/" + name
            entry = romfs.get_info_from_path(child)
            if entry.type == "dir":
                stack.append(child)
                continue
            dest = out / child.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with romfs.open(child) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            files += 1
            size += entry.size
    return files, size


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cia", nargs="?", type=Path, help="path to the .cia (default: first file in cia/)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "extracted")
    ap.add_argument("--skip-romfs", action="store_true", help="do not extract the RomFS tree")
    args = ap.parse_args()

    cia_path = args.cia or find_cia()
    out: Path = args.out
    print(f"[+] CIA: {cia_path}")

    with cia_path.open("rb") as fp:
        cia = CIA.parse(fp)
        print(f"[+] Title ID {cia.title_id:016X}, version {cia.title_version}, {len(cia.contents)} content(s)")

        (out / "cia").mkdir(parents=True, exist_ok=True)
        for name, off, size in (("certchain", cia.cert_offset, cia.cert_size),
                                ("ticket", cia.ticket_offset, cia.ticket_size),
                                ("tmd", cia.tmd_offset, cia.tmd_size),
                                ("meta", cia.meta_offset, cia.meta_size)):
            if size:
                fp.seek(off)
                (out / "cia" / f"{name}.bin").write_bytes(fp.read(size))

        chunk, offset = next(cia.content_offsets())
        if chunk.encrypted:
            sys.exit("Content 0 is CIA-encrypted (title key); decrypt the CIA first (e.g. with GodMode9).")

        # No console keys are needed for a NoCrypto NCCH: skip loading boot9.
        crypto = CryptoEngine(setup_b9_keys=False)
        ncch = NCCHReader(SubsectionIO(fp, offset, chunk.size), crypto=crypto, closefd=False)
        if not ncch.flags.no_crypto:
            sys.exit("The game NCCH is encrypted; decrypt it first (e.g. with GodMode9 or Citra/Azahar tools).")
        print(f"[+] NCCH {ncch.product_code}, program {ncch.program_id}")

        ncch_out = out / "ncch"
        ncch_out.mkdir(parents=True, exist_ok=True)
        fp.seek(offset)
        (ncch_out / "header.bin").write_bytes(fp.read(0x200))
        for section, name in ((NCCHSection.ExtendedHeader, "exheader.bin"), (NCCHSection.Logo, "logo.bin"),
                              (NCCHSection.Plain, "plain.bin")):
            if section in ncch.sections:
                with ncch.open_raw_section(section) as f:
                    (ncch_out / name).write_bytes(f.read())

        exheader = ExHeader.parse((ncch_out / "exheader.bin").read_bytes())

        exefs_out = out / "exefs"
        exefs_out.mkdir(parents=True, exist_ok=True)
        code_raw = None
        for name in ncch.exefs.entries:
            with ncch.exefs.open(name) as f:
                data = f.read()
            if name == ".code":
                code_raw = data
                name = "code.lz" if exheader.code_compressed else "code.raw"
            (exefs_out / name.lstrip(".")).write_bytes(data)

        code = decompress_code(code_raw) if exheader.code_compressed else code_raw
        (out / "code.bin").write_bytes(code)
        print(f"[+] code.bin: {len(code):#x} bytes ({'decompressed' if exheader.code_compressed else 'raw'})")

        romfs_stats = None
        if not args.skip_romfs and ncch.romfs is not None:
            print("[+] Extracting RomFS...")
            romfs_stats = dump_romfs(ncch.romfs, out / "romfs")
            print(f"[+] RomFS: {romfs_stats[0]} files, {romfs_stats[1] / 1e6:.1f} MB")

    manifest = {
        "source": {"file": cia_path.name, "sha256": sha256_file(cia_path)},
        "title_id": f"{cia.title_id:016X}",
        "title_version": cia.title_version,
        "product_code": ncch.product_code,
        "contents": [{"index": c.index, "id": f"{c.id:08x}", "type": c.type, "size": c.size,
                      "encrypted_cia_layer": c.encrypted} for c in cia.contents],
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
    print(f"[+] Wrote {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
