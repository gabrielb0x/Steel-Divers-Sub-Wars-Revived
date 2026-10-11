# What the developers left behind

*Estimated progress: 90 % — every string of the executable, the scripts, the texts and the levels has been looked
through; the textures and models were not looked at one by one.*

The game ships without its developers' comments: the C++ was compiled (comments never reach a binary), the Pawn
scripts were compiled without debug information (no `AMX_FLAG_DEBUG`, no symbol table), and the data files hold no
comment fields. What remains are their **log messages** (the logging calls were compiled out of the retail build,
their format strings stayed), the **names** they chose, notes in the **texts**, and parts of the levels they turned
off. This page collects them. The decompiled sources quote them where they belong (`decomp/src/`).

To look for more: `python3 tools/strings.py --grep "pattern"` lists the strings of the executable with the function
and original source file that use them (`--all` for Nintendo's libraries too); the scripts' strings are in
`decomp/scripts/*.p` (`make scripts`), the texts and levels in `extracted/xml/` (`make data`).

## Notes to themselves

| Where | What they wrote | |
|---|---|---|
| `source/net/session.cpp` | `A session function is getting called without a connection. FIXME` | the FIXME outlived its check: no code uses the string any more |
| `source/net/network.cpp` | `[Network::handleError] Received error code %d! This should be resolved during production.` | logged for the codes they named `doProductionError`: NEX's internal errors, which they expected never to see once the game was out ([table](../decomp/src/net/network.cpp)) |
| `source/net/datastreamer.cpp` | `Too many incoming blocks!  Send less data or increase MAX_INCOMING_BLOCKS` | advice to a colleague; the constant is 1,024 blocks of 1,308 bytes |
| `source/sys/facesystem.cpp` | `[FaceSystem::printResult] Mii failed to make it into the back-end database via Mii encounter. (No error handling needed.)` | one of the descriptions of the Mii library's results, maybe taken from Nintendo's documentation |
| `source/amx/amxactor.cpp` | `%s calling %s(): Only synced actors can call actorSyncCallPublic. I'm not an actor.` / `I'm not synced.` | the engine speaks in the first person |
| `source/amx/amxbb.cpp` | `UNIMPLEMENTED` | the native `bbls` lists the actors around the player (a debug `ls`); the name it gives each one was never written |
| `source/amx/amxactor.cpp` | `Function %s not implemented` | |
| `source/sys/screenshot.cpp` | `This is UserMakerNote!` | the text written into the maker note of every 3D screenshot's EXIF |
| `source/net/datarouter.cpp` | `Header 0x%x does not match PAUSE_NOTIFICATION_HDR 0x%x` | the pause message's header, `PAUS`, keeps its constant's name |

## Names

- **Vitei**, the studio that made the game for Nintendo, named its own node ids after itself:
  `Session::convertIdViteiToPia`, `convertIdPiaToVitei`, and the logs' `viteiEventCode`, `viteiNodeID`
  ([session.cpp](../decomp/src/net/session.cpp)).
- **`thehuntforredoctober`**: the key Pia signs every packet of a battle with — *The Hunt for Red October*, the
  submarine film ([connection.cpp](../decomp/src/net/connection.cpp)).
- **`BABBAGE_MATSURI`**: the passphrase of the local wireless network ("Babbage festival",
  [connectionLocal.cpp](../decomp/src/net/connectionLocal.cpp)).
- **`DummyName`**: the player's name in a session when the console has none.
- Variable names the logs kept: `sIsParticipationAllowed`, `sIsSaving`, `sProcessedMii`, `sMiiHead`, `sMiiTail`,
  `gDoFormatExit`, `gSaveAllRequested`, `gIsMorseChatDisable`...; the status names of the network (`DISCONNECTED`,
  `LOGGING_OUT`, `LOGGING_IN`, `LOGGED_IN`, `JOINING_SESSION`, `LEAVING_SESSION`, `IN_SESSION`).
- Japanese words in the code and data: `player.muteki` (無敵, invincible: their test mode), `idou` (移動, movement:
  an attribute of the sunken submarines), `Bgm_BattleKansen` (観戦, watching: the spectators' music).
- The original source tree, from `__FILE__` strings and the linker map: `source/main.cpp`, `source/net/...`,
  `source/sys/...`, `source/gfx/...`, `source/amx/...`; and the scripts' own files, from their logs: `actor.inc`,
  `button.inc`, `cards.inc`, `connect.inc`, `controls.inc`, `controls_observe.inc`, `dialog_common.inc`,
  `game_state.inc`, `lobby.inc`, `medal.inc`, `morse.inc`, `morse_lobby.inc`, `morsechat_disable.inc`,
  `multi_menu.inc`, `options.inc`, `overlay.inc`, `points.inc`, `rest.inc`, `save.inc`, `stageutil.inc`,
  `stats.inc`, `sub_customize.inc`, `surface_ship.inc`, `sync.inc`, `sync_legacy.inc`, `system.inc`,
  `torpedo.inc`; a script state is called `stasis` (`[stasis::enterReplayActorOffset]`).
- The build: revision **31308** of their repository for the launch version, **33269** for the update v5200
  (`bxml/buildinfo.bxml`); the debug menu can hide it ("Hide Revision Number").

## Typing slips

`dataRecieveCallback` (`syncevent.cpp`), the debug menu's `network recieve latency min/max`,
`[amxorld::worldSetLevel]`, `Applet: sleep later - repyling`, `[mode_peiscope::@setNpc]`,
`[Network::handleError] Unhandled case for status` in
`Network::performShutdown` (a log copied from one function to the other).

A slip with an effect: `FaceSystem` meant to skip the Mii of some players according to their team, formatting the
name of the global `player.<node>.team` — and then reading the global literally named `player.%x.team`, which does
not exist ([facesystem.cpp](../decomp/src/sys/facesystem.cpp)).

## Notes in the texts

- `【フォントの初期設定に使用】` — "[used for the initial setting of the font]": the Japanese text of the entry
  `1bt_s_dummy`, a placeholder that only sets up a font.
- Texts of cut screens, which the Japanese file marks `未使用 N` ("unused N", numbered up to 54): a **ranking** table
  (`ranking_title02..07`: Rank, Name, Decal, Record, Sub, Expert; `mode_ranking01..05`), **Download Play**
  (`btl_download_*`: "Looking for opponent...", "Confirm Opponent", "Transmitting data..."), a reminder to rest
  (`mode_break01`: "Take a little break when you're tired."), the old save messages (`save00..02`,
  `read_error01..02`), "Game Over", "NEW RECORD!", and empty slots for "units" (`mode_unit*`) and alerts.
- `Peri_test01..03` ("Test01"... in Japanese, a minutes/seconds template in the other languages), `CBF_STD_*` and
  `DEFAULT` set to `test2`, `LOG_*` set to `log_dummy`.
- `title_version`: `仮入隊（無料）` ("provisional enlistment (free)"), the label of the free version under the title.

## What they turned off or kept for testing

- **Disabled level nodes**: in the levels a node whose name starts with `_` is skipped by the loader — their way of
  commenting a line out: 187 `<_actor>`, 12 `<_collshape>`, 7 `<_fog>`, 3 `<_light>`, 1 `<_msg>` in 94 files.
  Mission 1 alone has 13 (morse rings, arches, a ship, a submarine, mines moved or removed).
- **Test levels** still in the RomFS: `lod_check`, `tank_test`, `scope00_offline_test`,
  `offline_mission_test/` (`area_2..5`, `scope00_offline_mission_test`), `scope00_online_test` and its eight player
  variants `_p1..p8`; the model `trp_test`; the Pawn script `mode_test`.
- **The debug menu** of the mode scripts (`consoleSystemMenu`: "goto mode_test", "Disable BGM", "killThemAll",
  "muteki", "stopTheTime", network latency and packet loss...): its logic was removed, see
  [mods.md](mods.md#debug-menu) and [pawn-scripts.md](pawn-scripts.md).
- `ConnectionLocal::debug()`: makes the next update fail with error 018-0306, to test the error screens.
- `Network::getLengthSent`, `DataRouter::dbgTotalsClear`, `DataStreamer::dbgSentClear`: statistics for a debug
  display that is gone (the sent byte counts are never even counted).
- Pia's traces are all switched on (`Connection::initPIA`), for a build of Pia whose traces were compiled out.
