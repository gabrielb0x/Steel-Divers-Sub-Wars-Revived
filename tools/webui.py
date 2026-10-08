"""The players' launcher: a page in the web browser, served by this computer to itself only.

    python3 subwars.py            (at the root of the project)

Everything the command-line tools do, with buttons: extract the game, prepare it for Azahar, build and
install mods (premium, cheats, characteristics, online), edit the save and the characteristics of the
submarines, start an online server. Standard library only, so that it runs anywhere Python 3.11 does.

The server listens on 127.0.0.1 and answers the API only with the random token of the page it served, and
only to requests addressed to 127.0.0.1 or localhost (no other site, no DNS rebinding).
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import azahar
import extract_cia
import bcstm
import mod
import music
import save
import subs
import versions
from ctr import CIA, GAME_TITLE_ID, UPDATE_TITLE_ID

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).with_name("webui.html")
EXTRACTED = ROOT / "extracted"
MODS_OUT = ROOT / "build" / "mods"
PREPARED = ROOT / "build" / "azahar"
MOD_ORDER = ["fixes", "nickname", "version", "premium", "missions", "specs", "cheats", "speed", "music",
             "online"]
STATE_FILE = "launcher.json"
OLD_STATE_FILE = "lanceur.json"            # its name before the project went English


class UserError(Exception):
    """A message for the player."""


# The tools, in import order. The launcher keeps running while the project is updated (git pull, a new
# version unpacked over it): their code is reloaded when their files change, between two tasks.
TOOL_MODULES = ["ctr", "ncch", "armasm", "bxml", "amx", "versions", "azahar", "extract_cia", "save", "subs", "bcstm",
                "music", "mod"]
TOOLS = Path(__file__).resolve().parent


class CodeWatcher:
    def __init__(self) -> None:
        self.tools = self._stamp(TOOLS / f"{name}.py" for name in TOOL_MODULES)
        self.launcher = self._stamp([Path(__file__), ROOT / "subwars.py"])

    @staticmethod
    def _stamp(paths) -> tuple:
        return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in paths)

    def refresh(self) -> bool:
        """Reloads the tools if one of them changed; True when it did."""
        now = self._stamp(TOOLS / f"{name}.py" for name in TOOL_MODULES)
        if now == self.tools:
            return False
        for name in TOOL_MODULES:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        self.tools = now
        return True

    def outdated(self) -> bool:
        """The launcher itself changed: only a restart takes it into account."""
        return self._stamp([Path(__file__), ROOT / "subwars.py"]) != self.launcher


class ThreadOutput(io.TextIOBase):
    """sys.stdout that each thread can send somewhere else (the tools print their progress): unlike
    contextlib.redirect_stdout, concurrent requests do not swap each other's output."""

    def __init__(self, default) -> None:
        self.default = default
        self.local = threading.local()

    def _target(self):
        return getattr(self.local, "target", None) or self.default

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        self._target().flush()

    @contextlib.contextmanager
    def to(self, target):
        previous = getattr(self.local, "target", None)
        self.local.target = target
        try:
            yield target
        finally:
            self.local.target = previous


def captured(target):
    """Context manager: what this thread prints goes to target."""
    if not isinstance(sys.stdout, ThreadOutput):
        sys.stdout = ThreadOutput(sys.stdout)
    return sys.stdout.to(target)


# ---- background tasks ----------------------------------------------------------------------------

class Task:
    def __init__(self, title: str) -> None:
        self.id = secrets.token_hex(4)
        self.title = title
        self.lines: list[str] = []
        self.done = False
        self.error: str | None = None
        self.result = None

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.lines.append(line)
        return len(text)

    def flush(self) -> None:
        pass

    def json(self) -> dict:
        return {"id": self.id, "title": self.title, "lines": self.lines[-400:], "done": self.done,
                "error": self.error, "result": self.result}


