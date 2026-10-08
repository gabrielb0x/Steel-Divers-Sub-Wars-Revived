#!/usr/bin/env python3
"""Decrypts the player's own CIA of Steel Diver: Sub Wars, or of its update, with the decryptor of Batch CIA 3DS
Decryptor Redux.

Azahar and the tools need the game and its update decrypted. An update downloaded as it is from the eShop's
servers, with its ticket, is encrypted twice: by the title key (the CIA layer), then by the NCCH keys. This project
holds no console key: it downloads the decryptor that Batch CIA 3DS Decryptor Redux runs
(https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux, bin/decrypt.exe by davidmorom), pinned to the
version 1.0.6.3 and checked by its SHA-256, into build/decryptor/, and runs it on a copy of the file:

  Windows        directly
  Linux, macOS   with Wine: the Wine installed, when it runs the decryptor (32-bit Windows programs), else a
                 portable Wine downloaded into build/decryptor/ (Linux: Kron4ek's build, macOS: Gcenx's, with
                 Rosetta 2 on Apple silicon), no administrator password needed. The Wine prefix is a temporary
                 one, and the portable Wine is removed once the files are decrypted.

decrypt.exe is a PyInstaller program; under Wine it cannot unpack itself (it gives its temporary folder an access
list that Wine turns into the Unix mode 000: "cannot create temporary directory"), so its libraries are unpacked
here beforehand and passed to it in _MEIPASS2, as its own launcher does. It writes each content decrypted
(<name>.<index>.ncch); they are put back into a CIA with the original certificates, ticket and TMD (content
types and hashes updated), as the batch file does with makerom.

Only the game (00040000000D7E00) and its update (0004000E000D7E00) are accepted. Nothing is sent anywhere: the
only network access is the download of the tools.

    python3 tools/decrypt.py <file.cia>... [-o folder]      decrypted CIAs into cia/ (by default)
    python3 tools/decrypt.py --check                        how it would run on this computer
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import os
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import azahar
from ctr import _SIG_SIZES, CIA, GAME_TITLE_ID, UPDATE_TITLE_ID, program_encrypted

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "decryptor"
OUT_DIR = ROOT / "cia"
TITLES = {GAME_TITLE_ID: "Steel Diver Sub Wars", UPDATE_TITLE_ID: "Steel Diver Sub Wars update"}
NO_CRYPTO = 0x04                                   # NCCH flags[7]


class DecryptError(Exception):
    """A message for the player."""


@dataclass(frozen=True)
class Download:
    name: str
    url: str
    size: int
    sha256: str
    program: str = ""                              # in an archive: the program to run
    skip: tuple[str, ...] = ()                     # in an archive: parts not needed to run it (path fragments)


REDUX = ("https://raw.githubusercontent.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux/"
         "929471b979dd6b73de2d39334e978aa6c95d7e0c")                       # tag v1.0.6.3
DECRYPTOR = Download("decrypt.exe", REDUX + "/bin/decrypt.exe", 5_711_145,
                     "35506bc9c5610cd41c7a6e6c377b01bca30217e61d5b5e4842156120fa9e59a0")
WINE = {
    "linux": Download("wine-11.0-amd64-wow64.tar.xz",
                      "https://github.com/Kron4ek/Wine-Builds/releases/download/11.0/wine-11.0-amd64-wow64.tar.xz",
                      73_144_724, "39574efa1132c3ca0d5c77dd2eddbe4a49cca0d6cc2c290ff4924493a1c40314",
                      "wine-11.0-amd64-wow64/bin/wine", ("/include/", ".a")),
    "darwin": Download("wine-stable-11.0_1-osx64.tar.xz",
                       "https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.0_1/"
                       "wine-stable-11.0_1-osx64.tar.xz",
                       185_303_032, "b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388",
                       "Wine Stable.app/Contents/Resources/wine/bin/wine",
                       ("/share/wine/mono/", "/share/wine/gecko/")),
}
# No Mono or Gecko to install, and no menu entry or file association added to the player's desktop.
WINE_ENV = {"WINEDEBUG": "-all", "WINEDLLOVERRIDES": "mscoree,mshtml=;winemenubuilder.exe=d"}
PYI_MAGIC = b"MEI\014\013\012\013\016"             # end of a PyInstaller archive (its "cookie")


# ---- the files --------------------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def title_of(path: Path) -> tuple[int, int]:
    """(title id, title version) of a CIA of the game or of its update; any other title is refused."""
    if path.suffix.lower() != ".cia":
        raise DecryptError(f"{path.name}: only a .cia is decrypted here (a .3ds or a .cxi must be decrypted "
                           "already: use the game's .cia instead)")
    try:
        with path.open("rb") as f:
            cia = CIA.parse(f)
    except (OSError, struct.error, KeyError, ValueError) as e:
        raise DecryptError(f"{path.name}: not a readable CIA") from e
    if cia.title_id not in TITLES:
        raise DecryptError(f"{path.name} is the title {cia.title_id:016X}: only Steel Diver: Sub Wars (Europe, "
                           f"{GAME_TITLE_ID:016X}) and its update ({UPDATE_TITLE_ID:016X}) are decrypted here")
    return cia.title_id, cia.title_version


def needs_decrypting(path: Path) -> bool:
    """Whether the program of a game file is still encrypted (ctr.program_encrypted)."""
    try:
        return program_encrypted(path)
    except (ValueError, struct.error, KeyError, StopIteration) as e:
        raise DecryptError(f"{path.name}: not a readable game file") from e


def decrypted_name(title_id: int, version: int) -> str:
    return (f"{TITLES[title_id]} v{version} (decrypted).cia" if title_id == UPDATE_TITLE_ID
            else f"{TITLES[title_id]} (decrypted).cia")


def align(x: int, a: int = 64) -> int:
    return (x + a - 1) & ~(a - 1)


def rebuild_cia(src: Path, contents: dict[int, Path], dest: Path) -> None:
    """The CIA src with its contents replaced by the decrypted ones (content index -> NCCH file): the same
    certificate chain, ticket and meta; in the TMD each content loses its "encrypted" type bit and gets the
    size and SHA-256 of its new data, and the info records' hashes are recomputed (its signature then no longer
    matches, which the emulator does not check)."""
    with src.open("rb") as f:
        cia = CIA.parse(f)

        def read(offset: int, size: int) -> bytes:
            f.seek(offset)
            return f.read(size)
        header = bytearray(read(0, cia.header_size))
        certs = read(cia.cert_offset, cia.cert_size)
        ticket = read(cia.ticket_offset, cia.ticket_size)
        tmd = bytearray(read(cia.tmd_offset, cia.tmd_size))
        meta = read(cia.meta_offset, cia.meta_size) if cia.meta_size else b""
    body = 4 + _SIG_SIZES[struct.unpack_from(">I", tmd, 0)[0]]
    info, chunks = body + 0xC4, body + 0xC4 + 64 * 0x24
    count = struct.unpack_from(">H", tmd, body + 0x9E)[0]
    data = []
    for n in range(count):
        at = chunks + n * 0x30
        index, kind = struct.unpack_from(">HH", tmd, at + 4)
        if index not in contents:
            raise DecryptError(f"content {index} is missing from the decrypted files")
        path = contents[index]
        size = path.stat().st_size
        struct.pack_into(">HQ", tmd, at + 6, kind & ~1, size)
        tmd[at + 0x10:at + 0x30] = bytes.fromhex(sha256_of(path))
        data.append((path, size))
    for record in range(64):
        at = info + record * 0x24
        first, number = struct.unpack_from(">HH", tmd, at)
        if number:
            covered = tmd[chunks + first * 0x30:chunks + (first + number) * 0x30]
            tmd[at + 4:at + 0x24] = hashlib.sha256(covered).digest()
    tmd[body + 0xA4:body + 0xC4] = hashlib.sha256(tmd[info:chunks]).digest()
    if [size for _, size in data] != [chunk.size for chunk in cia.contents]:
        struct.pack_into("<Q", header, 0x18, sum(align(size) for _, size in data))

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with part.open("wb") as out:
        for blob in (header, certs, ticket, tmd):
            out.write(blob)
            out.write(bytes(align(out.tell()) - out.tell()))
        for path, size in data:
            with path.open("rb") as f:
                shutil.copyfileobj(f, out, 1 << 20)
            out.write(bytes(align(out.tell()) - out.tell()))
        out.write(meta)
    part.replace(dest)


# ---- the tools ----------------------------------------------------------------------------------------

def download(item: Download, dest: Path, log=print) -> Path:
    """Downloads a file, then checks its size and SHA-256: an interrupted or altered download is refused."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    host = item.url.split("/")[2] if "://" in item.url else item.url
    size = f"{item.size / 1e6:.1f}" if item.size < 10_000_000 else f"{item.size / 1e6:.0f}"
    log(f"Downloading {item.name} ({size} MB, {host})…")
    try:
        request = urllib.request.Request(item.url, headers={"User-Agent": "sub-wars-open-sourced"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
            done, step = 0, 1
            while block := response.read(1 << 20):
                out.write(block)
                done += len(block)
                if item.size > 20_000_000 and done * 10 >= item.size * step:
                    log(f"  {min(100, done * 100 // item.size)} %")
                    step = done * 10 // item.size + 1
    except (OSError, http.client.HTTPException, ValueError) as e:
        curl = shutil.which("curl")                # macOS' python.org builds may lack certificates
        if curl is None or item.url.startswith("file:"):
            part.unlink(missing_ok=True)
            raise DecryptError(f"could not download {item.name}: {e}") from e
        log(f"  ({e}: with curl)")
        result = subprocess.run([curl, "-fL", "--retry", "2", "-o", str(part), item.url], capture_output=True,
                                text=True)
        if result.returncode:
            part.unlink(missing_ok=True)
            raise DecryptError(f"could not download {item.name}: {result.stderr.strip() or e}") from e
    if part.stat().st_size != item.size or sha256_of(part) != item.sha256:
        part.unlink(missing_ok=True)
        raise DecryptError(f"{item.name}: the downloaded file is not the expected one (size or SHA-256), refused")
    part.replace(dest)
    return dest


def local_decryptor(places: list[Path] | None = None) -> tuple[Path, bytes] | None:
    """The same decrypt.exe in a Batch CIA 3DS Decryptor Redux the player already has, unpacked or as its zip
    (where it was found, its bytes): no download then."""
    places = places if places is not None else [ROOT, *azahar.user_folders()]

    def expected(data: bytes) -> bool:
        return len(data) == DECRYPTOR.size and hashlib.sha256(data).hexdigest() == DECRYPTOR.sha256
    for place in places:
        with contextlib.suppress(OSError):
            for exe in sorted(place.glob("Batch*Decryptor*/bin/decrypt.exe")):
                if exe.stat().st_size == DECRYPTOR.size and expected(data := exe.read_bytes()):
                    return exe, data
            for archive in sorted(place.glob("Batch*Decryptor*.zip")):
                with contextlib.suppress(OSError, zipfile.BadZipFile), zipfile.ZipFile(archive) as z:
                    for member in z.infolist():
                        if member.filename.endswith("bin/decrypt.exe") and member.file_size == DECRYPTOR.size:
                            if expected(data := z.read(member)):
                                return archive, data
    return None


def decryptor(log=print) -> Path:
    """decrypt.exe in build/decryptor/: already there, taken from the player's Batch CIA 3DS Decryptor Redux,
    or downloaded from it."""
    exe = TOOLS_DIR / DECRYPTOR.name
    if exe.is_file() and exe.stat().st_size == DECRYPTOR.size and sha256_of(exe) == DECRYPTOR.sha256:
        return exe
    found = local_decryptor()
    if found is not None:
        log(f"Decryptor: the one of {found[0]}")
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(found[1])
        return exe
    log("The decryptor of Batch CIA 3DS Decryptor Redux (decrypt.exe by davidmorom), version 1.0.6.3:")
    return download(DECRYPTOR, exe, log)


def pyinstaller_files(exe: Path, out: Path) -> int:
    """Unpacks what a PyInstaller program unpacks at start-up (its libraries and data) into out; returns their
    number."""
    data = exe.read_bytes()
    at = data.rfind(PYI_MAGIC)
    if at < 0:
        raise DecryptError(f"{exe.name}: not the expected program")
    length, toc, toc_length = struct.unpack_from("!iii", data, at + 8)
    start = at + 88 - length                       # the cookie: magic, 4 numbers, the Python library's name
    pos, end, count = start + toc, start + toc + toc_length, 0
    while pos < end:
        size, offset, packed, _, compressed, kind = struct.unpack_from("!iiiiBc", data, pos)
        name = data[pos + 18:pos + size].rstrip(b"\0").decode("utf-8", "replace")
        pos += size
        if kind not in b"bxZ":
            continue
        parts = name.replace("\\", "/").split("/")
        if not name or name.startswith("/") or ":" in name or ".." in parts:
            raise DecryptError(f"{exe.name}: unexpected entry {name!r}")
        blob = data[start + offset:start + offset + packed]
        dest = out.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zlib.decompress(blob) if compressed else blob)
        count += 1
    return count


def skipped(member: tarfile.TarInfo, skip: tuple[str, ...]) -> bool:
    """Whether skip names an archive member: "/folder/" anywhere in its path, or ".ext" at its end."""
    path = "/" + member.name + ("/" if member.isdir() else "")
    return any(s in path if s.startswith("/") else member.name.endswith(s) for s in skip)


def unpack(archive: Path, dest: Path, skip: tuple[str, ...] = ()) -> None:
    """Unpacks a tar archive into dest, without the parts skip names, refusing paths that leave dest."""
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if not skipped(m, skip)]
        if hasattr(tarfile, "data_filter"):
            try:
                tar.extractall(dest, members=members, filter="data")
            except tarfile.FilterError as e:
                raise DecryptError(f"{archive.name}: {e}") from e
            return
        root = dest.resolve()
        for m in members:                          # Python 3.11 before 3.11.4: the same checks by hand
            target = (dest / m.name).resolve()
            link = (target.parent / m.linkname).resolve() if m.issym() or m.islnk() else root
            if root not in (target, *target.parents) or root not in (link, *link.parents) or m.isdev():
                raise DecryptError(f"{archive.name}: unexpected entry {m.name!r}")
        tar.extractall(dest, members=members)


