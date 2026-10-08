#!/usr/bin/env python3
"""Characteristics of the submarines (bxml/pscope_plyNN_stats.bxml: 23, 39 with the update), to change them in a mod.

  subs.py show [sub]                 the characteristics (of the game, or of your file with --file)
  subs.py export [--force]           writes your file: every submarine with its values, commented
  subs.py set <sub> key=value...     changes values in your file (created from the game's values if needed)
  subs.py reset [sub]                puts the game's values back in your file
  subs.py check                      checks your file

<sub> is a number (1 to 23, 39 with the update) or a name ("Type VII"). Your file is submarines.toml in this
project's settings folder, submarines-v5200.toml for the update (its values differ: --file to use another): edit
it with any text editor, then build the "specs" mod:
  tools/mod.py build specs --install            (or with other mods: tools/mod.py build premium specs ...)
Only the values that differ from the game's are written. Online, the server is told that the build changes
the characteristics (flag "specs"): it treats it like the cheat mod (server/server.toml, cheats).

How the game uses them (scripts pscope_player and periscope_move): the five ratings (turn, speeds, armour,
dive) go from 1 to 10 and select a value in bxml/table_* (table_maxturn: 0.01 to 0.09 rad...), after adding
the crew bonuses and clamping to 1..10 (customUpdateSubBonusStats); torpedoReplenishTime is clamped to 1..30.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import azahar
import versions

ROOT = Path(__file__).resolve().parent.parent
SUBS = 23                       # in v0; count() for a version


@dataclass(frozen=True)
class Field:
    key: str
    kind: type                      # int or float
    low: float
    high: float
    help: str
    advanced: bool = False


FIELDS = [
    Field("maxTurn", int, 1, 10, "turning, rated 1 to 10 (bxml/table_maxturn)"),
    Field("aboveAccel", int, 1, 10, "surface speed, rated 1 to 10"),
    Field("belowAccel", int, 1, 10, "underwater speed, rated 1 to 10"),
    Field("damageRate", int, 1, 10, "armour, rated 1 to 10 (damage taken × 1.8 at 1, × 0.7 at 10)"),
    Field("diveRate", int, 1, 10, "dive and climb speed, rated 1 to 10"),
    Field("torpedoMax", int, 1, 99, "number of torpedoes"),
    Field("torpedoReplenishTime", int, 1, 30, "seconds to get the torpedoes back (the game caps it at 30)"),
    Field("torpedoFireInterval", int, 1, 600, "frames between two shots (30 frames = 1 second)"),
    Field("torpedoLevel", int, 1, 3, "torpedo model, 1 to 3 (surface_torpedo_lv01 to lv03)"),
    Field("crewCount", int, 1, 5, "crew places, 1 to 5"),
    Field("maskerUseAir", float, 0, 100, "air used by the masker (0: free)"),
    Field("torpedoAccel", float, 0, 10, "torpedo acceleration", True),
    Field("torpedoFireBrakeTime", int, 0, 600, "frames of braking after a shot", True),
    Field("torpedoFireBrakeRate", float, 0, 1, "braking after a shot (speed multiplied by this factor)", True),
    Field("diveMax", float, 0, 10, "top dive speed", True),
    Field("diveDrag", float, 0, 1, "vertical drag", True),
    Field("linDrag", float, 0, 1, "forward drag", True),
    Field("latDrag", float, 0, 1, "lateral drag", True),
    Field("waterline", float, -1000, 1000, "height of the waterline", True),
    Field("depthTest", float, -10000, 0, "test depth (historical submarines)", True),
    Field("depthMaxOp", float, -10000, 0, "maximum operating depth (historical)", True),
    Field("depthDesign", float, -10000, 0, "design depth (historical)", True),
    Field("depthCrush", float, -10000, 0, "crush depth (historical)", True),
    Field("depthLevelsEnabled", int, 0, 1, "depth limits on (historical, 0 or 1)", True),
]
BY_KEY = {f.key: f for f in FIELDS}
SHORT = {"maxTurn": "turn", "aboveAccel": "surface", "belowAccel": "under", "damageRate": "armour",
         "diveRate": "dive", "torpedoMax": "torp.", "torpedoReplenishTime": "reload",
         "torpedoFireInterval": "rate", "torpedoLevel": "type", "crewCount": "crew", "maskerUseAir": "masker"}


class SubsError(Exception):
    pass


def stats_file(n: int) -> str:
    return f"bxml/pscope_ply{n:02d}_stats.bxml"


def count(version: str = versions.BASE) -> int:
    """Number of submarines of a version of the game (its stats files)."""
    return len(versions.game_files(version).glob("bxml/pscope_ply[0-9][0-9]_stats.bxml")) or SUBS


def read_game_stats(n: int, version: str = versions.BASE) -> dict[str, str]:
    path = versions.game_files(version).path(stats_file(n))
    if not path.exists():
        raise SubsError(f"{stats_file(n)} introuvable : il faut d'abord extraire le jeu (make extract)")
    from bxml import Bxml
    return dict(ET.fromstring(Bxml(path.read_bytes()).to_xml()).attrib)


def game_values(version: str = versions.BASE) -> dict[int, dict[str, int | float]]:
    out = {}
    for n in range(1, count(version) + 1):
        raw = read_game_stats(n, version)
        out[n] = {f.key: f.kind(float(raw[f.key])) if f.kind is float else int(raw[f.key])
                  for f in FIELDS if f.key in raw}
    return out


def names(version: str = versions.BASE) -> dict[int, str]:
    from save import game_texts, sub_name
    texts = game_texts(version=version)
    return {n: sub_name(texts, n - 1, version) for n in range(1, count(version) + 1)}


def default_file(version: str = versions.BASE) -> Path:
    """The player's file: one per version of the game, whose values differ (the update rebalanced subs)."""
    if version == versions.BASE:
        return azahar.settings_file("submarines.toml", "sous-marins.toml")
    return azahar.settings_file(f"submarines-{version}.toml", f"sous-marins-{version}.toml")