class Tasks:
    """One task at a time: the tools print their progress, which goes to the task (stdout redirected)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current: Task | None = None
        self.known: dict[str, Task] = {}

    def start(self, title: str, work) -> Task:
        with self.lock:
            if self.current and not self.current.done:
                raise UserError(f"A task is already running: {self.current.title}")
            task = Task(title)
            self.current = task
            self.known[task.id] = task

        def run() -> None:
            with captured(task):
                try:
                    task.result = work(task.write)
                except SystemExit as e:              # the tools exit with a message
                    task.error = str(e.code) if e.code not in (None, 0) else None
                except (UserError, mod.ModError, save.SaveError, subs.SubsError, extract_cia.ExtractError,
                        music.MusicError, bcstm.BcstmError, OSError, ValueError, KeyError,
                        tomllib.TOMLDecodeError) as e:
                    task.error = str(e)
                except Exception as e:                # a bug: keep the traceback for the report
                    task.write(traceback.format_exc())
                    task.error = f"unexpected error: {e}"
                finally:
                    task.done = True
        threading.Thread(target=run, daemon=True).start()
        return task


# ---- the online server, as a child process --------------------------------------------------------

SERVER_DIR = ROOT / "server"
SERVER_STATE = SERVER_DIR / "data" / "server.json"        # written by the server while it runs


def server_command(cmdline: str) -> bool:
    """A command line that runs our online server (python -m sdsw_server)."""
    return "sdsw_server" in cmdline and "testclient" not in cmdline


def udp_port_owners(ports: set[int]) -> dict[int, str]:
    """pid -> command line of the processes that have one of these UDP ports open, as far as this user can
    see them ({} when the system does not tell)."""
    try:
        if sys.platform.startswith("linux"):
            return _owners_linux(ports)
        if sys.platform == "darwin":
            return _owners_lsof(ports)
        if sys.platform.startswith("win"):
            return _owners_windows(ports)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {}


def _owners_linux(ports: set[int]) -> dict[int, str]:
    inodes = set()
    for table in ("/proc/net/udp", "/proc/net/udp6"):
        with contextlib.suppress(OSError):
            for line in Path(table).read_text().splitlines()[1:]:
                fields = line.split()
                if len(fields) > 9 and int(fields[1].rsplit(":", 1)[1], 16) in ports:
                    inodes.add(f"socket:[{fields[9]}]")
    owners = {}
    if not inodes:
        return owners
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        with contextlib.suppress(OSError):
            if any(os.readlink(fd) in inodes for fd in (proc / "fd").iterdir()):
                owners[int(proc.name)] = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                    "utf-8", "replace").strip()
    return owners


def _owners_lsof(ports: set[int]) -> dict[int, str]:
    args = ["lsof", "-nP", "-t"] + [f"-iUDP:{port}" for port in sorted(ports)]
    pids = {int(line) for line in subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.split()}
    return {pid: subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                                timeout=10).stdout.strip() for pid in pids}


def _owners_windows(ports: set[int]) -> dict[int, str]:
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    table = subprocess.run(["netstat", "-ano", "-p", "UDP"], capture_output=True, text=True, timeout=15,
                           creationflags=hidden).stdout
    pids = set()
    for line in table.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == "UDP" and fields[1].rsplit(":", 1)[-1].isdigit():
            if int(fields[1].rsplit(":", 1)[1]) in ports and fields[-1].isdigit():
                pids.add(int(fields[-1]))
    owners = {}
    for pid in pids:
        query = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
        owners[pid] = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True,
                                     text=True, timeout=20, creationflags=hidden).stdout.strip()
    return owners


def busy_udp_ports(ports: list[int]) -> list[int]:
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                busy.append(port)
    return busy


class GameServer:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.lines: deque[str] = deque(maxlen=500)
        self._others: tuple[float, dict[int, str]] = (0.0, {})

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        """Starts the server, after stopping the one already running: ours (a restart), or one started
        elsewhere (an earlier launcher, a terminal) that holds its ports."""
        if sys.version_info < (3, 11):
            raise UserError("the server needs Python 3.11 or newer")
        self.lines.clear()
        if self.running:
            self.lines.append("[restarting the server]")
            self.stop()
        self.stop_others()
        self.process = subprocess.Popen([sys.executable, "-u", "-m", "sdsw_server", "-c", "server.toml",
                                         "--exit-with-stdin"],
                                        cwd=SERVER_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                        env=os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def stop_others(self, strict: bool = True) -> None:
        """Stops the servers started elsewhere (an earlier launcher, a terminal) that hold our ports. When
        another program holds one, strict refuses to go on."""
        ports = self.ports()
        busy = busy_udp_ports(ports)
        if not busy:
            return
        owners = udp_port_owners(set(busy))
        others = {pid: cmd for pid, cmd in owners.items() if not server_command(cmd)}
        if strict and (others or not owners):
            who = ", ".join(f"{(cmd.split() or ['?'])[0]} (PID {pid})" for pid, cmd in others.items())
            raise UserError(f"UDP port {busy[0]} is taken by another program"
                            + (f": {who}. Close it" if who else ", not found. Close the program that holds it")
                            + ", or change the ports in server.toml.")
        servers = [pid for pid in owners if pid not in others]
        for pid in servers:
            self.lines.append(f"[server started elsewhere (PID {pid}): stopped]")
            try:
                os.kill(pid, signal.SIGTERM)               # Windows: TerminateProcess
            except ProcessLookupError:
                pass
            except PermissionError:
                raise UserError(f"A server started by another user (PID {pid}) holds UDP port "
                                f"{busy[0]}: stop it from their account.") from None
        self._others = (0.0, {})
        if not servers or self._wait_free(ports, 2 if others else 8):    # others: some ports stay busy
            return
        for pid in servers:                                # it did not stop cleanly
            with contextlib.suppress(OSError):
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        if not self._wait_free(ports, 4) and strict:
            raise UserError(f"The server already running (PID {', '.join(map(str, servers))}) does not stop.")

    @staticmethod
    def _wait_free(ports: list[int], seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while busy_udp_ports(ports):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)
        return True

    def others(self) -> dict[int, str]:
        """Servers started elsewhere that hold our ports (checked every few seconds: on Windows and macOS,
        finding them starts programs)."""
        if self.running:
            return {}
        if time.monotonic() - self._others[0] > (3 if sys.platform.startswith("linux") else 10):
            busy = busy_udp_ports(self.ports())
            owners = udp_port_owners(set(busy)) if busy else {}
            self._others = (time.monotonic(), {pid: cmd for pid, cmd in owners.items() if server_command(cmd)})
        return self._others[1]

    def _read(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            self.lines.append(line.rstrip())
        self.lines.append(f"[server stopped, code {process.wait()}]")

    def stop(self) -> None:
        """Closing its standard input stops the server cleanly (it removes its forwards on the router)."""
        if self.running:
            with contextlib.suppress(OSError):
                self.process.stdin.close()
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    self.process.kill()

    @staticmethod
    def config() -> dict:
        try:
            return tomllib.loads((SERVER_DIR / "server.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    @classmethod
    def ports(cls) -> list[int]:
        """UDP ports the server will open: each realm's two, and the NAT check's (fixed by the game)."""
        data = cls.config()
        if not data:
            return [61000, 61001, 10025, 10125]
        ports = [int(r[k]) for r in data.get("realm", []) for k in ("auth_port", "secure_port") if k in r]
        return ports + ([10025, 10125] if data.get("server", {}).get("nat_check", True) else [])

    def state(self, pids: set[int]) -> dict | None:
        """The state file of the running server (public address, router forwards), when it is one of pids
        (or their child: the python.exe of a Windows virtual environment starts the real one)."""
        with contextlib.suppress(OSError, ValueError):
            state = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
            if state.get("pid") in pids or state.get("ppid") in pids:
                return state
        return None

    def json(self) -> dict:
        data = self.config()
        realms = [{"name": r.get("name"), "auth_port": r.get("auth_port"), "cheats": r.get("cheats", "separate"),
                   "max_players": r.get("max_players", 8), "duration": r.get("duration", 10),
                   "bots": r.get("bots", True),
                   "bots_delay": r.get("bots_delay", 60), "bots_format": r.get("bots_format", "4v4"),
                   "bots_level": r.get("bots_level", "hard")} for r in data.get("realm", [])]
        settings = data.get("server", {})
        try:
            status_port = int(settings.get("status_port", 0))
        except ValueError:
            status_port = 0
        others = self.others()
        pids = ({self.process.pid} if self.running else set()) | set(others)
        return {"running": self.running, "lines": list(self.lines)[-200:], "addresses": local_addresses(),
                "config": str(SERVER_DIR / "server.toml"), "realms": realms,
                "public_setting": str(settings.get("public_address", "auto")), "upnp": bool(settings.get("upnp")),
                "others": [{"pid": pid, "command": cmd} for pid, cmd in others.items()],
                "state": self.state(pids),
                "status_page": f"http://127.0.0.1:{status_port}/" if status_port else None}


def server_package():
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    from sdsw_server import config
    return config


def map_names() -> dict[str, str]:
    """Names of the battle maps (number -> name), from the player's own game texts, when available."""
    names = {}
    with contextlib.suppress(OSError, ValueError, ImportError):
        import xml.etree.ElementTree as ET
        from bxml import Bxml
        text = EXTRACTED / "v5200" / "romfs" / "text" / "EU_English.bxml"       # the update names its maps too
        if not text.is_file():
            text = EXTRACTED / "romfs" / "text" / "EU_English.bxml"
        root = ET.fromstring(Bxml(text.read_bytes()).to_xml())
        for node in root.iter("string"):
            key = node.get("key", "")
            if key.startswith("stage_multi_") and key[12:].isdigit():
                names[str(int(key[12:]))] = node.get("text", "")
    return names


