#!/usr/bin/env python3
"""The project's own updates: its latest release on GitHub, downloaded and put in place over this folder.

Each version of the project is a GitHub release, tag v<VERSION>, made by tools/release.py: it holds
Sub-Wars-Open-Sourced.zip (the project's files at that tag) and the installers (Install-here.bat,
install-here.sh, Install-here-macOS.zip). The launcher compares VERSION with the latest release and, when there is
a newer one, offers to update:

- the zip is downloaded, checked by the SHA-256 GitHub gives for it, and read in memory;
- every file that changed is replaced, VERSION last (an interrupted update is offered again); the files the new
  version removed or renamed (GitHub's comparison of both tags) are deleted;
- server/server.toml stays as it is when the player changed it (the options it lacks take their default values);
- the player's files are never touched: cia/, extracted/, build/, server/data/, a mod of their own;
- the launcher then restarts.

A git clone is not updated this way: git pull.

    python3 tools/selfupdate.py            the version here and the latest one
    python3 tools/selfupdate.py --apply    update this folder
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
ASSET = "Sub-Wars-Open-Sourced.zip"
FOLDER = "Sub-Wars-Open-Sourced"                   # the folder the zip unpacks to
PLAYER_DIRS = ("cia", "extracted", "build", "server/data", ".git")
KEPT_WHEN_CHANGED = ("server/server.toml",)
CHECK_EVERY = 3600                                 # seconds between two questions to GitHub


class UpdateError(Exception):
    """A message for the player."""


def current() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)) or (0,)


def is_git() -> bool:
    return (ROOT / ".git").exists()


def fetch(url: str, timeout: int = 20, accept: str = "") -> bytes:
    """GET url; with curl when this Python has no usable certificates (python.org's macOS builds before
    "Install Certificates", portable builds)."""
    headers = {"User-Agent": "sub-wars-open-sourced"} | ({"Accept": accept} if accept else {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise UpdateError(f"{url}: HTTP {e.code}") from e
    except (OSError, http.client.HTTPException, ValueError) as e:
        curl = shutil.which("curl")
        if curl is None:
            raise UpdateError(f"no answer from GitHub ({e})") from e
        command = [curl, "-fsSL", "--max-time", str(timeout), "-A", headers["User-Agent"]]
        command += ["-H", f"Accept: {accept}"] if accept else []
        result = subprocess.run(command + [url], capture_output=True, timeout=timeout + 10)
        if result.returncode:
            raise UpdateError(f"no answer from GitHub ({result.stderr.decode(errors='replace').strip() or e})") from e
        return result.stdout


def latest() -> dict:
    """The latest release: its version, notes, page, and its zip (address, size, SHA-256)."""
    try:
        try:
            data = json.loads(fetch(f"{API}/releases/latest", accept="application/vnd.github+json"))
        except UpdateError as e:
            if "HTTP 404" in str(e):
                raise UpdateError("no release of the project yet") from e
            raise
        asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET), None)
        if asset is None:
            raise UpdateError(f"the latest release has no {ASSET}")
        digest = asset.get("digest") or ""
        return {"version": data["tag_name"].lstrip("v"), "tag": data["tag_name"], "notes": data.get("body") or "",
                "url": data.get("html_url") or f"https://github.com/{REPO}/releases",
                "zip": {"url": asset["browser_download_url"], "size": int(asset["size"]),
                        "sha256": digest[7:] if digest.startswith("sha256:") else None}}
    except (KeyError, TypeError, ValueError) as e:
        raise UpdateError(f"unexpected answer from GitHub ({e})") from e


_checked: dict = {"at": 0.0, "result": None}


def check(force: bool = False) -> dict:
    """{"current", "latest", "newer", "git", "notes", "url", "error"}: asked to GitHub at most once an hour."""
    if not force and _checked["result"] and time.time() - _checked["at"] < CHECK_EVERY:
        return _checked["result"] | {"current": current()}
    result = {"current": current(), "latest": None, "newer": False, "git": is_git(), "notes": "", "url": "",
              "error": None}
    try:
        info = latest()
        result.update(latest=info["version"], notes=info["notes"][:4000], url=info["url"],
                      newer=version_key(info["version"]) > version_key(current()))
    except UpdateError as e:
        result["error"] = str(e)
    _checked.update(at=time.time(), result=result)
    return result


def unpack(data: bytes) -> dict[str, tuple[bytes, int]]:
    """The files of a release zip: path in the project -> (content, Unix mode)."""
    files = {}
    with zipfile.ZipFile(BytesIO(data)) as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            parts = member.filename.split("/")[1:]          # without the zip's own folder
            if not parts or "" in parts or ".." in parts or "\\" in member.filename or ":" in member.filename:
                raise UpdateError(f"unexpected entry in the release: {member.filename!r}")
            files["/".join(parts)] = (z.read(member), (member.external_attr >> 16) & 0o777)
    if "VERSION" not in files or "subwars.py" not in files:
        raise UpdateError("the release does not hold the project")
    return files


def players(path: str) -> bool:
    """Whether a path of the project is the player's (their game, its files, the server's data)."""
    return any(path == d or path.startswith(d + "/") for d in PLAYER_DIRS)


def removed_files(old: str, new: str) -> set[str]:
    """The files that new removed or renamed since old (GitHub's comparison of both tags)."""
    gone, page = set(), 1
    while page <= 30:
        data = json.loads(fetch(f"{API}/compare/v{old}...v{new}?per_page=100&page={page}",
                                accept="application/vnd.github+json"))
        files = data.get("files") or []
        for f in files:
            if f.get("status") == "removed":
                gone.add(f["filename"])
            elif f.get("status") == "renamed" and f.get("previous_filename"):
                gone.add(f["previous_filename"])
        if len(files) < 100:
            return gone
        page += 1
    return gone


def changed_by_player(path: str, version: str) -> bool:
    """Whether a file differs from the one version shipped (unknown: considered changed, so that it is kept)."""
    try:
        return (ROOT / path).read_bytes() != fetch(f"{RAW}/v{version}/{path}")
    except (OSError, UpdateError):
        return True


def apply(log=print) -> str:
    """Updates this folder to the latest release; returns its version."""
    if is_git():
        raise UpdateError("this folder is a git clone: update it with git pull")
    info, old = latest(), current()
    if version_key(info["version"]) <= version_key(old):
        raise UpdateError(f"version {old} is already the latest")
    log(f"Downloading version {info['version']} ({info['zip']['size'] / 1e6:.1f} MB)…")
    data = fetch(info["zip"]["url"], timeout=300)
    if len(data) != info["zip"]["size"] or (info["zip"]["sha256"]
                                             and hashlib.sha256(data).hexdigest() != info["zip"]["sha256"]):
        raise UpdateError("the downloaded release is not the one GitHub describes (size or SHA-256): nothing changed")
    files = unpack(data)
    try:
        gone = removed_files(old, info["version"])
    except (UpdateError, ValueError) as e:
        log(f"(the files version {info['version']} removed are not known: {e}; they stay)")
        gone = set()
    written = 0
    for path in sorted(files, key=lambda p: p == "VERSION"):           # VERSION last
        content, mode = files[path]
        dest = ROOT / path
        if players(path) or (dest.is_file() and dest.read_bytes() == content):
            continue
        if path in KEPT_WHEN_CHANGED and dest.is_file() and changed_by_player(path, old):
            log(f"Kept your {path} (the options it lacks take their default values).")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".update")
        part.write_bytes(content)
        if os.name != "nt" and mode & 0o111:
            part.chmod(0o755)
        os.replace(part, dest)
        written += 1
    removed = 0
    for path in sorted(gone - set(files)):
        dest = ROOT / path
        if players(path) or not dest.is_file():
            continue
        dest.unlink()
        removed += 1
        parent = dest.parent
        while parent != ROOT and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    log(f"Version {info['version']}: {written} file(s) updated, {removed} removed.")
    _checked.update(at=0.0, result=None)
    return info["version"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="update this folder to the latest release")
    args = ap.parse_args()
    try:
        if args.apply:
            apply()
            return
        state = check(force=True)
        if state["error"]:
            sys.exit(f"[!] {state['error']}")
        print(f"This folder: {state['current']}; latest release: {state['latest']}"
              + (" (newer: python3 tools/selfupdate.py --apply)" if state["newer"] else ""))
    except UpdateError as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
