"""Local web server that powers the kemono-dl GUI.

By default the server only listens on the loopback interface and requires a
per-session token for every API call, so nothing on the network (or another web
page) can drive downloads.  When it is deployed behind a port mapping (Docker,
a NAS, a remote box) start it with ``--host 0.0.0.0`` and set
``KEMONO_DL_GUI_PASSWORD`` so the whole UI sits behind HTTP Basic auth.
It never re-implements the downloader: each job is a real ``python -m kemono_dl``
subprocess, therefore every CLI option keeps its exact behaviour.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import mimetypes
import os
import queue
import re
import secrets
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import args as args_module
from .args import DEFAULT_TEMPLATE, TEMPLATE_TYPES, build_command, normalise_config, shell_command

APP_DIR = Path(__file__).resolve().parent
#: True when running from the PyInstaller bundle (``kemono-dl-gui.exe``).
FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", str(APP_DIR))) if FROZEN else APP_DIR.parent
if FROZEN:
    APP_DIR = BUNDLE_ROOT / "kemono_dl_gui"
REPO_ROOT = BUNDLE_ROOT
STATIC_DIR = APP_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
VERSION_MODULE = REPO_ROOT / "kemono_dl" / "version.py"

def app_data_dir() -> Path:
    """Where uploads and generated helper files live."""
    override = os.environ.get("KEMONO_DL_GUI_DATA")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "kemono-dl-gui"
    return Path.home() / ".kemono-dl-gui"


def ensure_dir(path: Path) -> Path:
    """Create ``path``; fall back to the system temp dir when it is read-only."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "kemono-dl-gui" / path.name
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            return path
        return fallback


APP_DATA = app_data_dir()
UPLOAD_DIR = APP_DATA / "uploads"
CUSTOM_VARS_FILE = APP_DATA / "custom-template-variables.json"
HISTORY_FILE = APP_DATA / "history.jsonl"

#: Environment variables used by the Docker image / remote deployments.
DATA_ENV = "KEMONO_DL_GUI_DATA"
DOWNLOAD_DIR_ENV = "KEMONO_DL_GUI_DOWNLOAD_DIR"
PASSWORD_ENV = "KEMONO_DL_GUI_PASSWORD"

MAX_LOG_LINES = 20000
PROGRESS_PATTERN = re.compile(
    r"^\[downloading\]\s+(?P<percent>\d+(?:\.\d+)?)% of (?P<total>[\d.]+ \w+) eta (?P<eta>[\d:]+) at (?P<speed>[\d.]+ \w+/s)"
)
#: Percent step between two progress lines kept in the log pane.
PROGRESS_LOG_STEP = 5.0
#: ``kemono_dl.utils.format_bytes`` renders sizes as e.g. ``12.34 MiB``.
SIZE_PATTERN = re.compile(r"^(?P<value>\d+(?:\.\d+)?) (?P<unit>B|KiB|MiB|GiB|TiB|KB|MB|GB|TB)$")
SIZE_UNITS = {
    "B": 1.0,
    "KiB": 1024.0,
    "MiB": 1024.0 ** 2,
    "GiB": 1024.0 ** 3,
    "TiB": 1024.0 ** 4,
    "KB": 1000.0,
    "MB": 1000.0 ** 2,
    "GB": 1000.0 ** 3,
    "TB": 1000.0 ** 4,
}


def parse_bytes(text: str) -> float:
    """Turn ``"12.34 MiB"`` into a byte count (0.0 when unparsable)."""
    match = SIZE_PATTERN.match((text or "").strip())
    if not match:
        return 0.0
    return float(match.group("value")) * SIZE_UNITS[match.group("unit")]


#: ``[downloading] Post URL: https://kemono.cr/patreon/user/123/post/456``
POST_URL_PATTERN = re.compile(
    r"^\[downloading\] Post URL:\s*https?://(?P<site>[^/\s]+)/(?P<service>[^/\s]+)"
    r"/user/(?P<creator>[^/\s]+)/post/(?P<post>[^/\s]+)/?$"
)
#: ``[downloading] Post: some title``
POST_TITLE_PATTERN = re.compile(r"^\[downloading\] Post:\s*(?P<title>.+)$")
#: ``[Error] Failed to download attachment from 'URL' (2/3): 404 Client Error``
FAILURE_PATTERN = re.compile(
    r"^\[Error\] Failed to download attachment from '(?P<url>[^']+)' "
    r"\((?P<attempt>\d+)/(?P<total>\d+)\):\s*(?P<message>.*)$"
)



# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def read_version() -> str:
    try:
        text = VERSION_MODULE.read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if match:
        return match.group(1)
    try:  # frozen builds ship the package as bytecode, not as source files
        from kemono_dl.version import __version__

        return __version__
    except Exception:  # noqa: BLE001 - version is cosmetic
        return "unknown"