def server_config() -> dict:
    config = server_package()
    path = SERVER_DIR / "server.toml"
    try:
        options = config.read(path)
    except (OSError, ValueError) as e:
        raise UserError(f"server.toml illisible : {e}") from e
    return {"options": options, "schema": config.schema(), "maps": map_names(), "file": str(path)}


def save_server_config(changes: dict) -> dict:
    config = server_package()
    try:
        config.update(SERVER_DIR / "server.toml", changes)
    except config.ConfigError as e:
        raise UserError(str(e)) from e
    return server_config()


def test_server(address: str) -> dict:
    """From this computer, does a server answer? (what the game does before logging in)"""
    host, _, port = address.strip().partition(":")
    if not host:
        raise UserError("Enter the server's address.")
    if len(host) > 31:
        raise UserError("Address too long: the online mod takes 31 characters at most.")
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    from sdsw_server.testclient import probe
    result = probe(host, int(port) if port.isdigit() else 61000)
    return result | {"host": host, "port": int(port) if port.isdigit() else 61000}


def local_addresses() -> list[str]:
    """This computer's addresses on the local network (to give to friends playing on it)."""
    found = []
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))              # no packet is sent: only picks the outgoing interface
            found.append(s.getsockname()[0])
    with contextlib.suppress(OSError):
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if address not in found and not address.startswith("127."):
                found.append(address)
    return found


# ---- state ---------------------------------------------------------------------------------------

def load_state() -> dict:
    with contextlib.suppress(OSError, ValueError):
        state = json.loads(azahar.settings_file(STATE_FILE, OLD_STATE_FILE).read_text(encoding="utf-8"))
        installed = state.get("installed")
        if installed and installed.get("mods"):              # the mods' older (French) names
            installed["mods"] = [mod.canonical(n) for n in installed["mods"]]
            installed["params"] = {mod.PARAM_ALIASES.get(k, k): v for k, v in (installed.get("params") or {}).items()}
        return state
    return {}


