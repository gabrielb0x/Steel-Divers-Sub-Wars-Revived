#!/usr/bin/env python3
"""The game and its mods in the Azahar emulator.

  prepare     cia/*.cia -> build/azahar/SteelDiverSubWars_original.cia and .cxi, from the player's dump.
              The eShop CIA also holds the electronic manual (content 1), still NCCH-encrypted, and
              Azahar then refuses the whole installation ("Blocked unauthorized encrypted CIA
              installation"). The game itself (content 0) is not encrypted: the CIA written here
              holds it alone (TMD reduced to one content, its hashes recomputed), and the .cxi can
              also be opened directly (File > Load File). With the decrypted CIA of the update in
              cia/, also SteelDiverSubWars_update_v5200.cia, the update alone (Install CIA).
  patched-cxi a copy of the game's CXI with a mod's code patch applied (tools/mod.py build --cxi):
              SteelDiverSubWars_<mod>.cxi, to keep the original game and the modded one side by side
  install     copies a mod built by tools/mod.py into Azahar's load/mods/<title id>/
  uninstall   removes the mod files of the game from Azahar
  install-update    installs the update (its decrypted CIA) on the emulators' SD card, as Azahar's
                    File > Install CIA does: the game then runs as v5200 (tools/versions.py)
  uninstall-update  removes it: the game runs as v0 again
  where       prints the Azahar folders found, the version of the game they run and the mods installed

Nothing is sent anywhere: the files are written on this computer, from the player's own dump.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
from pathlib import Path

import versions
from ctr import CIA, UPDATE_TITLE_ID, _SIG_SIZES, find_game_cia

ROOT = Path(__file__).resolve().parent.parent
TITLE_ID = "00040000000D7E00"   # Steel Diver: Sub Wars, Europe
MARKER = "sdsw.json"            # in a built mod folder: the version of the game and the mods it holds
TMD_HEADER, INFO_RECORDS, CHUNK = 0xC4, 64 * 0x24, 0x30


# The 3DS emulators that load mods from load/mods/<title id>/ (exefs/code.ips, romfs/): Azahar and the Citra
# family it comes from, with their user folder on Linux (XDG, Flatpak), Windows (%APPDATA%) and macOS.
# (name, Linux/Flatpak folder name, Windows/macOS folder name, Flatpak ids)
EMULATORS = (
    ("Azahar", "azahar-emu", "Azahar", ("org.azahar_emu.Azahar",)),
    ("Lime3DS", "lime3ds-emu", "Lime3DS", ("io.github.lime3ds.Lime3DS",)),
    ("Citra", "citra-emu", "Citra", ("org.citra_emu.citra", "org.citra_emu.Citra")),
    ("Borked3DS", "borked3ds-emu", "Borked3DS", ("io.github.borked3ds.Borked3DS",)),
)


def emulator_dirs() -> list[tuple[str, Path]]:
    """(emulator, user folder) of every emulator found: AZAHAR_DIR first (a portable install: the "user"
    folder next to the emulator), then the usual places of Azahar, Lime3DS, Citra and Borked3DS."""
    candidates: list[tuple[str, Path]] = []
    for variable in ("AZAHAR_DIR", "SUBWARS_EMULATOR_DIR"):
        if os.environ.get(variable):
            candidates.append(("Émulateur (" + variable + ")", Path(os.environ[variable])))
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    appdata = Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else None
    mac = home / "Library/Application Support"
    flatpaks = home / ".var/app"
    for name, folder, windows, ids in EMULATORS:
        candidates += [(name + " (Flatpak)", flatpaks / app / "data" / folder) for app in ids]
        if flatpaks.is_dir():                                   # another Flatpak id of the same emulator
            candidates += [(name + " (Flatpak)", p) for p in sorted(flatpaks.glob(f"*/data/{folder}"))]
        candidates += [(name, data / folder), (name, mac / windows)]
        if appdata:
            candidates.append((name, appdata / windows))
    found: list[tuple[str, Path]] = []
    for name, path in candidates:
        if path.is_dir() and all(path != p for _, p in found):
            found.append((name, path))
    return found


def azahar_dirs() -> list[Path]:
    """User folders of the emulators found (emulator_dirs), Azahar first."""
    return [path for _, path in emulator_dirs()]


def config_dir() -> Path:
    """Folder of this project's settings on the player's computer (identities, save backups)."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "sub-wars-open-sourced"
    old = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sub-wars-open-sourced"
    if sys.platform == "darwin" and not old.exists():
        return Path.home() / "Library/Application Support/sub-wars-open-sourced"
    return old


