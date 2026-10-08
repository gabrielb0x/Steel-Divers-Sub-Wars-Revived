#!/usr/bin/env python3
"""Save editor of Steel Diver: Sub Wars: the "save" file of the game's save data, in the emulator.

  save.py show                       summary: submarine, unlocks, missions, online statistics
  save.py unlock [what...]           subs, patterns, crew, missions (cleared), gold (gold medals), all
  save.py premium-off                clears the premium flag (error 098-0101 when the full version is gone)
  save.py get <name>                 one value (save.sub.typenum, save.single.stage1.medal[1]...)
  save.py set <name> <value>         an integer, a float (best times) or, for an array, values separated by ","
  save.py list                       every value of the save
  save.py export <file.json>         the whole save as JSON, to edit by hand
  save.py import <file.json>
  save.py where                      the save files found

The save file is found in the emulator (Azahar, Lime3DS, Citra; --file to choose another). Close the game
before editing: it keeps its values in memory and would write them back. Every change first copies the
current file to the backups folder (see `where`).

Format (n_sysSaveDataLoad / n_sysSaveDataSave in source/amx/amxsys.cpp, SaveData::read, FlashMemory::
performWrite), little endian:
  u32 CRC-32 of everything after it (generateCRC: the CRC-32 of zlib)
  u32 version (27), u32 number of integer values, u32 number of arrays
  integers  name (NUL-terminated) + s32
  arrays    name (NUL-terminated) + u32 count + s32[count]
The values are the script globals whose name starts with "save" (sysSetGlobal / sysSetGlobalArray). Best
times are floats stored as their bits.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import azahar
import versions

ROOT = Path(__file__).resolve().parent.parent
VERSION = 27                   # sysSaveDataLoad("save", 27) in mode_title (save.inc), v0 and v5200
SUBS, PATTERNS, CREW = 23, 32, 32
STAGES, LEVELS = 7, 3          # single player: 7 areas of 3 missions
MEDAL_CLEARED, MEDAL_GOLD = 1, 2
# The unlock arrays of each version of the game (tools/versions.py). The update v5200 keeps save.sub.unlock[23] and
# holds its 39 submarines in save.sub.unlock2[36] (n° 1 to 36) and save.p3.sub.unlock[3] (37 to 39), and the crew
# of the submarines 37 to 39 in save.p3.sub.crew.unlock[8] (mode_title updateSubUnlock, medal.inc).
SUB_ARRAYS = {"v0": (("save.sub.unlock", 23),),
              "v5200": (("save.sub.unlock", 23), ("save.sub.unlock2", 36), ("save.p3.sub.unlock", 3))}
CREW_ARRAYS = {"v0": (("save.sub.crew.unlock", 32),),
               "v5200": (("save.sub.crew.unlock", 32), ("save.p3.sub.crew.unlock", 8))}
# Submarines sold apart (their prow in the add-on content): v0 19 to 23, v5200 also 27 to 36.
PAID_SUBS = {"v0": list(range(19, 24)), "v5200": list(range(19, 24)) + list(range(27, 37))}


def layout(version: str) -> str:
    """The save layout of a version: v0's, or the update's (later versions are taken as the update)."""
    return versions.BASE if version == versions.BASE else "v5200"


def sub_count(version: str = versions.BASE) -> int:
    return sum(size for name, size in SUB_ARRAYS[layout(version)] if name != "save.sub.unlock") or SUBS


class SaveError(Exception):
    pass


@dataclass
class SaveData:
    version: int = VERSION
    ints: dict[str, int] = field(default_factory=dict)
    arrays: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def parse(cls, data: bytes) -> "SaveData":
        if len(data) < 16:
            raise SaveError("file too short to be a save")
        crc, = struct.unpack_from("<I", data)
        if crc != zlib.crc32(data[4:]):
            raise SaveError("bad CRC: not a save of this game, or a damaged one")
        version, n_ints, n_arrays = struct.unpack_from("<III", data, 4)
        save, pos = cls(version), 16

        def name() -> str:
            nonlocal pos
            end = data.index(b"\0", pos)
            text = data[pos:end].decode("ascii")
            pos = end + 1
            return text
        try:
            for _ in range(n_ints):
                key = name()
                save.ints[key], = struct.unpack_from("<i", data, pos)
                pos += 4
            for _ in range(n_arrays):
                key = name()
                count, = struct.unpack_from("<I", data, pos)
                save.arrays[key] = list(struct.unpack_from(f"<{count}i", data, pos + 4))
                pos += 4 + 4 * count
        except (ValueError, struct.error) as e:
            raise SaveError(f"truncated save ({e})") from e
        if pos != len(data):
            raise SaveError(f"{len(data) - pos} unexpected byte(s) at the end")
        return save

    def to_bytes(self) -> bytes:
        body = bytearray(struct.pack("<III", self.version, len(self.ints), len(self.arrays)))
        for key, value in self.ints.items():
            body += key.encode("ascii") + b"\0" + struct.pack("<i", value)
        for key, values in self.arrays.items():
            body += key.encode("ascii") + b"\0" + struct.pack(f"<I{len(values)}i", len(values), *values)
        return struct.pack("<I", zlib.crc32(body)) + bytes(body)

    # -- values ----------------------------------------------------------------------------------

    def get(self, key: str) -> int | list[int] | None:
        return self.arrays[key] if key in self.arrays else self.ints.get(key)

    def set(self, key: str, value: int | list[int]) -> None:
        check_name(key)
        if isinstance(value, list):
            self.ints.pop(key, None)
            self.arrays[key] = [s32(v) for v in value]
        else:
            self.arrays.pop(key, None)
            self.ints[key] = s32(value)

    def array(self, key: str, size: int) -> list[int]:
        values = list(self.arrays.get(key, []))
        return values + [0] * (size - len(values))

    def medal(self, stage: int, level: int) -> int:
        return self.ints.get(f"save.single.stage{stage}.medal[{level}]", 0)

    def best_time(self, stage: int, level: int) -> float | None:
        bits = self.ints.get(f"save.single.stage{stage}.level{level}.time", 0)
        return struct.unpack("<f", struct.pack("<i", bits))[0] if bits else None

    def unlocked_subs(self, version: str = versions.BASE) -> list[bool]:
        """Unlocked state of each submarine (n° 1 is always available: mode_lobby, mode_customize)."""
        if layout(version) == versions.BASE:
            flags = self.array("save.sub.unlock", SUBS)[:SUBS]
        else:                                       # updateSubUnlock merges save.sub.unlock into unlock2
            old = self.array("save.sub.unlock", SUBS)
            flags = [a or (i < SUBS and old[i]) for i, a in enumerate(self.array("save.sub.unlock2", 36)[:36])]
            flags += self.array("save.p3.sub.unlock", 3)[:3]
        flags[0] = 1
        return [bool(f) for f in flags]

    # -- edits -----------------------------------------------------------------------------------

    def unlock_subs(self, version: str = versions.BASE) -> int:
        count = self.unlocked_subs(version).count(False)
        for name, size in SUB_ARRAYS[layout(version)]:
            self.set(name, [1] * size)
        return count

    def unlock_patterns(self, default_colours: dict[int, list[int]] | None = None) -> int:
        old = self.array("save.sub.pattern.unlock", PATTERNS)
        for pattern, colours in (default_colours or {}).items():
            if not old[pattern]:                # what the game writes when it unlocks one (func_110c4)
                for k, colour in enumerate(colours):
                    self.set(f"save.sub.pattern{pattern}.color{k}", colour)
        self.set("save.sub.pattern.unlock", [1] * PATTERNS)
        return old.count(0)

    def unlock_crew(self, version: str = versions.BASE) -> int:
        count = 0
        for name, size in CREW_ARRAYS[layout(version)]:
            count += self.array(name, size)[:size].count(0)
            self.set(name, [1] * size)
        return count

    def crew_unlocked(self, version: str = versions.BASE) -> tuple[int, int]:
        """(members unlocked, members) of the crew."""
        arrays = CREW_ARRAYS[layout(version)]
        return (sum(sum(1 for c in self.array(name, size)[:size] if c) for name, size in arrays),
                sum(size for _, size in arrays))

    def award_medals(self, medal: int) -> int:
        changed = 0
        for stage in range(1, STAGES + 1):
            for level in range(1, LEVELS + 1):
                if self.medal(stage, level) < medal:
                    self.set(f"save.single.stage{stage}.medal[{level}]", medal)
                    changed += 1
        return changed

    def premium_off(self) -> bool:
        was = bool(self.ints.get("save.sub.enlist"))
        if "save.sub.enlist" in self.ints:
            self.ints["save.sub.enlist"] = 0
        return was


def s32(value: int) -> int:
    value = int(value)
    if not -0x80000000 <= value <= 0xFFFFFFFF:
        raise SaveError(f"{value} ne tient pas sur 32 bits")
    return value - 0x100000000 if value > 0x7FFFFFFF else value


def check_name(key: str) -> None:
    if not key.startswith("save"):
        raise SaveError(f"{key}: the game only saves the values whose name starts with \"save\"")
    if len(key) > 63 or not key.isascii() or "\0" in key:
        raise SaveError(f"{key}: names are ASCII, 63 characters at most")


def parse_value(text: str) -> int | list[int]:
    """"12", "0x1F", "-3", "233.5" (a float, stored as its bits) or "1,0,1" (an array)."""
    def one(item: str) -> int:
        item = item.strip()
        try:
            return int(item, 0)
        except ValueError:
            return struct.unpack("<i", struct.pack("<f", float(item)))[0]
    try:
        return [one(t) for t in text.split(",")] if "," in text else one(text)
    except ValueError as e:
        raise SaveError(f"{text!r}: an integer, a decimal number or values separated by commas is needed") from e


# ---- game texts (optional: names of the submarines and crew) --------------------------------------

def game_texts(language: str = "EU_English", version: str = versions.BASE) -> dict[str, str]:
    """Texts of the player's game files (make extract), to show names; empty without them."""
    xml = ROOT / "extracted" / "xml" / "text" / f"{language}.xml"
    try:
        if version == versions.BASE and xml.exists():
            root = ET.parse(xml).getroot()
        else:
            from bxml import Bxml
            path = versions.game_files(version).path(f"text/{language}.bxml")
            root = ET.fromstring(Bxml(path.read_bytes()).to_xml())
    except (OSError, ET.ParseError, ValueError):
        return {}
    return {node.get("key"): node.get("text", "") for node in root.iter("string")}


