"""NEX structures exchanged with the game, with the fields of its NEX 3.7 DDL code.

  Gathering          _DDL_Gathering::Add/Extract (0x001F46F0 / 0x001FEA00)
  MatchmakeSession   _DDL_MatchmakeSession::Add/Extract (0x001D1B44 / 0x001D1D34): Gathering part, then
                     game mode, attributes, open participation, matchmake system type, application buffer,
                     participation count, progress score, session key, option
  MatchmakeSessionSearchCriteria   serialiser at 0x00331928 (inlined in AutoMatchmake)
  NotificationEvent  _DDL_NotificationEvent::Extract (0x001D3478)
  RVConnectionData   _DDL_RVConnectionData::Extract (0x001F2D0C); version 1 adds the server time
  AuthenticationInfo _DDL_AuthenticationInfo::Extract (0x001D4C10): Data part, then token, NGS version,
                     token type, server version
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .streams import StationURL, StreamIn, StreamOut


@dataclass
class Gathering:
    id: int = 0
    owner_pid: int = 0
    host_pid: int = 0
    min_participants: int = 0
    max_participants: int = 0
    participation_policy: int = 0
    policy_argument: int = 0
    flags: int = 0
    state: int = 0
    description: str = ""

    def write_gathering(self, s: StreamOut) -> None:
        s.u32(self.id); s.pid(self.owner_pid); s.pid(self.host_pid)
        s.u16(self.min_participants); s.u16(self.max_participants)
        s.u32(self.participation_policy); s.u32(self.policy_argument)
        s.u32(self.flags); s.u32(self.state); s.string(self.description)

    def read_gathering(self, s: StreamIn) -> None:
        self.id, self.owner_pid, self.host_pid = s.u32(), s.pid(), s.pid()
        self.min_participants, self.max_participants = s.u16(), s.u16()
        self.participation_policy, self.policy_argument = s.u32(), s.u32()
        self.flags, self.state, self.description = s.u32(), s.u32(), s.string()


@dataclass
class MatchmakeSession(Gathering):
    game_mode: int = 0
    attributes: list[int] = field(default_factory=list)
    open_participation: bool = True
    matchmake_system_type: int = 0
    application_buffer: bytes = b""
    participation_count: int = 0
    progress_score: int = 100
    session_key: bytes = b""
    option: int = 0

    CLASS_NAME = "MatchmakeSession"

    def encode_parts(self):
        def session(s: StreamOut) -> None:
            s.u32(self.game_mode)
            s.list(self.attributes, StreamOut.u32)
            s.bool(self.open_participation)
            s.u32(self.matchmake_system_type)
            s.buffer(self.application_buffer)
            s.u32(self.participation_count)
            s.u8(self.progress_score)
            s.buffer(self.session_key)
            s.u32(self.option)
        return [(0, self.write_gathering), (0, session)]

    @classmethod
    def decode(cls, stream: StreamIn) -> "MatchmakeSession":
        m = cls()
        _, sub = stream.structure_header()
        m.read_gathering(sub)
        _, sub = stream.structure_header()
        m.game_mode = sub.u32()
        m.attributes = sub.list(StreamIn.u32)
        m.open_participation = sub.bool()
        m.matchmake_system_type = sub.u32()
        m.application_buffer = sub.buffer()
        m.participation_count = sub.u32()
        m.progress_score = sub.u8()
        m.session_key = sub.buffer()
        m.option = sub.u32()
        return m


@dataclass
class SearchCriteria:
    attributes: list[str] = field(default_factory=list)
    game_mode: str = ""
    min_participants: str = ""
    max_participants: str = ""
    matchmake_system_type: str = ""
    vacant_only: bool = True
    exclude_locked: bool = True
    exclude_non_host_pid: bool = False
    selection_method: int = 0
    vacant_participants: int = 1

    @classmethod
    def decode(cls, stream: StreamIn) -> "SearchCriteria":
        _, s = stream.structure_header()
        c = cls()
        c.attributes = s.list(StreamIn.string)
        c.game_mode = s.string()
        c.min_participants = s.string()
        c.max_participants = s.string()
        c.matchmake_system_type = s.string()
        c.vacant_only = s.bool()
        c.exclude_locked = s.bool()
        c.exclude_non_host_pid = s.bool()
        c.selection_method = s.u32()
        if s.remaining() >= 2:
            c.vacant_participants = s.u16()
        return c


def criterion_matches(text: str, value: int) -> bool:
    """A criteria string is empty (anything), "n" (exact) or "a,b" (range)."""
    text = text.strip()
    if not text:
        return True
    try:
        if "," in text:
            low, high = (int(x) for x in text.split(",", 1))
            return low <= value <= high
        return int(text) == value
    except ValueError:
        return True


@dataclass
class NotificationEvent:
    source_pid: int
    type: int
    param1: int = 0
    param2: int = 0
    str_param: str = ""
    param3: int = 0

    def encode_parts(self):
        def body(s: StreamOut) -> None:
            s.pid(self.source_pid); s.u32(self.type); s.u32(self.param1); s.u32(self.param2)
            s.string(self.str_param); s.u32(self.param3)
        return [(0, body)]


@dataclass
class RVConnectionData:
    regular_url: StationURL
    special_url: StationURL = field(default_factory=lambda: StationURL("", {}))
    special_protocols: list[int] = field(default_factory=list)
    current_time: int = 0

    def encode_parts(self):
        def body(s: StreamOut) -> None:
            s.url(self.regular_url)
            s.list(self.special_protocols, StreamOut.u8)
            s.url(self.special_url)
            s.datetime(self.current_time)
        return [(1, body)]


@dataclass
class AuthenticationInfo:
    token: str = ""
    ngs_version: int = 0
    token_type: int = 0
    server_version: int = 0

    @classmethod
    def decode(cls, stream: StreamIn) -> "AuthenticationInfo":
        stream.structure_header()                 # Data (empty)
        _, s = stream.structure_header()
        return cls(s.string(), s.u32(), s.u8(), s.u32())
