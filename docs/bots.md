# Bots that play like players

In the battles against the server's bots (a player left alone, `server.bots`), the computer-controlled submarines are
no longer the game's bots. In a battle between players, those the game adds to fill the teams stay the game's own, as
players know them: the pilot would upset the balance of the battle (`botInit` only takes over when `server.bots` is
1). The [`online`](../mods/online/mod.toml) mod gives them a pilot written in Pawn
([`mods/online/src/bots_pilot.p`](../mods/online/src/bots_pilot.p)), compiled by `tools/pawn2pasm.py` and tried in a
sandbox (`tools/botsim.py`). Offline (missions), the game keeps its own bots.

## What was wrong with the game's bots

*Estimated progress: 100 % — everything comes from reading the scripts (`decomp/scripts/surface_sub.p`,
`surface_torpedo.p`, `surface_torpedo_p_homing.p`).*

- **They go through walls and submarines.** `surface_sub` writes its position every frame (`actorSetPosition`) and has
  no `@eventCollide`: the engine does report the contacts to it (`Actor::procCollisions`), but nobody reads them. The
  player, on the other hand, pushes itself away in its `@eventCollide` (`pscope_player.p`).
- **They circle around their target.** Their heading follows the target at 0.01 radian per frame at most. As they
  never back off, they describe a circle of nearly 300 units of radius around a nearby player.
- **They do not fight each other.** They only look for the submarines of the other team. Above all, their torpedoes
  (`enemy`) ignore the other bots: `surface_torpedo.p @eventCollide` compares the submarine hit with its own
  `npcActorId`, that is with itself. Online, their homing torpedoes hit nothing at all: their `@eventCollide` only
  handles them offline.
- **They only hit the player of their console.** Their torpedoes call `UID_PLAYER`, the local player, which checks that
  the hit is for it. Players of the other consoles are therefore never hit. They deal 10 points of damage, whatever the
  team.
- **They fire without aiming.** They fire straight ahead every 250 frames after "aiming" at the target, without taking
  their heading or the target's movement into account. They do not back off, do not dodge, and use neither the masker
  nor homing torpedoes.

## The pilot

*Estimated progress: 90 % — tried in the sandbox; remains to be seen in Azahar.*

The bot only does what a player can do. It flies with the same controls (turning stick, throttle, ballast, fire),
within the same limits. The sandbox checks every frame: turn rate, top speed, axis of each shot.

- **A player's physics** (`pscope_player.p func_12184`, `func_13494`):
  - the turn rate goes toward `maxTurn × stick × factor`, by 2 % per frame while the stick is pushed and 3.8 % when it
    is let go; the factor is √(forward speed) / 10, at least 0.4, so 0.4 at a submarine's speeds;
  - the thrust is `throttle × belowAccel`; a drag of 0.038 applies along the submarine and across it;
  - reversing goes at half power (`periscope_move.p`);
  - the submarine brakes for a moment at each shot (`torpedoFireBrakeTime` frames at `torpedoFireBrakeRate`);
  - the ballast acts on the vertical speed (`diveRate`, `diveDrag`);
  - the nose tilts with the dive (pitch → −0.1 × vertical speed);
  - a contact pushes it back by 5 units per frame, as a player.

  These are the characteristics of its submarine (`bxml/pscope_plyNN_stats` and the tables `table_maxturn`,
  `table_below_accel`, `table_dive_rate`), with its crew's bonuses. A server bot has those of the submarine it shows
  (`server.bots.sub<k>`).
- **Collisions**: an `@eventCollide` added to `surface_sub` pushes it away from the map and the other submarines, and
  removes the speed that would drive it in. It also looks ahead (`worldClipLine`, several headings) to go round an
  obstacle, always by the same side while the way is blocked. It sounds the bottom, and backs off if it has hardly moved
  for two seconds.
