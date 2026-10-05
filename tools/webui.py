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
import socket
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
import mod
import save
import subs
from ctr import GAME_TITLE_ID

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).with_name("webui.html")
EXTRACTED = ROOT / "extracted"
MODS_OUT = ROOT / "build" / "mods"
PREPARED = ROOT / "build" / "azahar"
MOD_ORDER = ["premium", "specs", "triche", "en-ligne"]
STATE_FILE = "lanceur.json"


class UserError(Exception):
    """A message for the player."""


# The tools, in import order. The launcher keeps running while the project is updated (git pull, a new
# version unpacked over it): their code is reloaded when their files change, between two tasks.
TOOL_MODULES = ["ctr", "ncch", "armasm", "bxml", "amx", "azahar", "extract_cia", "save", "subs", "mod"]
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
                raise UserError(f"Une tâche est déjà en cours : {self.current.title}")
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
                        OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
                    task.error = str(e)
                except Exception as e:                # a bug: keep the traceback for the report
                    task.write(traceback.format_exc())
                    task.error = f"erreur inattendue : {e}"
                finally:
                    task.done = True
        threading.Thread(target=run, daemon=True).start()
        return task


# ---- the online server, as a child process --------------------------------------------------------

class GameServer:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.lines: deque[str] = deque(maxlen=500)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        if sys.version_info < (3, 11):
            raise UserError("le serveur demande Python 3.11 ou plus récent")
        for port in self.ports():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                try:
                    probe.bind(("0.0.0.0", port))
                except OSError:
                    raise UserError(f"Le port UDP {port} est déjà pris : un serveur tourne sans doute déjà sur cet "
                                    "ordinateur (lancé ailleurs).") from None
        self.lines.clear()
        self.process = subprocess.Popen([sys.executable, "-u", "-m", "sdsw_server", "-c", "serveur.toml"],
                                        cwd=ROOT / "server", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def _read(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            self.lines.append(line.rstrip())
        self.lines.append(f"[serveur arrêté, code {process.wait()}]")

    def stop(self) -> None:
        if self.running:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    @staticmethod
    def ports() -> list[int]:
        """UDP ports the server will open: each realm's two, and the NAT check's (fixed by the game)."""
        try:
            data = tomllib.loads((ROOT / "server" / "serveur.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return [61000, 61001, 10025, 10125]
        ports = [int(r[k]) for r in data.get("realm", []) for k in ("auth_port", "secure_port") if k in r]
        return ports + ([10025, 10125] if data.get("server", {}).get("nat_check", True) else [])

    def json(self) -> dict:
        config = ROOT / "server" / "serveur.toml"
        realms = []
        try:
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            realms = [{"name": r.get("name"), "auth_port": r.get("auth_port"), "cheats": r.get("cheats", "separes"),
                       "max_players": r.get("max_players", 8)} for r in data.get("realm", [])]
            public = data.get("server", {}).get("public_address", "")
            status_port = int(data.get("server", {}).get("status_port", 0))
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            public, status_port = "", 0
        return {"running": self.running, "lines": list(self.lines)[-200:], "addresses": local_addresses(),
                "config": str(config), "public_address": public, "realms": realms,
                "status_page": f"http://127.0.0.1:{status_port}/" if status_port else None}


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
        return json.loads((azahar.config_dir() / STATE_FILE).read_text(encoding="utf-8"))
    return {}


def store_state(**values) -> None:
    state = load_state() | values
    path = azahar.config_dir() / STATE_FILE
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
            "prepared_dir": str(PREPARED), "title_id": f"{GAME_TITLE_ID:016X}"}


def emulator_state() -> dict:
    dirs = azahar.azahar_dirs()
    mods_dir = dirs[0] / "load" / "mods" / azahar.TITLE_ID if dirs else None
    installed = load_state().get("installed") if mods_dir and mods_dir.exists() else None
    return {"dirs": [str(d) for d in dirs], "mods_dir": str(mods_dir) if mods_dir else None,
            "mods_installed": bool(mods_dir and mods_dir.exists()), "installed": installed,
            "saves": [str(p) for p in azahar.save_files()]}


def mods_list() -> list[dict]:
    out = []
    for recipe in mod.MODS.glob("*/mod.toml"):
        data = tomllib.loads(recipe.read_text(encoding="utf-8"))
        if data.get("hidden"):
            continue
        params = []
        for key, spec in data.get("params", {}).items():
            default = str(spec.get("default", ""))
            kind = "bool" if default.lower() in mod.YES | mod.NO else "text"
            params.append({"key": key, "help": spec.get("help", ""), "default": default, "kind": kind})
        out.append({"id": recipe.parent.name, "name": data.get("name", recipe.parent.name),
                    "description": data.get("description", ""), "params": params,
                    "flags": data.get("token_flags", []), "online": "identity" in data})
    rank = {name: i for i, name in enumerate(MOD_ORDER)}
    return sorted(out, key=lambda m: (rank.get(m["id"], len(rank)), m["id"]))


# ---- actions -------------------------------------------------------------------------------------

def extract_game(source: Path, log) -> dict:
    if not source.exists():
        raise UserError(f"{source} : fichier introuvable")
    print(f"Extraction de {source}…")
    manifest = extract_cia.extract(source, EXTRACTED, log=print)
    store_state(source=str(source))
    print("Fichiers du jeu prêts.")
    return {"product": manifest["product_code"]}


def prepare_for_azahar(source: Path, log) -> dict:
    if source.suffix.lower() != ".cia":
        raise UserError("Seul un .cia a besoin d'être préparé : un .cxi ou un .3ds s'ouvre tel quel dans "
                        "Azahar (Fichier > Charger un fichier).")
    PREPARED.mkdir(parents=True, exist_ok=True)
    print("Copie du jeu sans le manuel chiffré (Azahar refuse le CIA de l'eShop entier)…")
    azahar.game_only_cia(source, PREPARED / "SteelDiverSubWars_original.cia")
    print("Copie du jeu en .cxi (à ouvrir sans l'installer)…")
    azahar.game_cxi(source, PREPARED / "SteelDiverSubWars_original.cxi")
    azahar.write_readme(PREPARED)
    print(f"Prêt : {PREPARED}")
    return {"dir": str(PREPARED)}


def build_mods(names: list[str], params: dict[str, str], install: bool, log) -> dict:
    if not names:
        raise UserError("Choisissez au moins un mod.")
    if not (EXTRACTED / "code.bin").exists():
        raise UserError("Il faut d'abord préparer les fichiers du jeu (onglet Jeu).")
    built = mod.build(names, MODS_OUT, params)
    result = {"built": str(built)}
    if install:
        dirs = azahar.azahar_dirs()
        if not dirs:
            raise UserError("Le dossier d'Azahar est introuvable : lancez Azahar une fois, puis réessayez.")
        dest = dirs[0] / "load" / "mods" / azahar.TITLE_ID
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(built / azahar.TITLE_ID, dest)
        public = {k: v for k, v in mod.build.params.items() if k not in ("pid", "password", "token")}
        store_state(installed={"mods": names, "params": public, "date": time.strftime("%Y-%m-%d %H:%M")})
        print(f"Installé dans {dest}")
        print("Lancez (ou relancez) le jeu dans Azahar : le mod s'applique au démarrage.")
        result["installed"] = str(dest)
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


def save_file(query: dict) -> Path:
    path = query.get("file")
    try:
        return save.find_save(Path(path) if path else None)
    except save.SaveError as e:
        raise UserError(str(e)) from e


def save_summary(path: Path) -> dict:
    data = save.SaveData.parse(path.read_bytes())
    texts = save.game_texts()
    unlocked = data.array("save.sub.unlock", save.SUBS)
    unlocked[0] = 1
    patterns = data.array("save.sub.pattern.unlock", save.PATTERNS)
    patterns[0] = 1
    crew = data.array("save.sub.crew.unlock", save.CREW)
    name = bytes(v & 0xFF for v in data.arrays.get("save.sub.filteredname", [])).split(b"\0")[0]
    typenum = data.ints.get("save.sub.typenum", 1)
    missions = [[{"medal": data.medal(s, l), "time": data.best_time(s, l)} for l in range(1, save.LEVELS + 1)]
                for s in range(1, save.STAGES + 1)]
    online = {k: data.ints.get(f"save.multi.{k}", 0) for k in
              ("games", "wins", "losses", "ties", "quits", "points", "kills", "killed", "hits", "shots")}
    return {"file": str(path), "version": data.version, "player": name.decode("utf-8", "replace"),
            "typenum": typenum, "sub_name": save.sub_name(texts, typenum - 1),
            "subs": [{"n": i + 1, "name": save.sub_name(texts, i), "unlocked": bool(unlocked[i])}
                     for i in range(save.SUBS)],
            "patterns": sum(1 for p in patterns if p), "patterns_total": save.PATTERNS,
            "crew": sum(1 for c in crew if c), "crew_total": save.CREW, "missions": missions,
            "gold": sum(m["medal"] >= save.MEDAL_GOLD for row in missions for m in row),
            "online": online, "premium_flag": bool(data.ints.get("save.sub.enlist")),
            "values": len(data.ints) + len(data.arrays)}


def edit_save(path: Path, change) -> dict:
    data = save.SaveData.parse(path.read_bytes())
    out = io.StringIO()
    with captured(out):
        message = change(data)
        save.write(path, data)
    return {"message": message, "log": out.getvalue(), "summary": save_summary(path)}


def subs_state() -> dict:
    try:
        game = subs.game_values()
    except subs.SubsError as e:
        raise UserError(str(e)) from e
    names = subs.names()
    path = subs.default_file()
    mine = subs.read_file(path) if path.exists() else {}
    return {"file": str(path), "exists": path.exists(),
            "fields": [{"key": f.key, "kind": f.kind.__name__, "low": f.low, "high": f.high, "help": f.help,
                        "advanced": f.advanced, "short": subs.SHORT.get(f.key, f.key)} for f in subs.FIELDS],
            "subs": [{"n": n, "name": names[n], "game": game[n], "mine": {**game[n], **mine.get(n, {})}}
                     for n in range(1, subs.SUBS + 1)]}


def subs_write(update) -> dict:
    game = subs.game_values()
    path = subs.default_file()
    current = subs.read_file(path) if path.exists() else {}
    values = {n: {**game[n], **current.get(n, {})} for n in game}
    update(values, game)
    subs.write_file(path, values, subs.names())
    return subs_state()


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
            self._json(403, {"error": "jeton invalide : rechargez la page"})
            return
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except ValueError:
                    self._json(400, {"error": "requête illisible"})
                    return
        try:
            self._json(200, self.server.api(method, url.path[5:], query, body))
        except UserError as e:
            self._json(400, {"error": str(e)})
        except (save.SaveError, subs.SubsError, extract_cia.ExtractError, mod.ModError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"erreur inattendue : {e}"})


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
                raise UserError("tâche inconnue")
            return task.json()
        if key == "GET files":
            return list_files(query.get("dir"))
        if key == "POST game/extract":
            source = Path(body.get("path") or "").expanduser() if body.get("path") else extract_cia.find_game()
            if source is None:
                raise UserError("Jeu introuvable dans cia/ ou dans Azahar : choisissez son fichier.")
            return self.tasks.start("Préparer les fichiers du jeu", lambda log: extract_game(source, log)).json()
        if key == "POST game/prepare":
            source = load_state().get("source")
            source = Path(source) if source else extract_cia.find_game()
            if source is None:
                raise UserError("Choisissez d'abord le fichier du jeu.")
            return self.tasks.start("Préparer le jeu pour Azahar", lambda log: prepare_for_azahar(source, log)).json()
        if key == "POST mods/build":
            names = [str(n) for n in body.get("mods", [])]
            params = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
            install = bool(body.get("install", True))
            title = ("Installer : " if install else "Construire : ") + " + ".join(names)
            return self.tasks.start(title, lambda log: build_mods(names, params, install, log)).json()
        if key == "POST mods/uninstall":
            return uninstall_mods()
        if key == "GET save":
            return save_summary(save_file(query))
        if key == "POST save/unlock":
            what = set(body.get("what") or [])
            colours = save.default_pattern_colours()

            def change(data: save.SaveData) -> str:
                done = []
                if "subs" in what:
                    done.append(f"{data.unlock_subs()} sous-marin(s)")
                if "patterns" in what:
                    done.append(f"{data.unlock_patterns(colours)} motif(s)")
                if "crew" in what:
                    done.append(f"{data.unlock_crew()} membre(s) d'équipage")
                if "gold" in what:
                    done.append(f"{data.award_medals(save.MEDAL_GOLD)} médaille(s) d'or")
                elif "missions" in what:
                    done.append(f"{data.award_medals(save.MEDAL_CLEARED)} mission(s) terminée(s)")
                return "Débloqué : " + (", ".join(done) or "rien")
            return edit_save(save_file(body), change)
        if key == "POST save/premium-off":
            return edit_save(save_file(body), lambda data: "Drapeau premium retiré" if data.premium_off()
                             else "Pas de drapeau premium : rien à changer")
        if key == "POST save/set":
            name, value = str(body.get("name", "")), save.parse_value(str(body.get("value", "")))
            return edit_save(save_file(body), lambda data: (data.set(name, value), f"{name} modifié")[1])
        if key == "GET save/export":
            data = save.SaveData.parse(save_file(query).read_bytes())
            return {"version": data.version, "ints": data.ints, "arrays": data.arrays}
        if key == "POST save/import":
            raw = body.get("data") or {}

            def replace(data: save.SaveData) -> str:
                data.ints.clear()
                data.arrays.clear()
                data.version = int(raw.get("version", save.VERSION))
                for k, v in raw.get("ints", {}).items():
                    data.set(k, int(v))
                for k, v in raw.get("arrays", {}).items():
                    data.set(k, [int(x) for x in v])
                return "Sauvegarde importée"
            return edit_save(save_file(body), replace)
        if key == "GET subs":
            return subs_state()
        if key == "POST subs/set":
            n = int(body.get("n", 0))
            if not 1 <= n <= subs.SUBS:
                raise UserError("sous-marin inconnu")

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
            return self.game_server.json()
        if key == "POST open":
            open_folder(Path(body.get("path", "")))
            return {}
        raise UserError(f"action inconnue : {key}")


def list_files(folder: str | None) -> dict:
    path = Path(folder).expanduser() if folder else Path.home()
    if not path.is_dir():
        raise UserError(f"{path} : dossier introuvable")
    entries = []
    with contextlib.suppress(PermissionError):
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            with contextlib.suppress(OSError):
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child), "type": "dir"})
                elif child.suffix.lower() in extract_cia.GAME_SUFFIXES:
                    game = extract_cia.program_id(child) == GAME_TITLE_ID
                    entries.append({"name": child.name, "path": str(child), "type": "game" if game else "other",
                                    "size": child.stat().st_size})
    return {"dir": str(path), "parent": str(path.parent) if path.parent != path else None, "entries": entries,
            "shortcuts": [{"name": "Dossier personnel", "path": str(Path.home())},
                          {"name": "Dossier cia/ du projet", "path": str(ROOT / "cia")}]
                         + [{"name": "Téléchargements", "path": str(p)} for p in
                            (Path.home() / "Downloads", Path.home() / "Téléchargements") if p.is_dir()]}


def open_folder(path: Path) -> None:
    """Shows a folder in the system's file manager."""
    if not path.exists():
        raise UserError(f"{path} n'existe pas")
    if sys.platform.startswith("win"):
        os.startfile(path)                                 # noqa: S606 (a folder chosen by the launcher)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(port: int = 0, open_browser: bool = True) -> None:
    server = LauncherServer(port)
    url = f"http://127.0.0.1:{server.port}/"
    print(f"Sub Wars Open Sourced : le lanceur est ouvert dans votre navigateur.\n"
          f"  Sinon, ouvrez cette adresse : {url}\n"
          f"  Gardez cette fenêtre ouverte pendant que vous l'utilisez ; Ctrl+C pour quitter.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAu revoir.")
    finally:
        server.game_server.stop()
        server.server_close()
