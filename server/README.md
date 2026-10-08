# Online server

A replacement server for the online mode of Steel Diver: Sub Wars: players' login, match search (matchmaking) and help
with the direct connection between consoles (NAT traversal). The battles themselves are played console to console (Pia,
P2P): the server only sees the bookkeeping of the lobbies.

Written in Python (3.11 or newer), **with no dependency at all**: the standard library is enough. Everything it
implements comes from reverse engineering the game (EUR v0); the details are in [../docs/online.md](../docs/online.md).

**Checked with the real game**: two Azahar instances with the [`online`](../mods/online/mod.toml) mod connect, meet in
the same lobby and start a battle together.

## Running the server

*Estimated progress: 100 %.*

```sh
cd server
python3 -m sdsw_server                          # both realms of server.toml + the NAT detection
python3 -m sdsw_server --realm emulator -v      # a single realm, detailed log (-vv: packets)
```

The simplest way is the launcher (`python3 subwars.py`, **Server** tab): one button starts it, shows the address to
give to your friends, and edits the options below.

## Two realms: emulator and PC

*Estimated progress: 90 % — the PC realm is ready on the server's side but waits for the PC port.*

The file [`server.toml`](server.toml) describes two fully separate "realms" (accounts, lobbies):

| Realm | Players | Authentication | Secure server |
|---|---|---|---|
| `emulator` | Azahar + `online` mod | UDP 61000 | UDP 61001 |
| `pc` | PC port (to come) | UDP 61010 | UDP 61011 |

Both run in the same process and share the NAT detection (UDP **10025** and **10125**, ports set by the game). The PC
port will run the same network code as the game (NEX and Pia), so the same protocol: only the port it aims at changes.
To have everybody play together, it would be enough to give it the `emulator` realm's port.

## Bots and cheating

*Estimated progress: 90 % — anti-cheat and keeping cheaters apart done; bots that play like players, to be seen in
Azahar.*