def auth_password() -> str:
    """Optional HTTP Basic password guarding the whole UI (Docker / remote boxes)."""
    return os.environ.get(PASSWORD_ENV, "").strip()


def basic_auth_ok(header: str, password: str) -> bool:
    """Check an ``Authorization: Basic …`` header against ``password``.

    The username is ignored (any value works); only the secret is compared, in
    constant time.  An empty ``password`` disables the check entirely.
    """
    if not password:
        return True
    scheme, _, encoded = (header or "").strip().partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        return False
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return False
    return secrets.compare_digest(decoded.partition(":")[2], password)


def default_download_path() -> str:
    override = os.environ.get(DOWNLOAD_DIR_ENV)
    if override:
        return str(Path(override).expanduser())
    downloads = Path.home() / "Downloads"
    return str(downloads / "kemono-dl")


def gui_version() -> str:
    """Version of the GUI package itself (shown in the About panel)."""
    try:
        from . import __version__ as version
    except ImportError:  # pragma: no cover - packaging edge case
        return "unknown"
    return version


def has_requests(python_exe: str) -> bool:
    if FROZEN:
        return True  # requests is compiled into the packaged executable
    try:
        result = subprocess.run(
            [python_exe, "-c", "import requests; print(requests.__version__)"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=create_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def create_no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]


def python_executable() -> str:
    if FROZEN:
        # the packaged exe re-launches itself with ``--run-cli``
        return sys.executable
    override = os.environ.get("KEMONO_DL_GUI_PYTHON")
    if override and Path(override).exists():
        return override
    return sys.executable


def write_custom_vars(text: str) -> str | None:
    """Persist custom template variables so the CLI can read them from a file."""
    global CUSTOM_VARS_FILE
    text = (text or "").strip()
    if not text:
        return None
    data = json.loads(text)
    CUSTOM_VARS_FILE = ensure_dir(APP_DATA) / "custom-template-variables.json"
    CUSTOM_VARS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(CUSTOM_VARS_FILE)


def list_drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    drives = []
    for letter in string.ascii_uppercase:
        candidate = f"{letter}:\\"
        if os.path.exists(candidate):
            drives.append(candidate)
    return drives


def upload_file(filename: str, content: str) -> str:
    target_dir = ensure_dir(UPLOAD_DIR)
    safe = re.sub(r"[^\w.\- ()\u4e00-\u9fff]", "_", Path(filename or "upload.txt").name) or "upload.txt"
    target = target_dir / safe
    if target.exists():
        target = target_dir / f"{target.stem}-{int(time.time())}{target.suffix}"
    target.write_text(content, encoding="utf-8")
    return str(target)


# --------------------------------------------------------------------------- #
# job management
# --------------------------------------------------------------------------- #
class Job:
    def __init__(self, job_id: str, title: str, argv: list[str], config: dict[str, Any], kind: str = "download"):
        self.id = job_id
        self.title = title
        self.argv = argv
        self.config = config
        self.kind = kind
        self.status = "queued"
        self.exit_code: int | None = None
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.lines: list[str] = []
        self.dropped = 0
        self.progress: dict[str, Any] = {
            "percent": 0.0,
            "total": "",
            "eta": "",
            "speed": "",
            "posts": 0,
            "files": 0,
            "pending": 0,
            "skipped": 0,
            "downloaded": 0,
            "remaining": 0,
            "bytesPerFile": 0,
        }
        self.process: subprocess.Popen[str] | None = None
        self.stop_requested = False
        self.lock = threading.Lock()
        #: per-attachment failures, each with its post URL so the UI can link back
        self.failures: list[dict[str, Any]] = []
        #: post URL announced by ``[downloading] Post URL:`` (current one)
        self._post_url = ""
        self._logged_percent = 0.0
        #: bytes of files that finished downloading (``_finished_bytes``) plus the
        #: size of the file currently in flight (``_current_total``).
        self._finished_bytes = 0.0
        self._current_total = 0.0
        #: attachment count announced by ``[downloading] Attachments: N``.
        self._expected_files = 0
        #: files handed to ``download_file`` so far (the last one may be running).
        self._started = 0
        self._in_file = False


    # -- log ---------------------------------------------------------------
    def append(self, line: str) -> None:
        with self.lock:
            if self._progress_tick(line):
                return
            self._push(line)

    def _push(self, line: str) -> None:
        """Append to the ring buffer (caller holds :attr:`lock`)."""
        self.lines.append(line)
        if len(self.lines) > MAX_LOG_LINES:
            trim = len(self.lines) - MAX_LOG_LINES
            del self.lines[:trim]
            self.dropped += trim

    def _refresh_totals(self) -> None:
        """Recompute the byte/file counters (caller holds :attr:`lock`).

        Only the file currently in flight has a known total size, so the size of
        the files still queued is estimated from the average of the files that
        already finished — the UI labels it with ``≈``.
        """
        percent = min(float(self.progress.get("percent", 0.0)), 100.0)
        current_done = self._current_total * percent / 100.0
        finished_files = max(0, self._started - (1 if self._in_file else 0))
        in_flight = 1 if self._in_file else 0
        pending_files = max(0, self._expected_files - finished_files)
        average = self._finished_bytes / finished_files if finished_files else 0.0
        queued = max(0, pending_files - in_flight)
        remaining = max(0.0, self._current_total - current_done) + average * queued
        self.progress.update(
            files=finished_files,
            pending=pending_files,
            downloaded=int(self._finished_bytes + current_done),
            remaining=int(remaining),
            bytesPerFile=int(average),
        )

    def finish_progress(self, success: bool) -> None:
        """Settle the counters when the child process is gone."""
        with self.lock:
            if self._in_file:
                percent = 100.0 if success else min(float(self.progress.get("percent", 0.0)), 100.0)
                self._finished_bytes += self._current_total * percent / 100.0
                self._in_file = False
            self._refresh_totals()
            # nothing is queued any more, so the "still to download" tiles stop
            # counting and a successful run ends at 100 %
            self.progress["pending"] = 0
            self.progress["remaining"] = 0
            if success and self._started:
                self.progress["percent"] = 100.0
                self.progress["eta"] = ""

    def _progress_tick(self, line: str) -> bool:
        """Feed one stdout line into :attr:`progress`; True when it was a tick.

        ``download_file`` repaints its ``[downloading] …% of …`` line with ``\\r``
        up to ten times per second.  Every tick moves the bar in the GUI, but only
        each ``PROGRESS_LOG_STEP``-th percent reaches the log pane so 200 MB files
        do not flood it.
        """
        stripped = line.strip()
        match = PROGRESS_PATTERN.match(stripped)
        if match:
            percent = float(match.group("percent"))
            self._current_total = parse_bytes(match.group("total"))
            self._in_file = True
            self.progress.update(
                percent=percent,
                total=match.group("total"),
                eta=match.group("eta"),
                speed=match.group("speed"),
            )
            self._refresh_totals()
            if percent >= 99.5 or percent - self._logged_percent >= PROGRESS_LOG_STEP:
                self._logged_percent = percent
                self._push(stripped)
            return True
        if stripped.startswith("[downloading] Post:"):
            self.progress["posts"] += 1
        elif stripped.startswith("[downloading] Attachments:"):
            try:
                count = int(stripped.rsplit(":", 1)[1].strip())
            except (IndexError, ValueError):
                count = 0
            self._expected_files += max(0, count)
        elif stripped.startswith("[skip]"):
            # the downloader verified a local file and did not fetch anything
            self.progress["skipped"] += 1
            self._in_file = False
            self._current_total = 0.0
        elif stripped.startswith("[downloading] Post URL:"):
            self._post_url = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("[downloading] Destination:"):
            # printed just before a file starts, so the previous one is finished
            if self._in_file:
                percent = min(float(self.progress.get("percent", 0.0)), 100.0)
                self._finished_bytes += self._current_total * percent / 100.0
            self._current_total = 0.0
            self._started += 1
            self._in_file = True
            self.progress["percent"] = 0.0
            self._logged_percent = 0.0
        elif stripped.startswith("[Error] Failed to download attachment"):
            failure = FAILURE_PATTERN.match(stripped)
            if failure:
                self.failures.append(
                    {
                        "postUrl": self._post_url,
                        "fileUrl": failure.group("url"),
                        "attempt": int(failure.group("attempt")),
                        "total": int(failure.group("total")),
                        "message": failure.group("message").strip(),
                        "time": time.time(),
                    }
                )
        self._refresh_totals()
        return False

    def lines_since(self, since: int) -> tuple[int, list[str]]:
        with self.lock:
            base = self.dropped
            start = max(0, since - base)
            return base + start, self.lines[start:]

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "exitCode": self.exit_code,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "progress": dict(self.progress),
            "failures": list(self.failures),
            "lineCount": self.dropped + len(self.lines),
            "config": self.config,
            "command": shell_command(self.argv),
        }

    def stop(self) -> None:
        self.stop_requested = True
        process = self.process
        if process is None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    creationflags=create_no_window(),
                    timeout=15,
                )
            else:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass


