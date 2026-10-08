"""Player accounts: principal id -> Kerberos key, registered on first login (trust on first use).

The online mod gives every player a random principal id and password, generated when the player builds
the mod, and puts the derived Kerberos key in the authentication token ("sdsw1:<32 hex digits>"). The
server cannot know the password otherwise: the console used to get it from Nintendo's account servers.
A known id must always come back with the same key.

The token may end with ":<flag>,<flag>": what the player's build changes in the game ("cheats" for the
cheat mod), so that the server can refuse it or keep those players apart. The build declares it
honestly; a modified game can always lie.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

TOKEN_PREFIX = "sdsw1:"

# Ids that NEX reserves for its own servers and guests
RESERVED_PIDS = {0, 1, 2, 3, 100, 0xFFFFFFFF}


class AccountError(Exception):
    pass


def parse_token(token: str) -> tuple[bytes, frozenset[str]]:
    """"sdsw1:<key>[:<flags>]" -> (Kerberos key, flags)."""
    if not token.startswith(TOKEN_PREFIX):
        raise AccountError(f"unknown token format {token[:16]!r}")
    key_hex, _, flags = token[len(TOKEN_PREFIX):].strip().partition(":")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as e:
        raise AccountError("token is not hexadecimal") from e
    if len(key) != 16:
        raise AccountError("token key must be 16 bytes")
    return key, frozenset(f for f in flags.split(",") if f)


class Accounts:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS accounts (pid INTEGER PRIMARY KEY, key BLOB NOT NULL, "
                        "created REAL NOT NULL, last_login REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value BLOB NOT NULL)")
        self.db.commit()

    def secret(self, name: str, size: int = 16) -> bytes:
        row = self.db.execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
        value = os.urandom(size)
        self.db.execute("INSERT INTO secrets VALUES (?, ?)", (name, value))
        self.db.commit()
        return value

    def key(self, pid: int) -> bytes | None:
        row = self.db.execute("SELECT key FROM accounts WHERE pid = ?", (pid,)).fetchone()
        return row[0] if row else None

    def login(self, pid: int, key: bytes) -> bool:
        """Checks or registers the key of an account; True when newly registered."""
        if pid in RESERVED_PIDS:
            raise AccountError(f"reserved principal id {pid}")
        known = self.key(pid)
        now = time.time()
        if known is None:
            self.db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)", (pid, key, now, now))
            self.db.commit()
            return True
        if known != key:
            raise AccountError(f"principal id {pid} is registered with another key")
        self.db.execute("UPDATE accounts SET last_login = ? WHERE pid = ?", (now, pid))
        self.db.commit()
        return False

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
