"""Status page of the server: what is running, for the players and for whoever hosts it.

    [server] status_port = 8730      (serveur.toml; 0 or absent: no status page)

  GET /              a small page (French), refreshed every 30 seconds
  GET /status.json   the same as JSON: uptime, and per realm the players online, the accounts, the options
                     and the matches being played (players, maximum, open to newcomers, cheaters' pool, age)

No personal data: player ids are not shown. Standard library only (asyncio), HTTP/1.0, GET only.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time

log = logging.getLogger("status")

POLICIES = {"separes": "ne jouent qu'entre eux", "autorises": "jouent avec tout le monde", "refuses": "refusés"}


class StatusServer:
    def __init__(self, realms: list, name: str = "Sub Wars Open Sourced") -> None:
        self.realms = realms
        self.name = name
        self.started = time.time()
        self.server: asyncio.AbstractServer | None = None

    def snapshot(self) -> dict:
        return {"server": self.name, "uptime": int(time.time() - self.started),
                "realms": [realm.status() for realm in self.realms]}

    def page(self) -> str:
        data = self.snapshot()
        hours, rest = divmod(data["uptime"], 3600)
        parts = [f"<h1>{html.escape(self.name)}</h1>",
                 f"<p class=muted>Serveur en ligne de Steel Diver: Sub Wars, lancé depuis {hours} h {rest // 60:02d}.</p>"]
        for realm in data["realms"]:
            matches = realm["matches"]
            rows = "".join(
                f"<tr><td>{m['players']} / {m['max']}</td><td>{'ouverte' if m['open'] else 'en cours'}</td>"
                f"<td>{'tricheurs' if m['cheaters'] else ''}</td><td>{m['minutes']} min</td></tr>" for m in matches)
            parts.append(
                f"<h2>Royaume « {html.escape(realm['name'])} » <small>("
                + (f"adresse {html.escape(realm['address'])}, " if realm.get("address") else "")
                + f"port UDP {realm['auth_port']})</small></h2>"
                f"<p><b>{realm['players_online']}</b> joueur(s) connecté(s), {realm['accounts']} compte(s). "
                f"Jusqu'à {realm['max_players']} joueurs humains par partie (des bots complètent les équipes) ; "
                f"les tricheurs {POLICIES.get(realm['cheats'], realm['cheats'])}.</p>"
                + (f"<table><tr><th>Joueurs</th><th>Partie</th><th></th><th>Depuis</th></tr>{rows}</table>"
                   if matches else "<p class=muted>Aucune partie en ce moment.</p>"))
        return ("<!doctype html><html lang=fr><meta charset=utf-8><meta http-equiv=refresh content=30>"
                "<meta name=viewport content='width=device-width,initial-scale=1'><title>"
                + html.escape(self.name) + "</title><style>body{font:15px/1.5 system-ui,sans-serif;max-width:760px;"
                "margin:24px auto;padding:0 16px;color:#14212e;background:#f3f6f9}.muted{color:#5b6b7a}"
                "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;"
                "border-bottom:1px solid #d8e0e8}small{color:#5b6b7a;font-weight:normal}</style>"
                + "".join(parts) + "</html>")

    async def start(self, host: str, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, host, port)
        log.info("status page on http://%s:%d/", host if host != "0.0.0.0" else "127.0.0.1", port)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), 5)
            for _ in range(100):                      # skip the headers
                line = await asyncio.wait_for(reader.readline(), 5)
                if line in (b"\r\n", b"\n", b""):
                    break
            fields = request.decode("latin-1").split()
            path = fields[1].split("?")[0] if len(fields) >= 2 else ""
            if len(fields) < 2 or fields[0] != "GET":
                status, kind, body = "405 Method Not Allowed", "text/plain", b"GET only"
            elif path == "/status.json":
                status, kind = "200 OK", "application/json"
                body = json.dumps(self.snapshot(), ensure_ascii=False).encode("utf-8")
            elif path in ("/", "/index.html"):
                status, kind, body = "200 OK", "text/html; charset=utf-8", self.page().encode("utf-8")
            else:
                status, kind, body = "404 Not Found", "text/plain", b"not found"
            writer.write(f"HTTP/1.0 {status}\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\n"
                         "Cache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
                         .encode("latin-1") + body)
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, UnicodeDecodeError):
            pass
        finally:
            writer.close()

    def close(self) -> None:
        if self.server:
            self.server.close()
