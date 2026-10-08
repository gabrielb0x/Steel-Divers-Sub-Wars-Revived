# Roadmap

## Part 1 — Pseudo source code (`decomp/`)

*Estimated progress: 20 % — everything is exported and the scripts are decompiled, but only 9 % of the game's code
is cleanly rewritten.*

Goal: readable C++ code that shows how the game was written.

Done:
- [x] CIA extraction, `code.bin` → ELF conversion (`tools/`)
- [x] Ghidra project: 9,431 functions named from `romfs:/map`, 439 functions found through the tables of pointers,
      SVC wrappers annotated (`ghidra/scripts/`)
- [x] Export of the raw pseudo-code, one file per original object file (`decomp/raw/`, generated locally)
- [x] Versioned knowledge (`ghidra/symbols.txt`, `ghidra/types.h`) applied again at every export; first entries:
      C runtime (`memcpy`, `strlen`, `__aeabi_uidiv`...), `operator new`, prototypes of the start-up sequence
- [x] First cleaned file: `decomp/src/main.cpp` (start-up, the "modes" system, 30 fps loop, stereo rendering)
- [x] Pawn scripts: disassembler + decompiler (`tools/amx.py`, `tools/amxdec.py`), 123 scripts as pseudo-Pawn;
      647 natives found and typed in Ghidra, parameter types deduced from the C++ (`tools/native_types.py`)
- [x] `World` and `AMXLoader` classes (vtable) typed; Ghidra's false "no-return" fixed (378 → 41)
- [x] Shop and add-on contents (`decomp/src/sys/dlc.cpp`, class `NsubShop` typed), save
      (`decomp/src/sys/savedata.cpp`, save globals and natives in `decomp/src/amx/amxsys.cpp`)

To do:
1. **Types**: rebuild the game's classes (`Actor`, `World`, `Session`, `Connection`, `Model`...) in Ghidra from the
   constructors and vtables, then export again: the pseudo-code becomes much more readable.
2. **Cleaning** module by module in `decomp/src/`, with the same tree as `source/`, starting with `main.cpp`,
   `sys/system.cpp`, `game/world.cpp`, `game/actor.cpp` and `amx/*` (the natives the scripts call).
3. **Pawn scripts**: native prototypes written (`decomp/pawn/natives.inc`), names propagated across scripts, Pawn
   states decompiled; keep naming the ~1,400 groups of functions left and the globals (`decomp/pawn/symbols.txt`).
4. ~~**In-house formats**~~: BXML both ways (`tools/bxml.py`, readable XML, rewritten byte for byte for the 490
   files); `hmap` and `edge` fully documented ([formats.md](formats.md)).

## Part 2 — PC port (`port/`)

*Estimated progress: 0 % — strategy chosen, nothing written.*

Recommended approach: **static recompilation + HLE, then progressive replacement by the decompiled code** (the
method of Zelda64Recomp or Unleashed Recompiled).

- The game runs on PC long before the decompilation is finished.
- Nintendo's libraries (NEX, Pia, NintendoWare, SDK: 80 % of the code) run as they are, without being rewritten.
- The original network stack works on PC sockets, so it stays compatible with NEX servers.
- Each function decompiled in part 1 can replace its recompiled version: that is where the improvements will be
  made (widescreen, high resolution, 60 fps).

Steps:
1. **ARM11 → C recompiler** (`tools/recomp/`): ARMv6K + VFPv2, list of functions from the map and Ghidra, `switch`
   tables, indirect calls (vtables) through an address → function table.
2. **Runtime** (`port/runtime/`): 3DS memory space, threads and synchronisation (SVC), HLE of the services used:
   `fs` → RomFS + saves, `hid`/`ir` → keyboard/gamepad, `apt`, `cfg`, `ptm`, `ac`, `frd`...
3. **Rendering**: PICA200 commands (through `gsp::Gpu` / `libgles2`) → OpenGL or Vulkan, two screens, upscaling.
4. **Audio**: HLE of the DSP (voices, ADPCM, mixing) → SDL.
5. **Network**: `soc:U`/`ssl:C`/`http:C` → PC sockets; `frd:u` (NASC authentication) → configurable server.

Alternative: a "pure source" port (decompile everything into compilable C++, rewrite the `nn`/`nw` layers). Cleaner
in the end, but nothing runs before everything is done.

## Part 3 — Online server (`server/`)

*Estimated progress: 90 % — left: see the new bots in Azahar, a real battle between two homes.*

Finding: the server only handles authentication, matchmaking and NAT traversal; the battles themselves are played
P2P through Pia. No NEX ranking or storage library is linked into the game.

1. ~~**Reverse engineering of the client**~~: PRUDP v1, Kerberos, RMC, NEX 3.7 structures, Pia's NAT detection,
   notifications ([online.md](online.md)).
