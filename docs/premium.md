# Free version, premium and add-on contents

Sub Wars was a free game. The **full version** ("premium", *enlist* in the code) and five historical submarines were
sold on the eShop as **add-on contents** (DLC). The eShop has sold nothing since 2023: the
[`premium`](../mods/premium/mod.toml) mod unlocks everything without it. This page explains how the game decides what
is bought, and what the mod changes.

## What is in the base game

*Estimated progress: 100 %.*

All the premium content is already in the free game's RomFS: the 7 mission areas, the 18 base submarines, the 32
patterns and the 32 crew members, and even the hulls of the 5 historical submarines (`n2ply_x001` to `n2ply_x005`,
which free players saw on the others online). The purchase only added a **right**, plus, for each historical
submarine, a small archive with its **prow**: the detailed model its own pilot sees (`n2ply_x00N_prow`).

| Submarine | File | Hull (base game) | Content |
|---|---|---|---|
| 19 | `bxml/pscope_ply19` | `n2ply_x002` | 1 |
| 20 | `bxml/pscope_ply20` | `n2ply_x004` | 2 |
| 21 | `bxml/pscope_ply21` | `n2ply_x001` | 3 |
| 22 | `bxml/pscope_ply22` | `n2ply_x003` | 4 |
| 23 | `bxml/pscope_ply23` | `n2ply_x005` | 5 |

The add-on contents form the title `0004008C000D7E00` (the game is `00040000000D7E00`), each purchase being a
numbered "content" of this title.

## How the game checks the purchases (`source/sys/dlc.cpp`)

*Estimated progress: 100 %.*

The `NsubShop` class (a singleton, `getNsubShop()`) wraps the `nn::ec` purchase library:

- `updateCondition()` asks `nn::ec::CTR::DataTitle` for the list of contents of the DLC title and, for each content
  present and bought, sets a bit in a 128-bit bitmap (`+0xFA0`, 4 words);
- `checkCondition(n)` reads bit `n`: true if content `n` is bought;
- `checkPaidForFullVer()` reads bit 27 of the third word (`+0xFA8`), that is **content 91**: the full version;
- `mountContentArchive(n)` / `unmountContentArchive()` mount the archive of content `n` as `content:`
  (`nn::fs::MountAddOnContent`);
- the rest (`initializeEc`, `validateSession`, catalogue, `purchaseItem`, `redownloadItem`, balance...) serves the
  shop and the purchase screen, talking to the eShop's servers.

The scripts reach it through the `sysDLC*` natives of `amxsys`; `sysDLCCheckPaidForFullVer` and
`sysDLCCheckCondition` are two tiny functions placed right before `checkPaidForFullVer` and `checkCondition`, into
which they "fall" after loading the singleton.

**Historical submarines**: their properties file (`bxml/pscope_ply19.bxml`...) holds
`<mount_dlc_arc content_index="n"/>` and an attribute `model_mutable_dlc` instead of `model_mutable`.
`Actor::readProperties` then mounts the content's archive if `checkCondition(n)` is true, and
`Actor::setAttributeString` only loads `model_mutable_dlc` if the archive is mounted (otherwise the submarine has no
prow). The hull, `modelship`, always comes from the base game: it is what the other consoles send
(`@syncNetworkSpawn`).

## What the free version limits (Pawn scripts)

*Estimated progress: 100 %.*

Every mode script has a copy of `isFullVersion()` (`return sysDLCCheckPaidForFullVer();`):

| Script | Free version | Full version |
|---|---|---|
| `mode_title` | title screen at sunset, "Free version" note (`trial` pane), "Enlist" button | daytime scenery, without the note or the button |
| `mode_select` | the Shop button offers the purchase (`alert_salemessage02`, then `mode_sale`) | it opens the shop (`mode_shop`) |
| `mode_mission_select` | only the first two areas | the 7 areas, unlocked by the number of medals |
| `mode_customize` | only submarines 1 and 2 (`sub_detail_unlock_not_enlist` otherwise) | every unlocked one |
| `mode_lobby` | submarines 1 and 2 online (`save.sub.unlock[2..22]` set to 0) | every unlocked one |

Submarines 19 to 23 follow `sysDLCCheckCondition(n° − 18)`: at the title screen, a historical submarine that is
chosen but no longer bought is replaced by n° 1 (`save.sub.typenum`).

## Unlocks and the save

*Estimated progress: 100 %.*

In the full version, submarines and patterns are won through **rewards** (`bxml/reward_data`: `decalNN` for a
pattern, `lobby_sub_nameNN` for a submarine, applied by `unlockReward`):

- in single player, at 3, 4, 8, 9, 15, 18 and 21 gold medals (`medal.inc::updateAwardMedal`, `reward100` to
  `reward106`): submarines 2 and 3 and five patterns;
- **online, at each rank level** (`reward02` to `reward42`): submarines 4 to 18 and most patterns. Without an online
  server, they had become impossible to get.