def default_pattern_colours() -> dict[int, list[int]]:
    """bxml/sub_color_set: the colours given to pattern n (1..31) when it is unlocked (loadSubColours)."""
    path = ROOT / "extracted" / "romfs" / "bxml" / "sub_color_set.bxml"
    if not path.exists():
        return {}
    from bxml import Bxml
    node = ET.fromstring(Bxml(path.read_bytes()).to_xml())
    colours = {}
    for pattern in range(1, PATTERNS):
        value = node.get(f"pattern_{pattern - 1:02d}")
        if value:
            colours[pattern] = [int(v) for v in value.split()]
    return colours


def sub_name(texts: dict[str, str], index: int, version: str = versions.BASE) -> str:
    """Submarine of index 0..22, 0..38 in v5200 (save.sub.typenum is this index + 1). The update numbers the texts
    from 1 and adds width codes ("\\x0e(70)Garfish\\x0e(142.85…)") around the names."""
    key = f"sub_icon_name{index:02d}" if layout(version) == versions.BASE else f"sub_icon_name{index + 1:02d}"
    return re.sub(r"\\x0e\([^)]*\)|\x0e\([^)]*\)", "", texts.get(key) or "").strip() or f"submarine {index + 1}"


def save_version(path: Path, save: "SaveData | None" = None) -> str:
    """The version of the game a save file is for: that of the emulator it is in, else what it holds."""
    for base in azahar.azahar_dirs():
        try:
            path.resolve().relative_to(base.resolve())
        except ValueError:
            continue
        return versions.emulator_version(base)
    return "v5200" if save is not None and "save.sub.unlock2" in save.arrays else versions.BASE


