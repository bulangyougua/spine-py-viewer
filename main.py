"""Local viewer for Spine .skel and .json animations.

Open a folder, pick one skeleton, then pause, play that clip, or cycle every clip.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

CREATE_NO_WINDOW = 0x08000000
WINDOW_TITLE = "Spine 动画查看器"

SKIP_DIRS = {
    ".git",
    ".idea",
    ".svn",
    ".vs",
    "LocalBackups",
    "__pycache__",
    "build",
    "cache",
    "dist",
    "library",
    "node_modules",
    "profiles",
    "temp",
}
SKELETON_SUFFIXES = (
    (".skel.bytes", "skel"),
    (".json", "json"),
    (".skel", "skel"),
)
ATLAS_SUFFIXES = (
    (".atlas.txt", "atlas"),
    (".atlas", "atlas"),
)
MIME = {
    ".atlas": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".skel": "application/octet-stream",
    ".txt": "text/plain; charset=utf-8",
    ".webp": "image/webp",
}
WEB_FILES = {
    "/": "index.html",
    "/app.css": "app.css",
    "/app.js": "app.js",
    "/index.html": "index.html",
    "/player.html": "player.html",
    "/player.js": "player.js",
}
VERSION_RE = re.compile(rb"(\d+\.\d+\.\d+(?:-[0-9A-Za-z]+)?)")
SPINE_JSON_RE = re.compile(br'"spine"\s*:\s*"(\d+\.\d+[^"]*)"')


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        path = Path(tempfile.gettempdir()) / "spine-py-viewer.log"
        if path.exists() and path.stat().st_size > 200_000:
            path.unlink()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def settings_file() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home()) / "spine-py-viewer"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(folders: list[Path]) -> None:
    try:
        settings_file().write_text(
            json.dumps({"folders": [str(folder) for folder in folders]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def source_id(folder: Path) -> str:
    key = os.path.normcase(str(folder.resolve())).encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:16]


def available_runtimes(vendor: Path) -> list[str]:
    found = []
    if not vendor.is_dir():
        return found
    for child in vendor.iterdir():
        if not child.is_dir():
            continue
        if (child / "spine-player.js").is_file() or (child / "spine-webgl.js").is_file():
            found.append(child.name)
    return sorted(found, key=lambda name: tuple(int(part) for part in name.split(".")))


def runtime_key(version: str, available: set[str]) -> str | None:
    match = re.match(r"(\d+)\.(\d+)", version or "")
    if not match:
        return None
    key = f"{match.group(1)}.{match.group(2)}"
    return key if key in available else None


def split_named(filename: str) -> tuple[str, str] | None:
    lower = filename.lower()
    for suffix, kind in SKELETON_SUFFIXES + ATLAS_SUFFIXES:
        if lower.endswith(suffix):
            return filename[: -len(suffix)], kind
    return None


def read_version(path: Path, kind: str) -> str:
    try:
        with path.open("rb") as handle:
            head = handle.read(16384 if kind == "json" else 160)
    except OSError:
        return ""
    if kind == "json":
        if not head.lstrip().startswith(b"{"):
            return ""
        match = SPINE_JSON_RE.search(head)
        if not match or (b'"skeleton"' not in head and b'"bones"' not in head):
            return ""
        return match.group(1).decode("utf-8", "replace")
    match = VERSION_RE.search(head)
    return match.group(1).decode("ascii") if match else ""


def atlas_uses_pma(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for index, line in enumerate(handle):
                if index > 30:
                    break
                text = line.strip().lower().replace(" ", "")
                if text.startswith("pma:"):
                    return text.endswith("true")
    except OSError:
        return False
    return False


def asset_url(folder: Path, path: Path) -> str:
    rel = path.resolve().relative_to(folder.resolve()).as_posix()
    encoded = "/".join(quote(part) for part in rel.split("/"))
    return f"/assets/{source_id(folder)}/{encoded}"


def scan_folder(folder: Path, available: set[str]) -> tuple[list[dict], str]:
    atlases: dict[tuple[str, str], Path] = {}
    atlases_by_dir: dict[str, list[Path]] = {}
    skeletons: list[tuple[Path, str, tuple[str, str], str, Path]] = []
    warning = ""
    for root, dirs, files in os.walk(folder, onerror=lambda err: log(str(err))):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        root_path = Path(root)
        dir_key = str(root_path).casefold()
        for name in files:
            parsed = split_named(name)
            if not parsed:
                continue
            stem, kind = parsed
            path = root_path / name
            key = (dir_key, stem.casefold())
            if kind == "atlas":
                atlases[key] = path
                atlases_by_dir.setdefault(dir_key, []).append(path)
            else:
                skeletons.append((root_path, stem, key, kind, path))
            if len(skeletons) >= 8000:
                warning = f"{folder.name} 文件太多，只列出了前 8000 个骨骼。"
                break
        if warning:
            break

    assets = []
    source = source_id(folder)
    for _root, stem, key, kind, path in skeletons:
        version = read_version(path, kind)
        if kind == "json" and not version:
            continue
        atlas = atlases.get(key)
        if atlas is None and len(atlases_by_dir.get(key[0], [])) == 1:
            atlas = atlases_by_dir[key[0]][0]
        rel = path.resolve().relative_to(folder.resolve()).as_posix()
        parent = Path(rel).parent.as_posix()
        assets.append(
            {
                "id": f"{source}:{rel}",
                "name": stem,
                "rel": rel,
                "dir": "" if parent == "." else parent,
                "source": source,
                "kind": kind,
                "version": version,
                "runtime": runtime_key(version, available),
                "pma": atlas_uses_pma(atlas),
                "skeletonUrl": asset_url(folder, path),
                "atlasUrl": asset_url(folder, atlas) if atlas else "",
                "abs": str(path.resolve()),
            }
        )
    assets.sort(key=lambda item: item["rel"].casefold())
    return assets, warning


def safe_join(root: Path, rel: str) -> Path | None:
    rel = unquote(rel).replace("\\", "/").lstrip("/")
    if not rel or any(part == ".." for part in rel.split("/")):
        return None
    root_r = root.resolve()
    candidate = (root_r / rel).resolve()
    try:
        candidate.relative_to(root_r)
    except ValueError:
        return None
    return candidate


class AppState:
    def __init__(self, vendor: Path) -> None:
        self.vendor = vendor
        self.lock = threading.Lock()
        self.folders: dict[str, Path] = {}
        self.assets_by_source: dict[str, list[dict]] = {}
        self.selected = ""
        self.scanning: set[str] = set()
        self.error = ""
        self.drop_error = ""
        self.warnings: list[str] = []
        self.revisions: dict[str, int] = {}
        self.last_beat = time.time()
        self.started = time.time()
        self.window_check_at = 0.0
        self.window_seen_at: float | None = None
        self.commands: queue.Queue = queue.Queue()
        self._select_abs = ""

    def supported(self) -> list[str]:
        return available_runtimes(self.vendor)

    def snapshot(self) -> dict:
        with self.lock:
            assets = [
                {k: v for k, v in item.items() if k != "abs"}
                for source in self.folders
                for item in self.assets_by_source.get(source, [])
            ]
            folders = [
                {"id": source, "path": str(path), "name": path.name or str(path)}
                for source, path in self.folders.items()
            ]
            pending = [self.folders[key].name for key in self.scanning if key in self.folders]
            return {
                "ok": True,
                "scanning": bool(self.scanning),
                "pending": pending,
                "folders": folders,
                "selected": self.selected,
                "error": self.error,
                "dropError": self.drop_error,
                "warning": "\n".join(self.warnings),
                "supported": self.supported(),
                "assets": assets,
            }

    def normalize_folder(self, raw: str) -> Path | None:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_file():
            self._select_abs = str(path.resolve())
            path = path.parent
        try:
            path = path.resolve()
        except OSError as exc:
            self.error = str(exc)
            return None
        if not path.is_dir():
            self.error = f"找不到文件夹：{path}"
            return None
        return path

    def add_folder(self, raw: str) -> bool:
        select_abs = ""
        if raw:
            probe = Path(raw).expanduser()
            if probe.is_file():
                select_abs = str(probe.resolve())
        path = self.normalize_folder(raw)
        if path is None:
            return False
        source = source_id(path)
        with self.lock:
            is_new = source not in self.folders
            self.revisions[source] = self.revisions.get(source, 0) + 1
            revision = self.revisions[source]
            self.folders[source] = path
            self.scanning.add(source)
            self.error = ""
            self._select_abs = select_abs
        save_settings(list(self.folders.values()))
        threading.Thread(target=self._scan, args=(path, source, revision), daemon=True).start()
        return is_new

    def _scan(self, folder: Path, source: str, revision: int) -> None:
        try:
            assets, warning = scan_folder(folder, set(self.supported()))
            selected = ""
            if self._select_abs:
                for item in assets:
                    if item["abs"] == self._select_abs:
                        selected = item["id"]
                        break
            error = ""
        except Exception as exc:
            log(f"scan failed: {exc}")
            assets, warning, selected = [], "", ""
            error = str(exc)
        with self.lock:
            if source not in self.scanning or revision != self.revisions.get(source):
                return
            self.assets_by_source[source] = assets
            if selected:
                self.selected = selected
            if warning:
                self.warnings.append(warning)
            self.error = error
            self.scanning.remove(source)
        log(f"scanned {folder} -> {len(assets)} skeletons")

    def rescan_all(self) -> bool:
        with self.lock:
            folders = list(self.folders.values())
        if not folders:
            self.error = "还没有添加文件夹"
            return False
        self.warnings = []
        for folder in folders:
            self.add_folder(str(folder))
        return True

    def source_folder(self, source: str) -> Path | None:
        with self.lock:
            return self.folders.get(source)


def content_type(path: Path) -> str:
    return MIME.get(path.suffix.lower(), "application/octet-stream")


def make_handler(state: AppState, web_root: Path, vendor_root: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            try:
                self.route_get()
            except Exception as exc:
                log(f"GET {self.path} {exc}")
                self.send_error(500)

        def do_POST(self) -> None:
            try:
                self.route_post()
            except Exception as exc:
                log(f"POST {self.path} {exc}")
                self.send_error(500)

        def route_get(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/api/assets":
                self.send_json(state.snapshot())
                return
            if path == "/api/heartbeat":
                state.last_beat = time.time()
                self.send_json({"ok": True})
                return
            if path in WEB_FILES:
                self.send_path(web_root / WEB_FILES[path], cache=False)
                return
            if path.startswith("/vendor/"):
                target = safe_join(vendor_root, path[len("/vendor/") :])
                self.send_path(target, cache=True)
                return
            if path.startswith("/assets/"):
                parts = path[len("/assets/") :].split("/", 1)
                folder = state.source_folder(parts[0]) if len(parts) == 2 else None
                target = safe_join(folder, parts[1]) if folder and parts[1] else None
                self.send_path(target, cache=False)
                return
            self.send_error(404)

        def route_post(self) -> None:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 1_000_000:
                self.send_error(413)
                return
            raw = self.rfile.read(length) if length else b""
            if parsed.path == "/api/heartbeat":
                state.last_beat = time.time()
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/rescan":
                if not state.rescan_all():
                    self.send_json({"ok": False, "error": "还没有添加文件夹"})
                    return
                self.send_json({"ok": True})
                return
            if parsed.path in ("/api/folder", "/api/drop"):
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_json({"ok": False, "error": "请求不是 JSON"}, 400)
                        return
                paths = body.get("paths") if parsed.path == "/api/drop" else None
                if paths is not None and not isinstance(paths, list):
                    self.send_json({"ok": False, "error": "拖放路径格式错误"}, 400)
                    return
                if paths is None:
                    paths = [str(body.get("path") or "")]
                if not paths or not paths[0]:
                    box: queue.Queue = queue.Queue(1)
                    state.commands.put(("pick", box))
                    try:
                        paths = [box.get(timeout=300)]
                    except queue.Empty:
                        self.send_json({"ok": False, "error": "选择文件夹超时"})
                        return
                if not paths[0]:
                    self.send_json({"ok": False, "cancelled": True})
                    return
                if len(paths) > 50:
                    self.send_json({"ok": False, "error": "一次最多添加 50 个文件夹"}, 400)
                    return
                added = 0
                for folder in paths[:50]:
                    if not isinstance(folder, str):
                        continue
                    if state.add_folder(folder):
                        added += 1
                if state.error:
                    self.send_json({"ok": False, "error": state.error})
                    return
                self.send_json({"ok": True, "added": added})
                return
            self.send_error(404)

        def send_json(self, payload: dict, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_path(self, path: Path | None, cache: bool) -> None:
            if path is None or not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type(path))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
            self.end_headers()
            try:
                with path.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

    return Handler


def powershell_path() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def run_dialog(args: list[str], timeout: float = 300) -> subprocess.CompletedProcess:
    """Run dialogs.ps1 with the hidden Windows PowerShell host."""
    command = [
        str(powershell_path()),
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(bundle_root() / "dialogs.ps1"),
    ] + args
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=flags,
    )


def ask_folder(initial: str | None) -> str:
    """Native folder picker; tkinter is not shipped by every Python build."""
    args = ["-Mode", "pick"]
    if initial:
        args += ["-Initial", initial]
    try:
        done = run_dialog(args)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"folder picker failed: {exc}")
        return ""
    if done.returncode != 0:
        log(f"folder picker exit {done.returncode}: {(done.stderr or '').strip()}")
        return ""
    return (done.stdout or "").strip()


def show_error(message: str, title: str = "Spine 动画查看器") -> None:
    try:
        run_dialog(["-Mode", "error", "-Message", message, "-Title", title], timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"error dialog failed: {exc}")


def find_browser() -> str | None:
    names = (
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    )
    for path in names:
        if path.is_file():
            return str(path)
    return None


def open_window(url: str) -> subprocess.Popen | None:
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return None
    profile = Path(tempfile.gettempdir()) / "spine-py-viewer-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            browser,
            "--app=" + url,
            "--user-data-dir=" + str(profile),
            "--no-first-run",
            "--disable-sync",
            "--disable-extensions",
            "--window-size=1440,900",
            # keep the player alive while the window sits in the background:
            # throttled or frozen timers would starve the heartbeat below.
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
    )


class NativeDropHelper:
    """Register Windows folder drops on the browser without exposing a file API."""

    def __init__(self, browser: subprocess.Popen, state: AppState) -> None:
        self.browser = browser
        self.window_pid: int | None = None
        self.state = state
        self.process: subprocess.Popen | None = None
        try:
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            self.process = subprocess.Popen(
                [str(powershell), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                 "-File", str(bundle_root() / "drop_helper.ps1"), "-ProcessId", str(browser.pid)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
            if self.process.stdin is not None:
                self.process.stdin.close()
            threading.Thread(target=self._read_paths, daemon=True).start()
            threading.Thread(target=self._read_errors, daemon=True).start()
        except (OSError, ValueError) as exc:
            self.state.drop_error = f"原生拖放初始化失败：{exc}"
            log(self.state.drop_error)

    def _read_paths(self) -> None:
        try:
            for line in self.process.stdout:
                line = line.strip()
                if line.startswith("READY "):
                    try:
                        self.window_pid = int(line.split()[1])
                    except (ValueError, IndexError):
                        pass
                    continue
                try:
                    path = base64.b64decode(line, validate=True).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                if path and self.window_pid is not None:
                    log(f"native drop: {path}")
                    self.state.add_folder(path)
            if self.window_pid is None:
                self.state.drop_error = "拖放组件初始化失败，请使用「添加文件夹」或重启程序。"
                log(self.state.drop_error)
        except (OSError, ValueError) as exc:
            log(f"drop helper stdout failed: {exc}")

    def _read_errors(self) -> None:
        try:
            for line in self.process.stderr:
                if line.strip():
                    log(f"drop helper: {line.strip()}")
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass


def parse_cli(argv: list[str]) -> tuple[bool, int, str | None, str | None]:
    no_browser = False
    port = 0
    scan_only = None
    folder = None
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--no-browser":
            no_browser = True
        elif arg == "--port":
            index += 1
            port = int(argv[index])
        elif arg == "--scan":
            index += 1
            scan_only = argv[index]
        elif arg.startswith("--"):
            raise SystemExit("未知参数: " + arg)
        elif folder is None:
            folder = arg
        index += 1
    return no_browser, port, scan_only, folder


def pump(state: AppState) -> None:
    try:
        cmd = state.commands.get(timeout=0.2)
    except queue.Empty:
        return
    if cmd[0] == "pick":
        initial = str(next(reversed(state.folders.values()))) if state.folders else ""
        cmd[1].put(ask_folder(initial or None))


def spine_window_open() -> bool:
    """True while a Chrome/Edge app window titled like ours exists.

    This is the only honest "is the window still there?" signal: heartbeats
    stall whenever Windows sends the window to the background, and the
    launcher process can exit immediately while Edge hands the URL over.
    Minimised windows keep their WS_VISIBLE style, so they still count.
    """
    if os.name != "nt":
        return True
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title.value == WINDOW_TITLE:
                klass = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(hwnd, klass, 128)
                if klass.value.startswith("Chrome_WidgetWin_"):
                    found.append(hwnd)
                    return False
        return True

    user32.EnumWindows(visit, 0)
    return bool(found)


def should_stop(no_browser: bool, proc: subprocess.Popen | None, state: AppState) -> bool:
    """Wait for the window to show up once, then exit shortly after it is gone."""
    if no_browser:
        return False
    now = time.time()
    if now - state.window_check_at < 1.0:
        return False
    state.window_check_at = now
    if spine_window_open():
        state.window_seen_at = now
        return False
    if state.window_seen_at is None:
        return False  # page never announced itself yet; keep waiting
    return now - state.window_seen_at > 6


def main() -> None:
    no_browser, port, scan_only, folder_arg = parse_cli(sys.argv)
    vendor = bundle_root() / "vendor"
    web_root = bundle_root() / "web"
    if scan_only:
        assets, warning = scan_folder(Path(scan_only).resolve(), set(available_runtimes(vendor)))
        summary = [
            {
                "kind": item["kind"],
                "version": item["version"],
                "runtime": item["runtime"],
                "atlas": bool(item["atlasUrl"]),
                "rel": item["rel"],
            }
            for item in assets
        ]
        print(json.dumps({"count": len(summary), "warning": warning, "assets": summary}, ensure_ascii=False, indent=2))
        return
    if not web_root.is_dir() or not any(available_runtimes(vendor)):
        show_error("播放器文件不完整，请先运行 fetch_runtimes.py。")
        return

    state = AppState(vendor)
    if folder_arg:
        state.add_folder(folder_arg)
    else:
        settings = load_settings()
        saved = settings.get("folders")
        if not isinstance(saved, list):
            saved = [str(settings.get("folder") or "")]
        for saved_folder in saved:
            if saved_folder and Path(saved_folder).is_dir():
                state.add_folder(str(saved_folder))

    handler = make_handler(state, web_root, vendor)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound = server.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    (Path(tempfile.gettempdir()) / "spine-py-viewer.port").write_text(str(bound), encoding="utf-8")
    log("listening " + url)
    proc = None if no_browser else open_window(url)
    drop_helper = NativeDropHelper(proc, state) if proc is not None else None
    try:
        while True:
            pump(state)
            if should_stop(no_browser, proc, state):
                break
    except KeyboardInterrupt:
        pass
    finally:
        if drop_helper is not None:
            drop_helper.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
