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
"""

from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field

from .ddl import MatchmakeSession, SearchCriteria, criterion_matches

log = logging.getLogger("matchmaking")

PARTICIPATION_JOINED = 3001
PARTICIPATION_LEFT = 3007
OWNERSHIP_CHANGED = 4000
GATHERING_UNREGISTERED = 109000
HOST_CHANGED = 110000


@dataclass
class Session:
    info: MatchmakeSession
    participants: list[int] = field(default_factory=list)
    created: float = field(default_factory=time.monotonic)

    @property
    def gid(self) -> int:
        return self.info.id

    def full(self) -> bool:
        return len(self.participants) >= max(self.info.max_participants, 1)


class Matchmaker:
    def __init__(self, notify) -> None:
        self.sessions: dict[int, Session] = {}
        self.by_pid: dict[int, int] = {}            # pid -> gid
        self.blocklists: dict[int, set[int]] = {}
        self._gids = itertools.count(1000)
        self.notify = notify                        # notify(pid, source_pid, type, param1, param2, str, param3)

    # -- search ----------------------------------------------------------------------------------

    def _matches(self, session: Session, c: SearchCriteria, pid: int) -> bool:
        info = session.info
        if not info.open_participation or session.full() or pid in session.participants:
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
        for n, text in enumerate(c.attributes):
            value = info.attributes[n] if n < len(info.attributes) else 0
            if not criterion_matches(text, value):
                return False
        mine = self.blocklists.get(pid, set())
        for other in session.participants:
            if other in mine or pid in self.blocklists.get(other, set()):
                return False
        return True

    def auto_matchmake(self, pid: int, criteria: list[SearchCriteria], proposal: MatchmakeSession,
                       message: str) -> MatchmakeSession:
        self.leave(pid, "")
        for c in criteria:
            found = [s for s in self.sessions.values() if self._matches(s, c, pid)]
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
        session = Session(info, [pid])
        self.sessions[info.id] = session
        self.by_pid[pid] = info.id
        log.info("pid %d creates session %d (game mode %d, attributes %s)", pid, info.id, info.game_mode,
                 info.attributes)
        return info

    def _join(self, session: Session, pid: int, message: str) -> None:
        session.participants.append(pid)
        session.info.participation_count = len(session.participants)
        self.by_pid[pid] = session.gid
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
        return True

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
