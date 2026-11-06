import os
import time

from .session import CustomSession
from .utils import format_bytes

#: Minimum delay between two progress repaints (seconds).
PROGRESS_INTERVAL = 0.1

#: Minimum delay between two requests to a file server (seconds, 0 = off).
REQUEST_INTERVAL = 1.0
#: Timestamp of the last file server request, used by :func:`_throttle`.
_last_request = 0.0

#: Returned when the local file was already complete and nothing was fetched.
STATUS_SKIPPED = "skipped"
#: Returned when an existing partial file was continued with a Range request.
STATUS_RESUMED = "resumed"
#: Returned when the file was downloaded from byte zero.
STATUS_DOWNLOADED = "downloaded"


def set_request_interval(seconds: float) -> None:
    """Configure the global delay applied before every file server request.

    Pawchive's file host (DDoS-Guard) answers with ``403`` when it sees more
    than about one request per second, so the default is deliberately polite.
    """
    global REQUEST_INTERVAL
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 1.0
    if value != value:  # NaN
        value = 1.0
    REQUEST_INTERVAL = max(0.0, value)


def _throttle() -> None:
    """Sleep just enough to keep ``REQUEST_INTERVAL`` between two requests."""
    global _last_request
    if REQUEST_INTERVAL <= 0:
        return
    now = time.monotonic()
    wait = _last_request + REQUEST_INTERVAL - now
    if wait > 0:
        time.sleep(wait)
        now = time.monotonic()
    _last_request = now


def get_remote_size(session: CustomSession, url: str, timeout: int = 30) -> int:
    """Best effort remote size lookup: HEAD first, then a one byte Range probe.

    Returns ``0`` when the server exposes nothing useful, in which case the
    caller falls back to unknown-size behaviour instead of guessing.
    """
    try:
        _throttle()
        with session.head(url, allow_redirects=True, timeout=timeout) as response:
            if getattr(response, "ok", True):
                size = int(response.headers.get("content-length") or 0)
                if size > 0:
                    return size
    except Exception:
        pass

    try:
        with session.get(
            url, stream=True, allow_redirects=True, headers={"Range": "bytes=0-0"}, timeout=timeout
        ) as response:
            content_range = response.headers.get("content-range") or ""
            if "/" in content_range:
                total = content_range.rsplit("/", 1)[-1].strip()
                if total.isdigit():
                    return int(total)
            if getattr(response, "status_code", 200) == 200:
                size = int(response.headers.get("content-length") or 0)
                if size > 0:
                    return size
    except Exception:
        pass

    return 0


def _progress_line(downloaded: int, total_size: int, started: float) -> str:
    elapsed = time.time() - started
    speed = downloaded / elapsed if elapsed > 0 else 0
    remaining = max(total_size - downloaded, 0)
    eta = remaining / speed if speed > 0 else 0
    percent = (downloaded / total_size) * 100 if total_size else 0.0
    when = time.strftime("%H:%M:%S", time.gmtime(eta))
    return (
        f"[downloading] {percent:6.2f}% of {format_bytes(total_size)} "
        f"eta {when} at {format_bytes(speed)}/s"
    )


