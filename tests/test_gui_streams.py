"""Regression tests for the frozen-build text streams.

The portable exe runs the downloader as ``kemono-dl-gui.exe --run-cli ...``.
Because it is a windowed (console=False) PyInstaller build, the bootloader
ignores ``PYTHONUTF8``/``PYTHONIOENCODING``, so CPython used to create
``sys.stdout`` with the Windows ANSI code page (GBK on zh-CN) and every post
whose title contained a character outside GBK — e.g. U+30FB KATAKANA MIDDLE DOT
from a Japanese title — crashed the download with::

    UnicodeEncodeError: 'gbk' codec can't encode character '\\u30fb'

``_ensure_std_streams()`` must therefore *reconfigure* an existing stream, not
only recreate a missing one.
"""

from __future__ import annotations

import io
import sys
import unittest

from kemono_dl_gui.__main__ import _ensure_std_streams

JAPANESE_TITLE = "【限定】ゆるキャラ・ステッカー セット"


class StdStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._stdout = sys.stdout
        self._stderr = sys.stderr

    def tearDown(self) -> None:
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def test_existing_gbk_stream_is_reconfigured(self) -> None:
        buffer = io.BytesIO()
        sys.stdout = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
        sys.stderr = io.StringIO()

        _ensure_std_streams()

        self.assertEqual(sys.stdout.encoding.replace("-", "").lower(), "utf8")
        sys.stdout.write(JAPANESE_TITLE + "\n")
        sys.stdout.flush()
        self.assertIn(JAPANESE_TITLE, buffer.getvalue().decode("utf-8"))

    def test_gbk_stream_would_have_failed(self) -> None:
        # documents the bug: without the fix the very same write raises
        stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
        with self.assertRaises(UnicodeEncodeError):
            stream.write(JAPANESE_TITLE)
            stream.flush()

    def test_missing_stream_is_recreated(self) -> None:
        sys.stdout = None  # type: ignore[assignment]
        sys.stderr = None  # type: ignore[assignment]

        _ensure_std_streams()

        self.assertIsNotNone(sys.stdout)
        self.assertIsNotNone(sys.stderr)
        self.assertEqual(sys.stdout.encoding.replace("-", "").lower(), "utf8")
        sys.stdout.write(JAPANESE_TITLE)  # must not raise

    def test_plain_stringio_is_replaced(self) -> None:
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        _ensure_std_streams()

        self.assertNotIsInstance(sys.stdout, io.StringIO)
        self.assertEqual(sys.stdout.encoding.replace("-", "").lower(), "utf8")

    def test_unbuffered_child_stream_bypasses_the_text_buffer(self) -> None:
        """``--run-cli`` must not wait for an 8 KiB buffer to fill up.

        The frozen child inherited a block-buffered ``sys.stdout``: progress and
        log lines only reached the GUI in bursts (appearing as "进度不同步").
        """
        import os
        import tempfile

        with tempfile.TemporaryFile() as handle:
            original = os.dup(1)
            try:
                os.dup2(handle.fileno(), 1)
                sys.stdout = io.TextIOWrapper(io.FileIO(1, "w", closefd=False), encoding="gbk", errors="strict")
                _ensure_std_streams(unbuffered=True)
                self.assertTrue(sys.stdout.write_through)
                self.assertFalse(sys.stdout.line_buffering)
                sys.stdout.write(JAPANESE_TITLE)  # no newline, no flush()
            finally:
                os.dup2(original, 1)
                os.close(original)
            handle.seek(0)
            written = handle.read()

        self.assertEqual(written.decode("utf-8"), JAPANESE_TITLE)


if __name__ == "__main__":
    unittest.main()
