"""Matchmaking state of one realm: the sessions ("gatherings") the game creates and joins.

The game (ConnectionInternet::automatchOpen, connectionInternet.cpp) calls
MatchmakeExtension::AutoMatchmakeWithSearchCriteria_Postpone with its search criteria (game mode 1000,
1 to 8 players, attributes: continent, lobby type, level, version checksum) and a MatchmakeSession
"Steel Matcher". When the returned session's owner is the player, the game hosts it with Pia and calls
OpenParticipation; otherwise it asks MatchMaking::GetSessionURLs for the host's station URLs and joins
it peer to peer. Matches are played between the consoles; the server only keeps this bookkeeping.

Notifications the clients act on (MyNotificationEventHandler::ProcessNotificationEvent and Pia):
  3001    a player joined the session (param1 gid, param2 pid)
  4000    the owner changed (param2 new owner): the game stores the new owner
  109000  the session was unregistered (param1 gid)
  110000  the host changed (param1 gid): Pia's host migration waits for it
  999001  ours, with the online mod: sets a script global of the game (string = name, param1 = value);
          how the server tells the game to start a battle against bots (server.bots.*), and more

Bots: the battle is played between the consoles and the game itself drives the computer subs (the host
fills each team up to four), but it only starts a countdown when each team has a player. With the online
mod, the server decides: a player alone in a match for BotSettings.delay seconds gets the server.bots.*
globals, and the mod's scripts then start the battle with bots on both teams (mods/en-ligne).
"""

from __future__ import annotations

import itertools
import logging
import random
import re
import time
from dataclasses import dataclass, field

from .ddl import MatchmakeSession, SearchCriteria, criterion_matches

log = logging.getLogger("matchmaking")

PARTICIPATION_JOINED = 3001
PARTICIPATION_LEFT = 3007
OWNERSHIP_CHANGED = 4000
GATHERING_UNREGISTERED = 109000
HOST_CHANGED = 110000
SET_GLOBAL = 999001            # our own types, handled by the online mod's patch of the game: an integer
SET_GLOBAL_STRING = 999002     # global (string = name, param1 = value), a string global ("name=value")

