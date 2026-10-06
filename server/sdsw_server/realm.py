"""A realm: the authentication server and the secure server of one player community.

Login, as the game performs it (JobCTRLogin, JobBackEndServicesLogin, JobTicketManagerLogin):
  1. auth server, "prudp:/address=...;port=P;stream=10;sid=1;type=2": TicketGranting::LoginEx with the
     principal id as user name and an AuthenticationInfo (token, NGS version 3, server version 1000).
     The answer holds a ticket encrypted with the user key (only checked: ValidateKey), the station URL
     of the secure server and a build name.
  2. TicketGranting::RequestTicket(pid, secure server pid): the ticket used to connect, i.e.
     Kerberos(user key: session key (32 bytes), target pid, Buffer(ticket for the server)).
  3. secure server: CONNECT with Buffer(ticket) + Buffer(Kerberos(session key: pid, connection id,
     check value)); the CONNECT-ACK carries Buffer(u32 check value + 1)
     (JobConnectSecureEndPoint::InitializeBufferRequest / ProcessConnectResult).
  4. SecureConnection::Register(local station URLs) -> connection id and public station URL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import rmc
from .accounts import AccountError, Accounts, parse_token
from .crypto import KerberosError, kerberos_decrypt, kerberos_encrypt
from .ddl import (AuthenticationInfo, MatchmakeSession, NotificationEvent, RVConnectionData,
                  SearchCriteria)
from .internet import Internet
from .matchmaking import SET_GLOBAL, SET_GLOBAL_STRING, BotSettings, Matchmaker
from .prudp import Connection, PRUDPServer
from .rmc import RMCDispatcher, RMCError
from .streams import StationURL, StreamIn, StreamOut, datetime_now

ACCESS_KEY = "fb9537fe"             # gameServerLogin -> NgsFacade::Login(..., 0xD7C00, L"fb9537fe", 60000)
SECURE_PID = 2                       # principal id of the secure server in its station URL
TICKET_LIFETIME = 3600

# Token flags of the builds that change the game in a player's favour: the cheat mod (mods/triche) and
# hand-made submarine characteristics (mods/specs). Other flags ("premium": the full version that the
# eShop used to sell) are only logged.
CHEAT_FLAGS = frozenset({"triche", "specs"})
CHEAT_POOL = "triche"                # matchmaking pool of the cheaters, with cheats = "separes"
CHEAT_POLICIES = ("autorises", "separes", "refuses")

# Anti-cheat of the online mod (mods/en-ligne/anti_triche_*.pasm): when the server does not allow cheats, it
# sets server.anticheat in the players' games; each game then watches its own submarine in battle, leaves
# the battle at the first cheat it sees (the "kick") and keeps the last kick in its save. It tells the server
# at each search for a match, in matchmaking attribute 4: 0x100 (a game that watches itself) | what it saw
# (bits 0-7) | the number of that kick (bits 16-30). Each kick is dealt with once (exclusions.json keeps the
# number of the last one), so a save that keeps it does not bring a new sanction at every search.
CHEAT_SEEN = {1: "dégâts annulés", 2: "torpilles infinies", 4: "tirs trop rapprochés", 8: "vitesse impossible"}
REPORT_ATTRIBUTE = 4                 # attributes 4 and 5 are reports, not matchmaking criteria


def is_cheater(flags) -> bool:
    return not CHEAT_FLAGS.isdisjoint(flags)

# Protocol ids
NAT_TRAVERSAL, TICKET_GRANTING, SECURE_CONNECTION, NOTIFICATION = 3, 10, 11, 14
MATCH_MAKING, MATCH_MAKING_EXT, MATCHMAKE_EXTENSION = 21, 50, 109


@dataclass
class RealmConfig:
    name: str
    listen: str
    public_address: str
    auth_port: int
    secure_port: int
    data_dir: Path
    build_name: str = "Sub Wars Open Sourced server"
    max_players: int = 8              # human players per match; the game fills each team up to 4 with AI subs
    cheats: str = "separes"           # players whose build declares the cheat mod: autorises/separes/refuses
    anticheat_ban: int = 30           # minutes a player caught cheating is kept out ("refuses") or apart ("separes")
    duration: int = 10                # minutes of an online battle (the game: 10), set in every game (online mod)
    bots: BotSettings = field(default_factory=BotSettings)    # a player alone in a match plays bots

    def __post_init__(self) -> None:
        if not 2 <= self.max_players <= 8:
            raise ValueError(f"realm {self.name}: max_players must be between 2 and 8")
        if self.cheats not in CHEAT_POLICIES:
            raise ValueError(f"realm {self.name}: cheats must be one of {', '.join(CHEAT_POLICIES)}")
        if not 0 <= self.anticheat_ban <= 7 * 24 * 60:
            raise ValueError(f"realm {self.name}: anticheat_ban must be between 0 and 10080 minutes")
        if not 1 <= self.duration <= 30:
            raise ValueError(f"realm {self.name}: duration must be between 1 and 30 minutes")


class Realm:
    def __init__(self, config: RealmConfig, natcheck=None, internet: Internet | None = None) -> None:
        self.config = config
        self.natcheck = natcheck                   # NatCheckService, to learn the public port of Pia
        self.internet = internet or Internet(config.public_address)     # public address, players at home
        self.log = logging.getLogger(config.name)
        self.accounts = Accounts(config.data_dir / "accounts.sqlite3")
        self.ticket_key = self.accounts.secret("ticket key")
        self.flags: dict[int, frozenset[str]] = {}     # pid -> flags of its build (token), set at login
        self.auth = AuthServer(self)
        self.secure = SecureServer(self)
        self.matchmaker = Matchmaker(self.notify, config.max_players, config.bots)
        self._bans: set[int] = set()
        self._bans_mtime: float | None = None
        self._ticker: asyncio.Task | None = None
        self.kicks = 0                                  # kicks dealt with during this run of the server

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self.auth, local_addr=(self.config.listen, self.config.auth_port))
        await loop.create_datagram_endpoint(lambda: self.secure,
                                            local_addr=(self.config.listen, self.config.secure_port))
        self.log.info("realm %s: authentication UDP %d, secure UDP %d, %d account(s)", self.config.name,
                      self.config.auth_port, self.config.secure_port, self.accounts.count())
        self.log.info("realm %s: up to %d human players per match (AI subs fill the teams), battles of %d min, "
                      "cheats %s", self.config.name, self.config.max_players, self.config.duration,
                      self.config.cheats)
        bots = self.config.bots
        if bots.enabled:
            self.log.info("realm %s: a player alone for %d s plays bots (%s, map %s, level %s)", self.config.name,
                          bots.delay, bots.format, bots.map or "random", bots.level)
        self._ticker = asyncio.get_running_loop().create_task(self._tick())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(1)
            with contextlib.suppress(Exception):
                self.matchmaker.tick()

    def close(self) -> None:
        if self._ticker:
            self._ticker.cancel()
        self.auth.close()
        self.secure.close()
        self.accounts.db.close()

    def status(self) -> dict:
        """For the status page: counts only, no player id."""
        online = list(self.secure.by_pid)
        now = time.monotonic()
        return {"name": self.config.name, "auth_port": self.config.auth_port, "players_online": len(online),
                "address": (self.config.public_address if self.config.public_address != "auto"
                            else self.internet.public_name or self.internet.public_ip),
                "cheaters_online": sum(1 for pid in online if is_cheater(self.flags.get(pid, ()))),
                "accounts": self.accounts.count(), "max_players": self.config.max_players,
                "duration": self.config.duration,
                "cheats": self.config.cheats, "caught_cheating": self.kicks,
                "bots": ({"delay": self.config.bots.delay, "format": self.config.bots.format,
                          "map": self.config.bots.map, "level": self.config.bots.level}
                         if self.config.bots.enabled else None),
                "matches": [{"players": len(s.participants), "max": s.info.max_participants,
                             "open": bool(s.info.open_participation), "cheaters": s.pool == CHEAT_POOL,
                             "bots": s.bots, "minutes": int((now - s.created) // 60)}
                            for s in self.matchmaker.sessions.values()]}

    def banned(self, pid: int) -> bool:
        """data/<realm>/bannis.txt: one principal id per line (# comments), read again when it changes."""
        path = self.config.data_dir / "bannis.txt"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if mtime != self._bans_mtime:
            bans = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                text = line.split("#", 1)[0].strip()
                if text:
                    try:
                        bans.add(int(text, 0))
                    except ValueError:
                        self.log.warning("%s: not a player id: %r", path, text)
            self._bans, self._bans_mtime = bans, mtime
        return pid in self._bans

    def pool(self, pid: int) -> str:
        """Matchmaking pool: with cheats "separes", players whose build cheats (or who were caught cheating)
        only meet each other."""
        if self.config.cheats == "separes" and (is_cheater(self.flags.get(pid, ())) or self._caught(pid)):
            return CHEAT_POOL
        return ""

    # -- anti-cheat ----------------------------------------------------------------------------

    @property
    def _exclusions_path(self) -> Path:
        return self.config.data_dir / "exclusions.json"

    def _exclusions(self) -> dict[str, dict]:
        """pid -> {"kick": number of its last kick, "until": end of the sanction, "reasons": [...]}; kept after
        the sanction, for the number of the kick."""
        with contextlib.suppress(OSError, ValueError):
            return dict(json.loads(self._exclusions_path.read_text(encoding="utf-8")))
        return {}

    def _caught(self, pid: int) -> dict | None:
        """The sanction of a player caught cheating, while it lasts (data/<realm>/exclusions.json)."""
        entry = self._exclusions().get(str(pid))
        return entry if entry and entry.get("until", 0) > time.time() else None

    def excluded(self, pid: int) -> dict | None:
        """Kept out: caught cheating less than anticheat_ban minutes ago, on a server that refuses cheaters."""
        return self._caught(pid) if self.config.cheats == "refuses" else None

    def caught_cheating(self, pid: int, seen: int, kick: int) -> bool:
        """A game reported its last kick: what it saw of itself, and the number of the kick. A kick not dealt
        with yet sends the player among the cheaters ("separes") or keeps them out ("refuses") for
        anticheat_ban minutes. Returns whether the kick is new."""
        data = self._exclusions()
        entry = data.get(str(pid))
        if entry and entry.get("kick") == kick:
            return False
        reasons = [text for bit, text in CHEAT_SEEN.items() if seen & bit] or [f"{seen:#x}"]
        until = int(time.time() + 60 * self.config.anticheat_ban)
        data[str(pid)] = {"kick": kick, "until": until, "reasons": reasons}
        with contextlib.suppress(OSError):
            self._exclusions_path.parent.mkdir(parents=True, exist_ok=True)
            self._exclusions_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        self.kicks += 1
        self.log.warning("pid %d caught cheating (%s): %s for %d min", pid, ", ".join(reasons),
                         "with the cheaters" if self.config.cheats == "separes" else "kept out",
                         self.config.anticheat_ban)
        return True

    def anticheat_on(self, pid: int) -> bool:
        """The games of this match watch themselves: cheats are not allowed here."""
        return self.config.cheats != "autorises" and self.pool(pid) != CHEAT_POOL

    # -- tickets -------------------------------------------------------------------------------

    def secure_address(self, client: tuple[str, int]) -> str:
        """Address of the secure server for this client: the public address for a client from the internet;
        clients on the server's machine, network or VPN get this machine's address on the way to them, so
        they do not depend on the router sending them back their own public address (hairpinning)."""
        return self.internet.secure_address(client[0], self.config.public_address)

    def secure_url(self, client: tuple[str, int]) -> StationURL:
        return StationURL("prudps", {"address": self.secure_address(client), "port": str(self.config.secure_port),
                                     "CID": "1", "PID": str(SECURE_PID), "sid": "1", "stream": "10",
                                     "type": "2"})

    def make_ticket(self, pid: int, user_key: bytes, target_pid: int) -> bytes:
        session_key = os.urandom(32)
        inner = StreamOut()
        inner.pid(pid)
        inner.u64(int(time.time()))
        inner.buffer(session_key)
        ticket = StreamOut()
        ticket.write(session_key)
        ticket.pid(target_pid)
        ticket.buffer(kerberos_encrypt(self.ticket_key, inner.get()))
        return kerberos_encrypt(user_key, ticket.get())

    def open_ticket(self, data: bytes) -> tuple[int, bytes]:
        s = StreamIn(kerberos_decrypt(self.ticket_key, data))
        pid, issued, session_key = s.pid(), s.u64(), s.buffer()
        if time.time() - issued > TICKET_LIFETIME:
            raise KerberosError("expired ticket")
        return pid, session_key

    # -- notifications -------------------------------------------------------------------------

    def notify(self, pid: int, source: int, type_: int, param1: int, param2: int, text: str, param3: int) -> None:
        conn = self.secure.by_pid.get(pid)
        if conn is None:
            return
        params = StreamOut()
        params.structure(NotificationEvent(source, type_, param1, param2, text, param3))
        if type_ in (SET_GLOBAL, SET_GLOBAL_STRING):
            self.log.debug("pid %d: %s", pid, text if type_ == SET_GLOBAL_STRING else f"{text} = {param1}")
        else:
            self.log.info("notification %d to pid %d (param1 %d, param2 %d)", type_, pid, param1, param2)
        self.secure.rmc.call_client(conn, NOTIFICATION, 1, params)


# ==== authentication server ======================================================================

class AuthServer(PRUDPServer):
    def __init__(self, realm: Realm) -> None:
        super().__init__(f"{realm.config.name}.auth", ACCESS_KEY)
        self.realm = realm
        self.rmc = RMCDispatcher(self.name)
        reg = self.rmc.register
        reg(TICKET_GRANTING, 1, "TicketGranting::Login", self.login)
        reg(TICKET_GRANTING, 2, "TicketGranting::LoginEx", self.login_ex)
        reg(TICKET_GRANTING, 3, "TicketGranting::RequestTicket", self.request_ticket)

    def on_data(self, conn: Connection, payload: bytes) -> None:
        self.rmc.handle_payload(conn, payload)

    def _login(self, conn: Connection, username: str, token: str) -> StreamOut:
        try:
            pid = int(username)
        except ValueError:
            raise RMCError(rmc.RV_INVALID_USERNAME, username)
        try:
            key, flags = parse_token(token)
            new = self.realm.accounts.login(pid, key)
        except AccountError as e:
            self.log.warning("%s: login refused for %s: %s", conn, username, e)
            raise RMCError(rmc.RV_INVALID_PASSWORD, str(e))
        if self.realm.banned(pid):
            self.log.warning("%s: pid %d refused, banned (bannis.txt)", conn, pid)
            raise RMCError(rmc.RV_ACCOUNT_DISABLED, "banned")
        exclusion = self.realm.excluded(pid)
        if exclusion:
            self.log.warning("%s: pid %d refused, caught cheating (%s) until %s", conn, pid,
                             ", ".join(exclusion.get("reasons", [])),
                             time.strftime("%H:%M", time.localtime(exclusion["until"])))
            raise RMCError(rmc.RV_ACCOUNT_DISABLED, "excluded")
        if is_cheater(flags) and self.realm.config.cheats == "refuses":
            self.log.warning("%s: pid %d refused, its build cheats (%s)", conn, pid,
                             ", ".join(sorted(flags & CHEAT_FLAGS)))
            raise RMCError(rmc.RV_ACCOUNT_DISABLED, "cheats refused")
        conn.pid = pid
        conn.data["user_key"] = key
        self.realm.flags[pid] = flags
        self.log.info("%s: %s pid %d%s", conn, "new player" if new else "login", pid,
                      f" (build: {', '.join(sorted(flags))})" if flags else "")
        out = StreamOut()
        out.result(rmc.SUCCESS)
        out.pid(pid)
        out.buffer(self.realm.make_ticket(pid, key, SECURE_PID))
        out.structure(RVConnectionData(self.realm.secure_url(conn.addr), current_time=datetime_now()))
        out.string(self.realm.config.build_name)
        return out

    def login(self, conn: Connection, s: StreamIn) -> StreamOut:
        username = s.string()
        raise RMCError(rmc.RV_INVALID_USERNAME, f"plain Login of {username} without a token")

    def login_ex(self, conn: Connection, s: StreamIn) -> StreamOut:
        username = s.string()
        name, data = s.anydata()
        if name != "AuthenticationInfo":
            raise RMCError(rmc.CORE_INVALID_ARGUMENT, f"extra data {name}")
        info = AuthenticationInfo.decode(data)
        self.log.debug("%s: LoginEx %s, NGS %d, token type %d, server version %d", conn, username,
                       info.ngs_version, info.token_type, info.server_version)
        return self._login(conn, username, info.token)

    def request_ticket(self, conn: Connection, s: StreamIn) -> StreamOut:
        source, target = s.pid(), s.pid()
        key = conn.data.get("user_key")
        if key is None or source != conn.pid:
            raise RMCError(rmc.RV_INVALID_PID, "ticket before login")
        out = StreamOut()
        out.result(rmc.SUCCESS)
        out.buffer(self.realm.make_ticket(source, key, target))
        return out


# ==== secure server ================================================================================

class SecureServer(PRUDPServer):
    def __init__(self, realm: Realm) -> None:
        super().__init__(f"{realm.config.name}.secure", ACCESS_KEY)
        self.realm = realm
        self.rmc = RMCDispatcher(self.name)
        self.by_pid: dict[int, Connection] = {}
        self.by_cid: dict[int, Connection] = {}
        self._next_cid = 1
        reg = self.rmc.register
        reg(SECURE_CONNECTION, 1, "SecureConnection::Register", self.register)
        reg(SECURE_CONNECTION, 7, "SecureConnection::ReplaceURL", self.replace_url)
        reg(SECURE_CONNECTION, 8, "SecureConnection::SendReport", self.send_report)
        reg(NAT_TRAVERSAL, 3, "NATTraversal::RequestProbeInitiationExt", self.request_probe_initiation_ext)
        reg(NAT_TRAVERSAL, 4, "NATTraversal::ReportNATTraversalResult", self.report_nat_traversal_result)
        reg(NAT_TRAVERSAL, 5, "NATTraversal::ReportNATProperties", self.report_nat_properties)
        reg(MATCH_MAKING, 40, "MatchMaking::UpdateSessionHostV1", self.update_session_host)
        reg(MATCH_MAKING, 41, "MatchMaking::GetSessionURLs", self.get_session_urls)
        reg(MATCH_MAKING_EXT, 1, "MatchMakingExt::EndParticipation", self.end_participation)
        reg(MATCHMAKE_EXTENSION, 1, "MatchmakeExtension::CloseParticipation", self.close_participation)
        reg(MATCHMAKE_EXTENSION, 2, "MatchmakeExtension::OpenParticipation", self.open_participation)
        reg(MATCHMAKE_EXTENSION, 15, "MatchmakeExtension::AutoMatchmakeWithSearchCriteria_Postpone",
            self.auto_matchmake)
        reg(MATCHMAKE_EXTENSION, 25, "MatchmakeExtension::AddToBlackList", self.add_to_blacklist)
        reg(MATCHMAKE_EXTENSION, 26, "MatchmakeExtension::RemoveFromBlackList", self.remove_from_blacklist)

    # -- connection ----------------------------------------------------------------------------

    def on_connect(self, conn: Connection, payload: bytes) -> bytes | None:
        s = StreamIn(payload)
        ticket, request = s.buffer(), s.buffer()
        try:
            pid, session_key = self.realm.open_ticket(ticket)
            r = StreamIn(kerberos_decrypt(session_key, request))
        except KerberosError as e:
            self.log.warning("%s: bad ticket (%s)", conn, e)
            return None
        user_pid, cid, check = r.pid(), r.u32(), r.u32()
        if user_pid != pid:
            self.log.warning("%s: ticket of %d used by %d", conn, pid, user_pid)
            return None
        old = self.by_pid.get(pid)
        if old is not None and old is not conn:
            self.drop(old, "logged in again")
        conn.pid = pid
        conn.set_session_key(session_key)
        self.by_pid[pid] = conn
        return struct.pack("<II", 4, (check + 1) & 0xFFFFFFFF)

    def on_data(self, conn: Connection, payload: bytes) -> None:
        self.rmc.handle_payload(conn, payload)

    def on_disconnect(self, conn: Connection, reason: str) -> None:
        if self.by_pid.get(conn.pid) is conn:
            del self.by_pid[conn.pid]
            self.realm.matchmaker.leave(conn.pid, "")
        cid = conn.data.get("cid")
        if cid is not None and self.by_cid.get(cid) is conn:
            del self.by_cid[cid]
        if "forwarded" in conn.data:
            self.realm.internet.release_player(conn.data.pop("forwarded"))

    # -- SecureConnection ----------------------------------------------------------------------

    def _station(self, conn: Connection, url: StationURL) -> StationURL:
        url = url.copy()
        url["PID"] = conn.pid
        url["RVCID"] = conn.data["cid"]
        return url

    def register(self, conn: Connection, s: StreamIn) -> StreamOut:
        urls = s.list(StreamIn.url)
        cid = self._next_cid
        self._next_cid += 1
        conn.data["cid"] = cid
        self.by_cid[cid] = conn
        local = [self._station(conn, u) for u in urls]
        public = (urls[0].copy() if urls else StationURL("prudp", {}))
        public["address"], public["port"] = self.realm.internet.seen_as(conn.addr)
        public["type"] = 3
        public = self._station(conn, public)
        conn.data["urls"] = local + [public]
        self.log.info("%s: registered, cid %d, local %s, public %s", conn, cid,
                      " ".join(map(str, urls)), public)
        out = StreamOut()
        out.result(rmc.SUCCESS)
        out.u32(cid)
        out.url(public)
        return out

    def replace_url(self, conn: Connection, s: StreamIn) -> StreamOut:
        """Pia calls this once its NAT detection is done (NatTraverser::updateLocalStationInfo): the
        private URL gets the port of Pia's own socket and the NAT type. The public URL from Register
        still has the port of the NEX socket, so it is updated too: the port our NAT check saw for
        this address (the public port of Pia's socket), else the private port. For a console at home
        (on the server's network) that port is forwarded on the router, if it does UPnP."""
        old, new = s.url(), s.url()
        urls = conn.data.setdefault("urls", [])
        station = self._station(conn, new) if "cid" in conn.data else new
        for n, u in enumerate(urls):
            if u.get("address") == old.get("address") and u.get("port") == old.get("port"):
                urls[n] = station
                break
        else:
            urls.insert(0, station)
        local_port = new.get_int("port") or None
        public_port = self.realm.natcheck.public_port(conn.addr[0], local_port) if self.realm.natcheck else None
        if local_port and "forwarded" not in conn.data:
            if self.realm.internet.forward_player(conn.addr[0], local_port, new.get("address")):
                conn.data["forwarded"] = local_port
        for u in urls:
            if u.get_int("type") & 2:
                u["port"] = public_port or new.get("port")
                for key in ("natm", "natf"):
                    if key in new.fields:
                        u[key] = new[key]
        self.log.info("%s: URL %s -> %s", conn, old, new)
        return None

    def send_report(self, conn: Connection, s: StreamIn) -> StreamOut:
        report_id = s.u32()
        data = s.qbuffer()
        self.log.info("%s: report %#x %s", conn, report_id, data.hex())
        return None

    # -- NATTraversal --------------------------------------------------------------------------

    def _target(self, url: StationURL) -> Connection | None:
        cid = url.get_int("RVCID", -1)
        if cid in self.by_cid:
            return self.by_cid[cid]
        return self.by_pid.get(url.get_int("PID", -1))

    def request_probe_initiation_ext(self, conn: Connection, s: StreamIn) -> StreamOut:
        targets = s.list(StreamIn.url)
        probe = s.url()
        done = set()
        for url in targets:
            target = self._target(url)
            if target is None:
                self.log.info("%s: probe target %s unknown", conn, url)
                continue
            if id(target) in done:
                continue
            done.add(id(target))
            params = StreamOut()
            params.url(probe)
            self.rmc.call_client(target, NAT_TRAVERSAL, 2, params)       # InitiateProbe
        self.log.info("%s: probe initiation towards %d station(s)", conn, len(targets))
        return None

    def report_nat_traversal_result(self, conn: Connection, s: StreamIn) -> StreamOut:
        cid, result, rtt = s.u32(), s.bool(), s.u32()
        self.log.info("%s: NAT traversal to cid %d %s (rtt %d)", conn, cid, "succeeded" if result else "failed", rtt)
        return None

    def report_nat_properties(self, conn: Connection, s: StreamIn) -> StreamOut:
        mapping, filtering, rtt = s.u32(), s.u32(), s.u32()
        conn.data["nat"] = (mapping, filtering)
        self.log.info("%s: NAT mapping %d, filtering %d, rtt %d", conn, mapping, filtering, rtt)
        return None

    # -- MatchMaking ---------------------------------------------------------------------------

    def _session(self, gid: int):
        session = self.realm.matchmaker.get(gid)
        if session is None:
            raise RMCError(rmc.RV_SESSION_VOID, f"no session {gid}")
        return session

    def get_session_urls(self, conn: Connection, s: StreamIn) -> StreamOut:
        session = self._session(s.u32())
        host = self.by_pid.get(session.info.host_pid)
        urls = host.data.get("urls", []) if host else []
        out = StreamOut()
        out.list(urls, StreamOut.url)
        self.log.info("%s: URLs of session %d host %d: %s", conn, session.gid, session.info.host_pid,
                      " ".join(map(str, urls)))
        return out

    def update_session_host(self, conn: Connection, s: StreamIn) -> StreamOut:
        gid = s.u32()
        if not self.realm.matchmaker.update_host(conn.pid, gid):
            raise RMCError(rmc.RV_SESSION_VOID, f"no session {gid}")
        return None

    def end_participation(self, conn: Connection, s: StreamIn) -> StreamOut:
        gid, message = s.u32(), s.string()
        out = StreamOut()
        out.bool(self.realm.matchmaker.leave(conn.pid, message, gid))
        return out

    # -- MatchmakeExtension --------------------------------------------------------------------

    def open_participation(self, conn: Connection, s: StreamIn) -> StreamOut:
        if not self.realm.matchmaker.set_open(conn.pid, s.u32(), True):
            raise RMCError(rmc.RV_SESSION_VOID)
        return None

    def close_participation(self, conn: Connection, s: StreamIn) -> StreamOut:
        if not self.realm.matchmaker.set_open(conn.pid, s.u32(), False):
            raise RMCError(rmc.RV_SESSION_VOID)
        return None

    def auto_matchmake(self, conn: Connection, s: StreamIn) -> StreamOut:
        criteria = s.list(SearchCriteria.decode)
        name, data = s.anydata()
        message = s.string()
        if name != MatchmakeSession.CLASS_NAME:
            raise RMCError(rmc.CORE_INVALID_ARGUMENT, f"gathering class {name}")
        proposal = MatchmakeSession.decode(data)
        self.log.debug("%s: auto matchmake, criteria %s, proposal %s", conn, criteria, proposal)
        report = 0
        with contextlib.suppress(IndexError, ValueError):
            report = int(criteria[0].attributes[REPORT_ATTRIBUTE] or 0)
        seen, kick = report & 0xFF, report >> 16 & 0x7FFF
        if seen and self.realm.config.cheats != "autorises":
            self.realm.caught_cheating(conn.pid, seen, kick)
            if self.realm.excluded(conn.pid):
                raise RMCError(rmc.RV_ACCOUNT_DISABLED, "caught cheating")
        session = self.realm.matchmaker.auto_matchmake(conn.pid, criteria, proposal, message,
                                                       self.realm.pool(conn.pid))
        self.realm.matchmaker.set_globals(conn.pid, {"server.anticheat": int(self.realm.anticheat_on(conn.pid)),
                                                     "server.duration": self.realm.config.duration * 60})
        out = StreamOut()
        out.anydata(MatchmakeSession.CLASS_NAME, session)
        return out

    def add_to_blacklist(self, conn: Connection, s: StreamIn) -> StreamOut:
        self.realm.matchmaker.set_blocklist(conn.pid, s.list(StreamIn.pid), True)
        return None

    def remove_from_blacklist(self, conn: Connection, s: StreamIn) -> StreamOut:
        self.realm.matchmaker.set_blocklist(conn.pid, s.list(StreamIn.pid), False)
        return None