def store_state(**values) -> None:
    state = load_state() | values
    path = azahar.settings_file(STATE_FILE, OLD_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def game_state() -> dict:
    manifest = None
    with contextlib.suppress(OSError, ValueError):
        manifest = json.loads((EXTRACTED / "manifest.json").read_text())
    ready = bool(manifest) and (EXTRACTED / "romfs").is_dir() and (EXTRACTED / "code.bin").exists()
    state = load_state()
    found = None
    with contextlib.suppress(OSError):
        found = extract_cia.find_game()
    source = state.get("source")
    return {"ready": ready, "product": manifest.get("product_code") if manifest else None,
            "source_name": manifest.get("source", {}).get("file") if manifest else None,
            "source": source, "found": str(found) if found else None,
            "prepared": (PREPARED / "SteelDiverSubWars_original.cia").exists(),
            "prepared_dir": str(PREPARED), "title_id": f"{GAME_TITLE_ID:016X}",
            "versions": versions.extracted_versions(), "update": update_state()}


def update_state() -> dict:
    """The update of the game: where it is (cia/ or an emulator), whether it is decrypted and extracted."""
    found = None
    with contextlib.suppress(OSError):
        found = extract_cia.find_update()
    version, encrypted, cia = None, False, False
    if found is not None:
        with contextlib.suppress(OSError, struct.error, KeyError, extract_cia.ExtractError):
            if found.suffix.lower() == ".cia":
                cia = True
                with found.open("rb") as f:
                    parsed = CIA.parse(f)
                version = versions.name(parsed.title_version)
                encrypted = next(parsed.content_offsets())[0].encrypted
            else:
                version = versions.name(extract_cia.update_version(found, None))
    return {"found": str(found) if found else None, "name": found.name if found else None, "cia": cia,
            "version": version, "encrypted": encrypted,
            "extracted": [v for v in versions.extracted_versions() if v != versions.BASE],
            "label": versions.label(version) if version else None}


def emulator_state() -> dict:
    found = azahar.emulator_dirs()
    dirs = [path for _, path in found]
    mods = [d / "load" / "mods" / azahar.TITLE_ID for d in dirs]
    installed = load_state().get("installed") if any(m.exists() for m in mods) else None
    emulators = []
    for name, base in found:
        version = versions.emulator_version(base)
        marker = azahar.installed_mods(base)
        built = marker.get("version", versions.BASE) if marker is not None else None   # no marker: before v5200
        emulators.append({"name": name, "dir": str(base), "version": version, "label": versions.label(version),
                          "mods": marker.get("mods") if marker else None, "mods_version": built,
                          "stale": built is not None and built != version})
    return {"dirs": [str(d) for d in dirs], "names": [name for name, _ in found],
            "mods_dir": str(mods[0]) if mods else None,
            "mods_installed": any(m.exists() for m in mods), "installed": installed,
            "saves": [str(p) for p in azahar.save_files()], "emulators": emulators,
            "versions": sorted({e["version"] for e in emulators}, key=lambda v: int(v[1:]))}


def mods_list() -> list[dict]:
    out = []
    for recipe in mod.MODS.glob("*/mod.toml"):
        data = tomllib.loads(recipe.read_text(encoding="utf-8"))
        if data.get("hidden"):
            continue
        params = []
        for key, spec in data.get("params", {}).items():
            default = str(spec.get("default", ""))
            kind = "choice" if "choices" in spec else "bool" if default.lower() in mod.YES | mod.NO else "text"
            params.append({"key": key, "help": spec.get("help", ""), "default": default, "kind": kind,
                           "choices": [str(c) for c in spec.get("choices", [])]})
        out.append({"id": recipe.parent.name, "name": data.get("name", recipe.parent.name),
                    "description": data.get("description", ""), "params": params,
                    "flags": data.get("token_flags", []), "online": "identity" in data,
                    "always": bool(data.get("always")), "versions": mod.recipe_versions(data)})
    rank = {name: i for i, name in enumerate(MOD_ORDER)}
    return sorted(out, key=lambda m: (rank.get(m["id"], len(rank)), m["id"]))


# ---- actions -------------------------------------------------------------------------------------

def extract_game(source: Path, log) -> dict:
    if not source.exists():
        raise UserError(f"{source}: file not found")
    print(f"Extracting {source}…")
    manifest = extract_cia.extract(source, log=print)
    if manifest["version"] == versions.BASE:
        store_state(source=str(source))
        update = extract_cia.find_update()
        if update is not None:
            print(f"Update found: {update}")
            try:
                extract_cia.extract(update, log=print)
            except extract_cia.ExtractError as e:          # encrypted: the game itself is ready anyway
                print(f"[!] {e}")
    print("The game's files are ready.")
    return {"product": manifest["product_code"], "version": manifest["version"]}


def decrypted_update() -> Path | None:
    """The decrypted CIA of the update in cia/, if any."""
    update = extract_cia.find_update()
    if update is None or update.suffix.lower() != ".cia":
        return None
    with update.open("rb") as f:
        return None if next(CIA.parse(f).content_offsets())[0].encrypted else update


def prepare_for_azahar(source: Path, log) -> dict:
    if source.suffix.lower() != ".cia":
        raise UserError("Only a .cia needs preparing: a .cxi or a .3ds opens as it is in "
                        "Azahar (File > Load File).")
    PREPARED.mkdir(parents=True, exist_ok=True)
    update = decrypted_update()
    print("Copying the game without the encrypted manual (Azahar refuses the whole eShop CIA), and as a .cxi"
          + (", and the update alone" if update else "") + "…")
    for path in azahar.prepare(source, PREPARED, update):
        print(f"  {path.name}")
    print(f"Ready: {PREPARED}")
    return {"dir": str(PREPARED)}


def build_mods(names: list[str], params: dict[str, str], install: bool, log) -> dict:
    names = [name for name in names if name not in mod.fixes()]     # always part of the build
    if not names and not mod.fixes():
        raise UserError("Choose at least one mod.")
    if not (EXTRACTED / "code.bin").exists():
        raise UserError("Prepare the game's files first (Game tab).")
    targets = mod.emulator_versions()                  # the version each emulator runs the game as
    if install and not targets:
        raise UserError("No emulator found (Azahar, Lime3DS, Citra, Borked3DS): start it once, "
                        "then try again.")
    targets = targets or {versions.BASE: []}
    problems = []
    for version in targets:
        if version not in versions.extracted_versions():
            problems.append(f"The game runs as {versions.label(version)} in the emulator, but the files of "
                            "this version are not prepared: Game tab, with the decrypted update in "
                            "cia/.")
        for name in names:
            recipe = mod.load_recipe(name)
            if not mod.supports(recipe, version):
                problems.append(mod.unsupported(name, recipe, version))
    if problems:
        raise UserError(" ".join(problems))
    result = {"built": [], "installed": []}
    for version, bases in sorted(targets.items()):
        built = mod.build(names, MODS_OUT, params, version=version)
        result["built"].append(str(built))
        if install:
            for base in bases:                         # every emulator of this computer gets the mod
                dest = base / "load" / "mods" / azahar.TITLE_ID
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(built / azahar.TITLE_ID, dest)
                print(f"Installed ({version}): {dest}")
                result["installed"].append(str(dest))
    if install:
        public = dict(mod.build.options) | {"sdsw_version": mod.build.params["sdsw_version"]}   # the player's options
        store_state(installed={"mods": names or mod.fixes(), "params": public,
                               "date": time.strftime("%Y-%m-%d %H:%M")})
        print("Start (or restart) the game in the emulator: the mod applies at start-up.")
    return result


def uninstall_mods() -> dict:
    dirs = azahar.azahar_dirs()
    removed = []
    for base in dirs:
        dest = base / "load" / "mods" / azahar.TITLE_ID
        if dest.exists():
            shutil.rmtree(dest)
            removed.append(str(dest))
    store_state(installed=None)
    return {"removed": removed}


def drop_stale_mods(version: str) -> list[str]:
    """After the update was installed or removed: the mods built for the other version would break the game
    (their code patch no longer matches): they are removed, to be installed again."""
    dropped = []
    for name, base in azahar.emulator_dirs():
        marker = azahar.installed_mods(base)
        if marker is not None and marker.get("version", versions.BASE) != version:
            shutil.rmtree(base / "load" / "mods" / azahar.TITLE_ID)
            dropped.append(name)
            print(f"Mods removed from {name}: built for {marker.get('version', versions.BASE)}, they do not "
                  f"work with {versions.label(version)}. Install them again (Mods tab).")
    if dropped and not any(azahar.installed_mods(base) is not None for base in azahar.azahar_dirs()):
        store_state(installed=None)
    return dropped


def install_update(log) -> dict:
    update = decrypted_update()
    if update is None:
        raise UserError("No decrypted CIA of the update in cia/: put yours there (decrypted), or "
                        "install it yourself into Azahar (File > Install CIA).")
    found = azahar.emulator_dirs()
    if not found:
        raise UserError("No emulator found (Azahar, Lime3DS, Citra, Borked3DS): start it once.")
    with update.open("rb") as f:
        version = versions.name(CIA.parse(f).title_version)
    if version not in versions.extracted_versions():
        print("Extracting its files (the mods need them)…")
        extract_cia.extract(update, log=print)
    for name, base in found:
        print(f"Update {version} installed for {name}: {azahar.install_update(update, base)}")
    drop_stale_mods(version)
    print("The game, installed or opened from its .cxi, now starts with the update.")
    return {"version": version}


def uninstall_update(log) -> dict:
    removed = []
    for name, base in azahar.emulator_dirs():
        for path in azahar.uninstall_update(base):
            print(f"Update removed from {name}: {path}")
            removed.append(str(path))
    if not removed:
        raise UserError("The update is not installed in any emulator.")
    drop_stale_mods(versions.BASE)
    return {"removed": removed}


def save_file(query: dict) -> Path:
    path = query.get("file")
    try:
        return save.find_save(Path(path) if path else None)
    except save.SaveError as e:
        raise UserError(str(e)) from e


def save_summary(path: Path) -> dict:
    data = save.SaveData.parse(path.read_bytes())
    version = save.save_version(path, data)
    texts = save.game_texts(version=version)
    unlocked = data.unlocked_subs(version)
    patterns = data.array("save.sub.pattern.unlock", save.PATTERNS)
    patterns[0] = 1
    crew, crew_total = data.crew_unlocked(version)
    name = bytes(v & 0xFF for v in data.arrays.get("save.sub.filteredname", [])).split(b"\0")[0]
    typenum = data.ints.get("save.sub.typenum", 1)
    missions = [[{"medal": data.medal(s, l), "time": data.best_time(s, l)} for l in range(1, save.LEVELS + 1)]
                for s in range(1, save.STAGES + 1)]
    online = {k: data.ints.get(f"save.multi.{k}", 0) for k in
              ("games", "wins", "losses", "ties", "quits", "points", "kills", "killed", "hits", "shots")}
    return {"file": str(path), "version": data.version, "player": name.decode("utf-8", "replace"),
            "game": version, "game_label": versions.label(version), "paid": save.PAID_SUBS[save.layout(version)],
            "typenum": typenum, "sub_name": save.sub_name(texts, typenum - 1, version),
            "subs": [{"n": i + 1, "name": save.sub_name(texts, i, version), "unlocked": flag}
                     for i, flag in enumerate(unlocked)],
            "patterns": sum(1 for p in patterns if p), "patterns_total": save.PATTERNS,
            "crew": crew, "crew_total": crew_total, "missions": missions,
            "gold": sum(m["medal"] >= save.MEDAL_GOLD for row in missions for m in row),
            "online": online, "premium_flag": bool(data.ints.get("save.sub.enlist")),
            "values": len(data.ints) + len(data.arrays)}


def edit_save(path: Path, change) -> dict:
    data = save.SaveData.parse(path.read_bytes())
    out = io.StringIO()
    with captured(out):
        message = change(data, save.save_version(path, data))
        save.write(path, data)
    return {"message": message, "log": out.getvalue(), "summary": save_summary(path)}


def subs_state() -> dict:
    version = azahar.game_version()
    try:
        game = subs.game_values(version)
    except subs.SubsError as e:
        raise UserError(str(e)) from e
    names = subs.names(version)
    path = subs.default_file(version)
    mine = subs.read_file(path, len(game)) if path.exists() else {}
    return {"file": str(path), "exists": path.exists(), "version": version, "label": versions.label(version),
            "fields": [{"key": f.key, "kind": f.kind.__name__, "low": f.low, "high": f.high, "help": f.help,
                        "advanced": f.advanced, "short": subs.SHORT.get(f.key, f.key)} for f in subs.FIELDS],
            "subs": [{"n": n, "name": names[n], "game": game[n], "mine": {**game[n], **mine.get(n, {})}}
                     for n in sorted(game)]}


def subs_write(update) -> dict:
    version = azahar.game_version()
    game = subs.game_values(version)
    path = subs.default_file(version)
    current = subs.read_file(path, len(game)) if path.exists() else {}
    values = {n: {**game[n], **current.get(n, {})} for n in game}
    update(values, game)
    subs.write_file(path, values, subs.names(version))
    return subs_state()


# ---- music ---------------------------------------------------------------------------------------

MUSIC_CACHE = ROOT / "build" / "cache" / "music"        # the game's music decoded, to listen to it
MAX_UPLOAD = 200 * 1024 * 1024


class Binary:
    """An answer that is not JSON: a file for the page (audio)."""

    def __init__(self, data: bytes, kind: str) -> None:
        self.data, self.kind = data, kind


def music_game() -> versions.GameFiles:
    version = azahar.game_version()
    if version not in versions.extracted_versions():
        version = versions.BASE
    game = versions.game_files(version)
    if not game.ready():
        raise UserError("Prepare the game's files first (Game tab).")
    return game


def music_track(game: versions.GameFiles, file: str) -> dict:
    for track in music.tracks(game):
        if track["file"] == file:
            return track
    raise UserError("unknown music")


def music_state() -> dict:
    game = music_game()
    folder = music.default_dir()
    mine = music.replaced(folder)
    out = []
    for track in music.tracks(game, map_names()):
        with game.path(f"{music.STREAMS}/{track['file']}").open("rb") as f:
            head = bcstm.read(f.read(0x1000))                # the header: rate, channels, length
        out.append(track | {"rate": head.rate, "channels": head.channels, "seconds": round(head.seconds, 1),
                            "mine": mine.get(track["stem"])})
    installed = (load_state().get("installed") or {}).get("mods") or []
    return {"folder": str(folder), "version": game.version, "label": versions.label(game.version), "tracks": out,
            "count": len(mine), "installed": "music" in installed}


def music_audio(file: str, which: str) -> Binary:
    game = music_game()
    track = music_track(game, file)
    if which == "mine":
        folder = music.default_dir()
        if not music.mine(folder, track).exists():
            raise UserError("no music of yours for this one")
        channels, rate = music.leveled(folder, track)          # as the game will play it
        out = io.BytesIO()
        bcstm.write_wav(out, channels, rate)
        return Binary(out.getvalue(), "audio/wav")
    cached = MUSIC_CACHE / f"{track['stem']}.wav"
    if not cached.exists():
        stream = music.original(game, track)
        cached.parent.mkdir(parents=True, exist_ok=True)
        part = cached.with_suffix(".part")
        bcstm.write_wav(part, bcstm.decode(stream), stream.rate)
        part.replace(cached)
    return Binary(cached.read_bytes(), "audio/wav")


def music_apply(log) -> dict:
    """Builds and installs the mods installed so far, with the music mod when there is music of yours (and
    without it when there is none)."""
    installed = load_state().get("installed") or {}
    names = [n for n in installed.get("mods") or [] if n not in mod.fixes() and n != "music"]
    if music.replaced(music.default_dir()):
        names.append("music")
        print(f"Your music: {len(music.replaced(music.default_dir()))}")
    else:
        print("No music of yours: the game's.")
    if not names and not installed.get("mods"):
        print("No mod installed so far: only the fixes.")
    params = {str(k): str(v) for k, v in (installed.get("params") or {}).items() if k != "sdsw_version"}
    return build_mods(names, params, True, log)


# ---- HTTP ----------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server: "LauncherServer"

    def log_message(self, format: str, *args) -> None:       # quiet: the console is for the player
        pass

    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _allowed(self) -> bool:
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}")

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        if not self._allowed():
            self._send(403, b"forbidden", "text/plain")
            return
        url = urlparse(self.path)
        if method == "GET" and url.path in ("/", "/index.html"):
            page = PAGE.read_text(encoding="utf-8").replace("{{TOKEN}}", self.server.token)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if not url.path.startswith("/api/"):
            self._send(404, b"not found", "text/plain")
            return
        if not secrets.compare_digest(self.headers.get("X-Token", ""), self.server.token):
            self._json(403, {"error": "invalid token: reload the page"})
            return
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        body = {}
        if method == "POST" and self.headers.get("Content-Type", "").startswith("application/octet-stream"):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                self._json(413, {"error": "file too large"})
                return
            body = {"raw": self.rfile.read(length)}
        elif method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except ValueError:
                    self._json(400, {"error": "unreadable request"})
                    return
        try:
            result = self.server.api(method, url.path[5:], query, body)
            if isinstance(result, Binary):
                self._send(200, result.data, result.kind)
            else:
                self._json(200, result)
        except UserError as e:
            self._json(400, {"error": str(e)})
        except (save.SaveError, subs.SubsError, extract_cia.ExtractError, mod.ModError, music.MusicError,
                bcstm.BcstmError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"unexpected error: {e}"})


class LauncherServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.port = self.server_address[1]
        self.token = secrets.token_urlsafe(24)
        self.tasks = Tasks()
        self.game_server = GameServer()
        self.code = CodeWatcher()

    def api(self, method: str, route: str, query: dict, body: dict):
        key = f"{method} {route}"
        if not (self.tasks.current and not self.tasks.current.done):     # never in the middle of a task
            self.code.refresh()
        if key == "GET state":
            return {"game": game_state(), "emulator": emulator_state(), "mods": mods_list(),
                    "task": self.tasks.current.json() if self.tasks.current else None,
                    "server": {"running": self.game_server.running}, "restart": self.code.outdated()}
        if route.startswith("task/") and method == "GET":
            task = self.tasks.known.get(route[5:])
            if task is None:
                raise UserError("unknown task")
            return task.json()
        if key == "GET files":
            return list_files(query.get("dir"))
        if key == "POST game/extract":
            source = Path(body.get("path") or "").expanduser() if body.get("path") else extract_cia.find_game()
            if source is None:
                raise UserError("Game not found in cia/ or in Azahar: choose its file.")
            return self.tasks.start("Prepare the game's files", lambda log: extract_game(source, log)).json()
        if key == "POST game/prepare":
            source = load_state().get("source")
            source = Path(source) if source else extract_cia.find_game()
            if source is None:
                raise UserError("Choose the game's file first.")
            return self.tasks.start("Prepare the game for Azahar", lambda log: prepare_for_azahar(source, log)).json()
        if key == "POST mods/build":
            names = [str(n) for n in body.get("mods", [])]
            params = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
            install = bool(body.get("install", True))
            title = ("Install: " if install else "Build: ") + " + ".join(names)
            return self.tasks.start(title, lambda log: build_mods(names, params, install, log)).json()
        if key == "POST mods/uninstall":
            return uninstall_mods()
        if key == "POST update/install":
            return self.tasks.start("Install the update into the emulator", install_update).json()
        if key == "POST update/uninstall":
            return self.tasks.start("Remove the update from the emulator", uninstall_update).json()
        if key == "GET save":
            return save_summary(save_file(query))
        if key == "POST save/unlock":
            what = set(body.get("what") or [])
            colours = save.default_pattern_colours()

            def change(data: save.SaveData, version: str) -> str:
                done = []
                if "subs" in what:
                    done.append(f"{data.unlock_subs(version)} submarine(s)")
                if "patterns" in what:
                    done.append(f"{data.unlock_patterns(colours)} pattern(s)")
                if "crew" in what:
                    done.append(f"{data.unlock_crew(version)} crew member(s)")
                if "gold" in what:
                    done.append(f"{data.award_medals(save.MEDAL_GOLD)} gold medal(s)")
                elif "missions" in what:
                    done.append(f"{data.award_medals(save.MEDAL_CLEARED)} mission(s) completed")
                return "Unlocked: " + (", ".join(done) or "nothing")
            return edit_save(save_file(body), change)
        if key == "POST save/premium-off":
            return edit_save(save_file(body), lambda data, version: "Premium flag cleared" if data.premium_off()
                             else "No premium flag: nothing to change")
        if key == "POST save/set":
            name, value = str(body.get("name", "")), save.parse_value(str(body.get("value", "")))
            return edit_save(save_file(body), lambda data, version: (data.set(name, value), f"{name} changed")[1])
        if key == "GET save/export":
            data = save.SaveData.parse(save_file(query).read_bytes())
            return {"version": data.version, "ints": data.ints, "arrays": data.arrays}
        if key == "POST save/import":
            raw = body.get("data") or {}

            def replace(data: save.SaveData, version: str) -> str:
                data.ints.clear()
                data.arrays.clear()
                data.version = int(raw.get("version", save.VERSION))
                for k, v in raw.get("ints", {}).items():
                    data.set(k, int(v))
                for k, v in raw.get("arrays", {}).items():
                    data.set(k, [int(x) for x in v])
                return "Save imported"
            return edit_save(save_file(body), replace)
        if key == "GET subs":
            return subs_state()
        if key == "POST subs/set":
            n = int(body.get("n", 0))
            if not 1 <= n <= subs.count(azahar.game_version()):
                raise UserError("unknown submarine")

            def update(values, game):
                for k, v in (body.get("values") or {}).items():
                    values[n][k] = subs.check_value(k, v, f"n° {n} {k}")
            return subs_write(update)
        if key == "POST subs/reset":
            n = body.get("n")

            def reset(values, game):
                for i in ([int(n)] if n else game):
                    values[i] = dict(game[i])
            return subs_write(reset)
        if key == "GET server":
            return self.game_server.json()
        if key == "POST server/start":
            self.game_server.start()
            return self.game_server.json()
        if key == "POST server/stop":
            self.game_server.stop()
            self.game_server.stop_others(strict=False)
            return self.game_server.json()
        if key == "POST server/test":
            return test_server(str(body.get("address", "")))
        if key == "GET server/config":
            return server_config()
        if key == "POST server/config":
            result = save_server_config(body)
            result["restart"] = self.game_server.running
            return result
        if key == "GET music":
            return music_state()
        if key == "GET music/audio":
            return music_audio(str(query.get("file", "")), str(query.get("which", "original")))
        if key == "POST music/upload":
            game = music_game()
            track = music_track(game, str(query.get("file", "")))
            try:
                rate, count = int(query.get("rate", 0)), int(query.get("channels", 0))
            except ValueError:
                raise UserError("unreadable rate or channels") from None
            music.store_pcm(music.default_dir(), game, track, body.get("raw") or b"", rate, count,
                            str(query.get("name", "music"))[:120], query.get("normalize", "1") == "1")
            return music_state()
        if key == "POST music/reset":
            if body.get("all"):
                music.remove(music.default_dir())
            else:
                music.remove(music.default_dir(), music_track(music_game(), str(body.get("file", ""))))
            return music_state()
        if key == "POST music/match":
            game = music_game()
            track = None if body.get("all") else music_track(game, str(body.get("file", "")))
            music.set_match(music.default_dir(), game, track, bool(body.get("on", True)))
            return music_state()
        if key == "POST music/apply":
            return self.tasks.start("Apply the music in the emulator", music_apply).json()
        if key == "POST music/folder":
            folder = music.default_dir()
            folder.mkdir(parents=True, exist_ok=True)
            open_folder(folder)
            return {}
        if key == "POST open":
            open_folder(Path(body.get("path", "")))
            return {}
        raise UserError(f"unknown action: {key}")


