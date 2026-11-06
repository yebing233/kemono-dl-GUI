"""End-to-end smoke test for the kemono-dl GUI.

Starts the local server, talks to every API endpoint the front-end uses and
reports a compact JSON summary.  Run it after changing the server::

    python tools/smoke_test.py
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
PORT = int(os.environ.get("SMOKE_PORT", "8799"))
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout: float = 40.0) -> str:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as response:
                html = response.read().decode("utf-8", "replace")
            match = re.search(r'name="gui-token" content="([^"]+)"', html)
            if match:
                return match.group(1)
            last_error = "token not found in index.html"
        except (urllib.error.URLError, OSError) as exc:
            last_error = repr(exc)
        time.sleep(0.4)
    raise SystemExit(f"server did not start: {last_error}")


def call(token: str, route: str, payload: dict | None = None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + route, data=data, method="POST" if data else "GET")
    request.add_header("X-GUI-Token", token)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "kemono_dl_gui", "--port", str(PORT), "--no-browser"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        token = wait_for_server()
        report: dict[str, object] = {}

        status, meta = call(token, "/api/meta")
        report["meta"] = {"status": status, "keys": sorted(meta) if isinstance(meta, dict) else meta}
        report["metaValues"] = {
            key: meta.get(key) for key in ("version", "hasRequests", "frozen", "installable", "repoRoot", "python")
        } if isinstance(meta, dict) else meta

        status, fs = call(token, "/api/fs?files=1")
        report["fs"] = {
            "status": status,
            "dirCount": len(fs.get("dirs", [])) if isinstance(fs, dict) else None,
            "fileCount": len(fs.get("files", [])) if isinstance(fs, dict) else fs,
            "path": fs.get("path") if isinstance(fs, dict) else None,
        }

        config = {
            "urls": ["https://kemono.cr/patreon/user/12345"],
            "path": str(REPO_ROOT / "downloads"),
            "templates": {"attachments": "{service}/{creator_id}/{post_id}/{filename}"},
            "templateSplit": False,
            "restrictNames": True,
            "noTmp": False,
            "writeContent": True,
            "writeJson": False,
            "skipExtensions": ["psd", "zip"],
            "skipAttachments": False,
            "dates": {"date": {"enabled": True, "type": "published", "value": "2024-05-06"}},
            "cookies": [],
            "logins": {"kemono": {"user": "", "password": ""}, "coomer": {"user": "", "password": ""}, "pawchive": {"user": "", "password": ""}},
            "favorite": {"kemono": False, "coomer": False, "pawchive": False},
            "batchFiles": [],
            "archive": "",
            "customVars": "",
        }
        status, preview = call(token, "/api/preview", config)
        report["preview"] = {"status": status, "paths": preview.get("paths") if isinstance(preview, dict) else preview}

        status, validate = call(token, "/api/validate", config)
        report["validate"] = {
            "status": status,
            "ok": validate.get("ok") if isinstance(validate, dict) else None,
            "command": validate.get("command") if isinstance(validate, dict) else None,
            "errors": validate.get("errors") if isinstance(validate, dict) else None,
            "warnings": validate.get("warnings") if isinstance(validate, dict) else None,
        }

        status, state = call(token, "/api/state")
        report["state"] = {"status": status, "jobs": len(state.get("jobs", [])) if isinstance(state, dict) else state}

        bad = call(token, "/api/meta")
        report["authHeaderIgnored"] = bad[0] == 200

        # a request without the session token must be rejected
        anonymous = urllib.request.Request(BASE + "/api/state")
        try:
            with urllib.request.urlopen(anonymous, timeout=10) as response:
                report["unauthenticatedStatus"] = response.status
        except urllib.error.HTTPError as exc:
            report["unauthenticatedStatus"] = exc.code

        print(json.dumps(report, ensure_ascii=False, indent=2))

        # /api/quit must answer and then actually stop the process
        status, bye = call(token, "/api/quit", {})
        exited = False
        try:
            process.wait(timeout=8)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        print(json.dumps(
            {"quit": {"status": status, "ok": bye.get("ok") if isinstance(bye, dict) else bye, "processExited": exited}},
            ensure_ascii=False,
            indent=2,
        ))
        return 0 if exited else 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