class JobManager:
    def __init__(self, python_exe: str):
        self.python_exe = python_exe
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._loop, name="kemono-dl-worker", daemon=True)
        self.worker.start()

    # -- public API --------------------------------------------------------
    def submit(self, title: str, argv: list[str], config: dict[str, Any], kind: str = "download") -> Job:
        job_id = secrets.token_hex(6)
        job = Job(job_id, title, argv, config, kind)
        with self.lock:
            self.jobs[job_id] = job
            self.order.append(job_id)
            if len(self.order) > 50:
                for stale in self.order[:-50]:
                    if self.jobs.get(stale) and self.jobs[stale].status not in {"running", "queued"}:
                        self.jobs.pop(stale, None)
                self.order = self.order[-50:]
        job.append(f"[gui] 已加入队列 · {title}")
        job.append(f"[gui] {shell_command(argv)}")
        self.queue.put(job_id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def summaries(self) -> list[dict[str, Any]]:
        with self.lock:
            jobs = [self.jobs[job_id] for job_id in reversed(self.order) if job_id in self.jobs]
        return [job.summary() for job in jobs]

    def active_job(self) -> Job | None:
        with self.lock:
            for job_id in reversed(self.order):
                job = self.jobs.get(job_id)
                if job and job.status in {"running", "queued"}:
                    return job
        return None

    def stop(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job.stop()
        if job.status == "queued":
            job.status = "stopped"
            return True
        return True

    # -- worker ------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            job_id = self.queue.get()
            job = self.get(job_id)
            if job is None or job.status == "stopped":
                continue
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                job.append(f"[gui] 运行线程异常：{exc!r}")
                job.status = "failed"
                job.exit_code = -1
                job.finished_at = time.time()

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = time.time()
        job.append(f"[gui] 开始执行 · {time.strftime('%H:%M:%S')}")

        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        })
        if not FROZEN:
            env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        # the frozen bundle lives in a throw-away temp dir, so run jobs from home
        work_dir = str(Path.home()) if FROZEN else str(REPO_ROOT)

        target_path = normalise_config(job.config, default_download_path()).get("path")
        if target_path:
            try:
                os.makedirs(target_path, exist_ok=True)
            except OSError as exc:
                job.append(f"[gui] 无法创建下载目录 {target_path!r}：{exc}")

        try:
            process = subprocess.Popen(
                job.argv,
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=create_no_window(),
            )
        except OSError as exc:
            job.append(f"[gui] 无法启动进程：{exc}")
            job.status = "failed"
            job.exit_code = -1
            job.finished_at = time.time()
            return

        job.process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            job.append(raw_line.rstrip("\r\n"))
        process.wait()
        job.process = None
        job.exit_code = process.returncode
        job.finished_at = time.time()

        if job.stop_requested:
            job.status = "stopped"
            job.append("[gui] 任务已被用户停止")
            job.finish_progress(success=False)
        elif process.returncode == 0:
            job.status = "done"
            job.finish_progress(success=True)
            job.append(f"[gui] 完成 · 用时 {job.finished_at - (job.started_at or job.finished_at):.1f} 秒")
        else:
            job.status = "failed"
            job.finish_progress(success=False)
            job.append(f"[gui] 进程退出码 {process.returncode}")

        records = parse_post_records(job.lines)
        if records:
            append_history(records)


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
class AppState:
    def __init__(self) -> None:
        self.python = python_executable()
        self.token = secrets.token_urlsafe(24)
        self.version = read_version()
        self.default_path = default_download_path()
        self.manager = JobManager(self.python)
        self.requests_ok = has_requests(self.python)
        self.start_time = time.time()