def platform_key() -> str:
    return "darwin" if sys.platform == "darwin" else "windows" if os.name == "nt" else "linux"


def portable_wine_program() -> Path | None:
    item = WINE.get(platform_key())
    return TOOLS_DIR / "wine" / item.program if item else None


def ensure_rosetta(log=print) -> None:
    """Wine is an Intel program: on Apple silicon it runs with Rosetta 2, installed if needed (macOS asks for
    the password of an administrator)."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return
    if subprocess.run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"], capture_output=True).returncode == 0:
        return
    log("Wine needs Rosetta 2 on this Mac: macOS asks for your password to install it…")
    script = ('do shell script "/usr/sbin/softwareupdate --install-rosetta --agree-to-license" '
              'with administrator privileges')
    subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True)
    if subprocess.run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"], capture_output=True).returncode:
        raise DecryptError("Rosetta 2 is not installed: run \"softwareupdate --install-rosetta\" in the Terminal, "
                           "then try again")


def portable_wine(log=print) -> Path:
    """A portable Wine in build/decryptor/wine/, downloaded if needed (no installation, no password)."""
    key = platform_key()
    item = WINE.get(key)
    machines = {"x86_64", "amd64"} | ({"arm64"} if key == "darwin" else set())
    if item is None or platform.machine().lower() not in machines:
        raise DecryptError(f"no Wine for this computer ({platform.system()} {platform.machine()}): decrypt the "
                           "file on another computer, or with GodMode9 on a console")
    ensure_rosetta(log)
    program = TOOLS_DIR / "wine" / item.program
    if program.is_file():
        return program
    archive = TOOLS_DIR / item.name
    log("No Wine able to run the decryptor on this computer: a portable Wine, removed afterwards.")
    download(item, archive, log)
    log("Unpacking Wine…")
    shutil.rmtree(TOOLS_DIR / "wine", ignore_errors=True)
    try:
        unpack(archive, TOOLS_DIR / "wine", item.skip)
    finally:
        archive.unlink(missing_ok=True)
    if key == "darwin":                            # downloaded here, not by a browser: in case it is flagged
        subprocess.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(TOOLS_DIR / "wine")],
                       capture_output=True)
    if not program.is_file():
        raise DecryptError(f"{item.name}: no {item.program} in it")
    return program


def installed_wines() -> list[Path]:
    """The Wines of this computer: SUBWARS_WINE, Wine's macOS apps, then the one in the PATH."""
    found = []
    if os.environ.get("SUBWARS_WINE"):
        found.append(Path(os.environ["SUBWARS_WINE"]))
    if sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            for app in ("Wine Stable", "Wine Devel", "Wine Staging"):
                found.append(apps / f"{app}.app/Contents/Resources/wine/bin/wine")
        found += [Path("/opt/homebrew/bin/wine"), Path("/usr/local/bin/wine")]
    if shutil.which("wine"):
        found.append(Path(shutil.which("wine")))
    unique = []
    for path in found:
        with contextlib.suppress(OSError):
            if path.is_file() and os.access(path, os.X_OK) and path.resolve() not in [p.resolve() for p in unique]:
                unique.append(path)
    return unique