- **The walls, with the whole hull.** A player's submarine is a capsule 550 units long: its nose is 300 units from its
  centre. The pilot used to sound from the centre and only slowed down at 300 units from a wall, that is nose against
  the rock. Worse, this braking and the climb in front of a slope only applied one frame in three, when `steerClear`
  runs. Now:
  - it looks 750 units ahead plus 80 times its speed (about 1,500 at full speed), the time it takes for a turn to
    build up;
  - it also checks two rays along its flanks (a central ray misses a corner);
  - it slows down according to the room in front of its nose, and backs off when it is about to touch;
  - it respects the ceiling of a cave;
  - these limits apply every frame.
- **Starting like a player.** The game puts each player on a spawn point of the map, the file `<map>_p<slot>`
  (position and bearing): the slot is (rank of its console + `network.randomstartloc`) mod 8, plus 1. On the maps
  where the teams start from two sides (`teamSpawnIndex` of `mode_settings`: maps 4, 7 and 10), it is
  (`randomstartloc` + rank in the team) mod 4, plus 1, and 4 more for the second team (`mode_periscope.p`
  `func_540c`; the decompiler loses these modulos, `sdiv.alt` followed by `move.pri`). The game's bots appeared at the
  six points of its computer subs (`func_10120`), scattered over the map, teammates included. Now each bot takes, on
  its first frame, the slot that follows the players', as one more player would. The points come from the map's own
  files, copied when the mod is built into `bxml/sdsw_spawn_<map>[_p<n>]` (recipe `[[bxml]] extract`,
  `mods/online/mod.toml`).
- **What it sees, like a player** (`player_label.p func_32fc`, `func_305c`): an enemy within 7,000 units, with nothing
  of the map between them, and not masked. Or an enemy its sonar found less than 300 frames ago, up to 15,000 units.
  Nothing else: it does not see through walls and does not have a map of every submarine. It aims at any enemy, player
  or bot, of this console or another one. It prefers the nearest, the most damaged, the one it can see.
- **A player's sonar** (`sonar.p func_414c`, `func_42d4`): with no enemy in sight, it pings now and then, with 120
  frames between two pings, and goes toward what it heard, otherwise around the middle of the map. The sonar does not
  hear a stopped submarine of another console (throttle under 0.05). Every console sees its ping on its sonar
  (`last_sonar`), like a player's.
- **The masker blinds it**: a masked enemy (`masker` or `masker_on`) is never seen, near or far. If its target masks
  itself, the bot loses it. It only knows where it was heading: it goes looking for it there for 8 s and may fire one or
  two torpedoes there at a guess. A homing torpedo loses its target too (the game, `surface_torpedo_p_homing.p
  func_4800`).
- **Aiming**: it aims where the target will be when the torpedo gets there. It knows a torpedo's exact run,
  118.8 × (n − 100 × (1 − 0.99ⁿ)) units in n frames (`func_1778`, `func_2ef4`), plus the submarine's speed, which the
  torpedo keeps at launch and which fades like its own. Like a player, it can only turn its hull:
  - the torpedo leaves from its tube (`torpedoSpawnPoint`), along the submarine's axis, with its pitch and speed
    (`periscope_move.p func_fbdc`);
  - to aim higher or lower, it climbs or dives, which tilts its nose and brings it closer to the target's depth;
  - it only fires if a torpedo leaving there, now, would pass close enough to the target;
  - the line must be clear, without a teammate within 220 units of the path;
  - a target that changes the way it turns is only aimed at from close.
- **It does not lead two shots the same way.** At each shot it draws how to lead the next one: the target keeps
  turning (a steady turn is a circle), it goes straight, or it dodges the way it has dodged so far (after a human's
  reaction time, 15 frames). It **learns how you dodge**: after each shot, it looks at how its target turns 30 frames
  later, and keeps the average per player for the whole session, in `bots.dodge.<node>`: every bot of the console
  benefits from it. Whoever always breaks the same way gets caught; whoever learns "the" bots' shot no longer sees a
  single one.
