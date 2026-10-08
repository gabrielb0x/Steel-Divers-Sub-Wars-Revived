#!/usr/bin/env python3
"""Your own music in the game: replacements for its music streams, applied by the mod "music".

    tools/music.py list                         # the game's music, and what you replaced
    tools/music.py set Title_lr my-music.wav    # replaces it (a WAV; the launcher also takes MP3, OGG, FLAC...)
    tools/music.py reset Title_lr               # the game's music again (or: reset --all)
    tools/music.py export Title_lr -o titre.wav # the game's music, to listen to it
    tools/mod.py build music --install          # then the mod (with your other mods: build premium music ...)

The music of the game is in romfs:/audiores/stream/*.bcstm (tools/bcstm.py); the sound archive
(audiores/sound_data.xml, which the game ships) says which sounds play each file: Bgm_TITLE, Bgm_MultiPlay3_Battle...
Your replacements are WAV files (16 bits, already at the rate and channels of the music they replace) in the
folder "music" of the settings folder (azahar.config_dir()), named after the stream they replace, with
music.json for the names of the files you gave and their loudness. On request (the default), the level of
yours is matched to the original's (loudness: gated mean power of 400 ms blocks, as EBU R 128 without its
weighting; a soft limiter for the peaks). The mod turns each into a PCM16 stream that loops from its start. Removing a file brings the game's music back. Standard library only (a tool of the players).
"""

from __future__ import annotations

import argparse
import array
import json
import math
import re
import sys
from pathlib import Path

import azahar
import bcstm
import versions

STREAMS = "audiores/stream"
INDEX = "music.json"
OLD_INDEX = "musique.json"              # its name before the project went English
LEVELS_FILE = "levels.json"
MAX_SECONDS = 15 * 60
TARGET_RMS = 6000.0                 # about the level of the game's music (rms of Title, Fleet: 6000 to 7400)

# What plays each stream: the sounds of the archive (sound_data.xml).
LABELS = {
    "Bgm_TITLE": "Title screen",
    "Bgm_ENDING": "Ending credits",
    "Bgm_SELECT_BASE": "Menu: the base",
    "Bgm_SELECT_ON_STAGE": "Menu: mission select",
    "Bgm_SELECT_ON_SUBMARINE": "Menu: aboard the submarine",
    "Bgm_MAIN_MENU": "Main menu (silent in the game)",
    "Bgm_SUBMARINE_SELECT": "Submarine select (silent in the game)",
    "Bgm_LEAVE_PORT_FANFARE": "Leaving port (silent in the game)",
    "Bgm_SELECT_OPTION": "Options",
    "Bgm_Shop": "Shop",
    "Bgm_FANFARE_EXPERT_OPEN": "Fanfare: expert mode unlocked",
    "Bgm_WinBattle": "Battle won",
    "Bgm_LoseBattle": "Battle lost",
    "Bgm_DrawBattle": "Draw",
    "Bgm_BattleKansen": "Spectator",
    "Bgm_SUCCESS_PERISCOPE": "Mission complete",
    "Bgm_SUCCESS_LAST": "Last mission complete",
    "Bgm_OVER": "Mission failed",
    "Bgm_RANKING": "Results",
    "Bgm_SELECTSEABATTLEforTUTORIAL": "Tutorial",
    "Bgm_F2P": "Free version introduction",
}


class MusicError(Exception):
    pass


def default_dir() -> Path:
    folder = azahar.settings_file("music", "musique")
    old = folder / OLD_INDEX
    if old.exists() and not (folder / INDEX).exists():
        old.rename(folder / INDEX)
    return folder


