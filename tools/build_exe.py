"""Build ``dist/kemono-dl-gui.exe``: a one-file, Python-free GUI build.

What it does:

1. vendors ``requests`` and PyInstaller into ``.build/site`` (wheels are fetched
   straight from PyPI, so ``pip`` is never required);
2. runs PyInstaller with ``kemono-dl-gui.spec``;
3. prints the path and size of the produced executable.

Usage::

    python tools/build_exe.py            # full build
    python tools/build_exe.py --skip-deps  # reuse .build/site
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / ".build"
SITE_DIR = BUILD_DIR / "site"
WHEELS_DIR = BUILD_DIR / "wheels"
WORK_DIR = BUILD_DIR / "pyinstaller"
DIST_DIR = REPO_ROOT / "dist"
EXE_NAME = "kemono-dl-gui.exe"


def run(argv: list[str], env: dict[str, str], cwd: Path) -> None:
    print("$ " + " ".join(argv), flush=True)
    subprocess.run(argv, env=env, cwd=str(cwd), check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-deps", action="store_true", help="do not re-vendor the wheels")
    parser.add_argument("--keep-work", action="store_true", help="keep the PyInstaller work directory")
    args = parser.parse_args(argv)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(SITE_DIR), str(REPO_ROOT)])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if not args.skip_deps:
        run([sys.executable, str(REPO_ROOT / "tools" / "fetch_wheels.py"), "--group", "runtime", "--group", "pyinstaller",
             "--site", str(SITE_DIR), "--wheels", str(WHEELS_DIR)], env, REPO_ROOT)

    if not (SITE_DIR / "PyInstaller").is_dir():
        print("PyInstaller is missing; run without --skip-deps first", file=sys.stderr)
        return 1

    if WORK_DIR.exists() and not args.keep_work:
        import shutil

        shutil.rmtree(WORK_DIR, ignore_errors=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(WORK_DIR),
            str(REPO_ROOT / "kemono-dl-gui.spec"),
        ],
        env,
        REPO_ROOT,
    )

    exe = DIST_DIR / EXE_NAME
    if not exe.is_file():
        print(f"build failed: {exe} not found", file=sys.stderr)
        return 1
    print(f"\nbuilt {exe}  ({exe.stat().st_size / 1048576:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