- **Combat with no two fights alike.**
  - Each bot draws its temper at the start: the distance it likes (0.85 to 1.25 times the usual one, 2,200 to 3,000
    units, 1,700 against an agile target), its aggressiveness, the side it circles by, the depth it takes.
  - In combat it changes maneuver every 2 to 10 seconds, at random and according to its temper: holding its distance
    facing the target, circling it, closing in, breaking off then coming back, changing depth, or stopping short (a
    torpedo led on its speed then passes in front of it).
  - Ready to fire and nearly facing it, it turns in and fires, like a player.
  - When its teammates fight the same target, it comes from another side.
  - It backs off from an enemy that is too close and never rams it.
- **Dodging**: a torpedo that is going to pass close to it, it sees coming, and gets out of the way in a way of its own
  choosing: to one side or the other, climbing or diving (a torpedo keeps its depth), at full speed or braking hard to
  let the torpedo pass in front.
- **A player's waiting times** (`periscope_move.p`):
  - between two torpedoes, its submarine's `torpedoFireInterval`, plus 15 frames;
  - the reload, all at once, `torpedoReplenishTime` seconds after the last torpedo, and only when none is left;
  - weapons, homing ones included, wait 135 frames after each shot, and the next torpedo `torpedoFireInterval` + 15
    frames (`func_10e04`: the game's delay plus 15);
  - the masker waits 150 frames after the previous one.
- **Homing torpedoes**: none at the start. Like a player, it only gets some by picking up the containers a sunk
  submarine leaves, 3 at most. They are the players' (`surface_torpedo_p_homing`, locked by `@lockOnTarget`), fired
  along the submarine's axis at a target followed for 1.5 s. It fires them at a target that turns hard or crosses fast,
  or when it is damaged.
- **Containers**: the game forbade its submarines to pick them up (`surface_item.p @eventCollide`). The bot picks them
  up like a player, and goes for the one it sees when it needs it. A repair gives back a fifth of its hull, or all that
  is missing if less than 20 is missing; a homing torpedo adds to its stock. Every console removes the container
  picked up (`@botTakesItem`).
- **Low hull** (under 40 %): it keeps its target and backs off while firing. When an enemy closes in, it goes under its
  masker (`masker`, `masker_on`: 300 frames for 33.3 of air) and flees deep. Like a player, it only gets air back at
  the surface: three maskers per life at most, never more.
- **Its torpedoes** are the players' (`surface_torpedo_lv0N`, 20 to 30 points of damage). They hit like a player's
  ([`bots_shot.inc`](../mods/online/src/bots_shot.inc)): the target's console takes the hit
  (`@eventMessageWeaponHitTorp` for a player, `@torpedoHitOnNpcToOwner` for a bot). They go through their teammates and
  their shooter. The shooter is marked as a bot: the console's player does not count its kills.
- **Its death counts**: the game only reports a bot sunk by a torpedo (`@eventMessageAISubDead`). It does not for a bot
  sunk by an explosion (`@explosionHitOnNpc`), and finds the bot's team again by its sync number. The battle could
  therefore never end. Now the bot's pilot announces its death itself, once, with its team: every console hears it
  (`@botDown`, [`bots_game_state.p`](../mods/online/src/bots_game_state.p)) and removes the bot from its team's
  counter.
- **The victory replay**: at the end of the battle the game shows the run of the torpedo that sank the last submarine of
  the losing team. It learns it from a player's death (`@scheduleCheckGameOver(node, time, node and number of the
  torpedo)`) and finds the dead one's team by `player.<node>.team`. A bot's death had neither torpedo nor node: when a
  bot was the last one sunk, that is when the players won, there was no replay. Now each torpedo that hits a bot tells
  every console (`@botHitBy`). The bot's death is recorded like a player's, with this torpedo and a node of its team
  (`0x7b070000` + team).

  When no torpedo sank it, or the last one is more than 5 s old (it ran into the map), the replay shows the bot itself,
  like a player's (`pscope_player.p func_8d38`). For that, it stays synchronised 215 frames after its death, like a
  torpedo after its explosion.
- **A player for the game**: the game recognises players by their network node (`player.<node>.name`, `.team`). Each
  bot k has one of its own, `0x7b070000` + k, with its name and team
  ([`bots_game_state.p`](../mods/online/src/bots_game_state.p)). It therefore has what a player has:
  - "You hit <bot>!" (`@pushTargetHitMessage`) and the hit marker for whoever hits it;
  - "<bot> is attacking you!" (`@pushHitByShooterMessage`) for the player it hits;
  - "<bot> has been sunk!" for everyone, instead of the computer subs' "The enemy has been sunk!";
  - the kill counted for its shooter (`incrementKills`);
  - the HUD's hit marker no longer appears when a bot of this console hits another one.
- **Dying like a player**: it explodes and disappears at once (`explosion_player_dead`), without sinking slowly for 6 s
  (`func_ba34`). On the other consoles, its copy explodes like a player's.
- **A player's life and damage**:
  - 100 life points, multiplied by the size of the other team over its own when its own is smaller
    (`pscope_player.p func_14f60`);
  - the game only counted human players; now the bots are counted, for the players too
    ([`bots_player.pasm`](../mods/online/bots_player.pasm)): alone against 4 bots, a player has 400 life points, as
    alone against 4 players;
  - a player's damage (`@eventDamageTorp`, `@eventMessageExplosionHit`), where the game gave other values to its computer
    subs:

    | Hit | Player (and bot) | Computer sub |
    |---|---|---|
    | torpedo | its damage | the same |
    | homing torpedo | 30 | 70 |
    | explosion | 5, within 750 units | 30, within 300 |
    | after a hit (and at the start) | nothing for 60 frames | everything |
    | contact with the map or a submarine | 2.5, once a second | nothing |
    | an ally's torpedo or explosion | nothing ("You hit an ally!") | everything |

  - each hit is multiplied by its submarine's `damageRate`, rounded up;
  - the spectator sees its gauge go down (`lifecapacity`, read by `hud.p @setTelecastPlayer`).
- **The oil leak** (the black smoke of a damaged submarine) appears under 40 % of its hull, as for a player
  (`netplay_dummy_sub.p`: `life < lifecapacity / 2.5`). The game turned it on under 100 points, whatever the hull.
- **Seen for a moment under its masker when hit**, like a player: `pscope_player.p func_a758` sets display flag 6 when
  the life goes down and `func_60b4` makes the masked submarine flash. Nobody set it for `surface_sub`. The bots also see
  for a moment a masked enemy that was just hit.
- **Its name for spectators**: `world_map.p` names the submarine followed by its `nodeid`. A bot's was the node of the
  console flying it ("Position of <your nickname>'s ship"). Now it is its own node, and each console knows its name as
  soon as it arrives (`@botJoin`).
- **Always within a player's limits.** Everything goes through the same controls (stick, throttle, ballast, firing along
  the axis). The sandbox checks every frame.

## The crew

*Estimated progress: 85 % — checked in the sandbox (ratings, repair, loading `crew_stats`); remains to be seen in
Azahar.*

The server gives each bot a crew, like a player's (`server.bots.crew<k>`: up to five members, 6 bits each). The bot only
keeps as many as its submarine takes (`crewCount`, 1 to 5). It reads the members in the `crew_NN` actors the player's
script loads (`worlds/crew_stats`), and loads them itself if they are missing. At the normal level it takes 0 to 3
members at random; at the hard level, 2 to 5; at the expert level, 4 or 5 members that only add (`bots_crew = false`:
no crew).

- **The ratings**, as for a player (`pscope_player.p customUpdateSubBonusStats`): each member adds its points of turning,
  acceleration, dive, armour, torpedoes and reload to the submarine's. The ratings stay between 1 and 10, the reload
  between 1 and 30.
- **The abilities**, at the game's values:

  | Ability | Member | For the bot | What the game does |
  |---|---|---|---|
  | `lockOnLong` | 20 | sees and aims at 8,500 instead of 7,000 | `player_label.p func_32fc` |
  | `wideSonar` | 27 | sonar at 20,000 instead of 15,000 | `sonar.p func_42d4` |
  | `maskerConsumptionRate` | 25 | masker at 25 of air instead of 33.3 | `periscope_move.p maskerActivate` |
  | `repair` | 30 | repairs 1 % of its hull every 75 frames (60 in v5200) | `pscope_player.p func_14ca8` |
  | `longMasker` (v5200) | 33 | masker of 450 frames instead of 300 | `maskerActivate` |
  | `airRepairUp` (v5200) | 34 | air at 0.3 per frame at the surface instead of 0.2 | `periscope_move.p` |
  | `autoMasker` (v5200) | 36 | automatic masker when a homing torpedo locks on it or rushes at it; it takes it off after 3 s if it is not damaged | `@HomingLockOn` → `@autoMasker` |
  | `teamRepair` (v5200) | 37 | repairs its teammates within 2,000 | `pscope_player.p func_19744`, `func_1a424` |
  | `hideSonar` (v5200) | 39 | absent from the enemy sonar under 40 of hull | `sonar.p func_5d6c` |

  The server does not give the bots the members whose ability only helps a human: listening to the enemy's Morse (14),
  the allies on the map (31) and, in v5200, the mine dropped with the masker (32).
- **And for the others.** A player's abilities apply to the bots as to players:
  - a player's wide sonar and long lock-on range find the bots further away (the game);
  - a player's team repair repairs the bots of their team within 2,000;
  - a player under `hideSonar` and under 40 of hull escapes the bots' sonar.

  The other way round, a bot's team repair and hidden sonar go through its properties `teamRepair` and
  `targetHideSonar`, which the game synchronises. The game only looked at them on the copies of the other consoles'
  submarines: the mod extends these two tests to the submarines the console flies (`pscope_player` 0x1981C and `sonar`
  0x6150 in v5200, `0x80000` → `0x80004`). This way, a bot also repairs the player of its own console.

The server's level (`bots_level`, `server.bots.level`) sets the reflexes and the aim, never what the submarine can do.
All the values are in `bots_pilot.p`:

| Level | Looks around | Pause after reloading | Shot passing at most | Sees torpedoes coming | Turns predicted | Maneuvers | Learns your dodges |
|---|---|---|---|---|---|---|---|
| normal | every 10 frames | 40 to 60 frames | 90 units from the target | 35 % | no | hold, circle, depth; 5 to 10 s | no |
| hard (default) | every 6 frames | 12 to 18 frames | 60 units | 85 % | yes | all six; 2.5 to 6 s | yes |
| expert | every 3 frames | 0 | 45 units | always | yes | all six; 1.7 to 4.7 s | yes |

## In the update v5200

*Estimated progress: 90 % — checked in Azahar (v5200): the bots' damage, defeat, the torpedo's replay, victory on time;
victory by sinking every bot remains to be seen in the emulator.*

The bots' code is the same, translated for the update's recompiled scripts
([update-v5200.md](update-v5200.md#scripts-from-one-version-to-the-other)). Tried in Azahar, it broke in several
places, all fixed:

- **The battle did not end when the last bot sank.** `@botDown` (`bots_game_state.p`) stopped midway, after lowering the
  team's counter: no "... has been sunk!", no kill, no check of the end of the battle, no replay. Two causes: the v5200
  no longer has the text `sub_sunk` (replaced by `sub_sunk_01`, "%s sank %s!", and `sub_sunk_02`), and its scripts only
  have 8 KB of heap and stack, against 16 KB in the game. The message now follows the version
  (`#if SDSW_VERSION >= 5200`, a constant of `tools/pawn2pasm.py`), and the mods' code gives 16 KB back to every script it
  changes (`.heapstack`), except the torpedoes, loaded one by one.
