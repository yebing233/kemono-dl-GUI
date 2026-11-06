"""Smoke test for the *deployment* mode used by Docker / remote hosts.

It starts the GUI the same way ``Dockerfile.gui`` does — bound to ``0.0.0.0``,
no browser, an explicit download directory and ``KEMONO_DL_GUI_PASSWORD`` set —
and checks that:

* ``/healthz`` answers without credentials (container health probes),
* every other route sits behind HTTP Basic auth (401 without, 200 with),
* the session token still protects the JSON API,
* ``/api/meta`` reports the configured download directory,
* ``/api/quit`` really stops the process.

    python tools/docker_test.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("DOCKER_TEST_PORT", "8797"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "s3cret-pw"
USER = "kemono"


def basic_header(user: str = USER, password: str = PASSWORD) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def fetch(route: str, headers: dict[str, str] | None = None, payload: dict | None = None) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + route, data=data, method="POST" if data else "GET")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_for_health(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            status, body = fetch("/healthz")
            if status == 200 and body.strip() == "ok":
                return
            last = f"status={status} body={body[:80]!r}"
        except (urllib.error.URLError, OSError) as exc:
            last = repr(exc)
        time.sleep(0.4)
    raise SystemExit(f"server did not become healthy: {last}")


def main() -> int:
    download_dir = Path(tempfile.mkdtemp(prefix="kemono-docker-test-"))
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "KEMONO_DL_GUI_PASSWORD": PASSWORD,
            "KEMONO_DL_GUI_DOWNLOAD_DIR": str(download_dir),
            "KEMONO_DL_GUI_DATA": str(download_dir / "data"),
            "KEMONO_DL_GUI_HOST": "0.0.0.0",
            "KEMONO_DL_GUI_PORT": str(PORT),
            "KEMONO_DL_GUI_NO_BROWSER": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "kemono_dl_gui"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health()

        report: dict[str, object] = {}
        report["healthz"] = fetch("/healthz")[0]
        report["indexWithoutAuth"] = fetch("/")[0]
        report["indexBadPassword"] = fetch("/", basic_header(password="wrong"))[0]
        status, html = fetch("/", basic_header())
        report["indexWithAuth"] = status
        match = re.search(r'name="gui-token" content="([^"]+)"', html)
        token = match.group(1) if match else ""
        report["tokenFound"] = bool(token)

        api_headers = {**basic_header(), "X-GUI-Token": token}
        report["apiWithoutToken"] = fetch("/api/state", basic_header())[0]
        status, body = fetch("/api/meta", api_headers)
        report["metaWithAuth"] = status
        meta = json.loads(body) if status == 200 else {}
        report["meta"] = {
            "authRequired": meta.get("authRequired"),
            "defaultPath": meta.get("defaultPath"),
            "guiVersion": meta.get("guiVersion"),
            "frozen": meta.get("frozen"),
        }
        report["defaultPathIsEnv"] = str(meta.get("defaultPath")) == str(download_dir)

        status, _ = fetch("/api/quit", api_headers, {})
        report["quit"] = status
        try:
            process.wait(timeout=10)
            report["processExited"] = True
        except subprocess.TimeoutExpired:
            report["processExited"] = False

        print(json.dumps(report, ensure_ascii=False, indent=2))

        ok = (
            report["healthz"] == 200
            and report["indexWithoutAuth"] == 401
            and report["indexBadPassword"] == 401
            and report["indexWithAuth"] == 200
            and report["tokenFound"] is True
            and report["apiWithoutToken"] == 401
            and report["metaWithAuth"] == 200
            and report["defaultPathIsEnv"] is True
            and report["quit"] == 200
            and report["processExited"] is True
        )
        print("OK" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
