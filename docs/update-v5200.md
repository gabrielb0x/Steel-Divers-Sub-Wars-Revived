# The update v5200

*Estimated progress: 90 % — the update extracts, installs into Azahar and every mod works with it; the bots and the
anti-cheat of online play remain to be seen in the emulator (table below).*

Steel Diver: Sub Wars got updates as long as the eShop was open. The last one, in Europe, is the title
`0004000E000D7E00` in **version 5200** (5.5.0), built at revision 33269 of the developers' repository (the original
game, "v0": revision 31308, `bxml/buildinfo.bxml`). The project works with both versions.

## What it changes

*Estimated progress: 70 % — inventory of the files and of the code; the details of the rules remain to read.*

- **A new executable**: about 140 KB more code (`.text` from 0x251408 to 0x2736AC bytes), recompiled: every
  address moves. The libraries (NEX, Pia, nn::) and most of the game's functions are the same, at their new
  addresses.
- **No symbol table any more**: the v0's `romfs:/map` is not in the update. The names of the v5200's functions come
  from matching them with those of the v0 (same code, addresses of calls and data masked): 9,338 of the v0's 11,167
  functions are found that way.
- **16 more submarines** (n° 24 to 39: `bxml/pscope_ply24` to `39`, their models and patterns), **3 online maps**
  (`worlds/scope00_online_stage11` to `13`), a **floating mine**, **charged torpedoes**
  (`surface_torpedo_lv0N_charge`), a submarine customisation screen and a submarine shop.
- **The shop changes**: the add-on content library gains natives (`sysDLCCheckOwned`,
  `sysDLCSetFilterModeSubmarine`, `...CrewExp`, `...Enlist`, `sysDLCIsNewArrival`...): submarines and crew
  experience were sold separately.
- **The 123 Pawn scripts are recompiled** (10 to 30 % more code for those of the modes and submarines); the texts of
  the 9 languages, 4 fonts, 27 layouts and the balance of several submarines (`pscope_plyNN_stats`) change.
- **The save keeps its format** (version 27, `sysSaveDataLoad("save", 27)`).
- **Online, the same server**: same NEX server id (`0x000D7C00`) and same access key (`fb9537fe`).

## How the game reads its files

*Estimated progress: 100 %.*

The update's RomFS only holds the 424 files it changes or adds (38 MB, against 1,179 files and 200 MB for the game).
At start-up the v5200 mounts two archives (`0x00103A40`): `rom:` is the game's RomFS (SelfNCCH archive, path type 0)
and `rom2:` the update's (path type 5). For each file, it first tries `rom2:/<file>` then, if it does not exist,
`rom:/<file>` (`0x00257ACC`).

The tools do the same: `make extract` (or the launcher's Game tab) extracts the update into `extracted/v5200/` (its
`code.bin` and its RomFS alone), and a file of the v5200 is looked for there first, then in `extracted/romfs/`
(`tools/versions.py`).

## In Azahar

*Estimated progress: 90 % — the v5200 remains to be played at length in the emulator.*

An update is installed on the console's SD card: in Azahar, *File > Install CIA* with the **decrypted** `.cia` of the
update, or the launcher's *Install the update* button (Game tab), which writes the same files
(`sdmc/Nintendo 3DS/.../title/0004000e/000d7e00/content/00000000.tmd` and `00000006.app`). From then on the game
starts as v5200, whether it is installed or opened from its `.cxi`: Azahar takes the update's code
(`AppLoader_NCCH::Load`) and provides both RomFS.

The game's mod folder (`load/mods/00040000000D7E00/`) also applies to the update (`GetModId` turns `0004000E...` into
`00040000...`): `exefs/code.ips` to the update's code, `romfs/` to both RomFS. A mod built for the v0 would therefore
keep the v5200 from starting (its code patch would land in the wrong place). That is why:

- `tools/mod.py` builds for one version (`--version`, by default that of each emulator found);
- each built mod carries a marker `sdsw.json` (version and mods); the launcher warns when the installed mods no
  longer match the game's version, and removes those of the other version when it installs or removes the update;
