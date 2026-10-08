# Mods

> The simplest way: the launcher `subwars.py` (at the root of the project) does everything below with buttons, in
> your web browser. This page describes the command-line tools and the format of the recipes. They only need
> Python 3.11 (no venv): `python3 tools/mod.py ...` works as well as `.venv/bin/python tools/mod.py ...`.

The mods of Steel Diver: Sub Wars for the **Azahar** emulator, as **recipes**: each mod describes changes, which are
applied to the player's files (their own dump) when the mod is built. The repository therefore never holds game data,
and a mod is shared by sharing its recipe.

## Preparing the game for Azahar

*Estimated progress: 100 %.*

The launcher's Game tab does all of this with one button (*Set everything up*). By hand:

```sh
python3 tools/decrypt.py <file.cia>      # an encrypted game or update -> cia/<title> (decrypted).cia
python3 tools/azahar.py install-game     # the game into the emulators (their list of games), the save is kept
python3 tools/azahar.py install-update   # its update
```

`tools/decrypt.py` runs the decryptor of Batch CIA 3DS Decryptor Redux, downloaded and checked by its SHA-256, directly
on Windows and with Wine on Linux and macOS (the Wine installed, or a portable one downloaded for it and removed
afterwards): [../docs/update-v5200.md](../docs/update-v5200.md#an-encrypted-update).

The eShop CIA also holds the electronic manual, which stayed encrypted: Azahar then refuses the whole installation
("Blocked unauthorized encrypted CIA installation" in its log). The game itself is not encrypted:

```sh
make azahar          # or: .venv/bin/python tools/azahar.py prepare
```

makes, from `cia/*.cia`:

- `build/azahar/SteelDiverSubWars_original.cia`: the game alone, to install (Azahar > File > Install CIA);
- `build/azahar/SteelDiverSubWars_original.cxi`: or to open directly (Azahar > File > Load File).

`tools/mod.py build <mod> --cxi` adds `SteelDiverSubWars_<mod>[_<server>].cxi` there, the game with the mod's code
patch already applied, to keep the original version and the modded one side by side. `build/azahar/README.txt` says
what each file is for. They are copies of the game: they are not to be shared.

## Building and installing a mod

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/mod.py list                       # the mods available
.venv/bin/python tools/mod.py build title-text           # -> build/mods/title-text/
.venv/bin/python tools/mod.py build title-text --install
.venv/bin/python tools/azahar.py uninstall               # back to the original game
```

`--install` copies the mod into Azahar's folder (`load/mods/00040000000D7E00/`, Flatpak or native version found
automatically, or the variable `AZAHAR_DIR`). Only one mod folder is active at a time. `make extract` (or the launcher's
Game tab) must have run first: the recipes apply to the files extracted from the dump.

The mod is built for the version of the game the emulator runs: the v0, or the **update v5200** if it is installed
there ([../docs/update-v5200.md](../docs/update-v5200.md)). `--version v0` or `--version v5200` chooses one;
`tools/mod.py list` says which versions each mod works with. A build for the v5200 goes into
`build/mods/<name>-v5200/`.

```sh
.venv/bin/python tools/azahar.py install-update            # the update (its decrypted CIA in cia/) into Azahar
.venv/bin/python tools/azahar.py where                     # the game's version in each emulator, the mods installed
.venv/bin/python tools/azahar.py uninstall-update          # back to the v0
```

Every build includes the game's **fixes** (`mods/fixes`, `always = true`), unless `--no-fixes`;
`tools/mod.py build fixes --install` installs them alone. The older French names of the mods and of their options
(`en-ligne`, `triche`, `--set facteur=5`...) are still understood.

## Writing a recipe: `mods/<name>/mod.toml`

*Estimated progress: 100 %.*

```toml
name = "My mod"
description = "What it changes"

[[text]]                                  # a text of the game, in every language
key = "title_version"                     # key <string key=...> of extracted/xml/text/*.xml
text = "Modded version"                   # \n for a new line, ${option} for a value given when building;
                                          # a character missing from the font is reported
languages = ["EU_English"]                # optional
# like = "internet_mode_warning"          # optional: a key the game lacks, created after this one's model
                                          # (font, line spacing)
# or append = "\none more line"           # instead of text: added at the end, after every text = of the build
                                          # (several mods on the same line)

[[bxml]]                                  # any BXML file, changed as its XML (make data)
file = "worlds/scope00_online_stage01.bxml"
select = "actor[@name='mode_settings']"   # ElementTree path from the root
set = { timeLimit = "2400.0" }            # values written as in the XML: 2400.0 is an f32, 60 an s32
# rename = { old = "new" }                # renames attributes without moving them (before set)
# remove = true                           # or: removes the nodes selected

[[amx]]                                   # a Pawn script; addresses of decomp/scripts/asm/<script>.asm
file = "amx/periscope_move.amx"
at = 0x5D4C                               # a string of the data segment (without "at": all of them)
string = "player.muteki"
replace = "mode.ready"                    # not longer than the original
# or an operand of an instruction: address = 0x130D0, operand = 0, value = 1, expect = 0
# (jumps are relative to the instruction: value = 8 jumps to the next instruction)
# or Pawn code added to the script: asm_file = "file.pasm" (in the mod's folder) or asm = "..."

[[shader]]                                # an instruction of a PICA200 shader (shaders/*.shbin)
file = "shaders/metaball.shbin"
instruction = 0x084                       # its number in the code, as tools/shbin.py shows it
expect = 0xA4021800                       # optional: the original instruction
value = 0x84000000                        # nop

[[code]]                                  # a patch of the code, at an address of code.bin (syntax example)
address = 0x0021A82C
bytes = "8988883c"                        # or: arm = "mov r0, #1" (assembler tools/armasm.py),
                                          # ascii = "text", utf16 = "text", words = ["0x1234"]
                                          # (the labels of an arm block: ${arm_<label>} afterwards)
expect = "8988083d"                       # optional: bytes expected, protects against other versions
max_size = 116                            # optional: maximum size (the end of the function replaced)

[params.server]                           # optional: a value given when building
help = "address of the server"            #   tools/mod.py build <name> --set server=1.2.3.4
default = "127.0.0.1"                     # and used in the [[code]] entries as ${server}
# choices = ["2", "3", "5"]               # or: the only values accepted (a list in the launcher)

[identity]                                # optional: a player identity for an online server
scope = "${server}:${port}"               # gives ${pid}, ${password} and ${token}
```

An identity is created once per server and kept in `~/.config/sub-wars-open-sourced/identities.json`: building the mod
again keeps the same account.

Other possibilities:

- `from = "bxml/x.bxml"` in `[[bxml]]` creates a new file, a copy of that one, and
  `copy = { file = "...", select = "..." }` takes the attributes of a node of another file;
- `files = "bxml/pscope_ply??_stats.bxml"` (a pattern) instead of `file` in `[[bxml]]`, and `scale = "${factor}"`,
  which multiplies every number of the nodes selected (after `set`);
- `extract = "bxml/x_{stem}.bxml"` in `[[bxml]]` (with `files`): instead of changing them, a new properties file per
  file, holding attributes of the node selected (`keep = [...]`, `rename = {...}`, `floats = true`): that is how the
  online bots get the maps' spawn points;
- `[[music]] dir = "${folder}"`: the player's own music as the game's streams (`tools/music.py`);
- `if = "${option}"` on any entry (applied only if the option is `yes`), or `unless = "${option}"` (only if it is `no`);
- `token_flags = ["cheats"]` at the top of a recipe (told to the online server in the token); `always = true` at the
  top of a recipe: the mod is part of every build (the game's fixes);
- every recipe also gets `${sdsw_version}`, the version of Sub Wars Open Sourced (the `VERSION` file, and the number of
  commits in a git checkout: "v0.1.34");
- `[[layout]]` (`file`, `pane`, `width`, `height`) changes the size of a frame of a layout (`layouts/*.arc`): the game
  squeezes a text wider than its frame.

### Versions of the game

*Estimated progress: 100 %.*

A recipe that patches by address (`[[code]]`, `[[amx]]`, `[[shader]]`) says which versions of the game it works with;
a recipe that only touches data by name (texts, BXML values) works with all of them:

```toml
versions = ["v0", "v5200"]                # at the top of the recipe

[[code]]
address = { v0 = 0x00176C8C, v5200 = 0x00177FF0 }    # a version table: one value per version
expect = "1f402de9"
arm = "bl ${GetUserName}"

[symbols]                                 # addresses to use in the code (${GetUserName}), per version
GetUserName = { v0 = 0x0018A458, v5200 = 0x0018FEA4 }
```

Any value of an entry can be a version table (all its keys are versions: `v0`, `v5200`): `address`, `expect`,
`asm_file`, `asm`... `address` can also be a text such as `"${GetUserName}"`. The files read are those of the version
built: for the v5200, the update's first, then the game's. Each build writes `sdsw.json` (version and mods) into the
mod's folder: the launcher thus sees when the installed mods no longer match the game's version. A mod always included
(`always = true`) that does not work with the version built is left out, with a message.

**Several mods together**: `tools/mod.py build online cheats ...` builds them into a single folder
(`build/mods/online+cheats/`), since Azahar only loads one.

The addresses and names come from the decompilation (`decomp/`, `ghidra/symbols.txt`); the formats are described in
[../docs/formats.md](../docs/formats.md).

### Pawn code (`.pasm`)

*Estimated progress: 95 % — the whole instruction set, and compiled Pawn (`tools/pawn2pasm.py`).*

`tools/amxasm.py` assembles Pawn code (the mnemonics of `decomp/scripts/asm/`) and adds it at the end of a script:
nothing that exists moves. `.hook <address>` replaces the instruction(s) at this address (8 bytes at least) with a
jump to the code that follows; `.original` plays them again, `.return` comes back after them. Example (the lobby's
120-second countdown replaced by a variable):

```
.hook 0xebf8                    ; const.alt 0x1d4c0
    push.pri
    push.c "server.bots.countdown"
    sysreq.n sysGetGlobal, 1    ; a native by its name, and its number of arguments
    move.alt
    pop.pri
    .return
```

Also: functions (`name:` then `proc` ... `retn`, called with `call @name`), `.public @name` (one more public
function), `.var $name [cells]`, `.cells $name 1, 2`, `.string $name "text"`, strings between quotes (kept in the
script's data), the script's globals by their address (`g_504c`), `float(1.5)`. A native missing from the script is
added to its table. See the `bots_*.pasm` of [online](online/).

Longer code is written in Pawn: `tools/pawn2pasm.py src/x.p` compiles it with the Pawn 3.3 compiler (`make pawncc`, a
developers' tool) and writes `x.pasm`, which is published. The script's globals are declared
`// @game Float:g_1ca0[3]` and its functions `// @call 0x2ea0 name(parameters)`. The compiled code reads and writes
these globals at their real address, and its own data goes after the script's (`.data_at`). The hooks stay written by
hand, in `/* asm ... */` comments of the source. Example: the bots' pilot,
[`online/src/bots_pilot.p`](online/src/bots_pilot.p) ([../docs/bots.md](../docs/bots.md)).

## The mods available

*Estimated progress: 100 % — list up to date.*

| Mod | Versions | Effect |
|---|---|---|
| `fixes` | v0, v5200 | always included: fixes Azahar's crash when a torpedo hits a submarine underwater |
| `nickname` | v0, v5200 | always included: online and offline, your name is the console's (emulator's) nickname, not "Citra" |
| `version` | all | always included: the version of Sub Wars Open Sourced at the end of the line under the title ("... v0.1.34", in the same font as the line above) |
| `premium` | v0, v5200 | the full version, every submarine (23, 39 with the update), patterns and crew unlocked, without the eShop ([details](../docs/premium.md)) |
| `missions` | v0, v5200 | the 21 single-player missions playable at once, without touching the save |
| `online` | v0, v5200 | online play on a [Sub Wars Open Sourced](../server/README.md) server, with its bots for a player alone, which play like players ([bots.md](../docs/bots.md)), its anti-cheat, the length of the battles set by the server and a dialog that says which server is used |
| `music` | v0, v5200 | your music (MP3, WAV... converted by the launcher's Music tab, or `tools/music.py`) in place of the game's, at the same loudness; nothing changes online |
| `specs` | v0, v5200 | your own characteristics of the submarines (`tools/subs.py`); counted as cheating online |
| `title-credits` | all | "© 2026 Nintendo Lawyers" and "Open Sourced by gabrielb0x." under the title (options `line1`, `line2`) |
| `cheats` | v0, v5200 | invincible, infinite torpedoes and air, firing without delay, fast reload, free masker, boosted engine |
| `speed` | all | your submarine goes 2, 3, 5, 10 or 15 times faster (option `factor`); counted as cheating online |
| `title-text` | all | an example: "Free version" becomes "Modded version" on the title screen |

"v0": the game without its update; "v5200": with the update ([../docs/update-v5200.md](../docs/update-v5200.md)).

## Console nickname

*Estimated progress: 100 % — checked in Azahar.*

Included in every mod. Online as offline, the game shows for each player the name of their Mii, which each console sends
to the others. Under an emulator, nobody has a Mii of their own: the emulator gives the same one to everybody,
"Citra". The mod replaces this name with the **console's nickname**, the one you set in the emulator (Azahar: Emulation
> Configure > System > Username; the same setting in Citra, Lime3DS, Mandarine, Borked3DS), 10 characters at most. The
Mii's face does not change; an empty nickname keeps the Mii's name. Checked in Azahar: the lobby shows the console's
nickname instead of "Citra".

## Fixes

*Estimated progress: 100 %.*

Included in every mod. Without them, in Azahar, a torpedo that hits a submarine underwater freezes the game, then Azahar
closes: it fills the memory (5 GB of RAM and 4 GB of swap on a 7 GB machine) until the system kills it ("Out of memory"
in `journalctl -k`). The cause is a bug of Azahar's shader JIT, triggered by the oil leaking from a hit submarine; the
fix rewrites two instructions of the shader concerned without changing anything in the picture. Full explanation:
[../docs/mods.md](../docs/mods.md#fixes). Checked in Azahar: without the fix, memory goes from 1.2 to 3.4 GB in 4
seconds as soon as an oil slick is on screen; with it, it stays at 1.2 GB and the oil shows.

```sh
.venv/bin/python tools/mod.py build fixes --install     # without any other mod
```

If you want no mod at all, unchecking "Enable Shader JIT" in Azahar (Emulation > Configure > Graphics) also avoids the
bug, at the cost of a slower emulator.

## All missions

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/mod.py build missions --install
.venv/bin/python tools/mod.py build premium missions --install
```

The missions menu opens a mission when the previous ones of its area are completed, and an area according to the total
number of missions completed; in the free version, it only starts the first two areas. The mod counts each mission as
completed and opens every area, without writing anything to the save: your medals and times stay yours (the total shown
at the top of the menu says 21). Removing the mod puts the menu back as it was; to mark the missions completed for good:
`tools/save.py unlock missions`.

## Submarine speed

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/mod.py build speed --set factor=5 --install        # 2, 3, 5, 10 or 15
.venv/bin/python tools/mod.py build premium cheats speed --set factor=15 --install
```

Your submarine goes `factor` times faster, at the surface, underwater and in reverse, and reaches this speed in the same
time as before; turning, the dive and the other submarines do not change. The mod multiplies the two tables that turn
the speed ratings into acceleration (`bxml/table_above_accel` and `table_below_accel`): the game's top speed is about 25
times the acceleration (a drag of 3.8 % per frame). Online, the server counts it as cheating.

## Premium

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/mod.py build premium --install                                     # offline
.venv/bin/python tools/mod.py build online premium --set server=192.0.2.10 --install      # online
```

The full version ("premium") and the five historical submarines were sold on the eShop, closed since 2023. All their
content is in the base game, except the prow of the historical submarines: without the DLC, their pilot sees the prow
of a game submarine of the same size (the other players only ever saw the hull). Options: `unlock` (`yes`: every
submarine, pattern and crew member is unlocked in the save) and `dlc` (`yes` only if your own DLC is installed in
Azahar: the historical submarines' real models). The Shop button reloads the menu. Removing the mod does not lock the
save; a save flagged "premium" by another version is repaired with `tools/save.py premium-off`. How it works:
[../docs/premium.md](../docs/premium.md). Online, this mod does not count as cheating.

## Changing the characteristics of the submarines

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/subs.py show                         # the submarines and their characteristics
.venv/bin/python tools/subs.py export                       # your file, with the game's values
.venv/bin/python tools/subs.py set "Type VII" torpedoMax=10 maxTurn=9    # or edit the file by hand
.venv/bin/python tools/mod.py build premium specs --install
```

The file (`submarines.toml`, in `~/.config/sub-wars-open-sourced/`; `%APPDATA%\sub-wars-open-sourced\` on Windows;
`submarines-v5200.toml` for the update) lists each submarine with its values commented: ratings of turning, surface and
underwater speed, armour and dive (1 to 10, which the game turns into numbers through its tables `bxml/table_*`),
torpedoes, reload, rate of fire, torpedo model, crew places, the masker's air, and some fine-tuning of the physics.
`tools/subs.py check` says what differs from the game; values the game does not support are refused. Meant for offline
play: online, the server treats it as cheating.

## Changing the music

*Estimated progress: 80 % — conversion and listening checked in the launcher (MP3 decoded by the browser), streams read
back by `tools/bcstm.py`; remains to be heard in Azahar.*

The simplest way: the launcher's **Music** tab. Each music of the game is named there (title screen, missions, each
online map, calm and in combat...): "Game" plays it, "Replace" takes an audio file (MP3, WAV, OGG, FLAC, M4A..., what the
browser can read), "Yours" plays the result, the restore button brings the game's back, "Restore the original music"
brings them all back. "Apply in the emulator" installs your mods again with this one. On the command line:

```sh
python3 tools/music.py list                           # the game's music and what you replaced
python3 tools/music.py export Title_lr -o title.wav   # listen to the game's
python3 tools/music.py set Title_lr my-music.wav      # a WAV (the launcher also takes MP3...)
python3 tools/music.py reset --all                    # the game's again
.venv/bin/python tools/mod.py build premium music --install
```

The game reads its music in `audiores/stream/*.bcstm` (DSP-ADPCM, 32,728 Hz, looping); the sounds of the archive
(`audiores/sound_data.xml`, shipped with the game) say which plays when. Yours is converted to the channels and rate of
the one it replaces, and kept as a WAV in the `music` folder of the settings folder. **Matched loudness** (by default, a
switch per music): the launcher measures the loudness of the original and of yours (mean power over 400 ms blocks,
leaving out silences and quiet passages, as the LUFS of the EBU R 128 standard, without their weighting filter), then
raises or lowers yours by the difference. Peaks that would go past full scale are rounded off by a soft limiter rather
than clipped: no jump in volume between a music of the game and yours. The tab shows the adjustment ("adjusted by
−4.5 dB"). The mod writes it as a PCM16 stream (which the game's player reads like its DSP-ADPCM streams; the game has
a PCM8 stream of its own, whose layout `tools/bcstm.py` reproduces byte for byte), looping from the start. The music
only changes on your side: nothing online.

## Cheats

*Estimated progress: 100 %.*

```sh
.venv/bin/python tools/mod.py build cheats --install                                  # offline
.venv/bin/python tools/mod.py build online cheats --set server=192.0.2.10 --install   # online
.venv/bin/python tools/mod.py build cheats --set engine=no --set reload=no --install
```

Options (all `yes` by default): `invincible`, `torpedoes`, `air`, `reload`, `rapid_fire`, `masker`, `engine`. With
`rapid_fire`, each press of A (or ZR) fires a torpedo, without delay between two shots; with `torpedoes` too, the stock
never goes down. The invincibility and the infinite torpedoes and air reuse the `player.muteki` flag of the developers'
test mode; the rest changes the characteristics of the submarines. Checked in a single-player mission: torpedoes that
do not go down, hull intact under the bombs. Online, the server knows you cheat and, depending on its configuration,
only lets you play with other cheaters.

## Playing online

*Estimated progress: 95 % — left: seeing the new bots in Azahar.*

```sh
make extract                                               # once: the dump's files
.venv/bin/python tools/mod.py build online --set server=192.0.2.10 --install
```

`server` is the server's address (IP or name, 31 characters at most; `127.0.0.1` by default, for a server on the same
machine) and `port` its authentication port (61000 by default, the emulator players' realm). For a server at a
friend's, its public address: the friend's launcher shows it (Server tab), and
`python3 -m sdsw_server.testclient --probe <address>` (in `server/`) checks that it answers
([../server/README.md](../server/README.md#play-with-friends-far-away)). Then, in the game: *Multiplayer > Internet
Battle*. The game does not need to be modified: Azahar applies the patch (`exefs/code.ips`) at launch.

Why a patch is needed and what it changes: [../docs/online.md](../docs/online.md).
