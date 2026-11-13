"""Local viewer for Spine .skel and .json animations.

Open a folder, pick one skeleton, then pause, play that clip, or cycle every clip.
"""

from __future__ import annotations

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
import tkinter as tk
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import quote, unquote, urlparse

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


def save_settings(folder: Path) -> None:
    try:
        settings_file().write_text(
            json.dumps({"folder": str(folder)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


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
    return "/assets/" + "/".join(quote(part) for part in rel.split("/"))


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
                warning = "文件太多，只列出了前 8000 个骨骼，请换一个更小的文件夹。"
                break
        if warning:
            break

    assets = []
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
                "id": rel,
                "name": stem,
                "rel": rel,
                "dir": "" if parent == "." else parent,
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
        self.folder: Path | None = None
        self.assets: list[dict] = []
        self.selected = ""
        self.scanning = False
        self.error = ""
        self.warning = ""
        self.scan_id = 0
        self.last_beat = time.time()
        self.started = time.time()
        self.commands: queue.Queue = queue.Queue()
        self._select_abs = ""

    def supported(self) -> list[str]:
        return available_runtimes(self.vendor)

    def snapshot(self) -> dict:
        with self.lock:
            assets = [{k: v for k, v in item.items() if k != "abs"} for item in self.assets]
            return {
                "ok": True,
                "scanning": self.scanning,
                "folder": str(self.folder) if self.folder else "",
                "selected": self.selected,
                "error": self.error,
                "warning": self.warning,
                "supported": self.supported(),
                "assets": assets,
            }

    def set_folder(self, raw: str) -> bool:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        select_abs = ""
        if path.is_file():
            select_abs = str(path.resolve())
            path = path.parent
        try:
            path = path.resolve()
        except OSError as exc:
            with self.lock:
                self.error = str(exc)
                self.scanning = False
            return False
        if not path.is_dir():
            with self.lock:
                self.error = "找不到这个文件夹"
                self.folder = None
                self.assets = []
                self.scanning = False
            return False
        with self.lock:
            self.scan_id += 1
            scan_id = self.scan_id
            self.folder = path
            self.assets = []
            self.selected = ""
            self.scanning = True
            self.error = ""
            self.warning = ""
            self._select_abs = select_abs
        save_settings(path)
        threading.Thread(target=self._scan, args=(path, scan_id), daemon=True).start()
        return True

    def _scan(self, folder: Path, scan_id: int) -> None:
        try:
            assets, warning = scan_folder(folder, set(self.supported()))
            selected = ""
            if self._select_abs:
                for item in assets:
                    if item["abs"] == self._select_abs:
                        selected = item["id"]
                        break
        except Exception as exc:
            log(f"scan failed: {exc}")
            assets, warning, selected = [], "", ""
            error = str(exc)
        else:
            error = ""
        with self.lock:
            if scan_id != self.scan_id:
                return
            self.assets = assets
            self.selected = selected
            self.warning = warning
            self.error = error
            self.scanning = False
        log(f"scanned {folder} -> {len(assets)} skeletons")


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
                if state.folder is None:
                    self.send_error(404)
                    return
                target = safe_join(state.folder, path[len("/assets/") :])
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
                folder = state.folder
                if folder is None:
                    self.send_json({"ok": False, "error": "还没有打开文件夹"})
                    return
                state.set_folder(str(folder))
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/folder":
                body = {}
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_json({"ok": False, "error": "请求不是 JSON"}, 400)
                        return
                folder = str(body.get("path") or "")
                if not folder:
                    box: queue.Queue = queue.Queue(1)
                    state.commands.put(("pick", box))
                    try:
                        folder = box.get(timeout=300)
                    except queue.Empty:
                        self.send_json({"ok": False, "error": "选择文件夹超时"})
                        return
                if not folder:
                    self.send_json({"ok": False, "cancelled": True})
                    return
                if not state.set_folder(folder):
                    self.send_json({"ok": False, "error": state.error or "无法打开文件夹"})
                    return
                self.send_json({"ok": True})
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


def ask_folder(initial: str | None) -> str:
    root = tk.Tk()
    root.withdraw()
    root.update()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    kwargs = {"title": "选择包含 Spine 动画的文件夹"}
    if initial and Path(initial).is_dir():
        kwargs["initialdir"] = initial
    try:
        picked = filedialog.askdirectory(**kwargs)
    finally:
        root.destroy()
    return picked or ""


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
        ]
    )


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
        initial = str(state.folder) if state.folder else ""
        cmd[1].put(ask_folder(initial or None))


def heartbeat_dead(state: AppState) -> bool:
    if time.time() - state.started < 20:
        return False
    return time.time() - state.last_beat > 8


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
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Spine 动画查看器", "播放器文件不完整，请先运行 fetch_runtimes.py。")
        root.destroy()
        return

    state = AppState(vendor)
    if folder_arg:
        state.set_folder(folder_arg)
    else:
        last = str(load_settings().get("folder") or "")
        if last and Path(last).is_dir():
            state.set_folder(last)

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
    try:
        while True:
            pump(state)
            if no_browser:
                continue
            if proc is not None and proc.poll() is not None and heartbeat_dead(state):
                break
            if proc is None and heartbeat_dead(state):
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