STATE: AppState | None = None


# --------------------------------------------------------------------------- #
# download history — which posts came from which creator, and when
# --------------------------------------------------------------------------- #
def _history_path() -> Path:
    """Absolute path of the JSONL history file (creates its folder)."""
    global APP_DATA, HISTORY_FILE
    APP_DATA = ensure_dir(APP_DATA)
    HISTORY_FILE = APP_DATA / "history.jsonl"
    return HISTORY_FILE


def parse_post_records(lines: list[str]) -> list[dict[str, Any]]:
    """Group CLI output into one record per post.

    ``kemono_dl`` prints ``[downloading] Post URL:`` before each post, so every
    later ``Post:`` / ``Destination:`` / ``[skip]`` / ``[Error]`` line belongs to
    the most recent post URL.
    """
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in lines:
        line = raw.strip()
        match = POST_URL_PATTERN.match(line)
        if match:
            site = match.group("site")
            service = match.group("service")
            creator = match.group("creator")
            post = match.group("post")
            current = {
                "site": site,
                "service": service,
                "creatorId": creator,
                "postId": post,
                "url": f"https://{site}/{service}/user/{creator}/post/{post}",
                "title": "",
                "files": 0,
                "skipped": 0,
                "failures": 0,
                "errors": [],
            }
            records.append(current)
            continue

        if current is None:
            continue

        if line.startswith("[downloading] Post:"):
            title = POST_TITLE_PATTERN.match(line)
            if title:
                current["title"] = title.group("title").strip()
        elif line.startswith("[downloading] Destination:"):
            current["files"] += 1
        elif line.startswith("[skip]"):
            current["skipped"] += 1
        else:
            failure = FAILURE_PATTERN.match(line)
            if failure:
                current["failures"] += 1
                current["errors"].append(failure.group("message").strip())

    return records


