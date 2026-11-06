"""Verify the *built* portable executable (run this after ``tools/build_exe.py``).

It launches ``dist/kemono-dl-gui.exe`` exactly like an end user would, then checks
from the outside that

* the bundled runtime reports itself as frozen and ships ``requests``;
* the frozen CLI path is used (``--run-cli``) when building a download command;
* the bundled front-end is served (index.html + app.js + styles.css);
* ``/api/quit`` really terminates the process.

This is what CI runs on ``windows-latest``; locally it will fail if the sandbox
forbids executing newly built binaries (the process cannot be spawned at all).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# KEMONO_DL_GUI_EXE lets you point the check at a copy of the exe (e.g. one
# moved outside a sandboxed checkout that refuses to execute workspace binaries).
EXE = Path(os.environ.get("KEMONO_DL_GUI_EXE") or (REPO_ROOT / "dist" / ("kemono-dl-gui.exe" if os.name == "nt" else "kemono-dl-gui")))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _decoded(raw: bytes):
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def call(port: int, token: str, route: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}", data=data, method="POST" if data else "GET"
    )
    request.add_header("X-GUI-Token", token)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, _decoded(response.read()), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, _decoded(exc.read()), ""


def wait_for_exe(port: int, process: subprocess.Popen, timeout: float = 90.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"exe exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                html = response.read().decode("utf-8", "replace")
            match = re.search(r'name="gui-token" content="([^"]+)"', html)
            if match:
                return match.group(1)
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise SystemExit("timed out waiting for the portable exe to serve the UI")


def main() -> int:
    if not EXE.is_file():
        raise SystemExit(f"missing build output: {EXE} (run python tools/build_exe.py first)")

    port = free_port()
    report: dict[str, object] = {"exe": str(EXE), "size": EXE.stat().st_size, "port": port}
    process = subprocess.Popen([str(EXE), "--port", str(port), "--no-browser"], cwd=str(Path.home()))
    try:
        token = wait_for_exe(port, process)

        _, meta, _ = call(port, token, "/api/meta")
        report["meta"] = {key: meta.get(key) for key in ("frozen", "hasRequests", "installable", "version", "pythonVersion")}

        # the bundled front-end must be served from inside the exe
        for asset in ("/static/app.js", "/static/styles.css", "/static/logo.svg"):
            _, body, content_type = call(port, token, asset)
            report.setdefault("assets", {})[asset] = bool(body) if content_type else False

        config = {
            "urls": ["https://kemono.cr/patreon/user/12345"],
            "path": str(Path.home() / "Downloads" / "kemono-dl"),
            "templates": {"attachments": "{service}/{creator_id}/{post_id}/{filename}"},
        }
        _, preview, _ = call(port, token, "/api/preview", config)
        report["preview"] = preview.get("paths", {}).get("attachments")

        _, validate, _ = call(port, token, "/api/validate", config)
        report["validateCommand"] = validate.get("command")
        report["usesFrozenCli"] = "--run-cli" in str(validate.get("command", ""))

        status, bye, _ = call(port, token, "/api/quit", {})
        report["quit"] = {"status": status, "ok": bye.get("ok")}
        try:
            code = process.wait(timeout=20)
            report["exitedAfterQuit"] = True
            report["exitCode"] = code
        except subprocess.TimeoutExpired:
            report["exitedAfterQuit"] = False

        ok = (
            report["meta"]["frozen"] is True
            and report["meta"]["hasRequests"] is True
            and report["meta"]["installable"] is False
            and report["usesFrozenCli"] is True
            and all(report.get("assets", {}).values())
            and report["exitedAfterQuit"] is True
        )
        report["ok"] = ok
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        if process.poll() is None:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
