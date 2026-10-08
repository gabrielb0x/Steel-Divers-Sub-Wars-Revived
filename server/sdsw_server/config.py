"""serveur.toml: the options of the server, read and written back with their comments.

The launcher (tools/webui.py) shows these options and changes them with update(): each value is
replaced on its own line, so the comments of the file stay; a missing option is added at the end of its
section. Values are checked with the server's own rules (RealmConfig, BotSettings) before anything is
written. Standard library only.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Option:
    key: str
    kind: str                      # "text", "int", "bool", "choice"
    default: object
    label: str
    help: str = ""
    choices: tuple = ()
    low: int | None = None
    high: int | None = None


SERVER_OPTIONS = (
    Option("name", "text", "Sub Wars Open Sourced", "Nom", "affiché sur la page d'état"),
    Option("public_address", "text", "auto", "Adresse publique",
           "IP ou nom par lequel Internet joint ce serveur ; auto : celle de la box (UPnP), sinon STUN"),
    Option("upnp", "bool", True, "UPnP", "demander à la box d'ouvrir les ports du serveur"),
    Option("nat_check", "bool", True, "Détection de NAT", "UDP 10025 et 10125, ports fixés par le jeu"),
    Option("status_port", "int", 0, "Page d'état", "port TCP de la page d'état (0 : aucune)", low=0, high=65535),
    Option("listen", "text", "0.0.0.0", "Adresse d'écoute", "0.0.0.0 : toutes les interfaces"),
)

FORMATS = tuple(f"{a}v{b}" for a in range(1, 5) for b in range(1, 5))

REALM_OPTIONS = (
    Option("auth_port", "int", 61000, "Port", "authentification (UDP) ; le serveur sécurisé prend le suivant",
           low=1, high=65535),
    Option("secure_port", "int", 61001, "Port sécurisé", "UDP", low=1, high=65535),
    Option("max_players", "int", 8, "Joueurs humains par partie", "2 à 8 ; des bots complètent les équipes",
           low=2, high=8),
    Option("duration", "int", 10, "Durée d'une bataille",
           "minutes, pour toutes les batailles en ligne (le jeu : 10) ; il faut le mod Jeu en ligne à jour",
           low=1, high=30),
    Option("cheats", "choice", "separes", "Tricheurs",
           "separes : entre eux ; autorises : avec tout le monde ; refuses : connexion refusée. Sauf autorises, "
           "l'anti-triche du mod exclut de la bataille un joueur qui triche", choices=("separes", "autorises", "refuses")),
    Option("anticheat_ban", "int", 30, "Exclusion d'un tricheur",
           "minutes pendant lesquelles un joueur pris à tricher ne joue qu'avec les tricheurs (separes) ou ne peut "
           "plus jouer (refuses) ; 0 : seulement exclu de la bataille", low=0, high=10080),
    Option("bots", "bool", True, "Bots pour un joueur seul",
           "un joueur seul dans une partie joue contre des bots au bout du délai"),
    Option("bots_delay", "int", 60, "Délai avant les bots", "secondes seul dans la partie", low=5, high=3600),
    Option("bots_format", "choice", "4v4", "Équipes",
           "votre équipe contre l'autre : 4v4 = vous et 3 bots contre 4 bots, 1v4 = seul contre 4", choices=FORMATS),
    Option("bots_map", "choice", "aleatoire", "Carte", "aleatoire, ou le numéro d'une carte (11 à 13 : celles de "
           "la mise à jour v5200, aléatoire pour les joueurs du jeu d'origine)",
           choices=("aleatoire", "1", "2", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13")),
    Option("bots_level", "choice", "difficile", "Niveau des bots",
           "ils jouent comme des joueurs ; le niveau règle réflexes et précision (entre joueurs, les sous-marins "
           "que le jeu ajoute restent les siens)",
           choices=("normal", "difficile", "expert")),
    Option("bots_countdown", "int", 10, "Compte à rebours", "secondes avant la bataille contre les bots",
           low=6, high=120),
    Option("bots_crew", "bool", True, "Équipage des bots",
           "chaque bot prend un équipage, comme un joueur (meilleur au niveau expert) : ses notes et ses capacités"),
)


class ConfigError(ValueError):
    pass


def read(path: Path) -> dict:
    """{"server": {...}, "realm": [{...}, ...]} with every option (defaults filled in)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = {o.key: data.get("server", {}).get(o.key, o.default) for o in SERVER_OPTIONS}
    realms = []
    for entry in data.get("realm", []):
        realm = {"name": entry.get("name", "?"), "data_dir": entry.get("data_dir", "")}
        realm.update({o.key: entry.get(o.key, o.default) for o in REALM_OPTIONS})
        realms.append(realm)
    return {"server": server, "realm": realms}