def append_history(records: list[dict[str, Any]]) -> int:
    """Append one JSON line per post; returns how many were written."""
    if not records:
        return 0
    path = _history_path()
    stamp = time.time()
    try:
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps({**record, "ts": stamp}, ensure_ascii=False) + "\n")
    except OSError as exc:
        safe_print(f"[gui] 无法写入下载记录：{exc}")
        return 0
    return len(records)


def load_history() -> list[dict[str, Any]]:
    """Read the JSONL history, keeping the newest entry per post."""
    path = _history_path()
    newest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                key = (
                    str(record.get("site", "")),
                    str(record.get("service", "")),
                    str(record.get("creatorId", "")),
                    str(record.get("postId", "")),
                )
                if not all(key):
                    continue
                previous = newest.get(key)
                if previous is None or float(record.get("ts", 0)) >= float(previous.get("ts", 0)):
                    newest[key] = record
    except FileNotFoundError:
        return []
    except OSError as exc:
        safe_print(f"[gui] 无法读取下载记录：{exc}")
        return []
    return sorted(newest.values(), key=lambda item: float(item.get("ts", 0)), reverse=True)


def history_summary() -> dict[str, Any]:
    """Group the history by creator so the UI can answer “谁更新了？”."""
    records = load_history()
    creators: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (
            str(record.get("site", "")),
            str(record.get("service", "")),
            str(record.get("creatorId", "")),
        )
        entry = creators.get(key)
        if entry is None:
            entry = {
                "site": key[0],
                "service": key[1],
                "creatorId": key[2],
                "key": "/".join(part for part in key if part),
                "posts": 0,
                "files": 0,
                "skipped": 0,
                "failures": 0,
                "firstTs": float(record.get("ts", 0)),
                "lastTs": 0.0,
                "latest": None,
            }
            creators[key] = entry
        entry["posts"] += 1
        entry["files"] += int(record.get("files", 0))
        entry["skipped"] += int(record.get("skipped", 0))
        entry["failures"] += int(record.get("failures", 0))
        stamp = float(record.get("ts", 0))
        entry["firstTs"] = min(entry["firstTs"], stamp)
        if stamp >= entry["lastTs"]:
            entry["lastTs"] = stamp
            entry["latest"] = {
                "postId": record.get("postId", ""),
                "title": record.get("title", ""),
                "url": record.get("url", ""),
                "ts": stamp,
                "failures": int(record.get("failures", 0)),
            }
    ordered = sorted(creators.values(), key=lambda item: item["lastTs"], reverse=True)
    return {
        "path": str(_history_path()),
        "posts": len(records),
        "creators": ordered,
    }


def history_csv() -> str:
    """Render the history as CSV (UTF-8 with BOM so Excel keeps 中文)."""
    records = load_history()
    buffer = io.StringIO()
    buffer.write("\ufeff时间,站点,服务,作者,帖子ID,标题,帖子链接,文件数,跳过,失败,错误\n")
    writer = csv.writer(buffer)
    for record in records:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(record.get("ts", 0))))
        writer.writerow(
            [
                stamp,
                record.get("site", ""),
                record.get("service", ""),
                record.get("creatorId", ""),
                record.get("postId", ""),
                record.get("title", ""),
                record.get("url", ""),
                record.get("files", 0),
                record.get("skipped", 0),
                record.get("failures", 0),
                " | ".join(record.get("errors", []) or []),
            ]
        )
    return buffer.getvalue()


def clear_history() -> None:
    path = _history_path()
    try:
        path.write_text("", encoding="utf-8")
    except OSError as exc:
        safe_print(f"[gui] 无法清空下载记录：{exc}")


def build_job_argument(config: dict[str, Any]) -> tuple[list[str], list[str], list[str], str]:
    assert STATE is not None
    custom_file: str | None = None
    text = config.get("customVars") if isinstance(config.get("customVars"), str) else ""
    if text.strip():
        try:
            custom_file = write_custom_vars(text)
        except (OSError, json.JSONDecodeError) as exc:
            return [], [f"自定义变量写入失败：{exc}"], [], "下载任务"
    result = build_command(config, STATE.python, STATE.default_path, custom_vars_file=custom_file, frozen=FROZEN)
    return result.argv, result.errors, result.warnings, result.title