- **The player was invincible.** The v5200 adds "friendly fire" to `@eventDamageTorp`: no damage if the team of the
  shooter's node is the player's. A computer sub's shot carries the node of its console (the game finds the torpedo
  there for the replay): alone against the bots, that is the player's console, who therefore took no damage. A bot's
  torpedo that reaches the player is always an enemy's (the teammates' go through): for it, no more friendly fire (a
  hook in `mod.toml`, only against the server's bots).
- **"CPU sank <player>!"**: the v5200's `reportDeath` names the shooter, `name_npc` for a computer sub. Each console
  remembers the bot that last hit each player (`@botAttacks`): "Dolphin sank Ronald!".
- **The game stopped ("Exception Type: Break")** after a few minutes: each torpedo loads its own copy of its script
  (about 70 KB in v5200) into the 24 MB of main memory, which ran out with seven bots firing. The `fixes` mod raises the
  main memory to 26 MB, for both versions.
- **The characteristics of submarines 24 to 36**: a bot that showed one took those of the first.
- **The duration**: the battles against the bots last `duration`, like the others (`bots_duration` is removed).

To test: `tools/botsim.py --version v5200` (the pilot in the sandbox), then Azahar with a test server
(`bots_format = "1v1"`: the bot must sink the player, the defeat and the replay follow).

## The sandbox

*Estimated progress: 80 % — AMX interpreter, simple world; not the game's map nor its collision physics.*

```sh
make pawncc bots                        # the Pawn 3.3 compiler, then src/*.p -> mods/online/*.pasm
python3 tools/botsim.py                 # duel, close, walls, corner, canyon, cave, retreat, dodge, masker, habit,
                                        # melee, spawn, crew, at the three levels
python3 tools/botsim.py duel --level 3 --pitch-sign -1
```

`tools/botsim.py` assembles `bots_pilot.pasm` into the dump's real `surface_sub.amx`. It runs its code, as Pawn 3.3's
amx.c does, in a world of its own: bottom, blocks, submarines, and torpedoes with the game's physics. The natives
(`worldClipLine`, `worldFindActors`, properties...) are simulated there. It counts shots, hits and frames spent against
the map. It reports any movement a player could not make: turn rate beyond 0.4 × `maxTurn` (crew included), speed
beyond `belowAccel / linDrag`, a torpedo leaving off the submarine's axis. It reports any fault of the machine (stack,
memory, unknown instruction).