def resolve(path: str | Path | None, version: str = versions.BASE) -> Path:
    return default_file(version) if path in (None, "", "auto") else Path(path).expanduser()


def which(text: str, known: dict[int, str]) -> int:
    if text.isdigit() and 1 <= int(text) <= len(known):
        return int(text)
    wanted = text.strip().lower()
    found = [n for n, name in known.items() if name.lower() == wanted] or \
            [n for n, name in known.items() if wanted in name.lower()]
    if len(found) != 1:
        raise SubsError(f"{text!r}: unknown or ambiguous submarine (a number from 1 to {len(known)}, or its name)")
    return found[0]


# ---- the player's file ------------------------------------------------------------------------------

def format_value(value: int | float) -> str:
    if isinstance(value, float):
        text = repr(round(value, 6))
        return text if "." in text or "e" in text else text + ".0"
    return str(value)


def write_file(path: Path, values: dict[int, dict[str, int | float]], known: dict[int, str]) -> None:
    lines = [
        "# Characteristics of the submarines of Steel Diver: Sub Wars (tools/subs.py).",
        "# Change the values, then build the mod:  tools/mod.py build specs --install",
        "# (with other mods:  tools/mod.py build premium specs --install). Only the values that differ from",
        "# the game's are applied; online, the server treats this mod as cheating.",
        "#",
    ]
    for f in FIELDS:
        if not f.advanced:
            lines.append(f"#   {f.key:22s} {f.help}")
    lines.append("#   (the next ones fine-tune the physics: change them with care)")
    for f in FIELDS:
        if f.advanced:
            lines.append(f"#   {f.key:22s} {f.help}")
    for n in sorted(values):
        lines += ["", f"[{n:02d}]  # {known.get(n, f'submarine {n}')}"]
        for f in FIELDS:
            if f.key in values[n]:
                lines.append(f"{f.key} = {format_value(values[n][f.key])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_file(path: Path, subs: int = SUBS) -> dict[int, dict[str, int | float]]:
    if not path.exists():
        raise SubsError(f"{path} does not exist: create it with \"tools/subs.py export\"")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SubsError(f"{path}: {e}") from e
    out: dict[int, dict[str, int | float]] = {}
    for section, values in data.items():
        if not (re.fullmatch(r"\d{1,2}", section) and 1 <= int(section) <= subs) or not isinstance(values, dict):
            raise SubsError(f"{path}: [{section}] is not a submarine ([01] to [{subs}])")
        n = int(section)
        out[n] = {}
        for key, value in values.items():
            out[n][key] = check_value(key, value, f"[{section}] {key}")
    return out


def check_value(key: str, value, where: str) -> int | float:
    field = BY_KEY.get(key)
    if field is None:
        raise SubsError(f"{where}: unknown characteristic (see \"tools/subs.py show\")")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubsError(f"{where} = {value!r}: a number is needed")
    if field.kind is int:
        if float(value) != int(value):
            raise SubsError(f"{where} = {value}: a whole number is needed")
        value = int(value)
    else:
        value = float(value)
    if not field.low <= value <= field.high:
        raise SubsError(f"{where} = {value}: out of bounds ({format_value(field.kind(field.low))} "
                        f"to {format_value(field.kind(field.high))})")
    return value


def changes(path: str | Path | None, version: str = versions.BASE) -> dict[str, dict[str, str]]:
    """The edits of a player's file, ready for the mod: stats file -> {attribute: text as in the XML}."""
    game = game_values(version)
    user = read_file(resolve(path, version), len(game))
    edits: dict[str, dict[str, str]] = {}
    for n, values in user.items():
        diff = {k: format_value(v) for k, v in values.items() if game[n].get(k) != v}
        if diff:
            edits[stats_file(n)] = diff
    return edits


# ---- commands ------------------------------------------------------------------------------------

def show(values: dict[int, dict[str, int | float]], known: dict[int, str], only: int | None,
         base: dict[int, dict[str, int | float]] | None = None) -> None:
    main = [f for f in FIELDS if not f.advanced]
    if only:
        print(f"n° {only} {known[only]}")
        for f in FIELDS:
            if f.key in values[only]:
                mark = ""
                if base and base[only].get(f.key) != values[only][f.key]:
                    mark = f"   (game: {format_value(base[only][f.key])})"
                print(f"  {f.key:22s} {format_value(values[only][f.key]):>8s}  {f.help}{mark}")
        return
    print(f"{'n°':>3s} {'name':14s} " + " ".join(f"{SHORT[f.key]:>8s}" for f in main))
    for n in sorted(values):
        cells = []
        for f in main:
            v = values[n].get(f.key)
            text = format_value(v) if v is not None else "-"
            if base and base[n].get(f.key) != v:
                text += "*"
            cells.append(f"{text:>8s}")
        print(f"{n:3d} {known[n][:14]:14s} " + " ".join(cells))
    if base:
        print("(*: differs from the game)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help=f"your file (default: {default_file()}, submarines-<version>.toml for the update)")
    ap.add_argument("--version", help="the version of the game: v0, v5200 (default: the one of the emulator)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show", help="the characteristics: of the game, or of your file with --file / --mine")
    p.add_argument("sub", nargs="?")
    p.add_argument("--mine", action="store_true", help="your file instead of the game's values")
    p = sub.add_parser("export", help="write your file with the game's values")
    p.add_argument("--force", action="store_true", help="replace an existing file")
    p = sub.add_parser("set", help="change values in your file")
    p.add_argument("sub")
    p.add_argument("values", nargs="+", metavar="key=value")
    p = sub.add_parser("reset", help="put the game's values back in your file")
    p.add_argument("sub", nargs="?")
    sub.add_parser("check", help="check your file and list what it changes")
    args = ap.parse_args()

    try:
        version = args.version or azahar.game_version()
        known = names(version)
        game = game_values(version)
        path = resolve(args.file, version)
        if args.command == "show":
            only = which(args.sub, known) if args.sub else None
            if args.mine or args.file:
                mine = read_file(path, len(game))
                merged = {n: {**game[n], **mine.get(n, {})} for n in game}
                show(merged, known, only, game)
            else:
                show(game, known, only)
        elif args.command == "export":
            if path.exists() and not args.force:
                raise SubsError(f"{path} already exists (--force to replace it)")
            write_file(path, game, known)
            print(f"[+] {path}\n    change it, then: tools/mod.py build specs --install")
        elif args.command in ("set", "reset"):
            current = {n: {**game[n], **v} for n, v in read_file(path, len(game)).items()} if path.exists() else {}
            values = {n: dict(current.get(n, game[n])) for n in game}
            if args.command == "set":
                n = which(args.sub, known)
                for item in args.values:
                    key, sep, text = item.partition("=")
                    if not sep:
                        raise SubsError(f"{item!r}: key=value is needed (torpedoMax=10, for example)")
                    try:
                        number = float(text) if "." in text else int(text)
                    except ValueError:
                        raise SubsError(f"{item!r}: {text!r} is not a number") from None
                    values[n][key.strip()] = check_value(key.strip(), number, f"[{n:02d}] {key.strip()}")
                print(f"[+] n° {n} {known[n]}: " + ", ".join(args.values))
            else:
                for n in ([which(args.sub, known)] if args.sub else game):
                    values[n] = dict(game[n])
                print("[+] the game's values put back" + (f" for {args.sub}" if args.sub else ""))
            write_file(path, values, known)
            print(f"    {path}; then: tools/mod.py build specs --install")
        elif args.command == "check":
            edits = changes(path, version)
            if not edits:
                print(f"[=] {path}: no difference with the game")
            for file, diff in edits.items():
                n = int(file[-13:-11])
                print(f"  n° {n:2d} {known[n]:14s} " + ", ".join(f"{k}={v}" for k, v in diff.items()))
    except SubsError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
