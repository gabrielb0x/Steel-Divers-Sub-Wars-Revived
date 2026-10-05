# Steel Diver: Sub Wars — Open Sourced

Reverse engineering of the 3DS game (EUR, title 00040000000D7E00, v0) with three goals: readable pseudo-source
(`decomp/`), a native PC port (`port/`), and an online server (`server/`). The user writes in French: docs and
replies in French, code and code comments in English.

## Hard rules

- Never commit game data or anything derived mechanically from it: `cia/`, `extracted/`, `decomp/raw/`,
  `ghidra/project/` stay gitignored. Tools must read the user's own dump at runtime. Mods are recipes
  (`mods/<name>/mod.toml`) applied to the dump at build time; built mods and modified game files are never committed.
- Targets: the EUR v0 executable (no update available), mods for the Azahar emulator, then the PC port. Not real 3DS.
- The repo is MIT-licensed: never copy GPL/AGPL code (Pretendo, Azahar/Citra) into it; use it as reference only.
- Ghidra must live in a path without non-ASCII characters (its log4j config fails on `Téléchargements`):
  it is in `~/tools/ghidra_12.1.4_PUBLIC`, referenced by `local.env`.

## Pipeline

```
./setup.sh      venv (.venv) + Ghidra detection -> local.env
make extract    tools/extract_cia.py  -> extracted/{code.bin,exefs,ncch,romfs,manifest.json}
make elf        tools/code2elf.py     -> extracted/nsub.elf
make analyze    ghidra/analyze.sh     -> ghidra/project/ (import + romfs map symbols + auto-analysis)
make export     ghidra/export.sh      -> decomp/raw/ (pseudo-code per original object file + functions.csv)
make scripts    tools/native_types.py, tools/amx.py, tools/amxdec.py (+ amxsym.py) -> decomp/scripts/ (Pawn asm + pseudo-Pawn)
make data       tools/bxml.py -> extracted/xml/ (BXML: levels, stats, texts; name hash = zlib CRC-32)
make azahar     tools/azahar.py prepare -> build/azahar/ (CIA without the encrypted manual, which Azahar rejects; CXI)
tools/mod.py build <name>... [--install] [--cxi]   mods/<name>/mod.toml -> build/mods/<a+b>/ -> Azahar load/mods/00040000000D7E00/
tools/save.py, tools/subs.py                        save editor (Azahar save), submarine characteristics (mod "specs")
tools/shbin.py <file.shbin> [--check]               PICA200 shader disassembler; --check: loops Azahar's JIT runs wrong
python3 subwars.py                                  players' launcher: local web UI (tools/webui.py + webui.html)
python3 -m unittest discover -s tools/tests         tests of the players' tools (no game file needed)
cd server && python3 -m sdsw_server        online server (realms "emulateur" and "pc", serveur.toml); tests: python3 -m unittest discover -s tests -t .
```

Players' tools (subwars.py, mod.py, save.py, subs.py, extract_cia.py) must run with Python 3.11 alone on
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
- Save: "data:/save" = CRC-32 + script globals named save* (version 27); docs/formats.md#sauvegarde.
- Online: NEX 3.7 (auth, matchmaking, NAT traversal) + Pia P2P, fully documented in `docs/online.md` and checked
  with the real game: PRUDP v1, RC4 "CD&ML" before the Kerberos session key, aggregate ACKs (MULTI_ACK, substream 1).
  Azahar's frd:u lacks game authentication, hence the `en-ligne` mod. Pretendo's server (Go, AGPL-3.0) is cloned for
  reference in `build/ref/pretendo-sdsw`; Azahar sources (GPL, reference only) in `build/ref/azahar` (sparse).
- Azahar crash "torpedo hits a sub underwater" = OOM kill, not a game bug: Azahar's x64 shader JIT clobbers the
  outer LOOP counter when a subroutine CALLed from a loop has its own LOOP (geometry shader of the oil metaballs,
  shaders/metaball.shbin) -> ~4e9 iterations emitting triangles. mods/correctifs (always = true, in every build)
  NOPs the two loops. `journalctl -k` shows such OOM kills; Azahar's own log only flushes on errors.
- Testing in Azahar: portable profiles in `~/.var/app/org.azahar_emu.Azahar/sdsw-test/<p>/user/`
  (`flatpak run --cwd=<p>`), shown in Xephyr. The machine has 7 GB of RAM: OpenGL under Xephyr can reach 5 GB per
  instance (two got OOM-killed) and the software renderer runs at 3 %: one instance at a time.

See `docs/analyse-initiale.md` and `docs/roadmap.md`.
