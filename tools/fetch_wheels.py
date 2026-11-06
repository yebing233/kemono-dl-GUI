"""Fetch pure-Python wheels directly from PyPI and unpack them into a folder.

This exists because the portable build has to work without pip (some sandboxed
or locked-down machines cannot run ``pip install``).  Wheels are plain zip
archives, so downloading and extracting them is enough to vendor a dependency
tree next to the app.

Usage::

    python tools/fetch_wheels.py requests --site .build/site
    python tools/fetch_wheels.py --group pyinstaller --site .build/site
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

GROUPS: dict[str, list[str]] = {
    # runtime dependency of kemono_dl itself
    "runtime": ["requests", "certifi", "charset-normalizer", "idna", "urllib3"],
    # everything PyInstaller needs on Windows
    "pyinstaller": [
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "altgraph",
        "packaging",
        "pefile",
        "pywin32-ctypes",
    ],
}

PYPI_JSON = "https://pypi.org/pypi/{name}/json"


def wheel_rank(filename: str) -> int:
    """Lower is better; 99 means "not usable on this interpreter"."""
    name = filename.lower()
    if not name.endswith(".whl"):
        return 99
    if "win_amd64" in name and "cp312" in name:
        return 0
    if "win_amd64" in name and "abi3" in name:
        return 1
    if "py3-none-any" in name or "py2.py3-none-any" in name:
        return 2
    if "win_amd64" in name:
        return 5
    if "none-any" in name:
        return 6
    return 99


def pick_wheel(name: str) -> tuple[str, str]:
    with urllib.request.urlopen(PYPI_JSON.format(name=name), timeout=60) as response:
        data = json.load(response)
    version = data["info"]["version"]
    candidates = [item for item in data["urls"] if wheel_rank(item["filename"]) < 99]
    if not candidates:
        raise SystemExit(f"{name} {version}: no usable wheel")
    candidates.sort(key=lambda item: wheel_rank(item["filename"]))
    best = candidates[0]
    return best["url"], best["filename"]


def install(name: str, wheels_dir: Path, site_dir: Path, force: bool) -> None:
    url, filename = pick_wheel(name)
    target = wheels_dir / filename
    if force or not target.exists():
        wheels_dir.mkdir(parents=True, exist_ok=True)
        print(f"  -> {filename}")
        with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    else:
        print(f"  = {filename} (cached)")

    with zipfile.ZipFile(target) as archive:
        archive.extractall(site_dir)
    print(f"  ok {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="*", help="package names to vendor")
    parser.add_argument("--group", action="append", default=[], choices=sorted(GROUPS), help="predefined package group")
    parser.add_argument("--site", default=".build/site", help="destination directory (default: .build/site)")
    parser.add_argument("--wheels", default=".build/wheels", help="wheel cache (default: .build/wheels)")
    parser.add_argument("--force", action="store_true", help="re-download cached wheels")
    args = parser.parse_args(argv)

    packages = list(args.packages)
    for group in args.group:
        packages.extend(GROUPS[group])
    if not packages:
        parser.error("nothing to install")

    site_dir = Path(args.site).resolve()
    wheels_dir = Path(args.wheels).resolve()
    site_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    for package in packages:
        key = package.lower()
        if key in seen:
            continue
        seen.add(key)
        install(package, wheels_dir, site_dir, args.force)
    print(f"\n{len(seen)} package(s) vendored into {site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