def label_of(sound: str, maps: dict[str, str] | None = None) -> str:
    if sound in LABELS:
        return LABELS[sound]
    m = re.fullmatch(r"Bgm_Mission(\d)_(\w+)", sound)
    if m:
        part = {"GATE": "the gate", "BOSS": "the boss"}.get(m[2], f"part {m[2]}")
        return f"Mission {m[1]}, {part}"
    m = re.fullmatch(r"Bgm_MultiPlay(\d+)(_Battle)?", sound)
    if m:
        name = (maps or {}).get(m[1]) or f"map {m[1]}"
        return f"Online: {name}" + (", combat" if m[2] else "")
    return sound


def tracks(game: versions.GameFiles, maps: dict[str, str] | None = None) -> list[dict]:
    """The music streams the game plays: file, sounds, label (several sounds may share a file)."""
    path = game.path("audiores/sound_data.xml")
    if not path.is_file():
        raise MusicError("audiores/sound_data.xml not found: prepare the game's files (make extract)")
    text = path.read_text(encoding="utf-8", errors="replace")
    files = dict(re.findall(r'<InternalFile ID="([0-9A-F]+)" Name="stream/([^"]+\.bcstm)"', text))
    sounds: dict[str, list[str]] = {}
    for name, fid in re.findall(r'<StreamSound ID="[0-9A-F]+" Name="(\w+)" FileID="([0-9A-F]+)"', text):
        sounds.setdefault(fid, []).append(name)
    out = []
    for fid, file in files.items():
        if not game.exists(f"{STREAMS}/{file}"):
            continue
        names = sounds.get(fid, [])
        labels = list(dict.fromkeys(label_of(s, maps) for s in names))
        out.append({"file": file, "stem": file[: -len(".bcstm")], "sounds": names,
                    "label": " · ".join(labels) or file})
    return out


def find(game: versions.GameFiles, name: str) -> dict:
    """A track by its file name, its start, or one of its sounds."""
    all_tracks = tracks(game)
    for t in all_tracks:
        if name in (t["file"], t["stem"]) or name in t["sounds"]:
            return t
    found = [t for t in all_tracks if t["file"].lower().startswith(name.lower())]
    if len(found) == 1:
        return found[0]
    raise MusicError(f"{name}: no music of that name" + (" (several start like this)" if found else ""))


def original(game: versions.GameFiles, track: dict) -> bcstm.Stream:
    return bcstm.read(game.path(f"{STREAMS}/{track['file']}").read_bytes())


def mine(folder: Path, track: dict) -> Path:
    return folder / f"{track['stem']}.wav"


def _index(folder: Path) -> dict:
    try:
        return json.loads((folder / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _store_index(folder: Path, index: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / INDEX).write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def replaced(folder: Path) -> dict[str, dict]:
    """stem -> {source, seconds} of the replacements in the folder."""
    index = _index(folder)
    out = {}
    for wav in sorted(folder.glob("*.wav")) if folder.is_dir() else []:
        info = index.get(wav.stem, {})
        gain = None
        if info.get("loudness") is not None and info.get("target") is not None:
            gain = round(info["target"] - info["loudness"], 1)
        out[wav.stem] = {"source": info.get("source", wav.name), "seconds": info.get("seconds"),
                         "loudness": info.get("loudness"), "target": info.get("target"),
                         "match": bool(info.get("match")), "gain": gain}
    return out


def loudness(channels: list[array.array], rate: int) -> float | None:
    """How loud it sounds, in dB below full scale: the mean power of its 400 ms blocks, as LUFS measure it
    (EBU R 128: blocks under -70 dB, then under 10 dB below the mean, are left out, so that silences and quiet
    passages do not count), without the frequency weighting. None: silence."""
    size = max(1, int(rate * 0.4))
    step = 3                                            # every third sample: plenty for a mean power
    powers = []
    for start in range(0, len(channels[0]) - size + 1, size):
        total = 0.0
        for c in channels:
            block = c[start: start + size: step]
            total += sum(v * v for v in block) / len(block)
        powers.append(total / (32768.0 * 32768.0))
    if not powers:
        return None
    floor = 10 ** (-70 / 10)
    kept = [x for x in powers if x > floor]
    if not kept:
        return None
    mean = sum(kept) / len(kept)
    kept = [x for x in kept if x > mean / 10.0]
    return 10.0 * math.log10(sum(kept) / len(kept))


GAME_LEVEL = 20.0 * math.log10(TARGET_RMS / 32768.0)   # for a music of the game that is silence


def original_loudness(folder: Path, game: versions.GameFiles, track: dict) -> float:
    """The loudness of the game's music this one replaces (measured once, kept in levels.json)."""
    cache_file = folder / LEVELS_FILE
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    key = f"{game.version}/{track['file']}"
    if key not in cache:
        stream = original(game, track)
        cache[key] = loudness(bcstm.decode(stream), stream.rate)
        folder.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=1) + "\n", encoding="utf-8")
    value = cache[key]
    return GAME_LEVEL if value is None else value


