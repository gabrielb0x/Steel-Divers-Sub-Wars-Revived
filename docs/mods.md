# Mods: what is possible, and how to distribute them

Goal: that every player, with **their own copy** of the game, can apply a mod (online play on our server, 60 fps, new
features...). Two targets: the **Azahar** emulator now, and the **PC port** later, where mods will be simpler still. The
3DS itself is not a target.

## Distribute the mod, never the game

*Estimated progress: 100 %.*

A modified `.cia` holds the whole game: distributing it means distributing Nintendo's game, which is illegal and
against the repository's rule (no data of the game is published). We distribute **only the mod**, as a recipe
([../mods/README.md](../mods/README.md)): a list of changes that `tools/mod.py` applies to the player's files to make
the folder Azahar loads:

```
load/mods/00040000000D7E00/romfs/...        replaced files (texts, levels, scripts...)
load/mods/00040000000D7E00/exefs/code.ips   patch of the code
```

(paths checked in Azahar's code, `ncch_container.cpp`: the id in upper-case hexadecimal, `code.ips` or `code.bps`,
`romfs/`, `romfs_ext/`, `exheader.bin`). The Title ID above is the European version's.

**Installing the game into Azahar**: the eShop CIA also holds the electronic manual, which stayed encrypted, and Azahar
then refuses the whole installation. The launcher's *Set everything up* (or `tools/azahar.py install-game`) installs
the game itself on the emulator's SD card as *Install CIA* does (`title/00040000/000d7e00/content/`: the TMD reduced to
content 0 and its `.app`), keeping the save next to it (`data/`); `tools/azahar.py prepare` makes, on the player's
machine, a CIA holding the game alone (and a `.cxi` that loads directly).

**Version targeted**: the launch version (v0, Europe), that of the dump, and its update v5200
([update-v5200.md](update-v5200.md)). A code patch depends on the exact executable: recipes can check the original
bytes (`expect`) and give an address per version.

## Free room in the code

*Estimated progress: 100 % — a reserve of 1,940 bytes, 1,684 still free.*

To add ARM code, the executable needs room: either a function the patch makes useless (rewriting it shorter leaves its
end free), or code the game never calls. `SEQ_WRITELIST_Write` (0x0014BC90, 1,940 bytes, Mii library `libcfl`) is
referenced nowhere: no call, no aligned or unaligned pointer, no computed address (`add rX, pc`); the game never
changes the console's Mii database. It serves as a reserve, shared this way between the mods:

| Range | Mod | Content |
|---|---|---|
| 0x0014BC90-0x0014BD8F | `nickname` | the console's nickname in the player's Mii |
| 0x0014BD90-0x0014C423 | free | |

Data: the added code has no reserved room in RAM. It can allocate a block with the game's `operator new`
(0x00254000) and keep its pointer in one of the words of `main.o` that only the static initialiser writes (0x0038E628
to 0x0038E634; no other read or write in the executable), as the 60 frames/s attempt did.

In the Pawn scripts, room is no problem: `tools/amxasm.py` adds the code at the end of the script, and the script's
memory grows accordingly (the loader allocates `stp` + the stack asked for).

## What we can already change

*Estimated progress: 85 % — data, ARM code, Pawn scripts and music; not yet the models and textures.*

- **Data**: levels, statistics of the submarines and of the crew, texts, settings; `[[text]]` and `[[bxml]]`
  recipes. Formats in [formats.md](formats.md), including the levels'.
- **C++ code**: `[[code]]` recipes (bytes or ARM assembly), knowing the functions thanks to the game's symbol table and
  the decompilation.
- **Scripts**: the game's logic (modes, submarines, interface) is in Pawn ([pawn-scripts.md](pawn-scripts.md)).
  `tools/amxasm.py` adds code to them (Pawn assembly, hooks on existing instructions), and `tools/pawn2pasm.py`
  compiles Pawn sources into such hooks: that is how the online bots are made (`mods/online/src/*.p`). Next step:
  recompilable pseudo-Pawn with the Pawn 3.3 compiler.
- **Music**: `[[music]]` recipes write the player's own music as the game's streams (`tools/bcstm.py`,
  `tools/music.py`).

## Online play on our server

*Estimated progress: 90 % — a real battle between two homes remains.*

How the game finds its server (`source/net/connectionInternet.cpp`, `JobCTRLogin` of the NEX library):

