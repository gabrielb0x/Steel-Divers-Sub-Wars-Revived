#!/usr/bin/env python3
"""Publishes a version of the project: the GitHub release v<VERSION>, which the installers and the launcher's
updates download (tools/selfupdate.py).

    python3 tools/release.py --notes "What changed, for the players."
    python3 tools/release.py --dry-run           build the files in build/release/ without publishing

After each change that is finished: raise VERSION (0.2 -> 0.3), commit, push, then run this. The release holds:

  Sub-Wars-Open-Sourced.zip   the project at that commit (git archive: tracked files only, never a game file),
                              in a folder Sub-Wars-Open-Sourced/
  Install-here.bat            Windows installer: downloads the latest zip next to itself, unpacks it, removes the
                              zip, opens the launcher, which sets the game up
  install-here.sh             the same for Linux
  Install-here-macOS.zip      the same for macOS: "Install here.command", zipped so that it stays executable

It needs git and the GitHub CLI (gh, logged in), and the commit pushed to origin.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "release"
REPO = "gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced"
FOLDER = "Sub-Wars-Open-Sourced"


def run(*command: str, check: bool = True) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if check and result.returncode:
        sys.exit(f"[!] {' '.join(command)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def gh() -> str:
    found = os.environ.get("GH") or shutil.which("gh")
    if not found:
        for candidate in sorted((Path.home() / "tools").glob("gh_*/bin/gh")):
            found = str(candidate)
    if not found:
        sys.exit("[!] the GitHub CLI (gh) is needed: https://cli.github.com/")
    return found


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.replace("v", "").split(".") if n.isdigit())


def build_assets(out: Path) -> list[Path]:
    """The release's files, from the commit HEAD."""
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    archive = out / f"{FOLDER}.zip"
    run("git", "archive", "--format=zip", f"--prefix={FOLDER}/", "-o", str(archive), "HEAD")
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        bat = z.read(f"{FOLDER}/installer/Install-here.bat")
        sh = z.read(f"{FOLDER}/installer/install-here.sh")
    for forbidden in ("cia/", "extracted/", "build/", "server/data/"):
        if any(n.startswith(f"{FOLDER}/{forbidden}") for n in names):
            sys.exit(f"[!] {forbidden} would be in the release")
    if b"\r\n" not in bat or b"\r\n" in sh:
        sys.exit("[!] Install-here.bat needs CRLF line ends and install-here.sh LF ones (.gitattributes)")
    (out / "Install-here.bat").write_bytes(bat)
    (out / "install-here.sh").write_bytes(sh)
    mac = out / "Install-here-macOS.zip"
    with zipfile.ZipFile(mac, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("Install here.command", date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = (0o100755 << 16)                   # executable once unpacked by Finder
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, sh)
    return [archive, out / "Install-here.bat", out / "install-here.sh", mac]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes", default="", help="what changed, for the players (default: the commits' titles)")
    ap.add_argument("--dry-run", action="store_true", help="only build the files in build/release/")
    args = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    head = run("git", "rev-parse", "HEAD")
    assets = build_assets(OUT)
    print(f"[+] {tag} ({head[:7]}): " + ", ".join(f"{p.name} ({p.stat().st_size // 1024} KB)" for p in assets))
    if args.dry_run:
        return

    tool = gh()
    existing = run(tool, "release", "list", "-R", REPO, "--limit", "100", "--json", "tagName", "-q", ".[].tagName",
                   check=False).split()
    if tag in existing:
        sys.exit(f"[!] {tag} is already released: raise VERSION first")
    newer = [t for t in existing if version_key(t) >= version_key(tag)]
    if newer:
        sys.exit(f"[!] {', '.join(newer)} already released: VERSION must be above")
    run("git", "fetch", "-q", "origin")
    if run("git", "branch", "-r", "--contains", head, check=False) == "":
        sys.exit("[!] this commit is not pushed: git push first")
    notes = args.notes
    if not notes:
        previous = max(existing, key=version_key) if existing else None
        notes = run("git", "log", "--format=- %s", f"{previous}..HEAD" if previous else "-20", check=False)
    notes += ("\n\n**Install**: download the installer of your system below (Windows `Install-here.bat`, macOS "
              "`Install-here-macOS.zip`, Linux `install-here.sh`), put it where you want the game's folder, and "
              "open it. Already installed: the launcher offers this version by itself.")
    url = run(tool, "release", "create", tag, *map(str, assets), "-R", REPO, "--target", head,
              "--title", f"Sub Wars Open Sourced {version}", "--notes", notes)
    print(f"[+] {url}")


if __name__ == "__main__":
    main()
