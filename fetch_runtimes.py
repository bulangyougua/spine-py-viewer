"""Download the Spine player builds this viewer ships with."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
UA = "spine-py-viewer"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


def looks_like_js(data: bytes) -> bool:
    head = data[:300].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"{"):
        return False
    return b"spine" in data[:8000].lower() or b"skeleton" in data[:8000].lower()


def save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"saved {path.relative_to(ROOT)} {len(data)}")


def first_ok(urls: list[str]) -> tuple[str, bytes] | None:
    for url in urls:
        try:
            data = get(url)
        except Exception as exc:
            print(f"miss {url} ({exc})")
            continue
        if looks_like_js(data) or (b"spine" in data[:4000].lower() and not data[:200].lstrip().lower().startswith(b"<")):
            print(f"hit  {url}")
            return url, data
        print(f"bad  {url} {data[:60]!r}")
    return None


def latest_patches() -> dict[str, str]:
    meta = json.loads(get("https://registry.npmjs.org/@esotericsoftware/spine-player"))
    best: dict[str, tuple[int, str]] = {}
    for ver in meta["versions"]:
        if any(tag in ver for tag in ("beta", "alpha", "rc")):
            continue
        parts = ver.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        major, minor, patch = (int(p) for p in parts)
        if major < 4:
            continue
        key = f"{major}.{minor}"
        if key not in best or patch > best[key][0]:
            best[key] = (patch, ver)
    return {key: ver for key, (patch, ver) in best.items()}


def fetch_npm(key: str, ver: str) -> None:
    js_urls = [
        f"https://cdn.jsdelivr.net/npm/@esotericsoftware/spine-player@{ver}/dist/iife/spine-player.min.js",
        f"https://cdn.jsdelivr.net/npm/@esotericsoftware/spine-player@{ver}/dist/iife/spine-player.js",
        f"https://cdn.jsdelivr.net/npm/@esotericsoftware/spine-player@{ver}/dist/spine-player.min.js",
    ]
    css_urls = [
        f"https://cdn.jsdelivr.net/npm/@esotericsoftware/spine-player@{ver}/dist/spine-player.min.css",
        f"https://cdn.jsdelivr.net/npm/@esotericsoftware/spine-player@{ver}/dist/spine-player.css",
    ]
    found = first_ok(js_urls)
    if not found:
        print(f"FAILED js {key}")
        return
    _url, js = found
    save(VENDOR / key / "spine-player.js", js)
    css = None
    for url in css_urls:
        try:
            css = get(url)
        except Exception as exc:
            print(f"miss {url} ({exc})")
            continue
        if css and not css[:80].lstrip().lower().startswith(b"<"):
            break
        css = None
    if css:
        save(VENDOR / key / "spine-player.css", css)
    (VENDOR / key / "VERSION.txt").write_text(ver + "\n", encoding="utf-8")


def fetch_branch(branch: str) -> None:
    bases = [
        f"https://cdn.jsdelivr.net/gh/EsotericSoftware/spine-runtimes@{branch}/",
    ]
    js_rels = [
        "spine-ts/build/spine-player.js",
        "spine-ts/player/dist/spine-player.js",
        "spine-ts/build/spine-webgl.js",
        "spine-js/spine-webgl.js",
        "spine-js/spine.js",
    ]
    css_rels = [
        "spine-ts/player/css/spine-player.css",
    ]
    js_urls = [base + rel for base in bases for rel in js_rels]
    found = first_ok(js_urls)
    if not found:
        print(f"FAILED branch {branch}")
        return
    url, js = found
    filename = "spine-webgl.js" if "spine-webgl.js" in url else "spine-player.js"
    save(VENDOR / branch / filename, js)
    for base in bases:
        for rel in css_rels:
            try:
                css = get(base + rel)
            except Exception:
                continue
            if css and not css[:40].lstrip().lower().startswith(b"<"):
                save(VENDOR / branch / "spine-player.css", css)
                return
    print(f"no css for {branch}")


def inspect(key: str) -> None:
    path = VENDOR / key / "spine-player.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="ignore")
    keys = [
        "SpinePlayer",
        "skelUrl",
        "jsonUrl",
        "atlasUrl",
        "binaryUrl",
        "setAnimation",
        "SkeletonJson",
        "prototype.pause",
    ]
    found = [k for k in keys if k in text]
    print(f"inspect {key}: {', '.join(found)}")


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    try:
        lic = get("https://cdn.jsdelivr.net/gh/EsotericSoftware/spine-runtimes@4.2/LICENSE")
        save(ROOT / "SPINE-RUNTIMES-LICENSE.txt", lic)
    except Exception as exc:
        print("license", exc)
    for branch in ("3.6", "3.7", "3.8", "2.1"):
        fetch_branch(branch)
    patches = latest_patches()
    print("npm", patches)
    for key, ver in sorted(patches.items()):
        fetch_npm(key, ver)
    versions = {}
    for path in sorted(VENDOR.glob("*/VERSION.txt")):
        versions[path.parent.name] = path.read_text(encoding="utf-8").strip()
    for branch in ("2.1", "3.6", "3.7", "3.8"):
        if (VENDOR / branch / "spine-player.js").exists() and branch not in versions:
            versions[branch] = branch
    (VENDOR / "versions.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    for key in sorted(versions):
        inspect(key)


if __name__ == "__main__":
    main()