def schema() -> dict:
    def describe(o: Option) -> dict:
        return {"key": o.key, "kind": o.kind, "default": o.default, "label": o.label, "help": o.help,
                "choices": list(o.choices), "low": o.low, "high": o.high}
    return {"server": [describe(o) for o in SERVER_OPTIONS], "realm": [describe(o) for o in REALM_OPTIONS]}


def _coerce(option: Option, value) -> object:
    if option.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "oui", "yes", "on", "vrai")
        return bool(value)
    if option.kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{option.label} : un nombre entier est attendu") from None
        if option.low is not None and number < option.low or option.high is not None and number > option.high:
            raise ConfigError(f"{option.label} : entre {option.low} et {option.high}")
        return number
    text = str(value).strip()
    if option.kind == "choice" and text not in option.choices:
        raise ConfigError(f"{option.label} : {text!r} n'est pas une valeur possible")
    if len(text) > 200 or "\n" in text:
        raise ConfigError(f"{option.label} : valeur trop longue")
    return text


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def update(path: Path, changes: dict) -> dict:
    """Applies {"server": {key: value}, "realm": [{"name": ..., key: value}, ...]} to the file, after
    checking the result as the server would. Returns the new options (read())."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    # Sections: ("server", 0) or ("realm", n), with the range of their lines.
    sections: list[tuple[tuple[str, int], int, int]] = []
    realm_count, current, start = 0, None, 0
    for n, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            if current:
                sections.append((current, start, n))
            if stripped == "[[realm]]":
                current, start = ("realm", realm_count), n + 1
                realm_count += 1
            elif stripped == "[server]":
                current, start = ("server", 0), n + 1
            else:
                current = None
    if current:
        sections.append((current, start, len(lines)))
    found = {name: (a, b) for name, a, b in sections}

    edits: dict[tuple[str, int], dict[str, object]] = {}
    known = {o.key: o for o in SERVER_OPTIONS}
    values = {}
    for key, value in (changes.get("server") or {}).items():
        if key not in known:
            raise ConfigError(f"option inconnue : {key}")
        values[key] = _coerce(known[key], value)
    if values:
        if ("server", 0) not in found:
            raise ConfigError("pas de section [server] dans serveur.toml")
        edits[("server", 0)] = values
    names = [entry.get("name") for entry in tomllib.loads(text).get("realm", [])]
    known = {o.key: o for o in REALM_OPTIONS}
    for realm in changes.get("realm") or []:
        if realm.get("name") not in names:
            raise ConfigError(f"royaume inconnu : {realm.get('name')}")
        index = names.index(realm["name"])
        values = {}
        for key, value in realm.items():
            if key == "name":
                continue
            if key not in known:
                raise ConfigError(f"option inconnue : {key}")
            values[key] = _coerce(known[key], value)
        edits[("realm", index)] = values

    inserts: dict[int, list[str]] = {}
    for section, values in edits.items():
        first, end = found[section]
        for key, value in values.items():
            pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(\"(?:[^\"\\]|\\.)*\"|[^#\s]+)(.*)$", re.S)
            for n in range(first, end):
                m = pattern.match(lines[n])
                if m:
                    rest = m[3]
                    comment = re.match(r"^([ \t]+)(#.*)$", rest, re.S)
                    if comment:                     # keep the comment in its column
                        column = len(m[1]) + len(m[2]) + len(comment[1])
                        width = max(1, column - len(m[1]) - len(_toml(value)))
                        rest = " " * width + comment[2]
                    lines[n] = m[1] + _toml(value) + rest
                    break
            else:
                last = max((n for n in range(first, end) if "=" in lines[n] and not lines[n].lstrip().startswith("#")),
                           default=first - 1)
                inserts.setdefault(last + 1, []).append(f"{key} = {_toml(value)}\n")
    for at in sorted(inserts, reverse=True):
        lines[at:at] = inserts[at]
    new_text = "".join(lines)
    check(new_text, path)
    path.write_text(new_text, encoding="utf-8")
    return read(path)


def check(text: str, path: Path) -> None:
    """Raises ConfigError if the server would refuse this configuration."""
    from .__main__ import load_config               # the server's own reading of the file
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"fichier invalide : {e}") from e
    temp = path.with_name(path.name + ".check")
    try:
        temp.write_text(text, encoding="utf-8")
        _, realms = load_config(temp, None)
    except (ValueError, KeyError) as e:
        raise ConfigError(str(e)) from e
    finally:
        temp.unlink(missing_ok=True)
    ports = [p for r in realms for p in (r.auth_port, r.secure_port)]
    if len(ports) != len(set(ports)):
        raise ConfigError("deux royaumes utilisent le même port")
    if data.get("server", {}).get("status_port") in ports:
        raise ConfigError("la page d'état utilise le port d'un royaume")