def save_files(bases: list[Path] | None = None) -> list[Path]:
    """The game's save files ("save" of its save data archive) in the emulators' virtual SD cards:
    sdmc/Nintendo 3DS/<id0>/<id1>/title/00040000/000d7e00/data/00000001/save."""
    high, low = TITLE_ID[:8].lower(), TITLE_ID[8:].lower()
    found = []
    for base in bases if bases is not None else azahar_dirs():
        found += sorted((base / "sdmc" / "Nintendo 3DS").glob(f"*/*/title/{high}/{low}/data/*/save"))
    return found


def mods_dir(base: Path | None) -> Path:
    if base is None:
        found = azahar_dirs()
        if not found:
            sys.exit("No emulator folder found (Azahar, Lime3DS, Citra, Borked3DS): set AZAHAR_DIR or pass "
                     "--azahar-dir.")
        base = found[0]
    return base / "load" / "mods" / TITLE_ID


def mods_dirs(base: Path | None) -> list[Path]:
    """The mod folders of the game: the one of base, or of every emulator found."""
    if base is not None:
        return [base / "load" / "mods" / TITLE_ID]
    found = azahar_dirs()
    if not found:
        sys.exit("No emulator folder found (Azahar, Lime3DS, Citra, Borked3DS): set AZAHAR_DIR or pass "
                 "--azahar-dir.")
    return [d / "load" / "mods" / TITLE_ID for d in found]


def install(built: Path, base: Path | None = None, only: list[Path] | None = None) -> list[Path]:
    """Copies a mod built by tools/mod.py into the emulators: all of them, base only, or those of only (the
    emulators that run the version of the game the mod was built for)."""
    src = built / TITLE_ID if (built / TITLE_ID).is_dir() else built
    done = []
    targets = [b / "load" / "mods" / TITLE_ID for b in only] if only is not None else mods_dirs(base)
    for dest in targets:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        done.append(dest)
    return done


def installed_mods(base: Path) -> dict | None:
    """What tools/mod.py installed in an emulator: {"version", "mods"} (its marker), {} for a mod folder
    without marker (installed before 2026-10-06, or by hand), None without mod folder."""
    folder = base / "load" / "mods" / TITLE_ID
    if not folder.is_dir():
        return None
    try:
        return json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---- the update on the emulator's SD card -------------------------------------------------------

def sd_title_root(base: Path) -> Path:
    """sdmc/Nintendo 3DS/<id0>/<id1>/title/ of an emulator: the existing one, else Azahar's (zero ids)."""
    found = sorted((base / "sdmc" / "Nintendo 3DS").glob("*/*/title"))
    return found[0] if found else base / "sdmc" / "Nintendo 3DS" / ("0" * 32) / ("0" * 32) / "title"


