# Online mode: what the client does, what the server must answer

Reconstructed from the game's code (EUR v0, revision 31308): `source/net/connectionInternet.cpp`, the script
`connect.inc` and the NEX 3.7 libraries (`libOnlineCore`, `libRendezVous*`, `libJugem*`, `libMatchmakingClient`,
`libNATTraversalClient`) and Pia (`libpia_inet`), all named by the symbol table `romfs:/map`. It is the specification
the server of [`server/`](../server/README.md) follows, **checked with the game**: two Azahar instances connect, meet
in a lobby and start a battle.

## Overview

*Estimated progress: 100 %.*

| Step | Who | Protocol |
|---|---|---|
| 1. address of the game server, token | the console's "friends" module → NASC | replaced by the `online` mod |
| 2. authentication | authentication server (UDP) | PRUDP v1 + RMC `TicketGranting` |
| 3. secure connection | secure server (UDP) | PRUDP v1 + Kerberos, RMC `SecureConnection` |
| 4. NAT type | "nncs" servers (UDP 10025/10125) | 16-byte `NATCheckMessage` messages |
| 5. match search | secure server | `MatchmakeExtension`, `MatchMaking`, `NATTraversal` |
| 6. the battle | console to console | Pia (P2P): the server takes no part |
| 7. distant players | server, router | public address, UPnP forwards, players of the server's network |
| 8. server settings | server → game | notifications of our own, script variables (`online` mod) |

## 1. Login: `gameServerLogin` and `JobCTRLogin`

*Estimated progress: 100 %.*

`ConnectionInternet::matchmakerLogin` → `gameServerLogin(ngsFacade, ...)`:

1. `nn::friends::CTR::detail::Login`, then waiting for the event (the *friends* module connects to Nintendo's
   servers); `GetMyPrincipalId` gives the player's id (kept by the game).
2. `NgsFacade::Login(..., 0x000D7C00, L"fb9537fe", 60000)`: NEX server id, **access key** `fb9537fe`, 60 s timeout.
   The task `nn::nex::JobCTRLogin`:
   * `StepFirst` reads `GetGameAuthenticationData`; if the result is 1 and the HTTP code 200, it goes straight to
     `StepGameLogin`, otherwise it asks for an authentication (`RequestGameAuthentication`, NASC);
   * `StepGameLogin` reads the server's address and port in this data (a 0x138-byte structure: +0 result, +4 HTTP
     code, +8 address on 32 bytes, +0x28 port, +0x30 token on 256 bytes, +0x130 time), the account's password with
     `GetMyPassword` (32 bytes), and calls `RendezVous::Login` with the principal ID in decimal as the user name and
     an `AuthenticationInfo` (token, NGS version 3, type 0, server version 1000).

**In Azahar**, `frd:u` is an incomplete emulation: `RequestGameAuthentication` and `GetGameAuthenticationData` are
empty functions there that "succeed" without returning anything or signalling the event, and the game waits until the
60 s timeout. `GetMyFriendKey` (where the principal ID comes from) returns 0 for everybody. Hence the patch of the
[`online`](../mods/online/mod.toml) mod, which replaces `GetMyPrincipalId`, `GetMyPassword` and
`GetGameAuthenticationData`: the only caller of the last two is `JobCTRLogin`.

## 2. Transport: PRUDP version 1

*Estimated progress: 100 %.*

Streams of type 10 (RVSecure) use **version 1** of PRUDP: the `PRUDPStream` constructor takes the version from a NEX
global variable initialised to 1 (byte 0x00399D2E). `PRUDPMessageSelector` also accepts version 0 and a relay format
(`F5 D0`), which the client does not send to the server.

```
EA D0 | version 1 | options size | payload size (u16) | source | destination
      | type + flags (u16: type on 4 bits) | session | substream | sequence number (u16)
      | signature (16) | options | payload
```

* Types: SYN 0, CONNECT 1, DATA 2, DISCONNECT 3, PING 4. Flags: ACK 0x1, RELIABLE 0x2, NEED_ACK 0x4, HAS_SIZE 0x8
  (always in v1), MULTI_ACK 0x200.
* Options (`PRUDPMessageV1::OptionBuilder`): SYN and CONNECT carry 0 "functions" (u32: minor version in the low byte;
  the client announces 3), 1 connection signature (16 bytes), 3 initial unreliable sequence number (CONNECT, if not
  zero), 4 maximum substream (u8); DATA carries 2 fragment number (u8, 0 = last).
