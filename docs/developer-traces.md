# What the developers left behind

*Estimated progress: 95 % — every string of both executables (v0 and the update v5200), of the scripts, texts,
levels and layouts, the sound archives and the names inside the models have been looked through; the textures were
only sampled.*

The game ships without its developers' comments: the C++ was compiled (comments never reach a binary), the Pawn
scripts were compiled without debug information (no `AMX_FLAG_DEBUG`, no symbol table), and the data files hold no
comment fields. What remains are their **log messages** (the logging calls were compiled out of the retail build,
their format strings stayed), the **names** they chose, notes in the **texts**, the **placeholders** of the layouts,
parts of the levels they turned off, and a screenshot of a development build. This page collects them. The
decompiled sources quote them where they belong (`decomp/src/`).

To look for more: `python3 tools/strings.py --grep "pattern"` lists the strings of the executable with the function
and original source file that use them (`--all` for Nintendo's libraries too); the scripts' strings are in
`decomp/scripts/*.p` (`make scripts`), the texts and levels in `extracted/xml/` (`make data`); `--lines` (with
`--version v5200` for the update) lists the logs with their original source line.

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
| `lobby.inc` (update v5200) | `MIGRATION FAIL, DO FORFEIT GAME!!!1` / `player.consecwins IS RESET TO ZERO!!!1` | a programmer types the internet's "!!!1" in the logs of a forfeited game |
| v5200, `source/sys/playreport.cpp` | `[BOSS Sample]RegisterTask failed. Same name task(%s) already registered.If regist again, need to UnregisterTask before.` | copied with its prefix from Nintendo's SpotPass (BOSS) sample |
| layout `saving_u` | `潜水艦に貼られている番号は君の連勝記録だ！` / `NGワードはでない` / `さんだんめ` / `よんだんめ` | the default text of the loading tip box: a real tip ("the number on your sub is your win streak!"), then "no NG word comes out", "third line", "fourth line" — a test of the box |
| layout `mode_customize_u` | `アンロックされていないクルーの説明文がここに入ります。` | "the description of a crew member not yet unlocked goes here" |

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
  `torpedo.inc`. Their word for the replay is *stasis*: the native `actorSetReplayScript` calls
  `Actor::setStasisScript`, and the scripts log `[stasis::enterReplayActorOffset]`.
- The build: revision **31308** of their repository for the launch version, **33269** for the update v5200
  (`bxml/buildinfo.bxml`); the debug menu can hide it ("Hide Revision Number").
- **The lines of their source files**: the retail build compiled the logs' call out but kept its arguments, so
  307 logs still give `__FILE__`, `__LINE__` and their message (`tools/strings.py --lines`). The last line seen
  is a lower bound of each file's length: `amxactor.cpp` 2,942 lines, `amxsys.cpp` 2,183, `collision.cpp` 1,938
  (the quadtree's "Dropped tri %d at level %d"), `system.cpp` 1,878, `dlc.cpp` 1,451, `model.cpp` 1,446,
  `connectionInternet.cpp` 1,405, `world.cpp` 1,288, `layout.cpp` 1,014, `scene.cpp` 1,012; the order of the
  lines also gives the order of the functions in each file.
- **Giles's test mode**: the script `mode_giles`, reached from the debug menu of `mode_test`, is the personal test
  mode of Giles Goddard (credited as Program Director, Vitei's founder): it loads the test level `lod_check` under
  the periscope's sky and goes back to the title with Y+START.
- **The submarines' working names**, kept by the debug menu (`sub 01 Garfish`, `sub 02 Sea Fox`, `sub 03 Ninten`,
  `sub 04 Lobster`, `sub 05 Salamander`, `sub 06 Mega Mouse`, `sub 10 Manatee`): they became Sea Hound, Red Octopus,
  Great Seal, Megamouth and Deep Manatee; the third, **Ninten**, kept its name in Japan only (`ニンテン`, "Neptune"
  elsewhere).
- **A colleague as the placeholder player**: the periscope's layout (`peri_info_u`) shows the player name
  `いしばし` (Ishibashi) by default — Hiroki Ishibashi is in the credits' Special Thanks. The other placeholders are
  `nintendo` (25 times in `player_name`), `Player 0`..., and `なまえなまえなまえお` ("name name name o").
- **The projects' names**: the executable is `nsub` (exheader title) with its classes `NsubShop`, `NsubThread`; the
  assets are prefixed `n2` (`n2ply`, `n2enmy`, `n2obj`, `n2menu`), older ones not (`btl_stg00_sun01`, `efct_*`,
  `trp_test`); the sound manager is `DsSub`, from Steel Diver, which began as the DS demo "Submarine" (E3 2004).
- **Japanese in the names of the data**: rocks are `iwa` (岩), pillars `hashira` (柱), a stone lantern `tourou`
  (灯籠), seaweed `kaisou` (海藻), mines `kirai` (機雷), a lid `futa` (蓋), the Hot Springs map's rocks `furo_iwa`
  (風呂, bath), the front and back of the sea's surface `omote` / `ura`; the sounds `bakuhatsu` (爆発, explosion),
  `GyoraiSouten` (魚雷装填, torpedo loading), `GyoraiHassha` (魚雷発射, launch), `sensui_fujyou` (潜水浮上),
  `Bakugekiki` (爆撃機, bomber), `HANABI` (花火, fireworks); the scripts' `gekiha` (撃破), `kyoryoku` (協力,
  cooperation: `net.kyoryoku`), `tuika` (追加, the shop's "add funds" button), `mode_dairantou` (大乱闘, "Melee",
  Smash Bros.' Japanese name).
- **British English**, Vitei being a British studio: `uFadeColour` (the credits' shader), `I_colourmul`, and
  `mode_customise` in the debug menu (see below).
- **The models were made in Maya**: its default node names stayed (`pCube1`, `polySurface96`, `phong1`,
  `lambert19_s`, `locator1`, `import_pCube112`), as did a working file's name (`n2enmy_subboss02_temp017_...`,
  `n2obj_trp_hormin02_temp002_...`). The shaders keep the names of their sources (`bubbles.vsh`, `DMP_point.gsh`,
  `metaball3.gsh`, `gas0.vsh`, `torpedotrail3.gsh`) and of their subroutines (`draw_bubble`, `drawStrip`,
  `calculate_quaternion`, `transform_triangle`).

## Typing slips

`dataRecieveCallback` (`syncevent.cpp`), the native `fxFishAvaliable`, the debug menu's `network recieve latency min/max`,
`[amxorld::worldSetLevel]`, `Applet: sleep later - repyling`, `[mode_peiscope::@setNpc]`,
`[Network::handleError] Unhandled case for status` in
`Network::performShutdown` (a log copied from one function to the other), `randam choice` (the lobby, v0),
`errer` and `inpact` (`periscope_move`), `tutrial` (`surface_rockanim`, `surface_torpedo_p_homing`),
`contentIndex:%2d is enable` (v5200).

In the data: the sounds say `Horming` for homing (`SE_Lev_emergency_HormingTorpedo`, `SE_Trg_Horming_LockOn`),
`Deathcharge` for depth charge (`SE_Trg_DeathchargeMenuOpen`), `EnmTurm2MyTurn`, `STRM_SUB_SB_FILED_NULL` (field),
`SE_Lev_VewChangeRotate`, `SE_Trg_cursol`, `SE_Trg_SwimerRescue`, `SE_Trg_EnmyBombLaunch`; the models
`cealing_lambert`, `boday_mat`, `n2obj_rockcriff01`, `flotingturret01`, `exp01_bubleEmitter`,
`n2obj_bottom02_hightmap`, `n2obj_trp_hormin01`, `n2onj_geo12_ab`, `screw_reft_mesh` (next to `screw_left_mesh`),
`Light3_speculer` (also in the script `camera_scope`); the layouts `Text_loacal`, `Text_veb`, `t_balanceum`, and
`ブループ` for `グループ` (group) in the local lobby's placeholder text.

A slip with no effect but a dead entry: the debug menu of `mode_test` offers `mode_customise` — British spelling — and
switches to that mode, but the script is `mode_customize`: the entry starts a mode that does not exist.

A slip with an effect: `FaceSystem` meant to skip the Mii of some players according to their team, formatting the
name of the global `player.<node>.team` — and then reading the global literally named `player.%x.team`, which does
not exist ([facesystem.cpp](../decomp/src/sys/facesystem.cpp)).

The homing torpedoes' search (`surface_torpedo_p_homing`) suffers two slips at once: the native
`worldFindActorsSorted` takes its last two arguments as (max, mask) where `worldFindActors` takes (mask, max) — the
script passes them the `worldFindActors` way, so its target mask (the player, or the computer and remote subs)
becomes the maximum and its maximum, 10, the mask (the player and the computer subs' torpedoes); and the "sorted"
search stores the radius instead of each actor's distance as its key, so nothing is ever sorted
([world.cpp](../decomp/src/game/world.cpp), [amxworld.cpp](../decomp/src/amx/amxworld.cpp)).

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
- `stage_multi_14` (update v5200): a fourteenth map, `デバグ用` ("for debugging"), translated with the rest:
  "Debug Arena", "Arena debug", "For Debug". No level of that number exists.

## A development build in the credits

The credits show the player's own photos of the game (the console's image database, up to 40); without any, they
show ten "stock" pictures from the RomFS, `screenshots/credits0000.mpo` to `0009` (`Credits::loadStockMPO`,
`source/layouts/credits.cpp`). The ten files are the same 3D photo, and it comes from a development build: its
top-left corner reads **`26491-dirty`** — the revision overlay of their builds (the launch is revision 31308), on a
working copy with uncommitted changes. Its EXIF says the photo was taken on 2011-01-02 at 11:19 — a console clock
never set, the game being made in 2012-2013 — by the title `00d7c`: the unique id after which the game's NEX server
is numbered (`0x000D7C00`), not this European version's `0x00D7E`. A player who took no photo of the game sees this
picture, revision number included, ten times in the credits.

## The layouts' placeholders

The layouts (`layouts/*.arc`) keep the default text the designers typed in each text box; the game replaces it at
run time, so these never show.

- **A draft of the credits**: the staff roll's box (`ending_u`) holds an earlier credits list: no localisation teams,
  no Atsumi Sasamoto in the Special Thanks, `Tkakanobu Ohashi` for Takanobu, and `© 2013 Nintendo` where the
  game's texts end with ©2014.
- **Dates**: `2013/04/15` (a ranking's line, `battle_record_l`) and `2013-04-26` (ten results, `battle_record_u`):
  spring 2013, ten months before the release.
- **Every language at once**: the longest translations were typed in to size the boxes — German `Bilanz` and
  `Wiederholung`, Spanish `Enfrentamientos`, Italian `Fondi rimasti:`, French `Niv. 3`, and a balance of
  `1.000.00 DKK` in the shop.
- **Early content**: a mission `海上基地破壊作戦` ("Operation: destroy the sea base", 10 minutes) for the
  Garfish; crew members numbered with their skill (`09:体力じまんB` "stamina pride B", `17:体力じまんC`,
  `32:味方探索` "ally search"); a reward `ブラックシール` ("Black Seal"); the battle log
  `xxxx:魚雷発射！` ("xxxx: torpedo launched!"); the Morse box's `HELP ME`.
- **The debug console**: `debug_l` / `debug_u` are a box of 21 lines of 65 `x` on each screen, with on/off
  animations — the debug console of `gfxPrintStringf`. No script or code loads them.

## The sound archives

The sound names are the developers' own, from the SoundMaker header shipped in the RomFS
(`audiores/sound_data.csid`) — see the Japanese and the slips above.

- **Steel Diver's Steel Commander**: the archive `audiores_SeaBattle/sound_data_sea_battle.bcsar` holds the sounds
  of Steel Diver's strategy mode on a hex map (`SE_SB_Trg_SeaBattle_TurnChange`, `SE_SB_Lev_MyHexSea`,
  `SE_SB_Trg_DeathchargeMenuOpen`, `STRM_SB_SELECT_CHILD`); the game would load it as sound bank 1, but the scripts
  only ever call `sndInit(0)`. Its music stayed in the main archive: the Win and Lose jingles (`SeaBattleWin`,
  `SeaBattleLose`, at 22,050 Hz) and the shop's music (`STRM_SB_Field_Base`). The textures `hex`, `hex_frm`,
  `hex_grey` are its grid.
- **The music's file names** keep the composers' revisions: `Endingfix2`, `LastBossAwayfix3`, `LastBossComefix2`,
  `LPFDeepSeafix2`, `Challenge01_NoOptimized_lr_frontCut` (at 32,000 Hz, not resampled to the console's 32,728),
  `SEQ_SUB_SPOT_WATERFALL_rev_frontFadein` (a sequence of Steel Diver rendered to a stream), `Mission4Edit2Ch`.
  The calm music of the online maps is the same pieces through a low-pass filter (`LPF_Arctic`, `LPF_Cave`,
  `LPFJunglefix`...), the battle music the unfiltered ones. The menus' music (`Bgm_MAIN_MENU`,
  `Bgm_SUBMARINE_SELECT`, `Bgm_LEAVE_PORT_FANFARE`) points at `null_s`, an empty stream: the three layered tracks
  play instead ([DsSubAudioMgr.cpp](../decomp/src/DsSubAudioMgr.cpp)). Three files nothing references end in `_2`:
  two copies, and another export of `LastBossAwayfix3`.
- **Sounds of things Sub Wars does not have**: a Challenge mode (`SE_Trg_ChallengeMode_StartLinePass`,
  `GoalLinePass`, `SE_Trg_Dash`, `SE_Lev_bubble_ChallengeMode`, and its models: dash rings, numbered rings, clocks,
  coins), a bomber (`SE_Trg_Bakugekiki`), the last boss's tornado, the Arctic stage's breaking ice pillar, a ghost,
  a swimmer rescue, fireworks (`SEQ_HANABI`).

## Unused models

73 of the 261 models are named by no level, script or code: test models (`n2ply_sizetest`, `n2ply_em_test`,
`test_ply_lod`, `n2obj_plytest`, `n2obj_dropwatertest`, `anmtest`, `trp_test`, `n2obj_testbox`, `n2obj_sea01_test`),
the first three player submarines `n2ply01` to `03` with their prows, a tentacled monster (`n2enmy_tentacle`, bones
`Tentacle_body03_256`, `WeakPoint`), a sub-boss, a fortress, an iceberg, pillars (`n2obj_hashira01` to `04`), a
clock, items 07 to 10, a medal... The models also hold a tank (`panzer_body`, `tank_gun`) and three airplanes.

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
- **Steel Diver's sound manager**: `DsSubAudioMgr` still holds Steel Diver's missions' music logic
  (`Bgm_Mission1_1`... with variants and boss transitions), a "sound off" switch nothing sets, an empty iceberg
  update, and a voice test on the id `0x0100003E`, which Sub Wars' renumbered archive gives to
  `Bgm_MultiPlay9_Battle` ([DsSubAudioMgr.cpp](../decomp/src/DsSubAudioMgr.cpp)). The SoundMaker outputs ship in
  the RomFS (`audiores/sound_data.csid`, the C header of the sound ids, and its HTML map).
- **Their screen capture** (update v5200): `gfxTakeScreenshot(1)` writes both screens as raw TGA files,
  `sdmc:/screenshots/NNN_upper.tga`, `NNN_upper_ext.tga` (the right eye) and `NNN_lower.tga` — for the manual or
  the press; the scripts only call `gfxTakeScreenshot(0)`, the players' photo.
- `sysDLCDebugAllPurchased` (v5200): a native whose debug build said every add-on content was bought; the retail
  build returns 0.
- `ConnectionLocal::debug()`: makes the next update fail with error 018-0306, to test the error screens.
- **Texts from the SD card**: `TextData::loadStrings` first looks for `text/<language>.bxml` in the save data and, if
  it is there, reads that many bytes of `sdmc:/text/<language>.bxml` instead of the game's texts — a way for the
  translators to try their texts without a new build. The retail save never has the file
  ([textdata.cpp](../decomp/src/sys/textdata.cpp)).
- `Network::getLengthSent`, `DataRouter::dbgTotalsClear`, `DataStreamer::dbgSentClear`: statistics for a debug
  display that is gone (the sent byte counts are never even counted).
- **Why `romfs:/map` is in the game**: their crash handler named the functions of a backtrace with it (`"%x %d
  %s %s"`: address, size, function, object; `" 0x%08x : %s() in %s"`). The retail build no longer loads the file
  — the pointer to its text is never set — but the file stayed in the RomFS, which is how this project has the
  real names of 9,431 functions ([exception.cpp](../decomp/src/sys/exception.cpp)).
- Pia's traces are all switched on (`Connection::initPIA`), for a build of Pia whose traces were compiled out.

## What the update v5200 changed, line by line

The update's executable keeps its logs' `__FILE__` and `__LINE__` too (`tools/strings.py --lines --version v5200`).
Compared with the launch's, they show which source files grew:

| File | Last log line, v0 → v5200 | |
|---|---|---|
| `connectionInternet.cpp` | 1,405 → 1,641 | friend battles; the PIDs now logged in hexadecimal (`%x`, was `%d`) |
| `system.cpp` | 1,878 → 2,053 | |
| `amxactor.cpp` | 2,942 → 3,100 | |
| `amxsys.cpp` | 2,183 → 2,286 | the natives below, and `strFind` |
| `dlc.cpp` | 1,451 → 1,550 | the submarine shop |
| `session.cpp` | 876 → 954 | |
| `amxnet.cpp` | 534 → 600 | |
| `connection.cpp` | 863 → 884 | |
| `actor.cpp`, `graphics.cpp`, `network.cpp` | +4, +1, +1 | |
| new files: `friend.cpp`, `gamecoin.cpp`, `playreport.cpp` (at least 1,093 lines) | | `sdcard.cpp` (v0) gains a log |

`main.cpp` lost its log `Entering Mode : %s`.

- **Telemetry** (`playreport.cpp`): with the player's consent (asked at the title screen, then "Send Gameplay Data"
  in the options: "It will only be used in developing future products and services."), the game sends reports
  through SpotPass to `https://npvk.app.nintendo.net/reports`, built in its extra data
  (`Create ExtSaveData(ID=%lx)`, `%s/_PR_temp.dat`). They count everything: games, wins, kills, accuracy, distance,
  play time and play days, medals and first tries of each mission, each submarine's games, the options (gyro, Y
  axis, Morse off), the shop (visits, top-ups, purchases, the free trial's length before buying: `sale_trialspan`),
  each failed connection by its error code (`conn_180006`, `conn_60803`...), and the console's side: country,
  language, number of friends, the parental control's settings, Play Coins and the pedometer's total steps
  (`user_totstep10k`).
- **Play Coins for online battles, never switched on**: the update brings `GameCoin::useGameCoin` and the natives
  `sysGetGameCoinCount` / `sysUseGameCoin`, the telemetry counts `gamecoinpays`, and the texts are translated:
  "You will need %d Play Coins to play Internet Battle.", "You do not have enough Play Coins.", "Play Coins not
  required in Premium Version". No script calls the natives: the free version's online battles stayed free.
- **Their own list of forbidden words**: the Morse chat (Latin letters and digits only, which the console's
  Japanese word list does not catch) refuses, from the update on, a message containing `KOROSU` or `KOLOSU`
  (殺す, "kill"), `SINE` (死ね, "die"), `BAKA`, `AHO` (idiot) or `37564` — read "mi-na-go-ro-shi", 皆殺し, "kill
  them all", in Japanese number wordplay ([amxsys.cpp](../decomp/src/amx/amxsys.cpp)'s filter, through the new
  `amxsys::strFind`).
- New Morse phrases in the scripts: `GOOD`, `HELP`, `SORRY`, `THANK YOU`; a new include, `dialog.inc`; and the
  floating mine's programmer's prints, `----EXP-HERE!!!!`, `--IS MINE !!`, `----TEST01`, `---TEST02`.
