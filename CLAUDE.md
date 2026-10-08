# Steel Diver: Sub Wars — Open Sourced

Reverse engineering of the 3DS game (EUR, title 00040000000D7E00, v0) with three goals: readable pseudo-source
(`decomp/`), a native PC port (`port/`), and an online server (`server/`). The repository is public: docs, code,
comments, the launcher and the tools' messages are in English. The user writes in French: replies to them in French.

## Hard rules

- Never commit game data or anything derived mechanically from it: `cia/`, `extracted/`, `decomp/raw/`,
  `ghidra/project/` stay gitignored. Tools must read the user's own dump at runtime. Mods are recipes
  (`mods/<name>/mod.toml`) applied to the dump at build time; built mods and modified game files are never committed.
- Targets: the EUR v0 executable and its update v5200 (title 0004000E000D7E00, docs/update-v5200.md), mods for the
  Azahar emulator, then the PC port. Not real 3DS. The RE pipeline (Ghidra, decomp/) works on v0.
- The repo is MIT-licensed: never copy GPL/AGPL code (Pretendo, Azahar/Citra) into it; use it as reference only.
- Ghidra must live in a path without non-ASCII characters (its log4j config fails on them): it is in
  `~/tools/ghidra_12.1.4_PUBLIC`, referenced by `local.env`.
- Names were French before the project went English (mods `en-ligne`, `triche`..., options `facteur`..., server values
  `separes`, `difficile`..., settings files `identites.json`, `sous-marins.toml`...): the code still accepts them
  (mod.MOD_ALIASES, mod.PARAM_ALIASES, server config.VALUE_ALIASES, azahar.settings_file) and writes English.

## Pipeline

```
./setup.sh      venv (.venv) + Ghidra detection -> local.env
make extract    tools/extract_cia.py  -> extracted/{code.bin,exefs,ncch,romfs,manifest.json}, the update -> extracted/v5200/
make elf        tools/code2elf.py     -> extracted/nsub.elf
make analyze    ghidra/analyze.sh     -> ghidra/project/ (import + romfs map symbols + auto-analysis)
make export     ghidra/export.sh      -> decomp/raw/ (pseudo-code per original object file + functions.csv)
make scripts    tools/native_types.py, tools/amx.py, tools/amxdec.py (+ amxsym.py) -> decomp/scripts/ (Pawn asm + pseudo-Pawn)
make data       tools/bxml.py -> extracted/xml/ (BXML: levels, stats, texts; name hash = zlib CRC-32)
make azahar     tools/azahar.py prepare -> build/azahar/ (CIA without the encrypted manual, which Azahar rejects; CXI)
tools/mod.py build <name>... [--install] [--cxi] [--version v5200]   mods/<name>/mod.toml -> build/mods/<a+b>[-v5200]/
                    -> Azahar load/mods/00040000000D7E00/ (for the version each emulator runs; sdsw.json marker)
tools/azahar.py install-update | uninstall-update | where    the update on the emulators' SD card
tools/save.py, tools/subs.py                        save editor (Azahar save), submarine characteristics (mod "specs")
tools/music.py, tools/bcstm.py                      your music in place of the game's BCSTM streams (mod "music")
tools/shbin.py <file.shbin> [--check]               PICA200 shader disassembler; --check: loops Azahar's JIT runs wrong
make pawncc bots     build/pawncc (Pawn 3.3, built with -D_I32_MAX/_I32_MIN: else cellmin = 0 on 64 bits), then
                     tools/pawn2pasm.py mods/online/src/*.p -> mods/online/*.pasm (Pawn source of the bots' AI)
tools/botsim.py                                     bot sandbox: AMX interpreter + small world (docs/bots.md)
python3 subwars.py                                  players' launcher: local web UI (tools/webui.py + webui.html)
python3 -m unittest discover -s tools/tests         tests of the players' tools (no game file needed)
cd server && python3 -m sdsw_server        online server (realms "emulator" and "pc", server.toml); tests: python3 -m unittest discover -s tests -t .
```

Players' tools (subwars.py, mod.py, save.py, subs.py, music.py, bcstm.py, extract_cia.py) must run with Python 3.11 alone on
Windows/macOS/Linux: no pip package (tools/ncch.py reads NCCH/RomFS, tools/armasm.py assembles the recipes' ARM;
its encodings are checked against keystone in tools/tests). Only the RE pipeline uses the venv (capstone).

The Ghidra database is disposable (analyze.sh recreates it, keeping one backup in `ghidra/project.bak/`).
Knowledge goes into versioned text applied by `ApplySymbols.java` on every analyze/export:
`ghidra/symbols.txt` (`<address> <qualified name> [: <C prototype>]`) and `ghidra/types.h` (plain C, no macros).
Only add verified facts. Beware armlink identical-code folding: a call can carry another function's name.
Same for the Pawn scripts: `decomp/pawn/natives.inc` (native prototypes, enums) and `decomp/pawn/symbols.txt`
(`<script>:<address> name(params)`, propagated to every copy of the function in the other scripts).

