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
import logging
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from . import rmc
from .accounts import AccountError, Accounts
from .crypto import KerberosError, kerberos_decrypt, kerberos_encrypt
from .ddl import (AuthenticationInfo, MatchmakeSession, NotificationEvent, RVConnectionData,
                  SearchCriteria)
from .matchmaking import Matchmaker
from .prudp import Connection, PRUDPServer
from .rmc import RMCDispatcher, RMCError
from .streams import StationURL, StreamIn, StreamOut, datetime_now

ACCESS_KEY = "fb9537fe"             # gameServerLogin -> NgsFacade::Login(..., 0xD7C00, L"fb9537fe", 60000)
SECURE_PID = 2                       # principal id of the secure server in its station URL
TICKET_LIFETIME = 3600

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


class Realm:
    def __init__(self, config: RealmConfig, natcheck=None) -> None:
        self.config = config
        self.natcheck = natcheck                   # NatCheckService, to learn the public port of Pia
        self.log = logging.getLogger(config.name)
        self.accounts = Accounts(config.data_dir / "accounts.sqlite3")
        self.ticket_key = self.accounts.secret("ticket key")
        self.auth = AuthServer(self)
        self.secure = SecureServer(self)
        self.matchmaker = Matchmaker(self.notify)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self.auth, local_addr=(self.config.listen, self.config.auth_port))
        await loop.create_datagram_endpoint(lambda: self.secure,
                                            local_addr=(self.config.listen, self.config.secure_port))
        self.log.info("realm %s: authentication UDP %d, secure UDP %d, public address %s, %d account(s)",
                      self.config.name, self.config.auth_port, self.config.secure_port,
                      self.config.public_address, self.accounts.count())

    # -- tickets -------------------------------------------------------------------------------

    def secure_url(self) -> StationURL:
        return StationURL("prudps", {"address": self.config.public_address, "port": str(self.config.secure_port),
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
            key, new = self.realm.accounts.login(pid, token)
        except AccountError as e:
            self.log.warning("%s: login refused for %s: %s", conn, username, e)
            raise RMCError(rmc.RV_INVALID_PASSWORD, str(e))
        conn.pid = pid
        conn.data["user_key"] = key
        self.log.info("%s: %s pid %d", conn, "new player" if new else "login", pid)
        out = StreamOut()
        out.result(rmc.SUCCESS)
        out.pid(pid)
        out.buffer(self.realm.make_ticket(pid, key, SECURE_PID))
        out.structure(RVConnectionData(self.realm.secure_url(), current_time=datetime_now()))
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
        public["address"] = conn.addr[0]
        public["port"] = conn.addr[1]
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
        this address (the public port of Pia's socket), else the private port."""
        old, new = s.url(), s.url()
        urls = conn.data.setdefault("urls", [])
        station = self._station(conn, new) if "cid" in conn.data else new
        for n, u in enumerate(urls):
            if u.get("address") == old.get("address") and u.get("port") == old.get("port"):
                urls[n] = station
                break
        else:
            urls.insert(0, station)
        public_port = self.realm.natcheck.public_port(conn.addr[0]) if self.realm.natcheck else None
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
        session = self.realm.matchmaker.auto_matchmake(conn.pid, criteria, proposal, message)
        out = StreamOut()
        out.anydata(MatchmakeSession.CLASS_NAME, session)
        return out

    def add_to_blacklist(self, conn: Connection, s: StreamIn) -> StreamOut:
        self.realm.matchmaker.set_blocklist(conn.pid, s.list(StreamIn.pid), True)
        return None

    def remove_from_blacklist(self, conn: Connection, s: StreamIn) -> StreamOut:
        self.realm.matchmaker.set_blocklist(conn.pid, s.list(StreamIn.pid), False)
        return None