The sandbox's world gives the submarines a player's hull, a capsule 550 units long (five spheres along the axis). The
earlier version of the sandbox only had a sphere of 110 units at the centre: it did not see the submarine's nose hit
the walls.

Results (1,800 frames, one minute of play):

| Scenario | normal | hard | expert |
|---|---|---|---|
| duel against a player who zigzags and changes depth | 43 % of the shots hit | 67 % | 100 % |
| player turning very close | 25 % | 80 % | 80 % |
| behind a wall 6,000 units long | 100 % | 100 % | 100 % |
| zigzag channel, target at its end | 100 % | 100 % | 80 % |
| cave with a low ceiling | 57 % | 100 % | 100 % |
| player who always breaks the same way (`habit`) | 80 % | 80 % | 80 % |
| low hull, a player rushing at it: it backs off firing | player sunk in 22 s | in 17 s | in 15 s |
| player masked for 10 s | lost from sight, 1 shot at a guess | 2 shots at a guess | 1 shot at a guess, no hit |
| 4 bots against 4 bots | 19 hits | 22 hits | 22 hits |
| start (map 1, one player against 4 bots) | slots 5 to 8, the player in 4 | | |
| crew (5 members, repair included) | +45 of hull in one minute | | |

Frames spent against the map, at the expert level, with the capsule hull:

| Scenario | old pilot | new pilot |
|---|---|---|
| launched at full speed toward a corner (`corner`) | 30 | 0 |
| walls and rocks (`walls`) | 3 | 0 |
| cave (`cave`) | 11 | 5 |
| channel (`canyon`) | 0 | 0 |

On every scenario and at every level, the sandbox found no movement and no shot impossible for a player. Every shot
leaves along the submarine's axis, and the turn rates and top speeds stay under those of its submarine.

The pilot costs 2,000 to 7,000 AMX instructions per frame and per bot. Measurements in the sandbox settled several
choices:

- the exact interception, in closed form (straight lines and arcs of circle), replaced a frame-by-frame simulation six
  times more expensive;
- the prediction of a dive is limited to 25 frames;
- the side by which it goes round a wall stays the same while the way is blocked;
- to aim higher or lower, it climbs or dives: its nose tilts and the torpedo leaves along its axis;
- the stick is tuned to follow a moving heading (the error falls under 0.01 rad).