def list_files(folder: str | None) -> dict:
    path = Path(folder).expanduser() if folder else Path.home()
    if not path.is_dir():
        raise UserError(f"{path}: folder not found")
    entries = []
    with contextlib.suppress(PermissionError):
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            with contextlib.suppress(OSError):
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child), "type": "dir"})
                elif child.suffix.lower() in extract_cia.GAME_SUFFIXES:
                    game = extract_cia.program_id(child) in (GAME_TITLE_ID, UPDATE_TITLE_ID)
                    entries.append({"name": child.name, "path": str(child), "type": "game" if game else "other",
                                    "size": child.stat().st_size})
    return {"dir": str(path), "parent": str(path.parent) if path.parent != path else None, "entries": entries,
            "shortcuts": [{"name": "Home folder", "path": str(Path.home())},
                          {"name": "The project's cia/ folder", "path": str(ROOT / "cia")}]
                         + [{"name": p.name, "path": str(p)} for p in
                            (Path.home() / "Downloads", Path.home() / "Téléchargements") if p.is_dir()]}


def open_folder(path: Path) -> None:
    """Shows a folder in the system's file manager."""
    if not path.exists():
        raise UserError(f"{path} does not exist")
    if sys.platform.startswith("win"):
        os.startfile(path)                                 # noqa: S606 (a folder chosen by the launcher)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(port: int = 0, open_browser: bool = True) -> None:
    server = LauncherServer(port)
    url = f"http://127.0.0.1:{server.port}/"
    print(f"Sub Wars Open Sourced: the launcher is open in your web browser.\n"
          f"  Otherwise, open this address: {url}\n"
          f"  Keep this window open while you use it; Ctrl+C to quit.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        server.game_server.stop()
        server.server_close()
