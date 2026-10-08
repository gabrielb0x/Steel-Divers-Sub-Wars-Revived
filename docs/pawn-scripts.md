# The game's Pawn scripts

A large part of the logic of Steel Diver: Sub Wars is not in C++ but in **123 compiled Pawn scripts**
(`romfs:/amx/*.amx`). The C++ engine runs them with CompuPhase's AMX virtual machine (Pawn 3.3, file format 10)
and gives them 647 native functions.

## Organisation

*Estimated progress: 100 %.*

- **Modes**: `nnMain` loads a `mode_*` script (20 in all), runs it, then moves on to the next one
  (`decomp/src/main.cpp`). Each mode loops once per frame and gives control back to the engine with `sleep 0;`.

  ```
  mode_title  mode_select  mode_lobby  mode_internet_menu  mode_local_menu  mode_multi_menu
  mode_periscope  mode_peri_result  mode_mission_select  mode_shop  mode_sale  mode_customize
  mode_battle_record  mode_options  mode_settings  mode_controls  mode_staff  mode_giles  mode_test  mode_warning
  ```

- **Actors**: the objects of the world are scripted (`surface_sub`, `surface_torpedo_homing`, `surface_mine`,
  `surface_ship_boss`, `surface_fortress`...), as are the cameras (`camera_*`) and the interface (`hud`, `pause`,
  `sonar`, `morse`...). Public functions called by the engine: `@actorSync` (every script), `@eventCollide`,
  `@torpedoHit`, `@setPlayersPerTeam`, `@saveAll`...
- **Shared includes**: the `[file::function]` log messages left in the scripts give back the names of the functions
  and of their original `.inc` files: `actor.inc`, `button.inc`, `cards.inc`, `connect.inc`, `controls.inc`,
  `game_state.inc`, `lobby.inc`, `medal.inc`, `morse.inc`, `options.inc`, `overlay.inc`, `points.inc`, `rest.inc`,
  `save.inc`, `stageutil.inc`, `stats.inc`, `sub_customize.inc`, `surface_ship.inc`, `system.inc`, `torpedo.inc`...
- **Debug removed**: the debug display functions are empty in the retail build, but their calls (with their
  messages) are still there, which documents a lot of code. The decompiler names them `debugPrint` (or `stub` when
  they get no message).
- **Pawn states**: 23 scripts (the modes and the units of the surface mode) use Pawn's state machines
  (`function() <state>`, `state name;`). The compiler puts a dispatcher in front of the first function
  (`load.pri <state variable>; switch`) toward the implementation of the current state; the decompiler shows it as
  in the source (`func_0010(arg0, arg1) <state2>`, `state state3;`), with numbered state names.
- **Script UIDs**: a script takes an identifier with `sysSetUID()`; the others call it by that identifier
  (`sysCallPublic(UID_HUD, "@setBossLifeMeter", ...)`). 10000 is the current mode, 10010 the HUD, 11030
  `game_state`, 10100 the player... (enumeration `UID` of `decomp/pawn/natives.inc`). Below 1000, the UID is an
  actor number.
- **Debug console**: `mode_title` (and the other modes) still hold a complete debug menu (`consoleSystemMenu`:
  invincibility `player.muteki`, `player.godmode`, `killThemAll`, `life100%`, turning effects off, fog, simulated
  latency and packet loss for the network...), driven by the engine global `system.consolemode`. A lead for a
  future mod.

## Natives (C++ functions called by the scripts)

*Estimated progress: 55 % — the 647 natives found and linked to their C++ code; 343 Pawn prototypes written.*

The registration tables (`AMX_NATIVE_INFO`, declared *packed* and therefore sometimes unaligned) are found by
following the calls to `amx_Register`:

| Module | Natives | | Module | Natives |
|---|---|---|---|---|
| `amxsys` (system, globals, save) | 161 | | `amxxml` | 26 |
| `amxactor` (actors) | 148 | | `amxworld` (world) | 25 |
| `amxnet` (network) | 59 | | `float` | 22 |
| `amxeffects` | 56 | | `amxstring`, `amxcore`, `amxcons` | 19, 17, 15 |
| `amxgfx` (cameras, rendering) | 48 | | `amxvector` | 17 |
| `amxsound` | 30 | | `amxbb`, `amxdynamics` | 2, 2 |

The scripts use 466 of them. The type of each parameter (input/output string, array, Float, integer) is deduced
automatically from the C++ implementation (`tools/native_types.py`), and **`decomp/pawn/natives.inc`** gives the
hand-written Pawn prototypes of the ~340 most used natives (parameter names, `Float:`, references, variadic
functions), plus the `UID` and `BUTTON` enumerations. The game's conventions: the target actor is the last
parameter of the `actor*` natives (0 = the actor of the calling script), vectors are `Float:v[3]`.

## Tools

*Estimated progress: 90 % — disassembler, decompiler and assembler; a recompilable pseudo-Pawn remains to do.*

`make scripts` (after `make export`) writes into `decomp/scripts/` (not versioned):

- `asm/*.asm`: disassembly with labels, natives and their C++ implementation, string literals;
- `*.p`: **decompiled pseudo-Pawn** (`tools/amxdec.py`).

The decompiler rebuilds expressions, local variables and arrays (2D ones included), typed native calls, the
floating-point operators of `float.inc`, `&&`/`||` conditions, ternaries, the `if`/`else`, `while`, `for`, `switch`,
`break`/`continue` structures, and Pawn states. About 130 `goto` remain, nearly all in `sale_script`.

It analyses all the scripts together, in several passes:

1. **Parameter types**: each script function learns how its parameters are used (passed to a native that expects
   a string, an array, a `Float`, written by reference...), step by step through the calls. Calls then show
   strings, floats and global names instead of addresses (`consoleGlobalFloat("fog mindepth", "fog.near", 10.0,
   -1000000.0, 1000000.0, 0)` instead of `func_2f28(10000, "fog.near", 0x41200000, -0x368bdc00, 0x49742400, 0)`),
   and declarations are typed (`setControlAction(const control[], action, bool:replace)`).
2. **Matching between scripts** (`tools/amxsym.py`): the 6,037 functions come from the same `.inc` files compiled
   into several scripts. A fingerprint of the normalised code (natives by name, strings by content, globals
   renumbered, called functions by their own fingerprint) groups the copies: 4,500 functions belong to ~600 groups.
   A name given once applies to every copy, and the globals they use at the same place are linked across scripts.
3. **Names**: original names (logs `[file.inc::function]` or `[function]`), then **`decomp/pawn/symbols.txt`**
   (names and parameters given by hand, versioned, marked `[named by hand]` in the output), the `.inc` file deduced
   from the neighbours for functions without logs, globals initialised with a name called after it (`g_btn_ok`).

Example (`mode_title.amx`, `controls.inc`):

```pawn
// 0x0a8c  controls.inc  [named by hand]
setControlSet(set)
{
    ...
    sysSetGlobal("controls.controlSet", set);
    sysGetGlobalString("mode.current", local_180);
    sysCallPublic(UID_CAMERA, "@resetControlData");
    switch (set) {
        case 0:
            setStandardControls(local_184);
            setActionForInput(BUTTON_X, 1, 1);
    ...
```

To name a function: read its code in `decomp/scripts/*.p`, add a line `<script>:<address> name(parameters)` to
`decomp/pawn/symbols.txt`, run `make scripts` again.

Limits: local variables and most globals stay synthetic (`local_14`, `g_01c8`), as do state names; ~1,500 groups of
functions have no name yet.
