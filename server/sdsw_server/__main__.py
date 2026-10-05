"""Steel Diver: Sub Wars online server.

    cd server && python3 -m sdsw_server [-c serveur.toml] [--realm emulateur] [-v]

Starts the realms of the configuration (authentication + secure server each) and the NAT check service.
Python 3.11+, standard library only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tomllib
from pathlib import Path

from .natcheck import NatCheckService
from .realm import Realm, RealmConfig
from .status import StatusServer

HERE = Path(__file__).resolve().parent.parent


def load_config(path: Path, only: list[str] | None) -> tuple[dict, list[RealmConfig]]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    server = config.get("server", {})
    listen = server.get("listen", "0.0.0.0")
    public = server.get("public_address", "127.0.0.1")
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


async def run(server: dict, realms: list[RealmConfig]) -> None:
    natcheck = NatCheckService() if server.get("nat_check", True) else None
    started = []
    for config in realms:
        realm = Realm(config, natcheck)
        await realm.start()
        started.append(realm)
    if natcheck:
        await natcheck.start(server.get("listen", "0.0.0.0"))
    if int(server.get("status_port", 0)):
        await StatusServer(started, server.get("name", "Sub Wars Open Sourced")).start(
            server.get("listen", "0.0.0.0"), int(server["status_port"]))
    await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", type=Path, default=HERE / "serveur.toml")
    ap.add_argument("--realm", action="append", help="only start this realm (repeatable)")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="-v: packets, -vv: more")
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
    try:
        asyncio.run(run(server, realms))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        sys.exit(f"cannot open a port: {e}")


if __name__ == "__main__":
    main()