def install_update(cia_path: Path, base: Path) -> Path:
    """Installs the update on an emulator's SD card as Azahar's Install CIA does (AM CIAFile): the TMD as
    content/00000000.tmd and each content as content/<id>.app. Only content 0, the program, is kept (the
    manual of an eShop CIA may still be encrypted, which Azahar refuses)."""
    with cia_path.open("rb") as f:
        cia = CIA.parse(f)
        if cia.title_id != UPDATE_TITLE_ID:
            raise ValueError(f"{cia_path.name} is not the update ({UPDATE_TITLE_ID:016X})")
        chunk, offset = next(cia.content_offsets())
        if chunk.encrypted:
            raise ValueError(f"{cia_path.name} : la mise à jour est chiffrée, déchiffrez-la d'abord")
        f.seek(offset + 0x100)
        if f.read(4) != b"NCCH":
            raise ValueError(f"{cia_path.name}: content 0 is not a NCCH")
        f.seek(offset + 0x18F)
        if not f.read(1)[0] & 0x04:
            raise ValueError(f"{cia_path.name} : la mise à jour est chiffrée (NCCH), déchiffrez-la d'abord")
        f.seek(cia.tmd_offset)
        tmd = one_content_tmd(bytearray(f.read(cia.tmd_size)), len(cia.contents))
        high, low = f"{UPDATE_TITLE_ID:016x}"[:8], f"{UPDATE_TITLE_ID:016x}"[8:]
        content = sd_title_root(base) / high / low / "content"
        if content.parent.exists():
            shutil.rmtree(content.parent)
        content.mkdir(parents=True)
        (content / "00000000.tmd").write_bytes(tmd)
        f.seek(offset)
        with (content / f"{chunk.id:08x}.app").open("wb") as out:
            copy_range(f, out, chunk.size)
    return content


def uninstall_update(base: Path) -> list[Path]:
    removed = []
    for content in versions.update_folders(base):
        shutil.rmtree(content.parent)
        removed.append(content.parent)
    return removed


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

        new_tmd = one_content_tmd(tmd, len(cia.contents))

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


def one_content_tmd(tmd: bytearray, count: int) -> bytes:
    """A TMD reduced to content 0: one content chunk record, info record 0 covering it, hashes recomputed.
    The signature no longer matches, which the emulator does not check."""
    body = 4 + _SIG_SIZES[struct.unpack_from(">I", tmd, 0)[0]]
    chunks = body + TMD_HEADER + INFO_RECORDS
    chunk0 = next(tmd[chunks + n * CHUNK:chunks + (n + 1) * CHUNK] for n in range(count)
                  if struct.unpack_from(">H", tmd, chunks + n * CHUNK + 4)[0] == 0)
    info = bytearray(INFO_RECORDS)
    struct.pack_into(">HH", info, 0, 0, 1)
    info[4:0x24] = hashlib.sha256(chunk0).digest()
    new_tmd = bytearray(tmd[:body + TMD_HEADER])
    struct.pack_into(">H", new_tmd, body + 0x9E, 1)
    new_tmd[body + 0xA4:body + 0xC4] = hashlib.sha256(info).digest()
    return bytes(new_tmd + info + chunk0)


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


# ---- patched CXI -----------------------------------------------------------------------------

MEDIA_UNIT = 0x200
GAME_FILES = {
    "SteelDiverSubWars_original.cia": "le jeu d'origine, sans le manuel chiffré : Azahar > Fichier > Installer un CIA",
    "SteelDiverSubWars_original.cxi": "le même jeu, à ouvrir sans l'installer : Azahar > Fichier > Charger un fichier",
}
UPDATE_FILE = "SteelDiverSubWars_update_{version}.cia"


def apply_ips(code: bytearray, patch: bytes) -> None:
    if patch[:5] != b"PATCH":
        raise ValueError("not an IPS patch")
    pos = 5
    while patch[pos:pos + 3] != b"EOF":
        offset = int.from_bytes(patch[pos:pos + 3], "big")
        size = int.from_bytes(patch[pos + 3:pos + 5], "big")
        pos += 5
        if size == 0:                                   # RLE record
            count = int.from_bytes(patch[pos:pos + 2], "big")
            code[offset:offset + count] = patch[pos + 2:pos + 3] * count
            pos += 3
        else:
            code[offset:offset + size] = patch[pos:pos + size]
            pos += size


