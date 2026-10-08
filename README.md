<div align="center">

# Steel Diver: Sub Wars — Open Sourced

**Nintendo's free-to-play submarine shooter for the 3DS, brought back to life:**
**online battles on community servers, mods, and a decompilation of how the game was made.**

[![License: MIT](https://img.shields.io/badge/license-MIT-0a7c9c)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-0a7c9c)](https://www.python.org/downloads/)
![Windows · macOS · Linux](https://img.shields.io/badge/runs%20on-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0a7c9c)
[![Emulator: Azahar](https://img.shields.io/badge/emulator-Azahar-0a7c9c)](https://azahar-emu.org/)

[Install](#install) · [Features](#features) · [Play online](#play-online-with-friends) · [Mods](mods/README.md) ·
[How it works](#how-it-works) · [Docs](#documentation)

</div>

---

Steel Diver: Sub Wars (Nintendo / Vitei, 2014) lost its online mode when the Nintendo Network closed in April 2024, and
its full version can no longer be bought since the eShop closed. This project reverse engineers the game to:

1. **bring online play back**, with a server anyone can run and an emulator mod that connects to it;
2. **mod the game** (the full version, your own music, cheats, characteristics...), from recipes applied to your own copy;
3. **decompile it** into readable pseudo-source, toward a native **PC port**.

> [!IMPORTANT]
> **No game data is in this repository**, and none is ever downloaded by its tools. You bring your own copy of the game;
> the tools read it on your computer and never send it anywhere.

## Features

| | |
|---|---|
| 🌐 **Online battles again** | A self-hostable server (Python, no dependency) speaks the game's protocols (NEX, PRUDP, Kerberos, NAT traversal). One click in the launcher starts it, opens the router's ports (UPnP) and gives you the address to share. |
| 🤖 **Bots that play like players** | Alone in a match? Bots join the lobby like players and fly with a player's physics and limits: they aim where you will be, dodge, use the masker, take crews, start at the players' spawn points, and learn how you dodge. |
| ⭐ **Premium without the eShop** | The full version, every submarine (39 with the update), patterns and crew, unlocked from what is already in the free game. |
| 🎵 **Your own music** | Listen to any music of the game and replace it with an MP3, WAV, OGG, FLAC... at the original's loudness. One button brings the originals back. |
| 🛠️ **Mods** | All missions, cheats, submarine speed, your own characteristics, your console nickname instead of "Citra", and a fix for an Azahar crash. |
| 💾 **Save editor** | Unlock everything, gold medals, any value, export and import as JSON, with a backup before every write. |
| 🔍 **Decompilation** | 9,431 real function names recovered, the 123 Pawn scripts decompiled, in-house formats documented, the engine being rewritten as readable C++. |

## Install

1. **Download the installer** of your system from the [latest release](https://github.com/gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced/releases/latest):
   **Windows** `Install-here.bat` · **macOS** `Install-here-macOS.zip` (it unzips to `Install here.command`) ·
   **Linux** `install-here.sh`.
2. **Put it where you want the game's folder** (Documents, Desktop...) and open it: double-click it (Linux:
   `sh install-here.sh`; macOS, the first time: *System Settings › Privacy & Security › Open Anyway*). It downloads the
   project into a folder `Sub-Wars-Open-Sourced` next to it, opens the launcher in your web browser, and starts
   setting the game up.
3. **Your game**: the launcher finds your copy of the game and of its update by itself (your Downloads, Desktop and
   Documents folders, the project's `cia/` folder, the emulator), or you **drop the files** on its page. It decrypts
   them if needed, extracts the files the mods need, and installs the game and its update into the emulator: the
   game shows in Azahar's list, and your save stays.
4. **Mods tab** — tick what you want (**Premium** to start with), then *Install into the emulator*. Restart the game in
   Azahar: done.

On macOS and Linux, a terminal does the same in one line, in the folder it is in:
`curl -fsSL https://github.com/gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced/releases/latest/download/install-here.sh | sh`

You need **[Azahar](https://azahar-emu.org/)** (or another emulator of the Citra family: Lime3DS, Citra, Borked3DS),
started at least once, and **your own copy** of the European version of the game (`00040000000D7E00`): its eShop
`.cia`, **encrypted or not**, or a decrypted `.3ds` or `.cxi`; optionally its last **update v5200** (16 more
submarines, 3 more maps), a `.cia` encrypted or not. Python is not needed beforehand: the launcher uses yours when it
is 3.11 or newer, else downloads a portable one into its folder (11 MB on Windows, 25 to 30 MB on macOS and Linux).

**Updates**: at start, the launcher asks GitHub for a newer version and offers to update itself in one click (Help tab:
*Check for updates*). Your game, its files, your save and your settings stay.

<details>
<summary>Without the installer</summary>

Download the project (*Code › Download ZIP*, or a release's `Sub-Wars-Open-Sourced.zip`, or `git clone`), then
double-click `launch-windows.bat` (Windows), `launch-macos.command` (macOS) or `launch-linux.sh` (Linux), or run
`python3 subwars.py`. A git clone is updated with `git pull`, not by the launcher.

</details>

<details>
<summary>An encrypted game or update: what the launcher downloads to decrypt it</summary>

Azahar needs the game and its update decrypted, and this project holds no console key. When a file is encrypted (an
update downloaded with its ticket, typically), the launcher says so, then, once you agree:

- downloads the decryptor of [Batch CIA 3DS Decryptor Redux](https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux)
  (`decrypt.exe`, 5.7 MB, version 1.0.6.3, checked by its SHA-256) into `build/decryptor/`, or takes it from a copy
  of that tool already in your Downloads;
- runs it on a copy of your file: directly on **Windows**; with **Wine** on **Linux** and **macOS**, yours if it runs
  it, else a portable Wine downloaded for it (73 MB on Linux, 185 MB on macOS; no installation, no password, removed
  afterwards). On a Mac with Apple silicon, Wine needs Rosetta 2: macOS asks for your password to install it;
- puts the decrypted `.cia` in the project's `cia/` folder. Only Steel Diver: Sub Wars and its update are decrypted.

The same on the command line: `python3 tools/decrypt.py <file.cia>`.

</details>

<details>
<summary>What the launcher's tabs do</summary>

| Tab | |
|---|---|
| **Game** | finds your game and its update (or takes the files you drop), decrypts them if needed, installs them into the emulator and extracts the files the mods need |
| **Mods** | builds the mods you tick for the version of the game your emulator runs (v0 or v5200) and installs them into every emulator found |
| **Save** | unlock everything, gold medals, clear the premium flag of an old save, edit any value |
| **Submarines** | your own characteristics of each submarine (the *Characteristics* mod applies them) |
| **Music** | listen to the game's music, replace it with yours at the same loudness, restore the originals |
| **Server** | host online battles: start the server, share its address, test a friend's, edit its options |
| **Help** | short answers to the usual questions |

</details>

The same tools exist on the command line (`tools/mod.py`, `tools/save.py`, `tools/subs.py`, `tools/music.py`,
`tools/decrypt.py`): see [mods/README.md](mods/README.md). They run on Windows, macOS and Linux with Python alone.

## Play online with friends

1. **One player hosts**: launcher › **Server** › *Start the server*. It finds its public address, asks the router to open
   its ports, and shows **the address to give to your friends**.
2. **Everyone installs the *Online play* mod**: the host keeps the default address (`127.0.0.1`); friends paste the
   host's address in *Join a friend's server* (*Test* checks it answers), then *Use it for the Online play mod* and
   *Install into the emulator*.
3. In the game: **Multiplayer › Internet Battle**. Players of the same version who cheat or do not cheat alike meet in
   the same lobby; a player left alone gets bots after the delay set by the server.

Behind a router that cannot forward ports (shared IPv4, operator NAT), a virtual private network such as ZeroTier or
Tailscale works without opening anything: see [server/README.md](server/README.md#play-with-friends-far-away).

## Project status

| Part | Progress | |
|---|---|---|
| 🌐 Online server | `█████████░` 90 % | protocol complete, checked with the real game; a real battle between two homes remains |
| 🛠️ Mods for Azahar | `████████░░` 80 % | all listed mods work with v0 and v5200; 60 fps waits for the PC port |
| 🤖 Bots | `█████████░` 90 % | checked in a sandbox; remain to be seen in long battles in Azahar |
| 🔍 Pseudo-source | `██░░░░░░░░` 20 % | everything exported and the scripts decompiled; 9 % of the game's code rewritten cleanly |
| 💻 PC port | `░░░░░░░░░░` 0 % | strategy chosen: static recompilation + HLE ([roadmap](docs/roadmap.md)) |

## How it works

- **Mods are recipes, never modified games.** Each mod is a `mods/<name>/mod.toml` listing changes (texts, data, ARM code
  patches, Pawn script hooks, music) that `tools/mod.py` applies to your own files to make the folder Azahar loads
  (`load/mods/00040000000D7E00/`). Sharing a mod means sharing its recipe.
- **The game's logic is in Pawn.** 123 compiled scripts drive the modes, the submarines and the interface. The project
  disassembles, decompiles and assembles them, and compiles new Pawn code into hooks (that is how the bots are written).
- **The developers left the linker's symbol table** in the game's files: 9,431 functions with their real names, sizes
  and object files, applied automatically in Ghidra.
- **The online mod** replaces the three functions of the console's *friends* module that Azahar does not emulate, and
  points the game at your server; the battles stay peer to peer, as on the console.

## Documentation

| | |
|---|---|
| [docs/initial-analysis.md](docs/initial-analysis.md) | the dump, the symbol table, the game's architecture, the RomFS |
| [docs/online.md](docs/online.md) | the online mode, step by step, as the server implements it |
| [docs/bots.md](docs/bots.md) | the bots' pilot, crews, the sandbox and its results |
| [docs/mods.md](docs/mods.md) | what can be modded and how, the Azahar crash, 60 fps |
| [docs/premium.md](docs/premium.md) | free version, premium and add-on contents |
| [docs/update-v5200.md](docs/update-v5200.md) | the last update, and how mods follow both versions |
| [docs/formats.md](docs/formats.md) | BXML, levels, collisions, the save, music streams |
| [docs/pawn-scripts.md](docs/pawn-scripts.md) | the Pawn scripts and their decompiler |
| [docs/ai.md](docs/ai.md) | how many matches a trained AI would need to match a player |
| [docs/roadmap.md](docs/roadmap.md) | the plan, part by part |
| [mods/README.md](mods/README.md) · [server/README.md](server/README.md) · [decomp/README.md](decomp/README.md) | mods and recipes · the server · the pseudo-source |

## For developers

<details>
<summary>Publishing a version</summary>

After each finished change: raise `VERSION`, commit, push, then `python3 tools/release.py --notes "..."`. It makes the
GitHub release `v<VERSION>`: `Sub-Wars-Open-Sourced.zip` (`git archive` of the commit: tracked files only) and the
installers of `installer/`. The installers always download the latest release; the launcher updates a folder from it
(`tools/selfupdate.py`: changed files replaced, removed ones deleted, the player's files and a `server.toml` they
changed kept).

</details>

<details>
<summary>Reverse-engineering pipeline (Linux)</summary>

Requirements: Linux, Python 3.11+, Java 21+, [Ghidra 12](https://github.com/NationalSecurityAgency/ghidra/releases)
unpacked in a path **without non-ASCII characters** (e.g. `~/tools/`; Ghidra fails to start otherwise).

```sh
./setup.sh          # Python venv + Ghidra detection (writes local.env)
cp <your dump>.cia cia/
make                # extraction -> ELF -> Ghidra analysis -> C++ pseudo-code -> decompiled Pawn scripts
```

Individual steps: `make extract`, `make elf`, `make analyze`, `make export`, `make scripts`, `make data`; the bots:
`make pawncc bots`. To explore in the interface: start Ghidra and open `ghidra/project/SteelDiver.gpr`.

Tests: `python3 -m unittest discover -s tools/tests` (the players' tools, no game file needed) and
`cd server && python3 -m unittest discover -s tests -t .` (the server).

</details>

<details>
<summary>Repository layout</summary>

```
cia/               your game files (the launcher copies or decrypts them there), ignored by git
extracted/         extraction output: code.bin, nsub.elf, exefs/, romfs/; v5200/: the update (ignored)
tools/             Python tools: CIA extraction, Pawn (amx*.py), BXML, BCSTM, Azahar, mods, launcher, updates
installer/         the installers attached to each release (Windows, macOS, Linux)
mods/              mod recipes (no game data: they apply to the player's dump)
ghidra/            Ghidra scripts, hand-added symbols (symbols.txt) and types (types.h); project/ is disposable
decomp/            pseudo-source: raw/ (Ghidra C++, generated), scripts/ (decompiled Pawn, generated), src/ (cleaned)
port/              PC port
server/            online server (emulator and PC realms, NAT detection, tests)
docs/              reverse-engineering notes
```

</details>

## Legal

This project contains no part of the game: no code, no assets, no keys. Every tool works on the copy you own, on your
computer. To decrypt that copy, the launcher can download a third-party tool (Batch CIA 3DS Decryptor Redux's
decryptor), which runs on your computer and is not part of this repository. Steel Diver: Sub Wars, its data and its code remain the property of Nintendo; this project is not affiliated
with or endorsed by Nintendo or Vitei.

The code of this repository (tools, scripts, port, server, documentation) is under the [MIT](LICENSE) licence. GPL/AGPL
projects (Pretendo's server, Azahar/Citra) were only used as references; no code was copied from them.