1. `nn::friends::CTR::detail::Login`: the console's *friends* system module connects to Nintendo's friend server,
   then performs the NASC authentication.
2. `nn::friends::CTR::detail::GetGameAuthenticationData` returns the NASC result: the IP address and port of the
   game's NEX server, and a token. `JobCTRLogin::StepGameLogin` also reads the account's password (`GetMyPassword`)
   and calls `RendezVous::Login` (NEX authentication server), then the secure connection.
3. The rest (matchmaking, NAT traversal, P2P battles with Pia) goes through this server (see [online.md](online.md)).

**Done**: the [`online`](../mods/online/mod.toml) mod and the [`server/`](../server/README.md), checked with two
Azahar instances playing together. What follows explains the choice.

Two ways to redirect the game:

- **At the console's level** (Pretendo's method with Nimbus): patch the *friends* and *ssl* system modules so that
  they talk to another account server. Works for every game, but needs a whole account infrastructure (friends,
  NASC), and under an emulator a *friends* service that reproduces it.
- **At the game's level** (what we want): a code patch that replaces the connection to the friend server and the NASC
  result with our server's address and a token of ours, before `RendezVous::Login`. The mod becomes standalone: our
  server only has to accept the console's identifier (*principal ID*) and implement the game's NEX protocols.

Matchmaking only brings together consoles that announce the same version checksum (CRC-32 of the build number,
attribute 3): a mod that changes the gameplay must change this value so as not to meet players without the mod.

## Fixes

*Estimated progress: 100 % — the known crash is fixed, no other one is known.*

The [`fixes`](../mods/fixes/mod.toml) mod is part of every build (`always = true`).