* Signature (`CalcSignatureHelper`): HMAC-MD5 keyed with MD5(access key) over the 8 header bytes from the source to the
  sequence number, the session key (packets other than SYN/CONNECT, on the secure server), the sum of the bytes of the
  access key (u32), the connection signature **of the other side**, the options and the (encrypted) payload. The SYN
  includes none; the server therefore signs with the one the client put in its CONNECT, and the client with the one of
  the server's SYN-ACK (checked on the game's packets).
* Payload encryption (`PacketEncDec`): RC4, one continuous stream per direction, the Kerberos session key on the secure
  server and **`CD&ML`** on the authentication server (found by decrypting the game's first message: the key does not
  appear as such in the executable).
* Reliability: the first reliable packet expected from the server has number 1 (`PacketDispatchQueue`), the client's
  start at 2 (the CONNECT has 1). The game acknowledges with **aggregate ACKs**: a DATA packet, flag MULTI_ACK without
  ACK, substream 1, payload = u8 substream, u8 count n, u16 last number acknowledged (and all the earlier ones),
  n × u16. PINGs have their own numbering and ask for an ACK.

## 3. Authentication and secure connection

*Estimated progress: 100 %.*

Authentication server: `prudp:/address=<address>;port=<port>;stream=10;sid=1;type=2`
(`JobBackEndServicesLoginWithData::ConnectToAuthenticationService`).

| Call (protocol 10) | Parameters | Answer |
|---|---|---|
| `LoginEx` (2) | String name (= principal ID), AnyDataHolder `AuthenticationInfo` | result, PID, Buffer ticket, `RVConnectionData`, String server name |
| `RequestTicket` (3) | source PID, target PID (the secure server, 2) | result, Buffer ticket |