def patched_cxi(src: Path, code: bytes, dest: Path) -> None:
    """The game's NCCH with an uncompressed, patched .code: the exheader's "compressed" flag is cleared,
    the ExeFS rebuilt and the RomFS moved after it. Azahar checks neither hashes nor signatures, but they
    are recomputed anyway (exheader hash, ExeFS hashes and superblock hash)."""
    with src.open("rb") as f:
        cia = CIA.parse(f)
        game, base = next((c, o) for c, o in cia.content_offsets() if c.index == 0)
        f.seek(base)
        header = bytearray(f.read(0x200))
        if header[0x100:0x104] != b"NCCH":
            sys.exit("Content 0 is not an NCCH.")
        unit = MEDIA_UNIT << header[0x18E]
        exefs_off, exefs_size = struct.unpack_from("<II", header, 0x1A0)
        romfs_off, romfs_size = struct.unpack_from("<II", header, 0x1B0)
        f.seek(base)
        prefix = bytearray(f.read(exefs_off * unit))
        f.seek(base + exefs_off * unit)
        exefs = f.read(exefs_size * unit)

        files = []
        for n in range(10):
            name, off, size = struct.unpack_from("<8sII", exefs, n * 16)
            if name.rstrip(b"\0"):
                data = code if name.rstrip(b"\0") == b".code" else exefs[0x200 + off:0x200 + off + size]
                files.append((name, data))
        table = bytearray(0x200)
        body = bytearray()
        for n, (name, data) in enumerate(files):
            struct.pack_into("<8sII", table, n * 16, name, len(body), len(data))
            table[0x1E0 - n * 0x20:0x200 - n * 0x20] = hashlib.sha256(data).digest()
            body += data + bytes(align(len(data), 0x200) - len(data))
        new_exefs = bytes(table + body)
        new_exefs += bytes(align(len(new_exefs), unit) - len(new_exefs))

        prefix[0x200 + 0xD] &= ~1                                      # code not compressed
        prefix[0x160:0x180] = hashlib.sha256(prefix[0x200:0x600]).digest()
        new_romfs_off = align(exefs_off + len(new_exefs) // unit, 0x1000 // unit)
        struct.pack_into("<III", prefix, 0x1A0, exefs_off, len(new_exefs) // unit, 0x200 // unit)
        struct.pack_into("<I", prefix, 0x1B0, new_romfs_off if romfs_size else 0)
        prefix[0x1C0:0x1E0] = hashlib.sha256(new_exefs[:0x200]).digest()
        struct.pack_into("<I", prefix, 0x104, (new_romfs_off + romfs_size) if romfs_size else
                         exefs_off + len(new_exefs) // unit)

        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            out.write(prefix)
            out.write(new_exefs)
            if romfs_size:
                out.write(bytes(new_romfs_off * unit - out.tell()))
                f.seek(base + romfs_off * unit)
                copy_range(f, out, romfs_size * unit)


def write_readme(folder: Path) -> None:
    """build/azahar/LISEZMOI.txt: what each file of the folder is."""
    lines = ["Fichiers du jeu préparés pour Azahar, à partir de votre propre dump (cia/).",
             "Ne les partagez pas : ce sont des copies du jeu.", ""]
    for path in sorted(folder.iterdir()):
        if path.suffix not in (".cia", ".cxi"):
            continue
        what = GAME_FILES.get(path.name)
        if what is None and path.stem.startswith("SteelDiverSubWars_update_"):
            what = (f"la mise à jour {path.stem.rsplit('_', 1)[1]}, sans son manuel : Azahar > Fichier > Installer "
                    "un CIA (le jeu installé ou ouvert prend alors cette version ; mods à reconstruire)")
        elif what is None and path.stem.startswith("SteelDiverSubWars_"):
            mod, _, server = path.stem.removeprefix("SteelDiverSubWars_").partition("_")
            what = (f"le jeu avec le mod « {mod} » déjà appliqué" + (f" (serveur {server})" if server else "")
                    + " : tools/mod.py build --cxi ; à ouvrir sans l'installer (Azahar > Fichier > Charger un fichier)")
        if what is None:
            continue
        lines.append(f"{path.name}\n    {what}")
    (folder / "LISEZMOI.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare(src: Path, out: Path, update: Path | None = None) -> list[Path]:
    """build/azahar/: the game alone as a CIA and a CXI, and the update alone as a CIA when given."""
    for old in ("SteelDiverSubWars.cia", "SteelDiverSubWars.cxi"):      # names before 2026-10
        (out / old).unlink(missing_ok=True)
    written = [out / "SteelDiverSubWars_original.cia", out / "SteelDiverSubWars_original.cxi"]
    game_only_cia(src, written[0])
    game_cxi(src, written[1])
    if update is not None:
        with update.open("rb") as f:
            version = versions.name(CIA.parse(f).title_version)
        written.append(out / UPDATE_FILE.format(version=version))
        game_only_cia(update, written[-1])
    write_readme(out)
    return written


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
    p = sub.add_parser("install-update", help="install the update on the emulators' SD card")
    p.add_argument("cia", nargs="?", type=Path, help="its decrypted CIA (default: found in cia/)")
    sub.add_parser("uninstall-update", help="remove the update from the emulators' SD card")
    sub.add_parser("where", help="print Azahar's folders")
    args = ap.parse_args()

    if args.command == "prepare":
        src = args.cia or find_game_cia(ROOT / "cia")
        if src is None:
            sys.exit(f"No CIA of the game ({TITLE_ID}) in cia/.")
        update = find_game_cia(ROOT / "cia", UPDATE_TITLE_ID)
        if update is not None:
            with update.open("rb") as f:
                if next(CIA.parse(f).content_offsets())[0].encrypted:
                    print(f"[!] {update.name}: the update is encrypted, left aside (decrypt it first)")
                    update = None
        for path in prepare(src, args.out, update):
            how = "or Azahar > File > Load File, without installing" if path.suffix == ".cxi" else \
                "Azahar > File > Install CIA"
            print(f"[+] {path}: {how}")
    elif args.command == "install":
        for dest in install(args.mod, args.azahar_dir):
            print(f"[+] installed into {dest}")
    elif args.command == "uninstall":
        for dest in mods_dirs(args.azahar_dir):
            if dest.exists():
                shutil.rmtree(dest)
                print(f"[+] removed {dest}")
    elif args.command == "install-update":
        import extract_cia
        src = args.cia or extract_cia.find_update()
        if src is None or src.suffix.lower() != ".cia":
            sys.exit("No decrypted CIA of the update (0004000E000D7E00) in cia/: pass its path.")
        for base in [args.azahar_dir] if args.azahar_dir else azahar_dirs():
            try:
                print(f"[+] installed into {install_update(src, base)}")
            except ValueError as e:
                sys.exit(f"[!] {e}")
        print("[!] the game now runs as this version: rebuild and reinstall the mods (tools/mod.py build ... "
              "--install)")
    elif args.command == "uninstall-update":
        for base in [args.azahar_dir] if args.azahar_dir else azahar_dirs():
            for path in uninstall_update(base):
                print(f"[+] removed {path}")
    else:
        found = emulator_dirs()
        for name, d in found:
            mods = installed_mods(d)
            built = f" (built for {mods['version']}: {' + '.join(mods.get('mods', []))})" if mods else ""
            print(f"{name}: {d}\n  game: {versions.label(versions.emulator_version(d))}\n"
                  f"  mods: {d / 'load' / 'mods' / TITLE_ID}" + (built if mods is not None else " (none)"))
        if not found:
            print("No emulator folder found (Azahar, Lime3DS, Citra, Borked3DS): set AZAHAR_DIR.")


if __name__ == "__main__":
    main()