# Battle maps of the online mode: their number (the game's text key stage_multi_NN) and the stage of the
# scripts (player.stage = 9 + number). Number 3 exists in the files but the game never picks it. The update
# v5200 adds 11 to 13 (worlds/scope00_online_stage11..13; its getRandomStage draws stages 10 to 22).
MAPS = (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
MAPS_OF = {"v0": MAPS[:9], "v5200": MAPS}
LEVELS = {"normal": 1, "difficile": 2, "expert": 3}
# The game's versions, by the version checksum of their search (attribute 3, sysGetVersionChecksum): players of
# two versions never meet (maps, submarines and scripts differ), whatever their criteria say.
VERSIONS = {0xB95D7F2B: "v0", 868960903: "v5200"}
VERSION_ATTRIBUTE = 3
LOBBY_ATTRIBUTE = 1                 # lobby type: 0 random battle, 1 matched skills, 2 Morse chat room (v0)
CHAT_LOBBY = 2                      # no battle there: no bots
# Submarines the bots show, one at random as players would: the game's 23, the update's 36 (37 to 39 are the
# computer's own, rewards of the update's events).
SUBS = {"v0": 23, "v5200": 36}
# Crew members (worlds/crew_stats: crew_00 to crew_31, the update adds 32 to 39). The bots take a crew as a player
# does (server.bots.crew<k>), never the members whose ability only helps a human: Morse tapping (14), the allies
# on the map (31), the update's mine dropped with the masker (32). The expert bots take members that only add.
CREW = {"v0": 32, "v5200": 40}
CREW_NOT_FOR_BOTS = {14, 31, 32}
CREW_STRONG = (20, 21, 22, 24, 25, 26, 27, 28, 29, 30, 33, 34, 36, 37, 38, 39)
CREW_SIZE = {"normal": (0, 3), "difficile": (2, 5), "expert": (4, 5)}     # members drawn (the sub may hold fewer)
BOT_NAMES = ("Requin", "Kraken", "Narval", "Murene", "Espadon", "Barracuda", "Orque", "Nautilus", "Abysse",
             "Corsaire", "Marlin", "Calamar", "Triton", "Poseidon", "Sonar", "Torpille", "Ressac", "Hublot",
             "Abordage", "Typhon", "Neptune", "Leviathan", "Remous", "Sillage", "Capitaine", "Matelot",
             "Moussaillon", "Amiral", "Corail", "Lagon", "Maree", "Tempete", "Bathyscaphe", "Plongeur",
             "Scaphandre", "Lamantin", "Dauphin", "Mako", "Piranha", "Mistral")
MAX_NAME = 10                  # characters of a name, like a Mii name or a console nickname


@dataclass
class BotSettings:
    """serveur.toml, per realm: what happens to a player left alone in a match."""
    enabled: bool = True
    delay: int = 60                # seconds alone in a match before the bots come
    mine: int = 4                  # subs of the player's team, the player included (bots fill it)
    other: int = 4                 # subs of the other team, all bots
    map: int = 0                   # 0: a random map, else its number (MAPS)
    level: str = "difficile"       # how hard the bots are: normal, difficile, expert
    countdown: int = 10            # seconds before the battle once the bots are announced
    crew: bool = True              # the bots take a crew
    duration: int = 10             # minutes of the battle: the realm's duration, as for the other battles
    names: tuple[str, ...] = BOT_NAMES                  # the bots look like players: names, subs, levels

    @classmethod
    def from_config(cls, entry: dict, realm: str = "") -> "BotSettings":
        b = cls()
        b.enabled = bool(entry.get("bots", True))
        b.delay = int(entry.get("bots_delay", b.delay))
        fmt = str(entry.get("bots_format", f"{b.mine}v{b.other}")).lower().replace(" ", "")
        m = re.fullmatch(r"([1-4])(?:v|vs|contre|x|-)([1-4])", fmt)
        if not m:
            raise ValueError(f"realm {realm}: bots_format must look like 4v4, 1v4 or 2v3 (1 to 4 per team)")
        b.mine, b.other = int(m[1]), int(m[2])
        value = str(entry.get("bots_map", "aleatoire")).strip().lower()
        if value in ("aleatoire", "aléatoire", "random", "0", ""):
            b.map = 0
        else:
            try:
                b.map = int(value)
            except ValueError:
                raise ValueError(f"realm {realm}: bots_map must be aleatoire or a map number "
                                 f"({', '.join(map(str, MAPS))})") from None
            if b.map not in MAPS:
                raise ValueError(f"realm {realm}: no map {b.map} (maps: {', '.join(map(str, MAPS))})")
        b.level = str(entry.get("bots_level", b.level)).strip().lower()
        if b.level not in LEVELS:
            raise ValueError(f"realm {realm}: bots_level must be one of {', '.join(LEVELS)}")
        b.countdown = int(entry.get("bots_countdown", b.countdown))
        b.crew = bool(entry.get("bots_crew", b.crew))
        # a battle against bots lasts as the others (duration); bots_duration, an older option, is ignored
        b.duration = int(entry.get("duration", 10))
        names = entry.get("bots_names", b.names)
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        b.names = tuple(str(n).strip()[:MAX_NAME] for n in names
                        if str(n).strip() and not set(str(n)) & set("=%\\"))       # the game formats them
        if len(b.names) < 7:
            raise ValueError(f"realm {realm}: bots_names needs 7 names at least")
        if not 1 <= b.duration <= 30:
            raise ValueError(f"realm {realm}: duration must be between 1 and 30 minutes")
        if not 5 <= b.delay <= 3600:
            raise ValueError(f"realm {realm}: bots_delay must be between 5 and 3600 seconds")
        if not 6 <= b.countdown <= 120:
            raise ValueError(f"realm {realm}: bots_countdown must be between 6 and 120 seconds")
        return b

    @property
    def format(self) -> str:
        return f"{self.mine}v{self.other}"

    def identities(self, rng: random.Random | None = None, version: str = "v0") -> list[dict]:
        """Seven bots that look like players: a name, a submarine, a level (Lv shown by the game), a crew."""
        rng = rng or random.Random()
        return [{"name": name, "sub": rng.randint(1, SUBS.get(version, SUBS["v0"])), "level": rng.randint(4, 40),
                 "crew": self.crew_for(rng, version)} for name in rng.sample(self.names, 7)]

    def crew_for(self, rng: random.Random, version: str = "v0") -> list[int]:
        """The members of a bot's crew (up to 5, all different), better at the expert level."""
        if not self.crew:
            return []
        count = CREW.get(version, CREW["v0"])
        usable = [c for c in range(count) if c not in CREW_NOT_FOR_BOTS]
        strong = [c for c in CREW_STRONG if c < count]
        low, high = CREW_SIZE[self.level]
        pool = strong if self.level == "expert" else usable
        return rng.sample(pool, rng.randint(low, high))

    def game_globals(self, bots: list[dict] | None = None, version: str = "v0") -> dict[str, int | str]:
        """What the online mod's scripts read; server.bots last: it starts everything. Bot k (1 to 7):
        server.bots.name<k>, sub<k>, lv<k>; bots of the players' team first, then the other team's."""
        values: dict[str, int | str] = {}
        for k, bot in enumerate(bots or self.identities(version=version), 1):
            values |= {f"server.bots.name{k}": bot["name"], f"server.bots.sub{k}": bot["sub"],
                       f"server.bots.lv{k}": bot["level"], f"server.bots.crew{k}": pack_crew(bot.get("crew", []))}
        known = self.map in MAPS_OF.get(version, MAPS_OF["v0"])       # a map of the update: random for v0
        return values | {"server.bots.mine": self.mine, "server.bots.other": self.other,
                         "server.bots.stage": 9 + self.map if self.map and known else 0,
                         "server.bots.level": LEVELS[self.level], "server.bots.countdown": self.countdown * 1000,
                         "server.bots.duration": self.duration * 60, "server.bots": 1}


def pack_crew(members: list[int]) -> int:
    """server.bots.crew<k>: up to five members, 6 bits each (member + 1, 0: none), the first in the low bits;
    the bot keeps as many as its submarine holds (crewCount)."""
    packed = 0
    for i, member in enumerate(members[:5]):
        packed |= (member + 1) << (6 * i)
    return packed


@dataclass
class Session:
    info: MatchmakeSession
    participants: list[int] = field(default_factory=list)
    created: float = field(default_factory=time.monotonic)
    pool: str = ""                                  # players of different pools never meet
    version: int = 0                                # version checksum of the game that created it
    alone_since: float | None = None                # one player only, since then
    bots: bool = False                              # this round is played against bots
    bot_globals: dict = field(default_factory=dict)  # what its players were told about the bots
    closed: bool = False                            # the host closed it: the battle is starting

    @property
    def gid(self) -> int:
        return self.info.id

    def full(self) -> bool:
        return len(self.participants) >= max(self.info.max_participants, 1)

    @property
    def chat_room(self) -> bool:
        a = self.info.attributes
        return len(a) > LOBBY_ATTRIBUTE and a[LOBBY_ATTRIBUTE] == CHAT_LOBBY

    @property
    def version_name(self) -> str:
        return VERSIONS.get(self.version, f"{self.version:#x}")


def version_of(info: MatchmakeSession) -> int:
    """The version checksum a game puts in its search (0: none)."""
    return info.attributes[VERSION_ATTRIBUTE] if len(info.attributes) > VERSION_ATTRIBUTE else 0


class Matchmaker:
    """max_players caps the human players of a session: the host's game then fills each team up to four
    subs with computer-controlled ones (mode_periscope @setNpc: 4 - players of the team). bots: what to do
    with a player left alone (BotSettings), None for nothing."""

    def __init__(self, notify, max_players: int = 8, bots: BotSettings | None = None,
                 clock=time.monotonic) -> None:
        self.max_players = max_players
        self.bot_level = LEVELS[bots.level] if bots else 0          # every bot of the online battles
        self.bots = bots if bots and bots.enabled else None         # battles against bots for players alone
        self.sessions: dict[int, Session] = {}
        self.by_pid: dict[int, int] = {}            # pid -> gid
        self.blocklists: dict[int, set[int]] = {}
        self._gids = itertools.count(1000)
        self.notify = notify                        # notify(pid, source_pid, type, param1, param2, str, param3)
        self.clock = clock

    def set_globals(self, pid: int, values: dict[str, int | str]) -> None:
        """Script globals of a player's game (online mod), in this order."""
        for name, value in values.items():
            if isinstance(value, str):
                self.notify(pid, 0, SET_GLOBAL_STRING, 0, 0, f"{name}={value}", 0)
            else:
                self.notify(pid, 0, SET_GLOBAL, value & 0xFFFFFFFF, 0, name, 0)

    # -- search ----------------------------------------------------------------------------------

    def _matches(self, session: Session, c: SearchCriteria, pid: int, pool: str, version: int) -> bool:
        info = session.info
        if session.pool != pool or not info.open_participation or session.full() or pid in session.participants:
            return False
        if session.version != version:
            return False
        if c.vacant_only and len(session.participants) + max(c.vacant_participants, 1) > info.max_participants:
            return False
        if not criterion_matches(c.game_mode, info.game_mode):
            return False
        if not criterion_matches(c.matchmake_system_type, info.matchmake_system_type):
            return False
        if not criterion_matches(c.min_participants, info.min_participants):
            return False
        if not criterion_matches(c.max_participants, info.max_participants):
            return False
        for n, text in enumerate(c.attributes[:4]):     # 4 and 5: reports of the online mod, not criteria
            value = info.attributes[n] if n < len(info.attributes) else 0
            if not criterion_matches(text, value):
                return False
        mine = self.blocklists.get(pid, set())
        for other in session.participants:
            if other in mine or pid in self.blocklists.get(other, set()):
                return False
        return True

    def auto_matchmake(self, pid: int, criteria: list[SearchCriteria], proposal: MatchmakeSession,
                       message: str, pool: str = "") -> MatchmakeSession:
        self.leave(pid, "")
        version = version_of(proposal)
        for c in criteria:
            found = [s for s in self.sessions.values() if self._matches(s, c, pid, pool, version)]
            if found:
                session = max(found, key=lambda s: (len(s.participants), -s.created))
                self._join(session, pid, message)
                log.info("pid %d joins session %d (%d/%d)", pid, session.gid, len(session.participants),
                         session.info.max_participants)
                return session.info
        info = proposal
        info.id = next(self._gids)
        info.owner_pid = info.host_pid = pid
        info.participation_count = 1
        info.max_participants = min(info.max_participants or 8, self.max_players)
        session = Session(info, [pid], pool=pool, version=version, created=self.clock(), alone_since=self.clock())
        self.sessions[info.id] = session
        self.by_pid[pid] = info.id
        if self.bot_level:
            self.set_globals(pid, {"server.bots.level": self.bot_level, "server.bots": 0})
        log.info("pid %d creates session %d (game %s, game mode %d, attributes %s, %d players max%s)", pid, info.id,
                 session.version_name, info.game_mode, info.attributes, info.max_participants,
                 f", pool {pool}" if pool else "")
        return info

    def _join(self, session: Session, pid: int, message: str) -> None:
        session.participants.append(pid)
        session.info.participation_count = len(session.participants)
        session.alone_since = None
        self.by_pid[pid] = session.gid
        if self.bot_level:                          # a match already set for bots stays so
            self.set_globals(pid, session.bot_globals if session.bots and session.bot_globals
                             else {"server.bots.level": self.bot_level, "server.bots": 0})
        for other in session.participants:
            if other != pid:
                self.notify(other, pid, PARTICIPATION_JOINED, session.gid, pid, message,
                            len(session.participants))

    # -- session life ----------------------------------------------------------------------------

    def get(self, gid: int) -> Session | None:
        return self.sessions.get(gid)

    def set_open(self, pid: int, gid: int, value: bool) -> bool:
        session = self.sessions.get(gid)
        if session is None or pid not in session.participants:
            return False
        session.info.open_participation = value
        if not value:
            session.closed = True                   # five seconds before the battle (mode_lobby)
        elif session.closed:                        # back in the lobby after a battle: a new round
            session.closed = False
            if session.bots:
                session.bots = False
                for other in session.participants:
                    self.set_globals(other, {"server.bots": 0})
            if len(session.participants) == 1:
                session.alone_since = self.clock()
        return True

    def tick(self) -> list[Session]:
        """Called every second: the players alone for long enough get their bots. Returns those sessions."""
        if not self.bots:
            return []
        now, started = self.clock(), []
        for session in self.sessions.values():
            if (not session.bots and not session.closed and len(session.participants) == 1
                    and session.alone_since is not None and now - session.alone_since >= self.bots.delay
                    and not session.chat_room):
                session.bots = True
                session.alone_since = None
                session.bot_globals = self.bots.game_globals(version=VERSIONS.get(session.version, "v0"))
                log.info("session %d: alone for %d s, bots (%s)", session.gid, self.bots.delay, self.bots.format)
                self.set_globals(session.participants[0], session.bot_globals)
                started.append(session)
        return started

    def update_host(self, pid: int, gid: int) -> bool:
        session = self.sessions.get(gid)
        if session is None or pid not in session.participants:
            return False
        session.info.host_pid = pid
        log.info("session %d: new host %d", gid, pid)
        for other in session.participants:
            if other != pid:
                self.notify(other, pid, HOST_CHANGED, gid, pid, "", 0)
        return True

    def leave(self, pid: int, message: str, gid: int | None = None) -> bool:
        current = self.by_pid.get(pid)
        if current is None or (gid is not None and gid != current):
            return False
        del self.by_pid[pid]
        session = self.sessions.get(current)
        if session is None:
            return False
        if pid in session.participants:
            session.participants.remove(pid)
        session.info.participation_count = len(session.participants)
        if not session.participants:
            del self.sessions[current]
            log.info("session %d closed", current)
            return True
        if len(session.participants) == 1 and not session.bots:
            session.alone_since = self.clock()
        for other in session.participants:
            self.notify(other, pid, PARTICIPATION_LEFT, current, pid, message, len(session.participants))
        if session.info.owner_pid == pid:
            new_owner = session.participants[0]
            session.info.owner_pid = new_owner
            log.info("session %d: owner %d left, new owner %d", current, pid, new_owner)
            for other in session.participants:
                self.notify(other, pid, OWNERSHIP_CHANGED, current, new_owner, "", 0)
        return True

    def set_blocklist(self, pid: int, pids: list[int], add: bool) -> None:
        block = self.blocklists.setdefault(pid, set())
        if add:
            block.update(pids)
        else:
            block.difference_update(pids)
