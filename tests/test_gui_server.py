"""Unit tests for the server helpers used by the Docker / remote deployment."""

from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path
from unittest import mock

from kemono_dl_gui import __version__ as gui_version_string
from kemono_dl_gui import server


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")


class DownloadPathTests(unittest.TestCase):
    def test_env_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"KEMONO_DL_GUI_DOWNLOAD_DIR": "/downloads"}, clear=False):
            self.assertEqual(server.default_download_path(), str(Path("/downloads")))

    def test_windows_style_override(self) -> None:
        with mock.patch.dict(os.environ, {"KEMONO_DL_GUI_DOWNLOAD_DIR": "D:/media/kemono"}, clear=False):
            self.assertEqual(server.default_download_path(), str(Path("D:/media/kemono")))

    def test_falls_back_to_home_downloads(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEMONO_DL_GUI_DOWNLOAD_DIR", None)
            self.assertEqual(
                server.default_download_path(),
                str(Path.home() / "Downloads" / "kemono-dl"),
            )


class DataDirTests(unittest.TestCase):
    def test_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"KEMONO_DL_GUI_DATA": "/data"}, clear=False):
            self.assertEqual(server.app_data_dir(), Path("/data"))

    def test_default_is_under_appdata(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in ("KEMONO_DL_GUI_DATA", "LOCALAPPDATA", "APPDATA"):
                os.environ.pop(name, None)
            self.assertEqual(server.app_data_dir(), Path.home() / ".kemono-dl-gui")


class BasicAuthTests(unittest.TestCase):
    def test_disabled_without_password(self) -> None:
        self.assertTrue(server.basic_auth_ok("", ""))
        self.assertTrue(server.basic_auth_ok("Basic abc", ""))

    def test_accepts_correct_password(self) -> None:
        self.assertTrue(server.basic_auth_ok(basic("anything", "s3cret"), "s3cret"))

    def test_username_is_ignored(self) -> None:
        self.assertTrue(server.basic_auth_ok(basic("", "s3cret"), "s3cret"))
        self.assertTrue(server.basic_auth_ok(basic("kemono", "s3cret"), "s3cret"))

    def test_rejects_wrong_password(self) -> None:
        self.assertFalse(server.basic_auth_ok(basic("kemono", "nope"), "s3cret"))

    def test_rejects_missing_or_broken_header(self) -> None:
        self.assertFalse(server.basic_auth_ok("", "s3cret"))
        self.assertFalse(server.basic_auth_ok("Bearer abc", "s3cret"))
        self.assertFalse(server.basic_auth_ok("Basic !!!not-base64!!!", "s3cret"))
        self.assertFalse(server.basic_auth_ok("Basic " + base64.b64encode(b"no-colon").decode(), "s3cret"))


class MetaTests(unittest.TestCase):
    def test_gui_version_helper_matches_package(self) -> None:
        self.assertEqual(server.gui_version(), gui_version_string)
        self.assertNotEqual(server.gui_version(), "unknown")


class ProgressParsingTests(unittest.TestCase):
    """The progress line is repainted with ``\\r`` many times per second."""

    @staticmethod
    def line(percent: float, speed: str = "1.2 MB/s", eta: str = "00:00:12") -> str:
        return f"[downloading] {percent:6.2f}% of 10.00 MiB eta {eta} at {speed}"

    def job(self) -> server.Job:
        return server.Job("job-1", "demo", ["python", "-u"], {}, kind="download")

    def test_tick_moves_the_bar_without_logging(self) -> None:
        job = self.job()
        job.append(self.line(3.0))
        self.assertAlmostEqual(job.progress["percent"], 3.0)
        self.assertEqual(job.progress["speed"], "1.2 MB/s")
        self.assertEqual(job.progress["eta"], "00:00:12")
        self.assertEqual(job.lines, [])

    def test_log_keeps_one_line_per_step(self) -> None:
        job = self.job()
        for percent in (0.4, 3.0, 5.2, 7.0, 99.6):
            job.append(self.line(percent))
        self.assertEqual(len(job.lines), 2)
        self.assertIn("5.20%", job.lines[0])
        self.assertIn("99.60%", job.lines[1])
        self.assertAlmostEqual(job.progress["percent"], 99.6)

    def test_post_and_file_counters(self) -> None:
        job = self.job()
        job.append("[downloading] Post: '限定・セット'")
        job.append("[downloading] Destination: 'a.png'")
        self.assertEqual(job.progress["posts"], 1)
        # a destination line means the file *started*; it counts as downloaded
        # only once the next file begins (or the job ends)
        self.assertEqual(job.progress["files"], 0)
        job.append("[downloading] Destination: 'b.png'")
        self.assertEqual(job.progress["files"], 1)

    def test_pending_follows_attachment_count(self) -> None:
        job = self.job()
        job.append("[downloading] Post: 'one'")
        job.append("[downloading] Attachments: 3")
        self.assertEqual(job.progress["pending"], 3)
        job.append("[downloading] Destination: 'a.png'")
        job.append(self.line(50.0))
        self.assertEqual(job.progress["pending"], 3)  # nothing finished yet
        job.append(self.line(100.0))
        job.append("[downloading] Destination: 'b.png'")
        self.assertEqual(job.progress["pending"], 2)
        self.assertEqual(job.progress["files"], 1)

    def test_bytes_downloaded_and_remaining(self) -> None:
        job = self.job()
        job.append("[downloading] Attachments: 4")
        job.append("[downloading] Destination: 'a.png'")
        for percent in (25.0, 100.0):
            job.append(self.line(percent))
        job.append("[downloading] Destination: 'b.png'")
        job.append(self.line(50.0))
        # 10 MiB finished, 5 MiB of the current file done
        self.assertEqual(job.progress["downloaded"], 15 * 1024 * 1024)
        # 5 MiB left in the current file + 2 queued files at the 10 MiB average
        self.assertEqual(job.progress["remaining"], 25 * 1024 * 1024)
        self.assertEqual(job.progress["bytesPerFile"], 10 * 1024 * 1024)
        self.assertEqual(job.progress["pending"], 3)

    def test_finish_progress_clears_pending(self) -> None:
        job = self.job()
        job.append("[downloading] Attachments: 2")
        job.append("[downloading] Destination: 'a.png'")
        job.append(self.line(42.0))
        job.finish_progress(success=False)
        self.assertEqual(job.progress["pending"], 0)
        self.assertEqual(job.progress["remaining"], 0)
        self.assertAlmostEqual(job.progress["percent"], 42.0)

        job = self.job()
        job.append("[downloading] Attachments: 1")
        job.append("[downloading] Destination: 'a.png'")
        job.append(self.line(100.0))
        job.finish_progress(success=True)
        self.assertEqual(job.progress["percent"], 100.0)
        self.assertEqual(job.progress["files"], 1)
        self.assertEqual(job.progress["pending"], 0)

    def test_next_file_restarts_the_bar(self) -> None:
        job = self.job()
        job.append(self.line(80.0))
        job.append("[downloading] Destination: 'b.zip'")
        self.assertEqual(job.progress["percent"], 0.0)
        job.append(self.line(1.0))
        self.assertEqual(len(job.lines), 2)  # "Destination:" + the 80 % tick
        self.assertAlmostEqual(job.progress["percent"], 1.0)


if __name__ == "__main__":
    unittest.main()