def ascii_folder() -> Path:
    """A folder whose path is plain ASCII, for the decryptor's files: decrypt.exe runs Python 2.7, whose file
    names go through the system's code page."""
    candidates = [TOOLS_DIR, Path(tempfile.gettempdir())]
    if os.environ.get("PUBLIC"):
        candidates.append(Path(os.environ["PUBLIC"]))       # C:\Users\Public, when the user name is not ASCII
    for folder in candidates:
        with contextlib.suppress(OSError):
            folder.mkdir(parents=True, exist_ok=True)
            if str(folder.resolve()).isascii():
                return folder
    raise DecryptError("no folder with a plain ASCII path for the decryptor")


class Runner:
    """How decrypt.exe runs on this computer: directly on Windows, else with a Wine and a temporary prefix."""

    def __init__(self, wine: Path | None = None, libraries: Path | None = None) -> None:
        self.wine, self.libraries, self.prefix = wine, libraries, None
        if wine is not None:
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            self.prefix = Path(tempfile.mkdtemp(prefix="wineprefix-", dir=TOOLS_DIR))

    def run(self, work: Path, *args: str, timeout: int = 900) -> tuple[int, str]:
        env = dict(os.environ)
        command = [str(work / "decrypt.exe"), *args]
        if self.wine is not None:
            env.update(WINE_ENV, WINEPREFIX=str(self.prefix),
                       _MEIPASS2="Z:" + str(self.libraries.resolve()).replace("/", "\\"))
            for name in ("DISPLAY", "WAYLAND_DISPLAY"):             # a console program: no window
                env.pop(name, None)
            command = [str(self.wine), "decrypt.exe", *args]
        try:
            result = subprocess.run(command, cwd=work, env=env, input=b"\n", capture_output=True, timeout=timeout,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return -1, "the decryptor did not finish in time"
        except OSError as e:
            return -1, str(e)
        text = (result.stdout + b"\n" + result.stderr).decode("utf-8", "replace").replace("\r", "")
        return result.returncode, text

    def works(self, work: Path) -> bool:
        """Whether decrypt.exe starts (it then prints its usage). The first run also creates the prefix."""
        return "usage:" in self.run(work, timeout=600)[1]

    def close(self) -> None:
        if self.prefix is None:
            return
        server = self.wine.parent / "wineserver"
        server = server if server.is_file() else Path(shutil.which("wineserver") or "")
        if server.is_file():
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run([str(server), "-k"], env=dict(os.environ, WINEPREFIX=str(self.prefix)),
                               capture_output=True, timeout=30)
        dosdevices = self.prefix / "dosdevices"   # links to / and the drives: removed first, never followed
        if dosdevices.is_dir():
            for link in dosdevices.iterdir():
                with contextlib.suppress(OSError):
                    if link.is_symlink():
                        link.unlink()
        shutil.rmtree(self.prefix, ignore_errors=True)
        self.prefix = None


def find_runner(work: Path, libraries: Path, log=print) -> tuple[Runner, bool]:
    """A Wine that runs decrypt.exe: one of this computer's, else the portable one (then True)."""
    if platform_key() == "darwin":
        ensure_rosetta(log)
    portable = portable_wine_program()
    for wine in installed_wines():
        if portable is not None and wine.resolve() == portable.resolve():
            continue
        log(f"Wine: {wine} (it prepares itself, a few seconds the first time)…")
        runner = Runner(wine, libraries)
        if runner.works(work):
            return runner, False
        runner.close()
        log("  it cannot run the decryptor (a 32-bit Windows program).")
    wine = portable_wine(log)
    log("Wine: portable (it prepares itself, a few seconds)…")
    runner = Runner(wine, libraries)
    if runner.works(work):
        return runner, True
    runner.close()
    raise DecryptError("Wine does not run the decryptor on this computer: decrypt the file on another computer "
                       "(Windows: python tools/decrypt.py <file>), or with GodMode9 on a console")


def decrypt_one(runner: Runner, work: Path, src: Path, dest: Path, log=print) -> Path:
    title, _ = title_of(src)
    log(f"Decrypting {src.name}…")
    for old in work.glob("title.*"):
        old.unlink()
    shutil.copyfile(src, work / "title.cia")      # a plain name: Python 2.7 and the code page
    code, text = runner.run(work, "title.cia")
    with (work / "title.cia").open("rb") as f:
        cia = CIA.parse(f)
    contents = {}
    for chunk in cia.contents:
        path = work / f"title.{chunk.index}.ncch"
        if not path.is_file():
            tail = " / ".join(line.strip() for line in text.splitlines() if line.strip())[-300:]
            raise DecryptError(f"the decryptor did not write content {chunk.index} of {src.name}"
                               + (f": {tail}" if tail else ""))
        with path.open("rb") as f:
            header = f.read(0x200)
        if header[0x100:0x104] != b"NCCH" or not header[0x18F] & NO_CRYPTO:
            raise DecryptError(f"content {chunk.index} of {src.name} did not come out decrypted")
        if chunk.index == 0 and struct.unpack_from("<Q", header, 0x118)[0] != title:
            raise DecryptError(f"{src.name}: its program is not the title of its TMD")
        contents[chunk.index] = path
    rebuild_cia(work / "title.cia", contents, dest)
    for old in work.glob("title.*"):
        old.unlink()
    if needs_decrypting(dest):
        dest.unlink()
        raise DecryptError(f"{src.name}: still encrypted after the decryptor")
    log(f"Decrypted: {dest}")
    return dest


def decrypt_files(files: list[Path], out_dir: Path = OUT_DIR, log=print) -> list[Path]:
    """Decrypts CIAs of the game or of its update into out_dir; a file already decrypted is returned as it is.
    All of them in one go: one decryptor, one Wine."""
    jobs = []
    for path in files:
        title, version = title_of(path)
        if not needs_decrypting(path):
            jobs.append((path, None))
            continue
        jobs.append((path, out_dir / decrypted_name(title, version)))
    if all(dest is None for _, dest in jobs):
        return [path for path, _ in jobs]
    exe = decryptor(log)
    work = Path(tempfile.mkdtemp(prefix="work-", dir=ascii_folder()))
    runner, portable, done = None, False, []
    try:
        shutil.copyfile(exe, work / "decrypt.exe")
        if platform_key() == "windows":
            runner = Runner()
        else:
            pyinstaller_files(exe, work / "libraries")
            runner, portable = find_runner(work, work / "libraries", log)
        for path, dest in jobs:
            done.append(path if dest is None else decrypt_one(runner, work, path, dest, log))
    finally:
        if runner is not None:
            runner.close()
        shutil.rmtree(work, ignore_errors=True)
    if portable:                                   # only needed for this: its 500 MB are given back
        shutil.rmtree(TOOLS_DIR / "wine", ignore_errors=True)
        log("Portable Wine removed (it is downloaded again if another file needs decrypting).")
    return done


def check(log=print) -> None:
    """How decryption would run here, without running it."""
    exe = TOOLS_DIR / DECRYPTOR.name
    log(f"Decryptor: {'ready, ' + str(exe) if exe.is_file() else 'downloaded when needed (5.7 MB)'}")
    if platform_key() == "windows":
        log("Runs directly (Windows).")
        return
    wines = installed_wines()
    log("Wine of this computer: " + (", ".join(map(str, wines)) if wines else "none"))
    item = WINE.get(platform_key())
    if item:
        log(f"If it cannot run the decryptor: a portable Wine, {item.name} ({item.size / 1e6:.0f} MB), "
            "downloaded then removed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="CIAs of the game or of its update")
    ap.add_argument("-o", "--out", type=Path, default=OUT_DIR, help="where the decrypted CIAs go (default: cia/)")
    ap.add_argument("--check", action="store_true", help="how it would run on this computer")
    args = ap.parse_args()
    if args.check or not args.files:
        check()
        return
    try:
        for path in decrypt_files(args.files, args.out):
            print(f"[+] {path}")
    except (DecryptError, OSError) as e:
        sys.exit(f"[!] {e}")


if __name__ == "__main__":
    main()