The crew members are found in the missions (`crew.get`, `saveFoundCrew`). All of this is kept in three arrays of the
save ([formats.md](formats.md#save)):

- `save.sub.unlock[23]`: submarines (index 0 is always unlocked);
- `save.sub.pattern.unlock[32]`: hull patterns (*decal*);
- `save.sub.crew.unlock[32]`: crew members.

**The premium flag's trap**: at the title screen, the first time the full version is there, the game writes
`save.sub.enlist = 1`. If later this flag is in the save but the full version has gone (DLC deleted), the Start
button shows error **098-0101** (`sysShowErrEULA(98101)`) and the game no longer starts.

## The `premium` mod

*Estimated progress: 100 % — checked in Azahar.*

```sh
.venv/bin/python tools/mod.py build premium --install
```

1. `checkPaidForFullVer` and `checkCondition` always return true (two 8-byte patches): the full version and the five
   historical submarines.
2. `updateCondition` (the bitmap is no longer used) is replaced by a routine that sets the three unlock arrays (option
   `unlock`, on by default): the scripts call it at the title screen, right after the save is loaded, and before the
   lobby and the hangar. The game then saves these arrays: the unlocks stay even without the mod, as if they had
   been won.
3. Without the DLC (option `dlc=no`, the default), the historical submarines take the prow of a game submarine of the
   same size: no archive to mount any more (`mount_dlc_arc` removed), `model_mutable_dlc="n2ply_x00N_prow"` becomes
   for instance `model_mutable="n2ply_l001_prow"` (I-400). A first version gave them their hull as a prow: the
   pilot's camera ended up inside the hull (the whole view hidden on the v5200's huge Z class), and the patterns'
   colours did not show on it (the game puts them on the prows' `prow_mat` material). With `dlc=yes`, for whoever
   installed in Azahar the DLC they bought, the original files stay.
4. The menu's Shop button reloads the menu: the shop would wait for the eShop in endless loops.
5. `save.sub.enlist` is written into a global `mode.sub.enlist`, which the save does not keep: removing the mod does
   not trigger error 098-0101. A save already flagged is repaired with `tools/save.py premium-off`.
6. The patterns unlocked by the mod get their default colours (`bxml/sub_color_set`), which the game only gives to
   patterns unlocked by a reward: once per save (`save.sdsw.colors`), at the title screen, those whose three colours
   are still 0 (`mods/premium/src/colours.p`).

The missions remain to be played: they unlock with the medals. To open everything at once, the save editor
([../tools/save.py](../tools/save.py)) can also give medals, and the `missions` mod opens them all.

Online, this mod does not count as cheating: it gives what premium players had.

## In the update v5200

*Estimated progress: 90 % — checked in Azahar: complete crew, the update's submarines unlocked; the details of the
"refits" remain.*

The update ([update-v5200.md](update-v5200.md)) sells more:

- **15 submarines** separately: the 5 historical ones (n° 19 to 23, contents 1 to 5) and 10 new ones (n° 27 to 36:
  I-168, Type XXI, Blue-Marine, Z class, Soryu, USS Nautilus, S class, Daphné, Kilo, Victor III; contents 6 to 15),
  their prow in the add-on content like the historical ones' (`mount_dlc_arc`). The table matching them is in
  `mode_title` (submarines and contents, 15 cells each).
- **A "refit" of each submarine** (`save.sub.typeN.expanded`), bought as content N + 30.
- **Crew experience** and the full version (`sysDLCSetFilterModeCrewExp`, `...Enlist`).

`NsubShop::updateCondition` (`0x0013A9B0`) fills two bitmaps there: the contents bought (`+0x2DB0`, read by
`checkCondition` and `checkPaidForFullVer`) and the contents owned (`+0x2DC0`, read by the new native
`sysDLCCheckOwned`, `0x0030B988`). The submarines unlock in `save.sub.unlock[23]` (as in v0) and in
`save.sub.unlock2[36]` (n° 1 to 36) and `save.p3.sub.unlock[3]` (n° 37 to 39: the computer's submarines made
playable); `updateSubUnlock` (`mode_title`) deduces `save.sub.owned[36]` and `save.p3.sub.owned[3]` from them. The
crew of submarines 37 to 39 is in `save.p3.sub.crew.unlock[8]`.

The `premium` mod buys and owns everything there (the three checking functions return 1), fills the eight unlock
arrays, gives a prow of the game to submarines 27 to 36 without the DLC, and sends the Shop button and the v5200's
invitation to the "trial shop" to the menu.

**The patterns' colours**: at every start-up the v5200 resynchronises the rewards with the online level
(`mode_title`, `func_103e4`, new): everything above the player's level is locked again, and a pattern locked again
gets "default" colours that are not read yet (0, 0, 0). The mod then unlocked everything again: the colours chosen
for patterns 6 to 31 (rewards of levels 2 to 42) were lost at every start-up. With `unlock`, `func_10358` (unlock or
lock a reward) no longer locks. `tools/save.py` and the launcher know the 39 submarines and the v5200's arrays.