**The crash when a torpedo hits a submarine underwater.** In Azahar, in a single-player mission, a few moments after a
torpedo hits a submarine underwater, the game freezes and Azahar closes. It is not the game that crashes: the kernel
log (`journalctl -k`) shows that Azahar is killed by the system for lack of memory ("Out of memory: Killed process
(azahar)", 5.3 GB of RAM and 4.1 GB of swap). Azahar's log stops before that (it only writes to disk at each error).

- A damaged submarine leaks oil: its scripts (`surface_sub`, `surface_sub_rival`..., and the player in the replay)
  call `fxOilAdd` every 9 frames, and each bubble lives 2 seconds.
- `MetaBallSys` (`source/metaball.cpp`) draws these bubbles only when the camera is underwater (`visibleGroups & 1`),
  as sprites: program 2 of `shaders/metaball.shbin` is a geometry shader that, for each point in front of the camera
  (between the near and far planes), runs two nested loops: `loop i0` in `main`, which calls the subroutine
  `draw_strip`, which holds `loop i1`. The constants `i0 = i1 = (0, 0, 1, 0)` make them run once each: one square per
  bubble.
- Azahar never accelerates a geometry shader on the graphics card: it runs it with its shader JIT
  (`video_core/shader/shader_jit_x64_compiler.cpp`). `Compile_LOOP` keeps the loop counter in host registers (`esi`,
  `edi`, `r12d`) and only saves them for a loop nested in the same block of code. The loop of `draw_strip`, compiled
  separately, overwrites the outer loop's counter and leaves it at 0; the outer loop decrements it (−1) then tests
  whether it is zero: it goes on for about four billion iterations. Each iteration emits two triangles, which Azahar
  stores in an array before drawing them: memory grows by several hundred MB per second.

Hence the symptoms: only underwater, only when a bubble is in front of the camera (going up to the surface avoids the
crash, diving again triggers it), and nothing any more some twenty seconds after the last hit, when the leak stops.
The shader engine without JIT ("Enable Shader JIT" unchecked) runs the loops correctly.

The fix replaces both `LOOP` instructions with `NOP` (`[[shader]]` in the recipe): they run only once and no
instruction uses their counter (`aL`), so the shader draws exactly the same thing. `tools/shbin.py --check` looks for
this pattern (a loop reached by a `CALL` from another loop): only `metaball.shbin` has it. Checked in Azahar with a test
mod that makes the enemy submarines leak all the time: without the fix, memory goes from 1.2 to 3.4 GB in 4 seconds;
with it, it stays at 1.2 GB and the oil shows normally. The bug deserves a report to Azahar (save the loop registers
around each `CALL`, or keep them in the shader's state as the interpreter does).

## 60 and 120 frames per second

*Estimated progress: 10 % — engine understood, attempt in Azahar abandoned; to redo in the PC port.*

What the engine does:

- `nnMain` waits for at least **two VBlanks** per step: the game is locked at 30 frames per second.
- The simulation advances by a **fixed step of 1/30 s**: the world's clock (`World::update`) and
  `World::getDeltaTimeSeconds()`, which returns the constant 1/30 to the effects (distortion, motion blur, torpedo
  wakes, metaballs, fades, fish tank, credits).
- The scripts count in **frames**: timers (`600` = 20 s), animations (`actorPlayAnim` returns a duration in frames),
  call delays (`sysCallPublicDelayed`).
- The **replay** keeps the **last 210 frames** (7 s at 30 fps), 80 actors per frame.

Simply moving to one frame per VBlank would run the whole game twice as fast, and doubling the simulation rate would
mean fixing every counter of the 123 scripts (and would desynchronise online play with players at 30). The chosen
way: keep the simulation at 30 steps per second and draw **one more frame in the middle of each step**, actors and
camera halfway between their previous state and the current one.

**Attempt in Azahar, abandoned for now** (mod `60fps`, commit bfac07c, removed afterwards): at the title screen it did
give 60 emulated frames per second, but in battle the result was too buggy to be kept. What the attempt established
about the engine, for later:

- `nnMain`'s drawing (from `Fader::update`, 0x00100ABC, to `Graphics::runDraw`, 0x00100E50) only depends on r0 and r1:
  it can be replayed for a second frame; `vblankAtStart` is in r9; the possible hooks are at 0x00100ABC, after
  `Graphics::stopDraw` (0x00100DF4) and after `Graphics::runDraw` (0x00100E54).
- Each actor keeps its current matrix (`Actor::matrix`, +0xB8), which `Actor::updateMatrix` copies into its scene node
  (transform at +0x4C, "transform changed" flag 0x800 at +0x88).
- The scripts' camera (`gfxCameraLookAt`: position +0xC4, target +0xD0 of the renderer) is only applied to the camera
  node by `Renderer::updateCamera`, into which `Renderer::preCullUpdate` falls (a `nop` followed by the function).
- `Renderer::update` with `System::s_paused` at 1 computes the matrices again without advancing animations, particles
  or effects (`Scene::update`, `Scene::updateModels` and the effects that advance with time test the pause).
- Rendering is triple-buffered (`Graphics::flip`), command lists double-buffered (`Graphics::stopDraw` waits for the
  previous one): two frames per step keep the display order.
- With the emulated processor at 100 %, the game does not always have the time to draw two frames per step; at 200 %
  (Azahar: Emulation > Configure > Debug > CPU clock speed) it keeps up.

**120 frames per second** (or 144, 165...): impossible in an emulator. The emulated console's screen refreshes at
59.83 Hz (Azahar's `FRAME_TICKS`) and the emulator shows one frame per refresh; speeding the emulation up to 200 %
would give 120 frames, but also a sound twice as fast and a skewed network clock. The **PC port** is the right place for
60, 120 frames per second and more: simulation at 30 steps per second, and at each refresh of the screen a frame
interpolated at the fraction of step elapsed (1/4, 2/4, 3/4 at 120 Hz), with a rendering fully under our control.

Online, consoles that display at different rates would stay synchronised as long as all of them run the same 30
simulation steps per second: it is the simulation that must be common, not the display.

## Debug menu

*Estimated progress: 5 % — what is left of it is analysed; its logic and display must be written again.*

The mode scripts still hold the developers' debug console (`consoleSystemMenu` in `mode_title`, see
[pawn-scripts.md](pawn-scripts.md)): invincibility, `godmode`, `killThemAll`, turning effects off, fog and 3D
settings, simulated latency and packet loss, access to the developers' test mode (`mode_test`: choice of the mode, the
submarine, the missions). But it is not a quick mod:

- the logic that opens the console and moves from one menu to the next has gone: no script resets the menu counter
  (`gConsoleMenuIndex`) or closes the console again; only `mode_test` and `mode_controls` open their own menus;
- so has the display: `gfxPrintStringf` still writes into a text buffer of 50 columns (`System::getDebugBuffer`,
  0x800 characters), but no code draws it any more (`DebugFX::draw` only draws debug lines).

Both pieces would have to be written again: natural in the PC port (a debug overlay), possible later in Azahar with
script and code patches.