def with_gain(channels: list[array.array], db: float) -> list[array.array]:
    """Louder or quieter by db; the peaks that would go past full scale are rounded off (a soft limiter from
    -1 dB) rather than clipped."""
    if abs(db) < 0.1:
        return channels
    gain = 10 ** (db / 20.0)
    knee = 0.89 * 32767.0
    room = 32767.0 - knee
    out = []
    for c in channels:
        values = array.array("h", bytes(2 * len(c)))
        for i, v in enumerate(c):
            y = v * gain
            if y > knee:
                y = knee + room * math.tanh((y - knee) / room)
            elif y < -knee:
                y = -knee - room * math.tanh((-y - knee) / room)
            values[i] = int(y)
        out.append(values)
    return out


def leveled(folder: Path, track: dict) -> tuple[list[array.array], int]:
    """Your music as the game will play it: at the level of the original when you asked for it."""
    channels, rate = bcstm.read_wav(mine(folder, track))
    info = _index(folder).get(track["stem"], {})
    if info.get("match") and info.get("loudness") is not None and info.get("target") is not None:
        channels = with_gain(channels, info["target"] - info["loudness"])
    return channels, rate


def store(folder: Path, game: versions.GameFiles, track: dict, channels: list[array.array], rate: int,
          source: str, normalize: bool = True) -> dict:
    """Your music for this track: fitted to the original's channels and rate, kept as a WAV as it is, with its
    loudness and the original's (the level is matched when the game's stream is made: normalize)."""
    if not channels or not channels[0]:
        raise MusicError("file without sound")
    if len(channels[0]) > rate * MAX_SECONDS:
        raise MusicError(f"music too long (over {MAX_SECONDS // 60} minutes)")
    like = original(game, track)
    channels = bcstm.fit(channels, rate, like)
    folder.mkdir(parents=True, exist_ok=True)
    bcstm.write_wav(mine(folder, track), channels, like.rate)
    index = _index(folder)
    seconds = round(len(channels[0]) / like.rate, 1)
    level = loudness(channels, like.rate)
    index[track["stem"]] = {"source": source, "seconds": seconds,
                            "loudness": None if level is None else round(level, 2),
                            "target": round(original_loudness(folder, game, track), 2), "match": bool(normalize)}
    _store_index(folder, index)
    return {"file": track["file"], "source": source, "seconds": seconds} | index[track["stem"]]


def set_match(folder: Path, game: versions.GameFiles, track: dict | None, on: bool) -> int:
    """Matches (or not) the level of your music to the original's: one track, or all of them (None)."""
    index = _index(folder)
    done = 0
    for stem, info in index.items():
        if track is not None and stem != track["stem"]:
            continue
        info["match"] = bool(on)
        if on and info.get("target") is None:
            t = next((t for t in tracks(game) if t["stem"] == stem), None)
            if t:
                info["target"] = round(original_loudness(folder, game, t), 2)
        done += 1
    _store_index(folder, index)
    return done