Each realm has its match options in `server.toml` (the launcher shows and changes them, **Server** tab, "Server
configuration"):

* **`max_players`** (2 to 8): number of human players per match. The host console fills each team up to 4 submarines
  with the game's computer subs (`mode_periscope` › `@setNpc`): fewer humans means more computer subs. In a battle
  between players, these stay the game's own.
* **`duration`** (1 to 30 minutes, 10 by default like the game): length of an online battle. The server sends it to each
  console when it looks for a match (`server.duration`) and the [`online`](../mods/online/mod.toml) mod puts it in place
  of the 600 seconds set by the game (`mode_periscope` › `inputProperties`); an older online mod keeps 10 minutes. The
  battles against the bots last as long (the older option `bots_duration` is ignored).
* **Bots for a player alone** (`bots = true`, with an up-to-date [`online`](../mods/online/mod.toml) mod): a player left
  alone in a match for `bots_delay` seconds (60) plays against bots. The original game waits forever for an opponent;
  here the server sends the game the match's settings, and the bots **join the lobby like players**, one by one (name,
  submarine, level, ready), then the countdown (`bots_countdown` seconds) starts the battle. In battle they have the hull
  and colours of a real submarine, their name and level above them (not "CPU"), they count in the team counters and for
  the victory, and the spectator's camera can follow them. Options:
  * `bots_format`: both teams, `"4v4"` (you and 3 bots against 4 bots), `"1v4"` (alone against 4), `"2v3"`... 1 to 4 per
    team; if another player arrives before the battle, they play with you and the bots fill in;
  * `bots_map`: `"random"` or a map's number (1, 2, 4 to 10, and 11 to 13 for the update v5200; the launcher shows their
    names, read in your game);
  * `bots_level`: `"normal"`, `"hard"` or `"expert"`; the bots fly like players (physics and characteristics of their
    submarine, collisions, the players' spawn points, aiming where the target will be, varied maneuvers, learning how
    each player dodges, dodging, homing torpedoes, masker and retreat when their hull is low:
    `mods/online/src/bots_pilot.p`, [../docs/bots.md](../docs/bots.md)); the level sets their reflexes and aim;
  * `bots_crew`: `true` (by default), each bot takes a crew as a player does (up to 5 members, as many as its submarine
    takes), which changes its ratings and gives it their abilities (lock-on range, wide sonar, cheaper or longer masker,
    repair...); at the expert level, members that only add ([bots.md](../docs/bots.md#the-crew));
  * `bots_names`: the bots' names (7 at least, 10 characters at most), drawn at random for each match.

  How the server talks to the game: through NEX notifications of its own (types 999001 and 999002) that the `online`
  mod turns into script variables of the game (`server.bots.*`); details in
  [../docs/online.md](../docs/online.md#8-server--game-the-mods-variables).
* **`cheats`**: what to do with the players whose mod holds [cheats](../mods/cheats/mod.toml), a
  [faster submarine](../mods/speed/mod.toml) or [changed submarine characteristics](../mods/specs/mod.toml) (their token
  says so: flags `cheats` and `specs`): `"separate"` (by default: they only meet other cheaters), `"allowed"` (they play
  with everybody) or `"refused"` (connection refused). The [`premium`](../mods/premium/mod.toml) mod (flag `premium`) is
  not cheating: it gives what premium players had. The cheating itself is in the game, not in the server; a game
  modified some other way can always lie, as in any P2P game. For a server where everybody cheats, set
  `cheats = "allowed"`. The older French values (`separes`, `autorises`, `refuses`, `difficile`, `aleatoire`) are still
  understood.
* **Anti-cheat** (except with `cheats = "allowed"`, and not in the cheaters' matches): the server asks each player's
  `online` mod to watch its own submarine in battle — damage cancelled for no reason of the game (invincibility),
  torpedoes that do not go down, shots less than a second apart (no submarine fires faster than every 2.8 s), a speed
  beyond 20 units per frame for 3 seconds (the fastest caps at 14.2). At the first sign, the game **leaves the battle** as
  with the game's "quit" button (the cheater disappears from the others' battle) and keeps this kick in its save; at its
  next match search, it tells the server, which puts it with the cheaters (`separate`) or keeps it out (`refused`) for
  `anticheat_ban` minutes (30 by default; list in `data/<realm>/exclusions.json`, each kick is only punished once). This
  catches Azahar's cheat codes and cheat mods whose flag was hidden; a game whose watch was removed escapes it, as in any
  P2P game without a match server. In Azahar without the console's system files, the game cannot show the error code of
  a player kept out: their search simply goes back to the menu.

## Status page and bans

*Estimated progress: 100 %.*

* **Status page**: with `status_port = 8730` (section `[server]` of `server.toml`), the server publishes over HTTP a page
  (`http://<address>:8730/`) and its JSON version (`/status.json`): players online, accounts, options, and the matches
  under way (number of players, open or started, cheaters' match, for how long). No player identifier appears there.
  Open this TCP port to make it public.
* **Banning a player**: their identifier (the log shows `login pid ...` at each connection) on a line of
  `data/<realm>/bannis.txt` (lines starting with `#` are comments). The file is read again at each connection: no need
  to restart, that player's next connection is refused.

## Play with friends far away

*Estimated progress: 85 % — UPnP and STUN checked; not yet a real battle between two homes, no relay for strict NATs.*

The simplest way: the launcher (`python3 subwars.py`, **Server** tab). "Start the server" first stops a server already
running on the computer (started by an older launcher, a terminal), then shows the **address to give to your friends**.
Each friend enters this address in "Join a friend's server" ("Test" checks that the server answers from their home),
then installs the **Online play** mod with it. Whoever hosts plays on the same computer with the address `127.0.0.1`
(the mod's default setting).

What the server does to be reachable from the Internet:

* **Public address**: `public_address = "auto"` (the default) asks the router for its Internet address (UPnP), otherwise
  a public STUN server (Google, Cloudflare). It can also be written: an IP, or a name (`myserver.duckdns.org`, handy if
  the address changes; the game resolves names).
* **Ports opened on the router**: with `upnp = true` (the default), the server asks the router to forward its UDP ports
  to it (61000-61001, 61010-61011, 10025, 10125, and the status page's TCP port if there is one), renews these forwards
  while it runs and removes them when it stops. Checked with a consumer router.
* **The player who hosts**: their console connects through `127.0.0.1`, an address that means nothing to a friend. Yet,
  to join a match, a console compares the host's public address with its own: the same, it goes through the local
  network; another one, through the public address. The server therefore shows the players of its own network under its
  public address, and has the router forward their game's port (Pia, taken at random between 49152 and 65534) while
  they are connected. Without this forward, routers running Linux (most of them) make the direct connection fail: the
  friend's first packets create an entry there that forces another port for the answer.

Without UPnP (turned off on the router, or `upnp = false`), forward by hand to the server's computer: UDP 61000-61001
(and 61010-61011 for the PC realm), 10025 and 10125, and, to play yourself on that computer, the UDP range 49152-65535
(the game's port changes at each connection). The server tries UPnP again every 20 minutes.

### When the router is not enough

* **Shared IPv4**: the router only has part of the ports (some operators share one IPv4 address between several
  customers) and refuses forwards outside its range, or it is itself behind the operator's NAT (some mobile or
  satellite offers). The launcher shows the forwards refused, and reports "another NAT in front of the router" when the
  router's address is not the one the Internet sees. Many operators give a full IPv4 address on request.
* **Virtual private network** (ZeroTier, Tailscale, Radmin VPN...): all the players join the same network, and
  everybody, including whoever hosts, builds the mod with the server's address **on that network**. No port to open.
  The server gives each one the address through which it was reached.
* **Server on a rented machine** (VPS): run `python3 -m sdsw_server` there and open its UDP ports in its firewall; all
  the players are then "far away", including whoever rents it.

The battle itself stays console to console: if both players' NATs are strict (symmetric), the direct connection may fail
even with a reachable server.

### Checking from a friend's home

```sh
cd server && python3 -m sdsw_server.testclient --probe <address>[:61000]
```

sends what the console sends before connecting (start of the connection to both servers, NAT detection) and says
whether the server answers, and under which address it sees the friend. It is the launcher's "Test" button.

### Started by the launcher

The server writes `data/server.json` while it runs (process, ports, public address, the router's forwards), which the
launcher shows; `--exit-with-stdin` stops it cleanly (forwards removed) when the launcher that started it disappears,
even killed: no more forgotten server holding the ports.

## Accounts

*Estimated progress: 100 %.*

No sign-up: on a 3DS, the password came from Nintendo's account servers. The mod gives each player a random identifier
(principal ID) and password, created when they build the mod; the authentication token holds the Kerberos key derived
from the password. The server registers the identifier at its first connection and then demands the same key
(`data/<realm>/accounts.sqlite3`).

No game data is stored: the game uses no rankings or server-side storage.

## Organisation of the code

*Estimated progress: 100 %.*

| File | Role |
|---|---|
| `sdsw_server/prudp.py` | PRUDP v1 transport: handshake, HMAC signatures, RC4, reliability, fragments |
| `sdsw_server/rmc.py` | method calls (RMC), both ways |
| `sdsw_server/streams.py`, `ddl.py` | NEX serialisation and the game's structures (MatchmakeSession, criteria...) |
| `sdsw_server/crypto.py` | RC4, Kerberos encryption, key derivation |
| `sdsw_server/realm.py` | authentication server (TicketGranting) and secure server (SecureConnection, NATTraversal, MatchMaking, MatchmakeExtension) |
| `sdsw_server/matchmaking.py` | lobbies, notifications, bots for a player alone and their crews |
| `sdsw_server/config.py` | the options of `server.toml`, read and written back with their comments (launcher) |
| `sdsw_server/natcheck.py` | Pia's NAT detection ("nncs" servers) |
| `sdsw_server/internet.py` | public address, the router's forwards, players of the server's network |
| `sdsw_server/upnp.py`, `stun.py` | UPnP (router) and STUN clients, standard library only |
| `sdsw_server/accounts.py` | accounts |
| `sdsw_server/status.py` | status page (HTTP) |
| `sdsw_server/testclient.py` | a client that behaves like the game, to test without a console; `--probe` |

## Tests

*Estimated progress: 90 % — 46 automatic tests; trials with the real game stay manual.*

```sh
cd server
python3 -m unittest discover -s tests -t . -v      # formats, cryptography, a complete session with 3 players, matching
python3 -m sdsw_server.testclient --players 2       # against a running server (--server host:port)
```
