# A trained AI as strong as a player: how many matches?

The server's current bots (`mods/online/bots_*.pasm`) are **written by hand**: they aim at the nearest enemy where
it will be and fire as soon as they are lined up. This page estimates what an AI **learnt** by reinforcement
learning, as strong as a human player, offline and online, would take. These are orders of magnitude, not promises.

## In short

*Estimated progress: 0 % — no AI is trained; this page is only an estimate.*

10-minute 4-against-4 battles, the AI flying the 8 submarines (it plays against itself):

| Player to match | Training matches | Equivalent playing time (one match at a time) |
|---|---|---|
| **Local player**, casual (among friends, a few dozen matches) | **3,000 to 10,000** | 3 weeks to 2.5 months |
| **Average online player** (middle of the ranking of the time) | **15,000 to 40,000** | 3.5 to 9 months |
| **Good online player** (top of the ranking: long-range aiming, dodges, sonar and masker at the right time, team play) | **40,000 to 150,000** | 9 months to 3 years |

The rules are the same offline and online (same submarines, same maps): only the strength of the humans to match
changes. Offline, people mostly play among friends with little training; online, the regulars had hundreds of
matches behind them. The real computing time is much shorter than the playing time, because the AI plays several
matches at once and faster than real time (see below).

## What the AI has to learn

*Estimated progress: 10 % — we know where to read the game's state (script variables, actors) and which commands to
send; nothing is wired.*

- **Observe**: its position, heading, depth, speed; what the sonar and the periscope show (visible enemies,
  incoming torpedoes); the state of its team, its air and its torpedoes. This state is read in the game (script
  variables, actors) rather than in the image: that is 10 to 100 times cheaper to learn than pixels.
- **Act** 7 to 8 times a second (one decision every 4 frames): engine (ahead/astern), helm, dive, periscope
  direction, fire, homing torpedo, sonar, masker.
- **Win**: sink, not be sunk, stay alive with the team until time runs out.

## Where these numbers come from

*Estimated progress: 100 % for the estimate (assumptions and comparisons below); to be checked by a first
training.*

- **A match is a lot of experience**: 10 minutes at 30 frames per second, 18,000 frames; at one decision every 4
  frames, 4,500 decisions per submarine, 36,000 for the 8. The "good online player" level stands for 1.5 to 5
  billion decisions, the order of magnitude of the successful trainings on action games of this size.
- **Published comparisons**: DeepMind's *Capture the Flag* agents (Quake III, teams of 2, pixel vision) beat good
  human players after about 450,000 five-minute matches; OpenAI Five (Dota 2, far more complex) played the
  equivalent of tens of thousands of years. Sub Wars is slower, has fewer actions and simpler maps, and the AI would
  read the game's state instead of pixels: it needs 3 to 10 times fewer matches than in *Capture the Flag* for the
  top level.
- **Comparison with a human**: a beginner becomes a decent player in a few dozen matches and a good online player in
  a few hundred to two thousand; an AI starting from scratch needs 10 to 100 times more experience than a human, who
  arrives with a sense of space and of games already learnt.

## How much computing time

*Estimated progress: 0 % — neither a bridge to the game nor a simulator.*

Everything depends on how fast the game can be made to play.

**In the real game (Azahar)**: an emulator runs at 1 to 3 times real time on a good PC, and each console only flies
one submarine; a match of 8 AIs needs 8 emulators (about 1.2 GB of memory each). On a PC with 16 cores and 32 GB:
15 to 25 matches per hour.

| Player to match | Non-stop computing in Azahar |
|---|---|
| Local player | 5 days to 4 weeks |
| Average online player | 3.5 weeks to 4 months |
| Good online player | 2 to 14 months |

**In a simulator of our own**: write the game's physics again (movement of the submarines, torpedoes, damage,
collisions with the maps, sonar) from the decompiled scripts (`decomp/scripts/pscope_player.p`,
`periscope_move.p`, `surface_torpedo.p`; map formats in [formats.md](formats.md)), without display and vectorised on
a graphics card. It runs thousands of times faster than real time:

| Step | Estimated time |
|---|---|
| A simulator true to the game, checked against the game (same paths, same hits) | 1 to 3 months of development |
| Training up to the local player | a few hours on a recent graphics card |
| Training up to the good online player (self-play, leagues of opponents) | 2 to 7 days (or 30 to 150 € of GPU rental) |
| Bridge to the real game: the AI reads the state and sends the commands of an emulated console | 2 to 4 weeks |
| Tuning in the real game (gaps between simulator and game) | 1,000 to 5,000 matches, 1 to 2 weeks of computing |

That is **3 to 5 months** in all for one person, mostly development. A modest development PC (a few GB of memory,
no dedicated graphics card) is not enough for the training: it would take a PC with a graphics card, or a server
rented for a few days.

## Faster: imitate real players

*Estimated progress: 5 % — the server and the online mod exist; no recording of matches.*

Our server has humans playing online again: with their consent, the mod could record their commands and the game's
state. A few hundred matches of good players are enough to first learn to imitate them, then self-play improves the
AI: the level of a local player is reached in **a few hundred** training matches, and that of a good online player in
**5,000 to 20,000** instead of 40,000 to 150,000. No recording exists from the time of Nintendo's servers.

## And for bots like real players

*Estimated progress: 80 % — the hand-written bots now fly like players ([bots.md](bots.md)); a learnt AI remains to
do.*

The online bots now have a player's physics, collisions and weapons, and a hand-written pilot ([bots.md](bots.md)):
aiming where the target will be, dodging, retreating under the masker, varied maneuvers, learning how each player
dodges. A learnt AI would go further (team tactics, sonar, tricks), with the same commands. The logical next step:
run it on the server, wired to headless emulated consoles that join matches as players, or directly in the PC port.
