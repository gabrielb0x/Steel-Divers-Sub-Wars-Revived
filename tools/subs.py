#!/usr/bin/env python3
"""Characteristics of the 23 submarines (bxml/pscope_plyNN_stats.bxml), to change them in a mod.

  subs.py show [sub]                 the characteristics (of the game, or of your file with --file)
  subs.py export [--force]           writes your file: every submarine with its values, commented
  subs.py set <sub> key=value...     changes values in your file (created from the game's values if needed)
  subs.py reset [sub]                puts the game's values back in your file
  subs.py check                      checks your file

<sub> is a number (1 to 23) or a name ("Type VII"). Your file is sous-marins.toml in this project's settings
folder (--file to use another): edit it with any text editor, then build the "specs" mod:
  tools/mod.py build specs --install            (or with other mods: tools/mod.py build premium specs ...)
Only the values that differ from the game's are written. Online, the server is told that the build changes
the characteristics (flag "specs"): it treats it like the cheat mod (server/serveur.toml, cheats).

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

ROOT = Path(__file__).resolve().parent.parent
ROMFS = ROOT / "extracted" / "romfs"
SUBS = 23


@dataclass(frozen=True)
class Field:
    key: str
    kind: type                      # int or float
    low: float
    high: float
    help: str
    advanced: bool = False


FIELDS = [
    Field("maxTurn", int, 1, 10, "virage, note de 1 à 10 (bxml/table_maxturn)"),
    Field("aboveAccel", int, 1, 10, "vitesse en surface, note de 1 à 10"),
    Field("belowAccel", int, 1, 10, "vitesse en plongée, note de 1 à 10"),
    Field("damageRate", int, 1, 10, "résistance, note de 1 à 10 (dégâts reçus × 1,8 à la note 1, × 0,7 à la note 10)"),
    Field("diveRate", int, 1, 10, "vitesse de plongée et de remontée, note de 1 à 10"),
    Field("torpedoMax", int, 1, 99, "nombre de torpilles"),
    Field("torpedoReplenishTime", int, 1, 30, "secondes pour récupérer une torpille (le jeu plafonne à 30)"),
    Field("torpedoFireInterval", int, 1, 600, "images entre deux tirs (30 images = 1 seconde)"),
    Field("torpedoLevel", int, 1, 3, "modèle de torpille, de 1 à 3 (surface_torpedo_lv01 à lv03)"),
    Field("crewCount", int, 1, 5, "places d'équipage, de 1 à 5"),
    Field("maskerUseAir", float, 0, 100, "air consommé par le masqueur (0 : gratuit)"),
    Field("torpedoAccel", float, 0, 10, "accélération des torpilles", True),
    Field("torpedoFireBrakeTime", int, 0, 600, "images de freinage après un tir", True),
    Field("torpedoFireBrakeRate", float, 0, 1, "freinage après un tir (vitesse multipliée par ce facteur)", True),
    Field("diveMax", float, 0, 10, "vitesse de plongée maximale", True),
    Field("diveDrag", float, 0, 1, "frottement vertical", True),
    Field("linDrag", float, 0, 1, "frottement vers l'avant", True),
    Field("latDrag", float, 0, 1, "frottement latéral", True),
    Field("waterline", float, -1000, 1000, "hauteur de la ligne de flottaison", True),
    Field("depthTest", float, -10000, 0, "profondeur d'essai (sous-marins historiques)", True),
    Field("depthMaxOp", float, -10000, 0, "profondeur maximale d'utilisation (historiques)", True),
    Field("depthDesign", float, -10000, 0, "profondeur de conception (historiques)", True),
    Field("depthCrush", float, -10000, 0, "profondeur d'écrasement (historiques)", True),
    Field("depthLevelsEnabled", int, 0, 1, "limites de profondeur actives (historiques, 0 ou 1)", True),
]
BY_KEY = {f.key: f for f in FIELDS}
SHORT = {"maxTurn": "virage", "aboveAccel": "surface", "belowAccel": "plongée", "damageRate": "résist.",
         "diveRate": "plong./rem.", "torpedoMax": "torp.", "torpedoReplenishTime": "recharge",
         "torpedoFireInterval": "cadence", "torpedoLevel": "type", "crewCount": "équip.", "maskerUseAir": "masqueur"}


class SubsError(Exception):
    pass


def stats_file(n: int) -> str:
    return f"bxml/pscope_ply{n:02d}_stats.bxml"


def read_game_stats(n: int) -> dict[str, str]:
    path = ROMFS / stats_file(n)
    if not path.exists():
        raise SubsError(f"{stats_file(n)} introuvable : il faut d'abord extraire le jeu (make extract)")
    from bxml import Bxml
    return dict(ET.fromstring(Bxml(path.read_bytes()).to_xml()).attrib)


def game_values() -> dict[int, dict[str, int | float]]:
    out = {}
    for n in range(1, SUBS + 1):
        raw = read_game_stats(n)
        out[n] = {f.key: f.kind(float(raw[f.key])) if f.kind is float else int(raw[f.key])
                  for f in FIELDS if f.key in raw}
    return out


def names() -> dict[int, str]:
    from save import game_texts
    texts = game_texts()
    return {n: texts.get(f"sub_icon_name{n - 1:02d}") or f"sous-marin {n}" for n in range(1, SUBS + 1)}


def default_file() -> Path:
    return azahar.config_dir() / "sous-marins.toml"


def resolve(path: str | Path | None) -> Path:
    return default_file() if path in (None, "", "auto") else Path(path).expanduser()


def which(text: str, known: dict[int, str]) -> int:
    if text.isdigit() and 1 <= int(text) <= SUBS:
        return int(text)
    wanted = text.strip().lower()
    found = [n for n, name in known.items() if name.lower() == wanted] or \
            [n for n, name in known.items() if wanted in name.lower()]
    if len(found) != 1:
        raise SubsError(f"{text!r} : sous-marin inconnu ou ambigu (numéro de 1 à {SUBS}, ou son nom)")
    return found[0]


# ---- the player's file ------------------------------------------------------------------------------

def format_value(value: int | float) -> str:
    if isinstance(value, float):
        text = repr(round(value, 6))
        return text if "." in text or "e" in text else text + ".0"
    return str(value)


def write_file(path: Path, values: dict[int, dict[str, int | float]], known: dict[int, str]) -> None:
    lines = [
        "# Caractéristiques des sous-marins de Steel Diver: Sub Wars (tools/subs.py).",
        "# Modifiez les valeurs, puis construisez le mod :  tools/mod.py build specs --install",
        "# (avec d'autres mods :  tools/mod.py build premium specs --install). Seules les valeurs différentes",
        "# de celles du jeu sont appliquées ; en ligne, le serveur traite ce mod comme de la triche.",
        "#",
    ]
    for f in FIELDS:
        if not f.advanced:
            lines.append(f"#   {f.key:22s} {f.help}")
    lines.append("#   (les suivantes sont des réglages fins de la physique, à changer avec prudence)")
    for f in FIELDS:
        if f.advanced:
            lines.append(f"#   {f.key:22s} {f.help}")
    for n in range(1, SUBS + 1):
        lines += ["", f"[{n:02d}]  # {known[n]}"]
        for f in FIELDS:
            if f.key in values[n]:
                lines.append(f"{f.key} = {format_value(values[n][f.key])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_file(path: Path) -> dict[int, dict[str, int | float]]:
    if not path.exists():
        raise SubsError(f"{path} n'existe pas : créez-le avec « tools/subs.py export »")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SubsError(f"{path} : {e}") from e
    out: dict[int, dict[str, int | float]] = {}
    for section, values in data.items():
        if not (re.fullmatch(r"\d{1,2}", section) and 1 <= int(section) <= SUBS) or not isinstance(values, dict):
            raise SubsError(f"{path} : [{section}] n'est pas un sous-marin (de [01] à [{SUBS}])")
        n = int(section)
        out[n] = {}
        for key, value in values.items():
            out[n][key] = check_value(key, value, f"[{section}] {key}")
    return out


def check_value(key: str, value, where: str) -> int | float:
    field = BY_KEY.get(key)
    if field is None:
        raise SubsError(f"{where} : caractéristique inconnue (voir « tools/subs.py show »)")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubsError(f"{where} = {value!r} : il faut un nombre")
    if field.kind is int:
        if float(value) != int(value):
            raise SubsError(f"{where} = {value} : il faut un nombre entier")
        value = int(value)
    else:
        value = float(value)
    if not field.low <= value <= field.high:
        raise SubsError(f"{where} = {value} : hors limites ({format_value(field.kind(field.low))} "
                        f"à {format_value(field.kind(field.high))})")
    return value


def changes(path: str | Path | None) -> dict[str, dict[str, str]]:
    """The edits of a player's file, ready for the mod: stats file -> {attribute: text as in the XML}."""
    user = read_file(resolve(path))
    game = game_values()
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
                    mark = f"   (jeu : {format_value(base[only][f.key])})"
                print(f"  {f.key:22s} {format_value(values[only][f.key]):>8s}  {f.help}{mark}")
        return
    print(f"{'n°':>3s} {'nom':14s} " + " ".join(f"{SHORT[f.key]:>8s}" for f in main))
    for n in range(1, SUBS + 1):
        cells = []
        for f in main:
            v = values[n].get(f.key)
            text = format_value(v) if v is not None else "-"
            if base and base[n].get(f.key) != v:
                text += "*"
            cells.append(f"{text:>8s}")
        print(f"{n:3d} {known[n][:14]:14s} " + " ".join(cells))
    if base:
        print("(* : différent du jeu)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help=f"your file (default: {default_file()})")
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
        known = names()
        game = game_values()
        path = resolve(args.file)
        if args.command == "show":
            only = which(args.sub, known) if args.sub else None
            if args.mine or args.file:
                mine = read_file(path)
                merged = {n: {**game[n], **mine.get(n, {})} for n in game}
                show(merged, known, only, game)
            else:
                show(game, known, only)
        elif args.command == "export":
            if path.exists() and not args.force:
                raise SubsError(f"{path} existe déjà (--force pour le remplacer)")
            write_file(path, game, known)
            print(f"[+] {path}\n    modifiez-le, puis : tools/mod.py build specs --install")
        elif args.command in ("set", "reset"):
            current = {n: {**game[n], **v} for n, v in read_file(path).items()} if path.exists() else {}
            values = {n: dict(current.get(n, game[n])) for n in game}
            if args.command == "set":
                n = which(args.sub, known)
                for item in args.values:
                    key, sep, text = item.partition("=")
                    if not sep:
                        raise SubsError(f"{item!r} : il faut clé=valeur (par exemple torpedoMax=10)")
                    try:
                        number = float(text) if "." in text else int(text)
                    except ValueError:
                        raise SubsError(f"{item!r} : {text!r} n'est pas un nombre") from None
                    values[n][key.strip()] = check_value(key.strip(), number, f"[{n:02d}] {key.strip()}")
                print(f"[+] n° {n} {known[n]} : " + ", ".join(args.values))
            else:
                for n in ([which(args.sub, known)] if args.sub else game):
                    values[n] = dict(game[n])
                print("[+] valeurs du jeu remises" + (f" pour {args.sub}" if args.sub else ""))
            write_file(path, values, known)
            print(f"    {path} ; ensuite : tools/mod.py build specs --install")
        elif args.command == "check":
            edits = changes(path)
            if not edits:
                print(f"[=] {path} : aucune différence avec le jeu")
            for file, diff in edits.items():
                n = int(file[-13:-11])
                print(f"  n° {n:2d} {known[n]:14s} " + ", ".join(f"{k}={v}" for k, v in diff.items()))
    except SubsError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