def store_pcm(folder: Path, game: versions.GameFiles, track: dict, pcm: bytes, rate: int, count: int,
              source: str, normalize: bool = True) -> dict:
    """Interleaved signed 16-bit little-endian samples (what the launcher's page decoded and resampled)."""
    if not 1 <= count <= 2 or not 8000 <= rate <= 48000:
        raise MusicError("1 or 2 channels, 8,000 to 48,000 Hz")
    values = array.array("h", pcm[: len(pcm) // (2 * count) * 2 * count])
    if sys.byteorder == "big":
        values.byteswap()
    return store(folder, game, track, [values[c::count] for c in range(count)], rate, source, normalize)


def remove(folder: Path, track: dict | None = None) -> int:
    """The game's music again: for one track, or all of them (track None). Returns how many were removed."""
    index = _index(folder)
    removed = 0
    for wav in list(folder.glob("*.wav")) if folder.is_dir() else []:
        if track is None or wav.stem == track["stem"]:
            wav.unlink()
            index.pop(wav.stem, None)
            removed += 1
    if folder.is_dir():
        _store_index(folder, {k: v for k, v in index.items() if (folder / f"{k}.wav").exists()})
    return removed


def streams(folder: Path, game: versions.GameFiles) -> dict[str, bytes]:
    """The mod's files: romfs path -> stream, for each replacement of a music of this version."""
    out = {}
    known = {t["stem"]: t for t in tracks(game)}
    for wav in sorted(folder.glob("*.wav")) if folder.is_dir() else []:
        track = known.get(wav.stem)
        if track is None:
            print(f"[!] {wav.name}: no music of the game of that name, left out")
            continue
        channels, rate = leveled(folder, track)
        out[f"{STREAMS}/{track['file']}"] = bcstm.replacement(channels, rate,
                                                              game.path(f"{STREAMS}/{track['file']}").read_bytes())
    return out


def folder_of(value: str) -> Path:
    return default_dir() if value in ("", "auto") else Path(value).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", default="auto", help="folder of your music (auto: \"music\" in the settings "
                                                       "folder)")
    parser.add_argument("--version", default=versions.BASE, help="version of the game: v0, v5200")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the game's music and your replacements")
    p = sub.add_parser("set", help="replace a music with a WAV")
    p.add_argument("track")
    p.add_argument("wav", type=Path)
    p.add_argument("--keep-volume", action="store_true", help="do not match its loudness to the original's")
    p = sub.add_parser("reset", help="put the game's music back")
    p.add_argument("track", nargs="?")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("export", help="the game's music as a WAV")
    p.add_argument("track")
    p.add_argument("-o", "--out", type=Path)
    args = parser.parse_args()
    folder = folder_of(args.dir)
    game = versions.game_files(args.version)
    try:
        if args.command == "list":
            mine_ = replaced(folder)
            for t in tracks(game):
                r = mine_.get(t["stem"])
                print(f"{t['stem']:52} {t['label']}" + (f"  <- {r['source']}" if r else ""))
            print(f"\nYour music: {folder}")
        elif args.command == "set":
            track = find(game, args.track)
            channels, rate = bcstm.read_wav(args.wav)
            done = store(folder, game, track, channels, rate, args.wav.name, not args.keep_volume)
            gain = "" if done["loudness"] is None or not done["match"] else \
                f", volume {done['target'] - done['loudness']:+.1f} dB to sound like the original"
            print(f"{track['label']} : {done['source']} ({done['seconds']} s{gain}). "
                  "Then: tools/mod.py build music --install")
        elif args.command == "reset":
            if not args.all and not args.track:
                raise MusicError("reset <music>, or reset --all")
            n = remove(folder, None if args.all else find(game, args.track))
            print(f"{n} music stream(s) of the game put back")
        else:
            track = find(game, args.track)
            s = original(game, track)
            out = args.out or Path(f"{track['stem']}.wav")
            bcstm.write_wav(out, bcstm.decode(s), s.rate)
            print(f"{out} ({s.seconds:.1f} s)")
    except (MusicError, bcstm.BcstmError, OSError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
