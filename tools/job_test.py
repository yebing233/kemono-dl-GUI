"""Drive one real download job through the GUI server.

Unlike ``smoke_test.py`` (which only validates requests), this starts an actual
``kemono_dl`` subprocess and streams its log back through ``/api/state``, so it
proves the whole chain: form → command → subprocess → progress/log → job state.

    python tools/job_test.py https://kemono.cr/patreon/user/12345

The URL does not need to exist: a failing job is still a valid exercise of the
pipeline (exit code + captured log lines).  Exit status is 0 when the job
reached a terminal state.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("SMOKE_PORT", "8798"))
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout: float = 40.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as response:
                html = response.read().decode("utf-8", "replace")
            match = re.search(r'name="gui-token" content="([^"]+)"', html)
            if match:
                return match.group(1)
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    raise SystemExit("server did not start")


def call(token: str, route: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + route, data=data, method="POST" if data else "GET")
    request.add_header("X-GUI-Token", token)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "replace") or "{}")


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else "https://kemono.cr/patreon/user/12345"
    exe = os.environ.get("KEMONO_DL_GUI_EXE")
    out_dir = Path(os.environ.get("KEMONO_DL_GUI_OUT") or (REPO_ROOT / "downloads"))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / ".build" / "site")])
    if exe:
        # Frozen build: the exe carries its own interpreter and re-execs itself
        # for the download job, so no Python on this machine is involved.
        command = [exe, "--port", str(PORT), "--no-browser"]
        cwd = str(Path.home())
    else:
        command = [sys.executable, "-u", "-m", "kemono_dl_gui", "--port", str(PORT), "--no-browser"]
        cwd = str(REPO_ROOT)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        token = wait_for_server()
        config = {
            "urls": [url],
            "path": str(out_dir),
            "templates": {"attachments": "{service}/{creator_id}/{post_id}/{filename}"},
            "templateSplit": False,
            "restrictNames": False,
            "writeContent": False,
            "writeJson": False,
            "skipExtensions": [],
            "dates": {},
            "cookies": [],
            "logins": {},
            "favorite": {},
            "batchFiles": [],
            "archive": "",
            "customVars": "",
        }
        status, started = call(token, "/api/run", config)
        print(json.dumps({"run": {"status": status, "ok": started.get("ok"), "job": started.get("job", {}).get("status")}}, ensure_ascii=False))
        if not started.get("ok"):
            print(json.dumps(started, ensure_ascii=False, indent=2))
            return 1

        job_id = started["job"]["id"]
        since = 0
        lines: list[str] = []
        deadline = time.time() + 90
        summary: dict = {}
        while time.time() < deadline:
            _, state = call(token, f"/api/state?job={job_id}&since={since}")
            lines.extend(state.get("lines") or [])
            since = state.get("base", 0) + len(lines)
            summary = state.get("job") or {}
            if summary.get("status") in {"done", "failed", "stopped"}:
                break
            time.sleep(0.7)

        print("\n".join(lines[-25:]))
        print(json.dumps(
            {
                "job": {
                    "status": summary.get("status"),
                    "exitCode": summary.get("exitCode"),
                    "lineCount": summary.get("lineCount"),
                    "command": summary.get("command"),
                }
            },
            ensure_ascii=False,
            indent=2,
        ))
        call(token, "/api/quit", {})
        return 0 if summary.get("status") in {"done", "failed", "stopped"} else 1
    finally:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