Ghidra scripts are Java (`ghidra/scripts/`), compiled by Ghidra 12.1.4; check them with
`javac -cp "$(find ~/tools/ghidra_12.1.4_PUBLIC/Ghidra -name '*.jar' | tr '\n' :)" -d build/javac ghidra/scripts/*.java`.

## Key facts

- `romfs:/map` is the armlink symbol listing: 9431 functions (address, size, demangled name, object). Applied by
  `ImportSymbolMap.java`; it is the ground truth for names and object/file grouping.
- Segments: .text 0x00100000, .rodata 0x00352000, .data 0x00386000, .bss 0x003B4AE4. All code is ARM (no Thumb in
  the map), hard-float VFP ABI (floats in s0..). armcc places string literals inside .text, right after the
  functions using them.
- Game logic is largely Pawn (AMX file version 10 = Pawn 3.3, compact encoding, no packed opcodes) in
  `romfs:/amx/`. 647 natives in 15 packed (unaligned) AMX_NATIVE_INFO tables, found via amx_Register call sites.
  HALT 12 is `sleep` (yield one frame). Pawn 3.3 sources for reference: build/ref/compuphase-pawn @ 6d82fa4.
- armlink eliminated unused virtuals (vtable slots set to 0) and folded identical functions.
- Premium = add-on content title 0004008C000D7E00 checked by NsubShop (source/sys/dlc.cpp): content 91 is the full
  version, 1-5 the historical subs 19-23 (their prow models only exist in the DLC). docs/premium.md, mods/premium.
  Never use a DLC CIA that is not the player's own purchase (a "piratelegit"/generated ticket has console id 0).
- Save: "data:/save" = CRC-32 + script globals named save* (version 27); docs/formats.md#save.
- Online: NEX 3.7 (auth, matchmaking, NAT traversal) + Pia P2P, fully documented in `docs/online.md` and checked
  with the real game: PRUDP v1, RC4 "CD&ML" before the Kerberos session key, aggregate ACKs (MULTI_ACK, substream 1).
  Azahar's frd:u lacks game authentication, hence the `online` mod. Pretendo's server (Go, AGPL-3.0) is cloned for
  reference in `build/ref/pretendo-sdsw`; Azahar sources (GPL, reference only) in `build/ref/azahar` (sparse).
- Remote play: to join, Pia uses the host's private URL when the host's public IP equals its own, else the public
  one (pia::inet::NexConnectStationJob::StartupImpl). The server (`internet.py`) shows consoles on its own network
  (127.0.0.1, LAN) with its public address (Register, NAT check, URLs) and forwards their Pia port (random
  49152-65534) by UPnP: without it, Linux NATs lose the hole-punching race (netns simulation, docs/online.md §7).
  `public_address = "auto"` (UPnP, then STUN), `upnp = true`. The launcher stops any `sdsw_server` holding the
  ports before starting its own, and starts it with `--exit-with-stdin`. Never `pkill -f` a pattern that also
  matches the shell running the command.
- Online bots (docs/bots.md): our pilot replaces surface_sub's (which sets its position without reading its
  collisions, and whose "enemy" torpedoes skip every computer sub and only damage the local player). Pawn source
  in mods/online/src (`// @game g_X`, `// @call 0xADDR f()`, hooks in `/* asm */`); the generated .pasm are
  committed. worldClipLine(from, dir, length, typeMask) returns the distance to the first hit;
  worldFindActors(found, center, radius, typeMask, max) only finds visible actors. @eventCollide(other, point,
  normal...): normal points away from the other actor.
- Azahar crash "torpedo hits a sub underwater" = OOM kill, not a game bug: Azahar's x64 shader JIT clobbers the
  outer LOOP counter when a subroutine CALLed from a loop has its own LOOP (geometry shader of the oil metaballs,
  shaders/metaball.shbin) -> ~4e9 iterations emitting triangles. mods/fixes (always = true, in every build)
  NOPs the two loops. `journalctl -k` shows such OOM kills; Azahar's own log only flushes on errors.
- Testing in Azahar: portable profiles in `~/.var/app/org.azahar_emu.Azahar/sdsw-test/<p>/user/`
  (`flatpak run --cwd=<p>`), shown in Xephyr. The machine has 7 GB of RAM: OpenGL under Xephyr can reach 5 GB per
  instance (two got OOM-killed) and the software renderer runs at 3 %: one instance at a time.

- Update v5200 (docs/update-v5200.md): new executable (all addresses move, no romfs:/map: names come from matching
  v0 functions), 16 more subs, 3 maps, recompiled scripts. Its RomFS only holds changed/added files: the game
  opens "rom2:/" (update RomFS, SelfNCCH path type 5) then "rom:/" (v5200 0x00257ACC); tools/versions.py layers
  extracted/v5200/romfs over extracted/romfs. Azahar applies load/mods/00040000000D7E00/ to the update too, so a
  mod is built per version: recipes declare `versions = [...]` and give version tables `{ v0 = ..., v5200 = ... }`
  (+ `[symbols]`); tools/tests checks every recipe that patches by address declares its versions.

See `docs/initial-analysis.md` and `docs/roadmap.md`.