def download_file(
    session: CustomSession,
    url: str,
    filepath: str,
    chunk_size: int = 8192,
    temp_file: bool = True,
    overwrite: bool = False,
) -> str:
    """Download ``url`` into ``filepath``, resuming and skipping when possible.

    Behaviour:

    * the final file already has the remote size -> nothing is fetched (``skipped``);
    * only a partial file / ``.tmp`` exists -> a ``Range`` request continues it,
      and a server that ignores ``Range`` (HTTP 200) restarts cleanly instead
      of producing a corrupted file;
    * the finished size does not match the remote size -> the ``.tmp`` stays on
      disk and an exception is raised, so the caller's retry loop can reconnect
      and continue from where it stopped.
    """
    print(f"[downloading] Source: {url!r}")
    print(f"[downloading] Destination: {filepath!r}")

    temp_filepath = filepath + ".tmp" if temp_file else filepath
    final_size = os.path.getsize(filepath) if os.path.exists(filepath) else -1
    temp_size = os.path.getsize(temp_filepath) if os.path.exists(temp_filepath) else -1

    # Only ask the server for its size when there is something local to compare
    # against: a fresh download learns the size from the GET response anyway, and
    # skipping the probe halves the request count (which matters for the 1 req/s
    # politeness limit of the pawchive file host).
    has_local = final_size >= 0 or temp_size >= 0
    remote_size = 0 if (overwrite or not has_local) else get_remote_size(session, url)

    if overwrite and temp_file and temp_size >= 0:
        os.remove(temp_filepath)
        temp_size = -1

    if not overwrite:
        if remote_size and final_size == remote_size:
            print(f"[skip] Already downloaded, size verified ({format_bytes(remote_size)})")
            return STATUS_SKIPPED

        if remote_size and final_size > remote_size:
            print(
                f"[warning] Local file is {format_bytes(final_size)} but remote is "
                f"{format_bytes(remote_size)}; keeping the local copy"
            )
            return STATUS_SKIPPED

        if not remote_size and final_size >= 0:
            print("[skip] File already exists and the remote size is unknown; keeping it")
            return STATUS_SKIPPED

        if temp_file and remote_size and 0 <= final_size < remote_size and temp_size < 0:
            # Left over from an older version (or a crash without --no-tmp):
            # turn the partial final file into a resumable temp file.
            os.replace(filepath, temp_filepath)
            temp_size = final_size
            print(
                f"[info] Continuing an existing partial file "
                f"({format_bytes(final_size)} of {format_bytes(remote_size)})"
            )

    headers = {}
    mode = "wb"
    downloaded = 0
    if temp_file and temp_size > 0:
        downloaded = temp_size
        headers = {"Range": f"bytes={downloaded}-"}
        mode = "ab"
        print(f"[downloading] Resuming partially downloaded file ({format_bytes(downloaded)})")

    resumed = downloaded > 0
    started = time.time()
    progress = ""
    last_report = 0.0
    expected_size = remote_size or 0

    _throttle()
    with session.get(
        url, stream=True, allow_redirects=True, headers=headers, timeout=60
    ) as response:
        status_code = getattr(response, "status_code", 200)

        if resumed and status_code == 200:
            print("[warning] Server ignored the Range request; restarting from zero")
            resumed = False
            downloaded = 0
            mode = "wb"
        elif resumed and status_code == 416:
            # Nothing left to fetch: the temp file is already at least as big
            # as the remote object, so finish (or restart if it is too big).
            response.close()
            if remote_size and downloaded == remote_size:
                os.replace(temp_filepath, filepath)
                print(f"[skip] File was already complete ({format_bytes(downloaded)})")
                return STATUS_RESUMED
            print("[warning] Range request rejected; restarting from zero")
            resumed = False
            downloaded = 0
            mode = "wb"
            return download_file(
                session, url, filepath, chunk_size=chunk_size, temp_file=temp_file, overwrite=True
            )

        response.raise_for_status()

        content_length = int(response.headers.get("content-length") or 0)
        total_size = remote_size or (content_length + downloaded)
        expected_size = total_size or 0
        started = time.time()

        with open(temp_filepath, mode) as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                progress = _progress_line(downloaded, total_size, started)
                now = time.time()
                if now - last_report >= PROGRESS_INTERVAL:
                    last_report = now
                    # ``\r`` repaints the line in a terminal and the GUI reads
                    # every repaint as one live progress tick.
                    print(progress.ljust(100), end="\r", flush=True)

    if progress:
        print(progress.ljust(100), flush=True)

    actual_size = os.path.getsize(temp_filepath)
    if expected_size and actual_size != expected_size:
        raise IOError(
            f"incomplete download: got {format_bytes(actual_size)} of "
            f"{format_bytes(expected_size)}, keeping {os.path.basename(temp_filepath)!r} for resume"
        )

    if temp_file:
        os.replace(temp_filepath, filepath)
    return STATUS_RESUMED if resumed else STATUS_DOWNLOADED