class Handler(BaseHTTPRequestHandler):
    server_version = "kemono-dl-gui"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _authorised(self) -> bool:
        assert STATE is not None
        token = self.headers.get("X-GUI-Token") or ""
        if secrets.compare_digest(token, STATE.token):
            return True
        self._error("unauthorised", HTTPStatus.UNAUTHORIZED)
        return False

    def _password_ok(self) -> bool:
        """HTTP Basic gate, active only when ``KEMONO_DL_GUI_PASSWORD`` is set."""
        password = auth_password()
        if basic_auth_ok(self.headers.get("Authorization") or "", password):
            return True
        self._send(
            HTTPStatus.UNAUTHORIZED,
            "authentication required".encode("utf-8"),
            "text/plain; charset=utf-8",
            {"WWW-Authenticate": 'Basic realm="kemono-dl GUI", charset="UTF-8"'},
        )
        return False

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"请求体不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if route == "/healthz":
                # Unauthenticated on purpose: container/orchestrator probes.
                self._send(HTTPStatus.OK, b"ok", "text/plain; charset=utf-8")
            elif not self._password_ok():
                return
            elif route in {"/", "/index.html"}:
                self._serve_index()
            elif route.startswith("/static/"):
                self._serve_static(route[len("/static/"):])
            elif route == "/favicon.ico":
                self._serve_static("logo.svg")
            elif route == "/api/meta":
                if self._authorised():
                    self._json(self._meta())
            elif route == "/api/state":
                if self._authorised():
                    self._json(self._state(query))
            elif route == "/api/fs":
                if self._authorised():
                    self._json(self._fs(query))
            elif route == "/api/history":
                if self._authorised():
                    self._json(history_summary())
            elif route == "/api/history/export":
                if self._authorised():
                    self._send(
                        HTTPStatus.OK,
                        history_csv().encode("utf-8"),
                        "text/csv; charset=utf-8",
                        {"Content-Disposition": 'attachment; filename="kemono-dl-history.csv"'},
                    )
            else:
                self._error("not found", HTTPStatus.NOT_FOUND)
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001 - report instead of dying
            self._error(f"服务器内部错误：{exc!r}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        route = urllib.parse.urlparse(self.path).path
        if not self._password_ok():
            return
        if not self._authorised():
            return
        try:
            payload = self._read_json()
            handlers = {
                "/api/preview": self._preview,
                "/api/validate": self._validate,
                "/api/run": self._run,
                "/api/stop": self._stop,
                "/api/upload": self._upload,
                "/api/open": self._open_folder,
                "/api/install-deps": self._install_deps,
                "/api/clear": self._clear,
                "/api/history/clear": self._history_clear,
                "/api/quit": self._quit,
            }
            handler = handlers.get(route)
            if handler is None:
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            handler(payload)
        except ValueError as exc:
            self._error(str(exc))
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"服务器内部错误：{exc!r}", HTTPStatus.INTERNAL_SERVER_ERROR)

    # -- page --------------------------------------------------------------
    def _serve_index(self) -> None:
        assert STATE is not None
        html = INDEX_HTML.read_text(encoding="utf-8").replace("__GUI_TOKEN__", STATE.token)
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static(self, relative: str) -> None:
        relative = urllib.parse.unquote(relative)
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._error("not found", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript"}:
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), content_type)

    # -- api ---------------------------------------------------------------
    def _meta(self) -> dict[str, Any]:
        assert STATE is not None
        return {
            "version": STATE.version,
            "python": STATE.python,
            "pythonVersion": sys.version.split()[0],
            "appVersion": STATE.version,
            "guiVersion": gui_version(),
            "hasRequests": STATE.requests_ok,
            "frozen": FROZEN,
            "installable": not FROZEN,
            "authRequired": bool(auth_password()),
            "defaultPath": STATE.default_path,
            "defaultTemplate": DEFAULT_TEMPLATE,
            "templateTypes": list(TEMPLATE_TYPES),
            "repoRoot": str(REPO_ROOT),
            "platform": sys.platform,
            "uptime": int(time.time() - STATE.start_time),
            "sampleVariables": sorted(args_module.SAMPLE_VARIABLES.keys()),
        }

    def _state(self, query: dict[str, list[str]]) -> dict[str, Any]:
        assert STATE is not None
        manager = STATE.manager
        job_id = (query.get("job") or [""])[0]
        since = int((query.get("since") or ["0"])[0] or 0)
        payload: dict[str, Any] = {"jobs": manager.summaries()}
        job = manager.get(job_id) if job_id else None
        if job is None:
            active = manager.active_job()
            job = active
        if job is not None:
            base, lines = job.lines_since(since)
            payload["job"] = job.summary()
            payload["lines"] = lines
            payload["base"] = base
        else:
            payload["job"] = None
            payload["lines"] = []
            payload["base"] = since
        return payload

    def _fs(self, query: dict[str, list[str]]) -> dict[str, Any]:
        raw = (query.get("path") or [""])[0].strip()
        want_files = (query.get("files") or ["0"])[0].lower() in {"1", "true", "yes", "on"}
        if not raw:
            raw = str(Path.home())
        raw = os.path.expandvars(os.path.expanduser(raw))
        target = Path(raw)
        if not target.is_absolute():
            target = Path.home() / target

        def listing(directory: Path) -> dict[str, Any]:
            payload: dict[str, Any] = {"dirs": self._dirs(directory)}
            if want_files:
                payload["files"] = self._files(directory)
            return payload

        if target.is_file():
            target = target.parent
        if not target.exists():
            fallback = Path.home()
            return {"path": str(fallback), "parent": str(fallback.parent), "drives": list_drives(), "missing": str(target), **listing(fallback)}
        try:
            entries = listing(target)
        except OSError as exc:
            payload = {"path": str(target), "parent": str(target.parent), "drives": list_drives(), "error": str(exc)}
            if want_files:
                payload["files"] = []
            return payload
        parent = str(target.parent) if target.parent != target else None
        return {"path": str(target), "parent": parent, "drives": list_drives(), **entries}

    @staticmethod
    def _dirs(target: Path) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    if entry.is_dir() and not entry.name.startswith("$"):
                        items.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
        items.sort(key=lambda item: item["name"].lower())
        return items

    @staticmethod
    def _files(target: Path, limit: int = 500) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    if entry.is_file():
                        items.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
        items.sort(key=lambda item: item["name"].lower())
        return items[:limit]

    def _preview(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        cfg = normalise_config(payload, STATE.default_path)
        custom_variables, errors = args_module.parse_custom_variables(cfg["custom_vars_text"])
        post_id = args_module.SAMPLE_VARIABLES["post_id"]
        file_overrides = {
            "attachments": None,
            "content": {"filename": "content.html", "file_name": "content", "file_ext": "html", "server_filename": "content.html"},
            "json": {"filename": f"{post_id}.json", "file_name": str(post_id), "file_ext": "json", "server_filename": f"{post_id}.json"},
        }
        paths: dict[str, Any] = {}
        for template_type in TEMPLATE_TYPES:
            template = cfg["templates"][template_type] if cfg["template_split"] else cfg["templates"]["attachments"]
            try:
                paths[template_type] = args_module.render_template(
                    template,
                    cfg["path"],
                    cfg["restrict_names"],
                    custom_variables,
                    overrides=file_overrides[template_type],
                )
            except args_module.TemplateError as exc:
                paths[template_type] = {"error": str(exc)}
        self._json({"paths": paths, "errors": errors})

    def _validate(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        argv, errors, warnings, title = build_job_argument(payload)
        rendered = args_module.build_command(payload, STATE.python, STATE.default_path, frozen=FROZEN)
        self._json(
            {
                "ok": not errors,
                "errors": errors,
                "warnings": warnings,
                "title": title,
                "command": shell_command(rendered.argv),
                "argv": argv,
            }
        )

    def _run(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        argv, errors, warnings, title = build_job_argument(payload)
        if errors:
            self._json({"ok": False, "errors": errors, "warnings": warnings}, HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        if not STATE.requests_ok:
            STATE.requests_ok = has_requests(STATE.python)
        if not STATE.requests_ok:
            self._json(
                {
                    "ok": False,
                    "errors": ["当前 Python 缺少 requests 依赖，请先在「关于」面板中点击「安装依赖」"],
                    "warnings": warnings,
                },
                HTTPStatus.PRECONDITION_FAILED,
            )
            return
        job = STATE.manager.submit(title, argv, dict(payload))
        self._json({"ok": True, "job": job.summary(), "warnings": warnings, "errors": []})

    def _stop(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        job_id = payload.get("jobId") or ""
        if not STATE.manager.stop(str(job_id)):
            self._error("任务不存在", HTTPStatus.NOT_FOUND)
            return
        self._json({"ok": True})

    def _quit(self, payload: dict[str, Any]) -> None:
        """Stop the server after politely stopping whatever is downloading.

        The portable ``.exe`` is built without a console window, so the browser is
        the only handle the user has on the process: without this endpoint the
        background server would outlive the page forever.
        """
        assert STATE is not None
        active = STATE.manager.active_job()
        if active is not None:
            STATE.manager.stop(active.id)
        self._json({"ok": True, "message": "连接已关闭，可以关闭此页面。"})
        threading.Thread(target=self._shutdown, name="gui-quit", daemon=True).start()

    def _shutdown(self) -> None:
        time.sleep(0.3)
        safe_print("[gui] 已退出（用户点击「退出程序」）。")
        try:
            self.server.shutdown()
        except Exception:  # noqa: BLE001 - already gone
            pass
        try:
            self.server.server_close()
        except Exception:  # noqa: BLE001
            pass
        if not FROZEN:
            return  # keep running when embedded in a notebook / test process
        time.sleep(0.2)
        os._exit(0)

    def _upload(self, payload: dict[str, Any]) -> None:
        filename = payload.get("filename")
        content = payload.get("content")
        if not isinstance(filename, str) or not isinstance(content, str):
            self._error("需要 filename 与 content 字段")
            return
        self._json({"path": upload_file(filename, content)})

    def _open_folder(self, payload: dict[str, Any]) -> None:
        target = payload.get("path")
        if not isinstance(target, str) or not target:
            self._error("缺少 path")
            return
        path = Path(target)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            self._error(f"无法打开文件夹：{exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._json({"ok": True})

    def _install_deps(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        if FROZEN:
            self._error("打包版已内置所有依赖，无需安装", HTTPStatus.BAD_REQUEST)
            return
        requirements = REPO_ROOT / "requirements.txt"
        argv = [STATE.python, "-u", "-m", "pip", "install", "-r", str(requirements)]
        job = STATE.manager.submit("安装依赖 (pip install -r requirements.txt)", argv, {"path": ""}, kind="setup")
        self._json({"ok": True, "job": job.summary()})

    def _clear(self, payload: dict[str, Any]) -> None:
        assert STATE is not None
        with STATE.manager.lock:
            for job_id in list(STATE.manager.order):
                job = STATE.manager.jobs.get(job_id)
                if job and job.status not in {"running", "queued"}:
                    STATE.manager.jobs.pop(job_id, None)
            STATE.manager.order = [job_id for job_id in STATE.manager.order if job_id in STATE.manager.jobs]
        self._json({"ok": True})

    def _history_clear(self, payload: dict[str, Any]) -> None:
        clear_history()
        self._json({"ok": True, "history": history_summary()})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(host: str = "127.0.0.1", port: int = 0) -> Server:
    return Server((host, port), Handler)


def safe_print(message: str) -> None:
    """``print`` that survives a windowed (frozen) build where stdout is None."""
    try:
        print(message, flush=True)
    except (OSError, ValueError, AttributeError):
        pass


def show_error(message: str) -> None:
    """Surface a fatal error even when there is no console (double-clicked exe)."""
    safe_print(message)
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "kemono-dl GUI", 0x10)
    except Exception:  # noqa: BLE001 - best effort only
        pass


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    global STATE, APP_DATA, UPLOAD_DIR, CUSTOM_VARS_FILE
    APP_DATA = ensure_dir(app_data_dir())
    UPLOAD_DIR = APP_DATA / "uploads"
    CUSTOM_VARS_FILE = APP_DATA / "custom-template-variables.json"
    if CUSTOM_VARS_FILE.exists():
        try:
            CUSTOM_VARS_FILE.unlink()
        except OSError:
            pass

    STATE = AppState()
    try:
        server = create_server(host, port)
    except OSError as exc:
        if port == 0:
            show_error(f"无法启动本地服务：{exc}")
            raise
        safe_print(f"端口 {port} 不可用（{exc}），改用随机端口")
        try:
            server = create_server(host, 0)
        except OSError as retry_exc:
            show_error(f"无法启动本地服务：{retry_exc}")
            raise

    actual_port = server.server_address[1]
    wildcard = host in {"0.0.0.0", "::", ""}
    url = f"http://{'127.0.0.1' if wildcard else host}:{actual_port}/"
    safe_print(f"kemono-dl GUI · {url}")
    if wildcard:
        safe_print(f"监听所有网卡 {host}:{actual_port}（Docker / 远程访问）")
    if auth_password():
        safe_print("已启用访问密码（HTTP Basic），浏览器会弹窗要求登录")
    elif wildcard:
        safe_print("警告：当前没有访问密码，能连到这个端口的人都能操作下载；请设置 KEMONO_DL_GUI_PASSWORD")
    safe_print("按 Ctrl+C 结束服务")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("\n正在关闭…")
    finally:
        server.shutdown()
        server.server_close()
