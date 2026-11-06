"""The downloader must emit live progress even when stdout is a pipe.

Regression: ``download_file`` only repainted its progress line when
``sys.stdout.isatty()`` was true, so the GUI (which always pipes stdout) saw a
single line per file — the progress bar in the web UI stayed at 0 % until the
file was complete.
"""

from __future__ import annotations

import io
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from kemono_dl import downloader

CHUNK = 64 * 1024
CHUNKS = 5
TOTAL = CHUNK * CHUNKS


def workdir() -> Path:
    """A throw-away directory next to the sources (sandbox friendly)."""
    path = Path(__file__).resolve().parent.parent / ".build" / "test-tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class FakeResponse:
    headers = {"content-length": str(TOTAL)}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for _ in range(CHUNKS):
            yield b"x" * chunk_size

    def __enter__(self):  # pragma: no cover - context manager plumbing
        return self

    def __exit__(self, *exc_info) -> None:  # pragma: no cover
        return None


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


class ProgressOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._stdout = sys.stdout
        self.buffer = io.StringIO()
        sys.stdout = self.buffer
        patcher = mock.patch.object(downloader, "PROGRESS_INTERVAL", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        sys.stdout = self._stdout

    def test_pipe_gets_one_tick_per_chunk(self) -> None:
        folder = workdir()
        self.addCleanup(shutil.rmtree, folder, True)
        target = folder / "a.bin"
        downloader.download_file(FakeSession(), "http://example.invalid/a.bin", str(target), chunk_size=CHUNK, temp_file=False)
        self.assertEqual(target.stat().st_size, TOTAL)

        output = self.buffer.getvalue()
        self.assertEqual(output.count("\r"), CHUNKS)
        self.assertTrue(output.endswith("\n"), "the last paint must end with a newline")
        self.assertIn("[downloading]  20.00% of", output)
        self.assertIn("[downloading] 100.00% of", output)

    def test_unknown_size_does_not_crash(self) -> None:
        class NoLength(FakeResponse):
            headers: dict[str, str] = {}

        class Session:
            def get(self, *args, **kwargs):
                return NoLength()

        folder = workdir()
        self.addCleanup(shutil.rmtree, folder, True)
        target = folder / "b.bin"
        downloader.download_file(Session(), "http://example.invalid/b.bin", str(target), chunk_size=CHUNK, temp_file=False)
        self.assertEqual(target.stat().st_size, TOTAL)

        self.assertIn("0.00% of", self.buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
