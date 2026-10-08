"""server.toml: the options of the server, read and written back with their comments.

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


# The values of the options before the project went English: still understood, written back in English.
VALUE_ALIASES = {"separes": "separate", "autorises": "allowed", "refuses": "refused", "difficile": "hard",
                 "aleatoire": "random", "aléatoire": "random"}


def canonical(value):
    """An option's value, its older (French) spelling translated."""
    return VALUE_ALIASES.get(value.strip().lower(), value.strip()) if isinstance(value, str) else value


SERVER_OPTIONS = (
    Option("name", "text", "Sub Wars Open Sourced", "Name", "shown on the status page"),
    Option("public_address", "text", "auto", "Adresse publique",
           "IP or name by which the Internet reaches this server; auto: the router's (UPnP), else STUN"),
    Option("upnp", "bool", True, "UPnP", "ask the router to open the server's ports"),
    Option("nat_check", "bool", True, "NAT detection", "UDP 10025 and 10125, ports set by the game"),
    Option("status_port", "int", 0, "Status page", "TCP port of the status page (0: none)", low=0, high=65535),
    Option("listen", "text", "0.0.0.0", "Listening address", "0.0.0.0: every interface"),
)

FORMATS = tuple(f"{a}v{b}" for a in range(1, 5) for b in range(1, 5))

REALM_OPTIONS = (
    Option("auth_port", "int", 61000, "Port", "authentication (UDP); the secure server takes the next one",
           low=1, high=65535),
    Option("secure_port", "int", 61001, "Secure port", "UDP", low=1, high=65535),
    Option("max_players", "int", 8, "Human players per match", "2 to 8; computer subs fill the teams",
           low=2, high=8),
    Option("duration", "int", 10, "Battle length",
           "minutes, for every online battle (the game: 10); needs an up-to-date Online play mod",
           low=1, high=30),
    Option("cheats", "choice", "separate", "Cheaters",
           "separate: among themselves; allowed: with everybody; refused: connection refused. Except with allowed, "
           "the mod's anti-cheat takes a player who cheats out of the battle", choices=("separate", "allowed", "refused")),
    Option("anticheat_ban", "int", 30, "Cheater exclusion",
           "minutes during which a player caught cheating only plays with the cheaters (separate) or cannot play "
           "any more (refused); 0: only taken out of the battle", low=0, high=10080),
    Option("bots", "bool", True, "Bots for a player alone",
           "a player alone in a match plays against bots after the delay"),
    Option("bots_delay", "int", 60, "Delay before the bots", "seconds alone in the match", low=5, high=3600),
    Option("bots_format", "choice", "4v4", "Teams",
           "your team against the other: 4v4 = you and 3 bots against 4 bots, 1v4 = alone against 4", choices=FORMATS),
    Option("bots_map", "choice", "random", "Map", "random, or a map's number (11 to 13: the update v5200's, random "
           "for the players of the original game)",
           choices=("random", "1", "2", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13")),
    Option("bots_level", "choice", "hard", "Bot level",
           "they play like players; the level sets their reflexes and aim (between players, the computer subs "
           "the game adds stay the game's)",
           choices=("normal", "hard", "expert")),
    Option("bots_countdown", "int", 10, "Countdown", "seconds before the battle against the bots",
           low=6, high=120),
    Option("bots_crew", "bool", True, "Bot crews",
           "each bot takes a crew, as a player does (a better one at the expert level): its ratings and abilities"),
)


class ConfigError(ValueError):
    pass


def read(path: Path) -> dict:
    """{"server": {...}, "realm": [{...}, ...]} with every option (defaults filled in)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = {o.key: canonical(data.get("server", {}).get(o.key, o.default)) for o in SERVER_OPTIONS}
    realms = []
    for entry in data.get("realm", []):
        realm = {"name": entry.get("name", "?"), "data_dir": entry.get("data_dir", "")}
        realm.update({o.key: canonical(entry.get(o.key, o.default)) for o in REALM_OPTIONS})
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
            return value.strip().lower() in ("1", "true", "yes", "on", "oui", "vrai")
        return bool(value)
    if option.kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{option.label}: a whole number is expected") from None
        if option.low is not None and number < option.low or option.high is not None and number > option.high:
            raise ConfigError(f"{option.label}: between {option.low} and {option.high}")
        return number
    text = str(canonical(value)).strip()
    if option.kind == "choice" and text not in option.choices:
        raise ConfigError(f"{option.label}: {text!r} is not a possible value")
    if len(text) > 200 or "\n" in text:
        raise ConfigError(f"{option.label}: value too long")
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
            raise ConfigError(f"unknown option: {key}")
        values[key] = _coerce(known[key], value)
    if values:
        if ("server", 0) not in found:
            raise ConfigError("no [server] section in server.toml")
        edits[("server", 0)] = values
    names = [entry.get("name") for entry in tomllib.loads(text).get("realm", [])]
    known = {o.key: o for o in REALM_OPTIONS}
    for realm in changes.get("realm") or []:
        if realm.get("name") not in names:
            raise ConfigError(f"unknown realm: {realm.get('name')}")
        index = names.index(realm["name"])
        values = {}
        for key, value in realm.items():
            if key == "name":
                continue
            if key not in known:
                raise ConfigError(f"unknown option: {key}")
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
        raise ConfigError(f"invalid file: {e}") from e
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
        raise ConfigError("two realms use the same port")
    if data.get("server", {}).get("status_port") in ports:
        raise ConfigError("the status page uses a realm's port")