# ---- files ----------------------------------------------------------------------------------------

def find_save(path: Path | None) -> Path:
    if path:
        if path.is_dir():
            path = path / "save"
        if not path.exists():
            raise SaveError(f"{path}: file not found")
        return path
    found = azahar.save_files()
    if not found:
        raise SaveError("no save of the game found in Azahar (start the game once, up to the title screen, "
                        "or give it with --file)")
    if len(found) > 1:
        raise SaveError("several saves found, choose one with --file:\n  " + "\n  ".join(map(str, found)))
    return found[0]


def backup(path: Path) -> Path:
    folder = azahar.settings_file("save-backups", "sauvegardes")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while (folder / (stamp + (f"-{n}" if n else ""))).exists():
        n += 1
    dest = folder / (stamp + (f"-{n}" if n else "")) / "save"
    dest.parent.mkdir(parents=True)
    shutil.copy2(path, dest)
    return dest


def write(path: Path, save: SaveData) -> None:
    copy = backup(path)
    data = save.to_bytes()
    SaveData.parse(data)                         # never write something the game could not read back
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    print(f"[+] save written: {path}\n    copy of the old one: {copy}")


# ---- commands ------------------------------------------------------------------------------------

def show(save: SaveData, version: str = versions.BASE) -> None:
    texts = game_texts(version=version)
    typenum = save.ints.get("save.sub.typenum", 1)
    name = bytes(v & 0xFF for v in save.arrays.get("save.sub.filteredname", [])).split(b"\0")[0]
    print(f"Player: {name.decode('utf-8', 'replace') or '?'}    save version: {save.version}    "
          f"game: {versions.label(version)}")
    print(f"Submarine chosen: n° {typenum} ({sub_name(texts, typenum - 1, version)})")
    unlocked = save.unlocked_subs(version)
    paid = PAID_SUBS[layout(version)]
    print(f"Submarines unlocked: {sum(unlocked)}/{len(unlocked)} "
          f"(n° {', '.join(map(str, paid))} also depend on the DLC or the premium mod)")
    for i, flag in enumerate(unlocked):
        print(f"  {'x' if flag else ' '} {i + 1:2d} {sub_name(texts, i, version)}")
    patterns = save.array("save.sub.pattern.unlock", PATTERNS)
    patterns[0] = 1
    crew, crew_total = save.crew_unlocked(version)
    print(f"Patterns unlocked: {sum(1 for p in patterns if p)}/{PATTERNS}    crew: {crew}/{crew_total}")
    print("Missions (medal: - none, o completed, * gold; best time):")
    for stage in range(1, STAGES + 1):
        cells = []
        for level in range(1, LEVELS + 1):
            medal = "-o*"[min(save.medal(stage, level), 2)]
            t = save.best_time(stage, level)
            cells.append(f"{stage}-{level} {medal} {f'{t:6.1f} s' if t else '       -'}")
        print("  " + "    ".join(cells))
    gold = sum(save.medal(s, l) >= MEDAL_GOLD for s in range(1, STAGES + 1) for l in range(1, LEVELS + 1))
    print(f"  gold medals: {gold}/{STAGES * LEVELS}")
    stats = {k: save.ints.get(f"save.multi.{k}", 0) for k in
             ("games", "wins", "losses", "ties", "quits", "points", "kills", "killed", "hits", "shots")}
    print("Online: {games} battles, {wins} wins, {losses} losses, {ties} draws, {quits} quits; "
          "{points} points; {kills} sunk, sunk {killed} times; {hits} hits for {shots} shots".format(**stats))
    if save.ints.get("save.sub.enlist"):
        print("Premium flag: yes (without the full version or the premium mod, Start shows error 098-0101;"
              " \"save.py premium-off\" clears it)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, help="the save file (default: found in the emulator)")
    ap.add_argument("--version", help="the version of the game the save is for: v0, v5200 (default: that of the "
                                      "emulator it is in)")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="summary of the save")
    p = sub.add_parser("unlock", help="unlock: subs, patterns, crew, missions, gold, all (default: all)")
    p.add_argument("what", nargs="*", choices=["subs", "patterns", "crew", "missions", "gold", "all"],
                   default=["all"])
    sub.add_parser("premium-off", help="clear the premium flag of the save")
    p = sub.add_parser("get", help="print a value")
    p.add_argument("name")
    p = sub.add_parser("set", help="change a value")
    p.add_argument("name")
    p.add_argument("value")
    sub.add_parser("list", help="every value of the save")
    p = sub.add_parser("export", help="write the save as JSON")
    p.add_argument("json", type=Path)
    p = sub.add_parser("import", help="replace the save by a JSON file (from export)")
    p.add_argument("json", type=Path)
    sub.add_parser("where", help="save files found, and the backups folder")
    args = ap.parse_args()

    try:
        if args.command == "where":
            for path in azahar.save_files():
                print(path)
            print(f"backups: {azahar.settings_file('save-backups', 'sauvegardes')}")
            return
        path = find_save(args.file)
        save = SaveData.parse(path.read_bytes())
        game = args.version or save_version(path, save)
        if save.version != VERSION:
            print(f"[!] version {save.version}: the game expects {VERSION} and would ignore this save")
        if args.command == "show":
            print(f"{path}\n")
            show(save, game)
        elif args.command == "list":
            for key, value in sorted(save.ints.items()):
                print(f"{key} = {value}")
            for key, values in sorted(save.arrays.items()):
                print(f"{key}[{len(values)}] = {','.join(map(str, values))}")
        elif args.command == "get":
            value = save.get(args.name)
            if value is None:
                raise SaveError(f"{args.name}: not in the save (the game reads it as 0)")
            print(",".join(map(str, value)) if isinstance(value, list) else value)
        elif args.command == "export":
            args.json.write_text(json.dumps({"version": save.version, "ints": save.ints, "arrays": save.arrays},
                                            indent=1) + "\n", encoding="utf-8")
            print(f"[+] {args.json}")
        else:
            if args.command == "set":
                save.set(args.name, parse_value(args.value))
            elif args.command == "import":
                data = json.loads(args.json.read_text(encoding="utf-8"))
                save = SaveData(int(data.get("version", VERSION)))
                for key, value in data.get("ints", {}).items():
                    save.set(key, int(value))
                for key, values in data.get("arrays", {}).items():
                    save.set(key, [int(v) for v in values])
            elif args.command == "premium-off":
                if not save.premium_off():
                    print("[=] no premium flag in this save: nothing to do")
                    return
            elif args.command == "unlock":
                what = set(args.what)
                if "all" in what:
                    what = {"subs", "patterns", "crew", "missions"}
                if "subs" in what:
                    print(f"[+] submarines: {save.unlock_subs(game)} unlocked")
                if "patterns" in what:
                    colours = default_pattern_colours()
                    print(f"[+] patterns: {save.unlock_patterns(colours)} unlocked"
                          + ("" if colours else " (default colours unknown without the game's files)"))
                if "crew" in what:
                    print(f"[+] crew: {save.unlock_crew(game)} unlocked")
                if "gold" in what:
                    print(f"[+] missions: {save.award_medals(MEDAL_GOLD)} gold medal(s)")
                elif "missions" in what:
                    print(f"[+] missions: {save.award_medals(MEDAL_CLEARED)} mission(s) marked completed")
                print(f"    (submarines 2 to {sub_count(game)} need the full version: premium mod)")
            write(path, save)
            print("    Close the game in the emulator before starting it again: it would write the old save back.")
    except SaveError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
