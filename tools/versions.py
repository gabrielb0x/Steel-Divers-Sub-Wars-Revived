"""The versions of Steel Diver: Sub Wars that the tools tell apart: the game as sold (v0) and its update (v5200).

The update (title 0004000E000D7E00, title version 5200, revision 33269 against 31308 for the game) brings a new
executable, 16 more submarines, 3 more maps and recompiled scripts. Its RomFS only holds the files it changes or
adds: the game opens each file in it first ("rom2:/", the update's RomFS: path type 5 of the SelfNCCH archive),
then in its own RomFS ("rom:/") (v5200 0x00257ACC). On a 3DS, and in Azahar, the update replaces the game's code
as soon as it is installed on the SD card, and Azahar applies the game's mod folder (load/mods/00040000000D7E00/)
to it: exefs/code.ips to the update's code, romfs/ to both RomFS. A mod is therefore built for the version
installed in the emulator, from that version's files:

  extracted/           the game (make extract): code.bin, romfs/
  extracted/v5200/     the update: code.bin, romfs/ (its own files only), manifest.json
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ctr import _SIG_SIZES, UPDATE_TITLE_ID, tmd_title_version

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
BASE = "v0"                                     # the game without its update
LABELS = {"v0": "original game", "v5200": "update"}


def name(title_version: int) -> str:
    """The name of a version from its title version: v0, v5200."""
    return f"v{title_version}"


def label(version: str) -> str:
    """For the player: "v5200 (update)"."""
    return f"{version} ({LABELS.get(version, 'update')})"


def folder(version: str) -> Path:
    """Where `make extract` puts the files of a version."""
    return EXTRACTED if version == BASE else EXTRACTED / version


@dataclass(frozen=True)
class GameFiles:
    """The files a version of the game reads: its executable, and its RomFS folders in the order the game
    searches them (the update's own files, then the game's)."""
    version: str
    code_bin: Path
    layers: tuple[Path, ...]

    def path(self, file: str) -> Path:
        """The file the game opens (the last layer's path when no layer has it, for the messages)."""
        for layer in self.layers:
            if (layer / file).is_file():
                return layer / file
        return self.layers[-1] / file

    def exists(self, file: str) -> bool:
        return any((layer / file).is_file() for layer in self.layers)

    def glob(self, pattern: str) -> list[str]:
        """Files of every layer matching a pattern, relative to the RomFS root, sorted."""
        found = set()
        for layer in self.layers:
            if layer.is_dir():
                found.update(p.relative_to(layer).as_posix() for p in layer.glob(pattern) if p.is_file())
        return sorted(found)

    def ready(self) -> bool:
        return self.code_bin.is_file() and all(layer.is_dir() for layer in self.layers)


def game_files(version: str = BASE) -> GameFiles:
    base = EXTRACTED / "romfs"
    if version == BASE:
        return GameFiles(BASE, EXTRACTED / "code.bin", (base,))
    return GameFiles(version, folder(version) / "code.bin", (folder(version) / "romfs", base))


def extracted_versions() -> list[str]:
    """The versions whose files are extracted, the game's first."""
    found = [BASE] if game_files(BASE).ready() else []
    if EXTRACTED.is_dir():
        for path in sorted(EXTRACTED.glob("v*/manifest.json"), key=lambda p: int(p.parent.name[1:] or 0)
                           if p.parent.name[1:].isdigit() else 0):
            if path.parent.name[1:].isdigit() and game_files(path.parent.name).ready():
                found.append(path.parent.name)
    return found


# ---- the update in an emulator ------------------------------------------------------------------

def update_folders(base: Path) -> list[Path]:
    """content/ folders of the update in an emulator's virtual SD card (one per console id, usually one):
    sdmc/Nintendo 3DS/<id0>/<id1>/title/0004000e/000d7e00/content/."""
    high, low = f"{UPDATE_TITLE_ID:016x}"[:8], f"{UPDATE_TITLE_ID:016x}"[8:]
    return sorted((base / "sdmc" / "Nintendo 3DS").glob(f"*/*/title/{high}/{low}/content"))


def installed_update(base: Path) -> tuple[int, Path] | None:
    """(title version, .app of content 0) of the update installed in an emulator's user folder: the TMD
    with the smallest id (the installed one for Azahar, AM GetTitleMetadataPath) and its main content."""
    for content in update_folders(base):
        tmds = sorted(content.glob("*.tmd"))
        if not tmds:
            continue
        try:
            tmd = tmds[0].read_bytes()
            version = tmd_title_version(tmd)
            app = content / f"{main_content_id(tmd):08x}.app"
        except (OSError, struct.error, KeyError, ValueError):
            continue
        if app.is_file():
            return version, app
    return None


def main_content_id(tmd: bytes) -> int:
    """Id of content 0 (the program) in a TMD."""
    body = 4 + _SIG_SIZES[struct.unpack_from(">I", tmd, 0)[0]]
    count = struct.unpack_from(">H", tmd, body + 0x9E)[0]
    chunks = body + 0xC4 + 64 * 0x24
    for n in range(count):
        content_id, index = struct.unpack_from(">IH", tmd, chunks + n * 0x30)
        if index == 0:
            return content_id
    raise ValueError("no content 0 in the TMD")


def emulator_version(base: Path) -> str:
    """The version the game runs as in an emulator: its update when one is installed."""
    update = installed_update(base)
    return name(update[0]) if update else BASE
