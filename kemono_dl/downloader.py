import os
import time

from .session import CustomSession
from .utils import format_bytes

#: Minimum delay between two progress repaints (seconds).
PROGRESS_INTERVAL = 0.1


def download_file(session: CustomSession, url: str, filepath: str, chunk_size: int = 8192, temp_file: bool = True) -> None:
    print(f"[downloading] Source: {url!r}")
    print(f"[downloading] Destination: {filepath!r}")

    headers = {}
    mode = "wb"
    downloaded = 0
    temp_filepath = filepath

    if temp_file:
        temp_filepath = filepath + ".tmp"
        if os.path.exists(temp_filepath):
            downloaded = os.path.getsize(temp_filepath)
            headers = {"Range": f"bytes={downloaded}-"}
            mode = "ab"
            print("[downloading] Resuming partially downloaded file")

    with session.get(url, stream=True, allow_redirects=True, headers=headers) as response:
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0)) + downloaded

        start_time = time.time()
        progress = ""
        last_report = 0.0

        with open(temp_filepath, mode) as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    elapsed = time.time() - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    remaining = total_size - downloaded
                    eta = remaining / speed if speed > 0 else 0

                    percent = (downloaded / total_size) * 100 if total_size else 0.0
                    progress = f"[downloading] {percent:6.2f}% of {format_bytes(total_size)} eta {time.strftime('%H:%M:%S', time.gmtime(eta))} at {format_bytes(speed)}/s"
                    now = time.time()
                    if now - last_report >= PROGRESS_INTERVAL:
                        last_report = now
                        # ``\r`` repaints the line in a terminal and the GUI reads
                        # every repaint as one live progress tick.
                        print(progress.ljust(100), end="\r", flush=True)
        print(progress.ljust(100), flush=True)

    if temp_file:
        os.replace(temp_filepath, filepath)
