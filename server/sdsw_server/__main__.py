"""Steel Diver: Sub Wars online server.

    cd server && python3 -m sdsw_server [-c serveur.toml] [--realm emulateur] [-v]

Starts the realms of the configuration (authentication + secure server each) and the NAT check service,
finds the public address and asks the router to forward the ports (UPnP). While it runs, a state file
(data/serveur.json next to the configuration) tells the launcher its process, ports and public address.
Python 3.11+, standard library only.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import threading
import time
import tomllib
from pathlib import Path

from . import stun
from .internet import Internet
from .natcheck import PORTS as NAT_CHECK_PORTS, NatCheckService
from .realm import Realm, RealmConfig
from .status import StatusServer

HERE = Path(__file__).resolve().parent.parent
log = logging.getLogger("server")


def load_config(path: Path, only: list[str] | None) -> tuple[dict, list[RealmConfig]]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    server = config.get("server", {})
    listen = server.get("listen", "0.0.0.0")
    public = server.get("public_address", "auto")
    realms = []
    for entry in config.get("realm", []):
        if only and entry["name"] not in only:
            continue
        data_dir = Path(entry.get("data_dir", f"data/{entry['name']}"))
        if not data_dir.is_absolute():
            data_dir = path.parent / data_dir
        realms.append(RealmConfig(name=entry["name"], listen=listen,
                                  public_address=entry.get("public_address", public),
                                  auth_port=int(entry["auth_port"]), secure_port=int(entry["secure_port"]),
                                  data_dir=data_dir, max_players=int(entry.get("max_players", 8)),
                                  cheats=str(entry.get("cheats", "separes"))))
    return server, realms


class StateFile:
    """data/serveur.json while the server runs: what the launcher shows (and the process it may stop)."""

    def __init__(self, path: Path | None, config: Path, realms: list[RealmConfig], internet: Internet,
                 status_port: int) -> None:
        self.path = path
        self.base = {"pid": os.getpid(), "ppid": os.getppid(), "started": int(time.time()),
                     "config": str(config.resolve()),
                     "realms": [{"name": r.name, "auth_port": r.auth_port, "secure_port": r.secure_port}
                                for r in realms], "status_port": status_port}
        self.internet = internet

    def write(self) -> None:
        if not self.path:
            return
        with contextlib.suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.base | {"internet": self.internet.status()}, indent=1), encoding="utf-8")
            os.replace(temp, self.path)

    def remove(self) -> None:
        if self.path:
            with contextlib.suppress(OSError):
                if json.loads(self.path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                    self.path.unlink()


def watch_stdin(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    """--exit-with-stdin: the launcher keeps our standard input open; it closes when the launcher goes away."""
    def wait() -> None:
        with contextlib.suppress(OSError, ValueError):
            while os.read(sys.stdin.fileno(), 1024):
                pass
        loop.call_soon_threadsafe(stop.set)
    threading.Thread(target=wait, daemon=True).start()


async def run(server: dict, realms: list[RealmConfig], config: Path, state_path: Path | None,
              exit_with_stdin: bool = False) -> None:
    listen = server.get("listen", "0.0.0.0")
    status_port = int(server.get("status_port", 0))
    internet = Internet(server.get("public_address", "auto"), bool(server.get("upnp", False)),
                        server.get("stun_servers", stun.SERVERS))
    natcheck = NatCheckService(internet) if server.get("nat_check", True) else None
    started = []
    status = None
    state = StateFile(state_path, config, realms, internet, status_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError, AttributeError):       # not on Windows
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    if exit_with_stdin:
        watch_stdin(loop, stop)
    try:
        for realm_config in realms:
            realm = Realm(realm_config, natcheck, internet)
            await realm.start()
            started.append(realm)
        if natcheck:
            await natcheck.start(listen)
        if status_port:
            status = StatusServer(started, server.get("name", "Sub Wars Open Sourced"))
            await status.start(listen, status_port)
        state.write()
        internet.on_change = state.write
        ports = [("UDP", port) for r in realms for port in (r.auth_port, r.secure_port)]
        ports += [("UDP", port) for port in NAT_CHECK_PORTS] if natcheck else []
        ports += [("TCP", status_port)] if status_port else []
        await internet.start(ports)
        for realm_config in realms:
            address = (realm_config.public_address if realm_config.public_address != "auto"
                       else internet.public_name or internet.public_ip)
            log.info("realm %s: online mod with server=%s port=%d for players far away, server=127.0.0.1 on "
                     "this machine", realm_config.name, address or "<public address unknown>", realm_config.auth_port)
        await stop.wait()
        log.info("stopping")
    finally:
        await internet.close()
        for realm in started:
            realm.close()
        if status:
            status.close()
        state.remove()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", type=Path, default=HERE / "serveur.toml")
    ap.add_argument("--realm", action="append", help="only start this realm (repeatable)")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="-v: packets, -vv: more")
    ap.add_argument("--state-file", type=Path, help="state file (default: data/serveur.json next to the config)")
    ap.add_argument("--exit-with-stdin", action="store_true",
                    help="stop when standard input closes (the program that started the server is gone)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)-18s %(message)s", datefmt="%H:%M:%S")
    if args.verbose < 2:
        logging.getLogger("prudp").setLevel(logging.INFO)
    try:
        server, realms = load_config(args.config, args.realm)
    except (ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"bad configuration {args.config}: {e}")
    if not realms:
        sys.exit("no realm to start")
    state = args.state_file or args.config.parent / "data" / "serveur.json"
    try:
        asyncio.run(run(server, realms, args.config, state, args.exit_with_stdin))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        sys.exit(f"cannot open a port: {e}")


if __name__ == "__main__":
    main()