* The user's key: MD5 applied 65000 + PID mod 1024 times to the password (`MD5KeyDerivation`).
* Kerberos encryption: RC4(key), then HMAC-MD5(key, encrypted) appended.
* Ticket (decrypted by the client): 32-byte session key, target PID (u32), Buffer internal ticket (opaque to the
  client, the server's own). The ticket of `LoginEx` only serves to check the key (`ValidateKey`); the connection uses
  the one of `RequestTicket`.
* `RVConnectionData` (version 1): URL of the secure server
  (`prudps:/address=...;port=...;CID=1;PID=2;sid=1;stream=10;type=2`), empty list, empty URL, time (DateTime).
* CONNECT to the secure server: Buffer(internal ticket) + Buffer(Kerberos(session key: PID, connection number, check
  value)); the CONNECT-ACK must hold Buffer(u32 check value + 1) (`JobConnectSecureEndPoint::ProcessConnectResult`).
* `SecureConnection::Register` (11/1): list of local URLs → result, connection number (RVCID), public URL as the server
  sees the client. `ReplaceURL` (11/7) arrives once the NAT detection is over: Pia puts the port of **its own socket**
  and the NAT type into the private URL.

## 4. NAT detection (Pia)

*Estimated progress: 100 %.*

`NatTraverser::updateNatServerAddress` declares two servers to NEX, `nncs1` and `nncs2.app.nintendowifi.net` (UTF-16
strings read through the pointers 0x003B0940/0x003B0944), each on UDP ports 10025 and 10125. 16-byte big-endian
`NATCheckMessage` messages: type, port, address, extra; the answer sends back the type and the address and port seen
by the server.

* `NatPropertyDetecter`: types 101 and 102 to nncs1:10025, 103 to the **other** server (another IP address, same port).
  Without an answer to 101 *and* to 103, the detection fails. 102 serves the filtering test (Nintendo's server answered
  from its other address).
* `NatPortDetecter`: type 101 (public port of Pia's socket).
* NEX has its own test (`JobPerformNATCheck`, types 1 to 5).

Our server has only one address: the mod points both names at it, so Pia finds no second server and does not send
103; the server answers 103 together with 101 (Pia does not look at where the answers come from), which describes a NAT
whose mapping does not depend on the destination, the common case.

## 5. Match search

*Estimated progress: 95 % — remains to be put to the test with many players at once.*

`ConnectionInternet::automatchOpen`:

| Call | Protocol/method | Detail |
|---|---|---|
| `AutoMatchmakeWithSearchCriteria_Postpone` | 109/15 | criteria (attributes, game mode `1000`, 1 to 8 players, type 1), `MatchmakeSession` "Steel Matcher", message "Steel Diver 2 Auto matchmake" → the session joined or created |
| `OpenParticipation` / `CloseParticipation` | 109/2 and 109/1 | gid; the host opens the lobby, then closes it when the battle starts |
| `GetSessionURLs` | 21/41 | gid → URL of the host, to join it P2P |
| `RequestProbeInitiationExt` | 3/3 | target URLs, URL to probe: the server calls `InitiateProbe` (3/2) on each target |
| `ReportNATProperties`, `ReportNATTraversalResult` | 3/5, 3/4 | informative |
| `UpdateSessionHostV1` | 21/40 | host migration |
| `EndParticipation` | 50/1 | leave the lobby |
| `AddToBlackList` / `RemoveFromBlackList` | 109/25, 109/26 | players not to meet again |

If the owner of the session returned is the player, the game hosts (Pia `Session::create`); otherwise it joins the host
(`GetSessionURLs` then `Session::join`).

`MatchmakeSession` (NEX 3.7, `_DDL_MatchmakeSession`): the `Gathering` part (id, owner, host, min/max, policy,
argument, flags, state, description), then game mode, attributes (list of u32), open participation, matchmaking type,
application Buffer (`01 02 03`), participant count, progress score, session key Buffer, option. Each level has its own
structure header (u8 version, u32 size).

Attributes (script `connect.inc::joinSession`, native `inetSetAttribute`):

| # | Meaning |
|---|---|
| 0 | continent (`network.continent`) |
| 1 | lobby type (`network.lobbytype`, 1 = battles by level, 2 = Morse chat room) |
| 2 | level: rank / 5 (only if the lobby type is 1), else 0 |
| 3 | `sysGetVersionChecksum()` = CRC-32 of the build's revision (`"31308"` → `0xB95D7F2B` in v0) |

The network identifiers come from `bxml/settings.bxml` (`UniqueId` 3452/3453/3454 depending on the region, a common
`NetworkId` 3452): every region plays together.

**How our server matches players**: two players meet as soon as they play the same version (each session keeps the
version checksum of the game that created it, `Session.version`), cheat or not alike (matchmaking pools, server option
`cheats`), and the session waits (not in battle) with room. The continent (attribute 0) and the level (attribute 2) are
not compared: they kept two friends apart whose emulators are not set to the same country, or when one looked for a
random battle and the other a battle by level. Only the Morse chat rooms (lobby type 2) stay apart from the battles. A
session without bots comes before one whose bots are announced. When the server creates a session, its log says why
each other session was not proposed ("not proposed: cheats differ", "battle under way"...).

Notifications sent by the server (protocol 14, method 1, `NotificationEvent`: source PID, type, param1, param2, text,
param3):

| Type | When | What the client does with it |
|---|---|---|
| 3001 | a player joins the lobby | `MyNotificationEventHandler` resets a flag |
| 4000 | the owner changes (param2) | the game notes the new owner |
| 109000 | the lobby is deleted (param1) | the game notes it |
| 110000 | the host changes (param1 = gid) | Pia's host migration waits for it |

## 6. The lobby and the battle

*Estimated progress: 85 % — host migration and players leaving mid-battle remain to be put to the test.*

Entirely P2P (Pia: sessions, clock, reliable and unreliable streams, host migration) between the consoles' Pia
sockets. The server no longer takes part, except for `CloseParticipation` and departures.

What the game decides itself (scripts `mode_lobby` and `mode_periscope`):

* **Countdown**: 120 s (`0x1D4C0` ms in `mode_lobby`), started only when each team has at least one player
  (`checkCountdownStart`, `g_504c = 1`); 5 s before the end the host closes the lobby (`doNetSetParticipation(0)` →
  `CloseParticipation`). Alone, one waits forever (hence the server's bots, section 8).
* **Computer subs**: at the start of the battle, the first player of each team creates `4 − players of the team`
  computer-controlled submarines (`@setNpc`, actors `surface_sub_npc_blue/red`, 3 at most). A team without a player
  has none. The debug mode `player.debugmulti` (`gDebugSingleInMulti`, never turned on) removes them. With the
  `online` mod they stay the game's own in a battle between players; only the bots of the battles against the
  server's bots fly like players ([bots.md](bots.md)).
* **Invincibility**: the `player.muteki` flag (the developers' test mode) cancels the damage taken (`pscope_player`),
  the torpedo count and the loss of air (`periscope_move`). Damage is applied by the console that takes it: cheating
  works online too, hence the server's `cheats` option.

## 7. Distant players: public and private addresses

*Estimated progress: 85 % — validated in simulation and on a local network, not yet between two real homes; no relay
for strict NATs.*

To join the host, Pia gets its URLs (`GetSessionURLs`, one or two, otherwise an error:
`NexFacade::ConvertNexStationURLToStationConnectionInfo`), classes one as public (bit 2 of the `type` parameter:
`NexFacade::IsPublic`; bit 1 = behind a NAT) and the other as private, then (`NexConnectStationJob::StartupImpl`):

* if the host's public IP address is **its own** (same network behind the same router), it aims at the **private**
  address;
* otherwise it aims at the **public** address, and NEX's NAT traversal (`RequestProbeInitiationExt`, `InitiateProbe`)
  makes each one probe the other.

Its own public address comes from the URL that `SecureConnection::Register` returned to it
(`JobBackEndServicesLogin::CompleteLogin` adds it to its local URLs; `NatTraverser::updateLocalStationInfo` takes it
again). A console on the server's machine connects to it through `127.0.0.1`: the server would see it under this
address and give it to the others, unreachable. When the server has an Internet address, it therefore shows the
consoles of its own network (loopback, or local network behind the same router) under **its public address**,
everywhere the game learns it: the answer to `Register`, the answers of the NAT detection, the public URL passed on to
the others (`server/sdsw_server/internet.py`).

Pia's socket takes a random port between 49152 and 65534 (`NatDetecter::bindRandomPort`, `GetDifferentPortNumber`,
different from NEX's). The server learns it through `ReplaceURL` and has the router forward it (UPnP) to the console at
home while it is connected. This is needed with routers running Linux (simulation: two `nftables` "masquerade" NATs in
network namespaces, the server and the host behind one, a friend behind the other): the friend's first probes reach
the host's router before the host has written to the friend, create a connection-tracking entry there, and the host's
answer then leaves through another port, which the friend's NAT rejects. With the forward, the exchange goes through
both ways, whether the battle's host is the friend or the player at home; without it, in neither.

Names are resolved: `nn::nex::InetAddress::SetAddress` calls `GetHostByName` when the address is not numeric (flag
`0x00399D1F`, set to 1 in the executable), and Pia resolves the names of the NAT detection servers. The mod therefore
accepts a name (dynamic DNS) instead of an IP.

## 8. Server → game: the mod's variables

*Estimated progress: 100 %.*

The server has no way to act on a battle, which is played console to console. To set up the battles against bots (and
later other things), the `online` mod rewrites `MyNotificationEventHandler::ProcessNotificationEvent` (0x00185264, 568
bytes, most of which wrote logs removed from the final build): it keeps the three notifications the game kept (3001,
4xxx, 109xxx) and adds two, unknown to the original game, which ignores them:

| Type | Text | param1 | Effect in the game |
|---|---|---|---|
| 999001 | name | value | `amxSysSetGlobal(name, value)`: an integer variable of the scripts |
| 999002 | `name=value` | — | `amxSysSetGlobalArray(name, 96 cells)`: a string, as `sysSetGlobalString` |

A notification's text arrives in UTF-16 (`nn::nex::String`, buffer at +4); the patch converts it to UTF-8 with the
game's own function (`convertUTF16toUTF8`). Only names that start with `server.` are accepted: a server can touch
neither the save (`save.*`) nor the game's variables. NEX delivers the notifications on the main thread, during
`Network::dispatch()`, where the scripts run.

Variables used (`server/sdsw_server/matchmaking.py` and `realm.py`, `mods/online/*.pasm`):

| Variable | Meaning |
|---|---|
| `server.bots` | 1: the battle is played against bots (reset to 0 at each new lobby); the bots' pilot only flies in these battles |
| `server.bots.mine`, `server.bots.other` | sizes of the players' team and of the other one |
| `server.bots.stage` | map (`player.stage`, 10 to 22), 0: random |
| `server.bots.level` | 1 normal, 2 hard (without value), 3 expert: reflexes and aim of the bots |
| `server.bots.countdown`, `server.bots.duration` | countdown (ms) and length of the battle (s) |
| `server.bots.name<k>`, `sub<k>`, `lv<k>` | bot k (1 to 7): name, submarine, level shown |
| `server.bots.crew<k>` | its crew: up to 5 members, 6 bits each (member + 1, 0 none) |
| `server.anticheat` | 1: the games of this match watch themselves (sent at each search; 0 with `cheats = "allowed"` and among cheaters) |
| `server.duration` | length of every online battle (s) |

The other way round, the game only has its match search to talk to the server: the mod puts into attribute 4 of the
criteria (`inetSetAttribute(4, ...)`, next to the version checksum in 3) the anti-cheat's report, `0x100` (a game that
watches itself) | what it saw at its last kick (bits 0-7: 1 damage cancelled, 2 infinite torpedoes, 4 shots too close
together, 8 impossible speed) | the number of that kick (bits 16-30). The game keeps its last kick in the save
(`save.sdsw.cheat`, `save.sdsw.kick`) and repeats it at each search; the server handles each number only once
(`exclusions.json`). Attributes 4 and 5 do not serve to match players.

## 9. The update v5200

*Estimated progress: 85 % — connection, match search and lobby checked with the v5200 in Azahar; bots and anti-cheat
ported (the bots' sandbox: `tools/botsim.py --version v5200`), to be seen in the emulator.*

The update ([update-v5200.md](update-v5200.md)) keeps the same NEX server id (`0x000D7C00`), the same access key
(`fb9537fe`) and the same NEX and Pia libraries, at new addresses: the same server serves it. Differences found for the
`online` mod:

- the `frd` functions and the steps of `JobCTRLogin` are identical (`GetMyPrincipalId` `0x00222740`, `GetMyPassword`
  `0x002C9224`, `GetGameAuthenticationData` `0x002226CC`);
- **the v5200's Pia resolves the names of the NAT servers in ASCII** (`NatTraverser::updateNatServerAddress`, table
  `0x003D8018`), the v0's in UTF-16 (`0x003B0940`); NEX's table stays in UTF-16 (`0x003C13E4`);
- `MyNotificationEventHandler::ProcessNotificationEvent` (`0x0018A7B8`) is the same, except that the new owner
  (notification 4xxx) goes to `+0x1C` of its structure (`0x003B5668`), against `+0x18` in v0;
- the version checksum of the match search (attribute 3, `sysGetVersionChecksum`) is **868960903** in v5200
  (0xB95D7F2B in v0). Players of both versions never meet in the same match, on purpose (maps, submarines and scripts
  differ); the server's log gives the version of each session created;
- the v5200 adds **battles between friends** (third button of the Internet menu, full version): the same automatic
  search, with the continent (attribute 0) at −1; the server does not compare the continent: these consoles also meet
  those of the random battles. The other network natives it adds stay on the console: `netIsFriend` (its friend
  list), `netIsOwner`, `netDisallowParticipation` (a local flag, `0x0030AAEC`);
- the server's bots in v5200 show one of the update's 36 submarines (23 in v0), and `bots_map` accepts its three maps
  (11 to 13; random for a v0 player);
- the v5200's multiplayer menu no longer has the unused state where the mod opened the server dialog: it opens in the
  game's Dialog state, and closing it leads to the Internet menu (hooks `0xA4B4` and `0x603C`);
- **the bots and the anti-cheat** (the mod's Pawn code, [bots.md](bots.md)): the v5200's scripts are recompiled, every
  address of code and globals moves. `tools/amxport.py` aligns each script of both versions instruction by
  instruction (tokens without addresses: jump targets and globals masked, natives by name, strings by their text;
  functions paired by their code, their log names and their calls) and deduces the v5200's addresses from it; the Pawn
  sources compile for it (`tools/pawn2pasm.py --version v5200`), the hand-written `.pasm` are translated
  (`tools/amxport.py <script> --pasm`), hence the `*-v5200.pasm` (`make bots`). What the tool cannot pair is written by
  hand in `mods/online/v5200.toml`: the main loops of `mode_lobby` and `periscope_move` became functions called every
  frame (`doUpdate`), the lobby's countdown goes from 120 to 60 seconds, `surface_sub` no longer calls `func_cb2c`
  after sinking, and `mode_periscope` splits "Internet battle" in two (`gIsInternet` `g_10aa0`, and `g_10aa8`: an
  Internet battle that is not between friends, `network.continent` = −1).