2. ~~**Standalone server**~~ (Python, no dependency): TicketGranting, SecureConnection, NATTraversal, MatchMaking,
   MatchMakingExt, MatchmakeExtension, "nncs" servers; two separate realms, emulator and PC; options `max_players`
   (more computer subs) and `cheats` (cheaters allowed, separate or refused).
3. ~~**Validation with the game**~~: two Azahar instances with the `online` mod connect, find each other and play a
   battle together.
4. ~~**Public server**~~: public address found (router, STUN), ports opened by UPnP (checked with a consumer
   router), players of the server's network shown under the public address with their game's port forwarded
   ([online.md](online.md#7-distant-players-public-and-private-addresses)); validated by simulation (two Linux NATs
   in network namespaces); launcher: stopping a server already running, address to share, test.
5. ~~**Bots for a player alone**~~: alone for `bots_delay` seconds, the player plays against bots set by the server
   (teams 4v4, 1v4..., map, level, duration, names); they join the lobby like players, have real submarines, their
   name and level, and count for the victory. Checked in Azahar. The server sets the game through notifications of
   its own (script variables, [online.md](online.md#8-server--game-the-mods-variables)). The server's options are
   shown and editable in the launcher.
6. ~~**Bots that play like players**~~ ([bots.md](bots.md)): a player's submarine physics and characteristics,
   collisions with the map and the submarines, fighting any enemy (bots included), aiming where the target will be,
   dodging, homing torpedoes, masker and retreat, player spawn points, crews, varied maneuvers. Written in Pawn
   (`tools/pawn2pasm.py`), checked in a sandbox (`tools/botsim.py`); remain to be seen in Azahar. For a learnt AI,
   an estimate in [ai.md](ai.md).
7. **Next**: a real battle between two homes; a relay for strict NATs if needed; host migration and players leaving
   mid-battle to put to the test.

## Part 4 — Mods (Azahar, then the PC port)

*Estimated progress: 75 % — left: 60 frames/s (PC port), recompilable pseudo-Pawn, debug menu, a version checksum
of the gameplay mods.*

The detailed plan is in [mods.md](mods.md): we publish recipes (`mods/`), never a modified CIA.

1. ~~**Tooling**~~: game installable in Azahar (`tools/azahar.py`), mods as recipes built and installed by
   `tools/mod.py` (texts, BXML, IPS code patches).
2. **Pawn scripts**: ~~targeted patches~~ (strings and operands, compact re-encoding identical byte for byte:
   `tools/amx.py`, `[[amx]]` recipes, `cheats` mod); ~~assembler~~ (`tools/amxasm.py`: code, data, natives and
   public functions added, hooks on existing instructions, `.pasm` files); ~~Pawn compiler~~
   (`tools/pawn2pasm.py`: Pawn sources compiled into hooks); left: recompilable pseudo-Pawn. The developers' debug
   menu depends on it (its logic and display were removed).
3. ~~**Online play**~~: `online` mod (patch of the *friends* functions used by `JobCTRLogin`, NAT detection servers
   redirected, an identity per player). Left: a version checksum specific to the gameplay mods.
4. **60 fps**: an attempt in Azahar (an intermediate frame interpolated between two simulation steps, commit
   bfac07c) was set aside for now, too many glitches in the game ([mods.md](mods.md#60-and-120-frames-per-second)).
   To take up again in the PC port, where the rendering is ours: 60, 120 frames/s and more.
5. ~~**Premium**~~: `premium` mod (full version and add-on contents without the eShop, unlocks, historical submarines
   with a prow of the game), [premium.md](premium.md).
6. ~~**Save**~~: format decoded, editor `tools/save.py`.
7. ~~**Fixes**~~: Azahar's crash when a torpedo hits a submarine underwater (a bug of its shader JIT, worked around in
   `shaders/metaball.shbin`), mod `fixes` included everywhere ([mods.md](mods.md#fixes)).
8. ~~**Small mods**~~: `missions` (every mission), `speed` (submarine ×2 to ×15), firing without delay (`cheats`,
   option `rapid_fire`), `music` (your music, at the original's loudness).
9. ~~**Nickname**~~: online and offline, a player's name is their console's (emulator's) nickname, no more "Citra"
   for everybody (mod `nickname`, included everywhere).

## Decisions

*Estimated progress: 100 %.*

- **Versions of the game**: the launch version (v0, Europe), that of the dump, and its last update, v5200
  ([update-v5200.md](update-v5200.md)). Reverse engineering (Ghidra, `decomp/`) works on the v0; mods and online play
  work with both (the v5200's addresses found by matching: `tools/amxport.py` for the scripts), and the server never
  mixes players of both versions.
- **Targets**: mods for Azahar first, the PC port next (static recompilation + HLE). The 3DS is not a target.
- **The repository's licence: MIT**. GPL/AGPL code (Pretendo's server, Azahar/Citra) cannot be taken in as it is: it
  is used as a reference, and we write our own implementations.
