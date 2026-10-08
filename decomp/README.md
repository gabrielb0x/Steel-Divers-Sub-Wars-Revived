# Pseudo source code

## `raw/` — Ghidra's raw output (generated, not versioned)

*Estimated progress: 100 % — every function exported, sorted by original object file.*

`make export` (or `ghidra/export.sh`) decompiles every function and puts each one into the object file it comes from,
according to the linker's symbol table (`romfs:/map`):

```
raw/source/main.cpp, raw/source/net/session.cpp, ...   the game's code (original paths when they are known)
raw/lib/libnw_gfx/gfx_Model.cpp, ...                    NintendoWare, SDK, NEX, Pia, C runtime
raw/unmapped/0x00330000.cpp, ...                        functions missing from the map, by 64 KiB slices
raw/functions.csv                                       address, size (map / Ghidra), name, object, file
```

Each function is preceded by its address and its size in the map.

## `scripts/` — decompiled Pawn scripts (generated, not versioned)

*Estimated progress: 100 % — the 123 scripts decompiled; how readable they are depends on the names of `pawn/`.*

`make scripts` disassembles (`scripts/asm/*.asm`) and decompiles (`scripts/*.p`) the 123 scripts `romfs:/amx/*.amx`. See
[../docs/pawn-scripts.md](../docs/pawn-scripts.md).

## `pawn/` — knowledge about the scripts (versioned)

*Estimated progress: 35 % — 343 natives prototyped out of 647; 236 names of functions and globals, about 1,400 groups of
functions remain to be named.*

- `pawn/natives.inc`: Pawn prototypes of the natives (parameter names, `Float:`, references) and enumerations (`UID`,
  `BUTTON`), written from the C++ implementations;
- `pawn/symbols.txt`: names of the script functions without logs and of their parameters, and names of globals; a name
  applies to every copy of the function in the other scripts.

## Improving the pseudo-code

*Estimated progress: 15 % — classes rebuilt: `World`, `Actor`, `AMXLoader`, `NsubShop`...; most of the game's classes
remain to be typed.*

The Ghidra database is disposable (`make analyze` recreates it). Everything we understand goes into two versioned files,
applied again at every export:

- `ghidra/symbols.txt`: name and C prototype of functions (those missing from the map, or whose signature we know);
- `ghidra/types.h`: structures, enumerations and typedefs rebuilt.

Working loop: read `raw/`, check in the disassembly, complete `symbols.txt` / `types.h`, `make export`.

A known trap: `armlink` merges functions with identical code. A call can therefore carry the name of another function
(e.g. an emptied debug `printf` that shows as `Renderer::getActiveMask("source/main.cpp", ...)`).

## `src/` — cleaned code (versioned)

*Estimated progress: 9 % — 185 of the game's 2,126 functions rewritten (about 11 % of the game's code, Nintendo's
libraries aside).*

C++ rewritten by hand from the pseudo-code, with the same tree as `raw/source/`:

| File | Content |
|---|---|
| `main.cpp` | start-up, main loop at 30 fps, sequence of the modes |
| `amx/amxloader.cpp` | script loaders: list, frame-by-frame execution, messages, delayed calls, observers |
| `game/world.cpp` | the world: pool of 256 actors, loading the levels, 7-second replay buffer |
| `game/actor.cpp` | an actor's life cycle: properties, script and its public functions, death |
| `sys/system.cpp` | start-up, memory heap, time, HOME and power buttons |
| `net/connectionInternet.cpp` | online play: the console's network, connection to the server, match search (criteria, attributes, version checksum), session created or joined, block list, notifications |

Conventions:

- keep the original names of classes, methods and files (those of the map and of the `__FILE__` strings);
- give the original address above each function (`// 0x00101118`);
- do not copy the game's data (tables, texts, assets): read them from the RomFS.