- each recipe says which versions it works with (`versions = ["v0", "v5200"]`, see
  [mods/README.md](../mods/README.md#versions-of-the-game)), and the launcher shows it on each mod.

## Scripts from one version to the other

*Estimated progress: 90 % — `tools/amxport.py` pairs 97 % of the instructions of the 123 scripts (from 70 % for
`hud_pause` to 100 %); the changed functions remain to read by hand.*

`tools/amxport.py` tells where an address of a v0 script is in the v5200 (and the other way round, `--reverse`):

```sh
python3 tools/amxport.py surface_sub 0xcf80 g_1ca0      # 0xcf80 -> 0xf3b8, g_1ca0 -> g_3730
python3 tools/amxport.py --show mode_lobby 0xebf8      # the code around it, both versions aligned
python3 tools/amxport.py --stats                       # the share of each script paired
```

Each instruction becomes a token that does not depend on addresses (jump targets and globals masked, natives by
name, strings by their text); functions are paired by identical code, by their log name (`[file.inc::function]`),
by the functions they call, then by likeness (an update can move a whole `.inc` file: that of `connect.inc` moved in
`mode_internet_menu`); two paired functions are aligned instruction by instruction, and each global of an aligned
instruction votes for its address in the other version. The v5200's pseudo-Pawn is obtained with
`tools/amxdec.py --version v5200` (in `build/scripts-v5200/`, without the names of `decomp/pawn/symbols.txt`, which
are the v0's).

## An encrypted update

*Estimated progress: 100 %.*

Like the game, the update must be **decrypted**: Azahar refuses an encrypted CIA, and the project holds no console
key. An update downloaded as it is (with the eShop's ticket) is encrypted twice: by the title key (CIA layer), then
by the NCCH keys. GodMode9 on a console, or a CIA decryption tool, turns it into a decrypted CIA. The launcher can
also do it for you (Game tab: it downloads a public decryption tool and runs it on your file, see
[README.md](../README.md#install)); `tools/extract_cia.py` and the launcher recognise an update CIA that is still
encrypted and say so.

## The mods and the v5200

*Estimated progress: 95 % — every mod is ported to the v5200; the bots and the anti-cheat of online play, ported by
`tools/amxport.py`, remain to be seen in Azahar.*

The addresses come from matching the functions (ARM code) and the Pawn scripts between both versions: the same code
apart from addresses, or, for changed functions, an instruction-by-instruction alignment with the closest function.

| Mod | v0 | v5200 | |
|---|---|---|---|
| `fixes` | ✓ | ✓ | the fixed shader (`shaders/metaball.shbin`) did not change |
| `nickname` | ✓ | ✓ | the same `FaceSystem` functions, at their v5200 addresses |
| `version`, `title-credits`, `title-text` | ✓ | ✓ | texts and layout, taken from the v5200's files |
| `premium` | ✓ | ✓ | plus `sysDLCCheckOwned`, submarines 27 to 36 and eight unlock arrays ([premium.md](premium.md#in-the-update-v5200)); checked: the 40 crew members and the update's submarines unlocked; the patterns' colours are no longer lost at every start-up, and without the DLC the pilot sees a prow of the game (the Z class's hull hid the view) |
| `missions` | ✓ | ✓ | checked: every mission and all their levels open, the total says 21 |
| `cheats` | ✓ | ✓ | the invincibility also covers the floating mine; checked: firing without delay, infinite torpedoes |
| `speed` | ✓ | ✓ | the acceleration tables did not change |
| `specs` | ✓ | ✓ | the 39 submarines, in a file of their own (`submarines-v5200.toml`): their values differ |
| `music` | ✓ | ✓ | the update has the same music streams |
| `online` | ✓ | ✓ | connection to the server, match search and the server dialog checked ([online.md](online.md#9-the-update-v5200)); the server's bots and the anti-cheat ported by `tools/amxport.py` (`*-v5200.pasm`), to be seen in Azahar; never a common match between v0 and v5200 |
