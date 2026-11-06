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

    def test_skipped_files_are_counted(self) -> None:
        job = self.job()
        job.append("[downloading] Attachments: 2")
        job.append("[downloading] Destination: 'a.png'")
        job.append("[skip] Already downloaded, size verified (5.00 MiB)")
        self.assertEqual(job.progress["skipped"], 1)
        # a skipped file needs no download, so it leaves the queue
        self.assertEqual(job.progress["pending"], 1)

    def test_resume_lines_do_not_touch_counters(self) -> None:
        job = self.job()
        job.append("[downloading] Destination: 'b.png'")
        job.append("[downloading] Resuming partially downloaded file (2.00 MiB of 10.00 MiB)")
        self.assertEqual(job.progress["skipped"], 0)
        self.assertEqual(job.progress["files"], 0)

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


POST_A = "https://kemono.cr/patreon/user/12345/post/67890"
POST_B = "https://pawchive.pw/fanbox/user/72927321/post/111"
FAIL_A = (
    "[Error] Failed to download attachment from "
    "'https://file.pawchive.pw/data/aa/bb/cc.mp4?f=Momoko_.mp4' (1/3): 404 Client Error: Not Found"
)


class FailureTrackingTests(unittest.TestCase):
    """The GUI must remember which post a failed attachment belongs to."""

    def job(self) -> server.Job:
        return server.Job("job-1", "demo", ["x"], {}, kind="download")

    def test_failure_keeps_the_post_url(self) -> None:
        job = self.job()
        job.append(f"[downloading] Post URL: {POST_A}")
        job.append("[downloading] Post: 限定・ステッカー")
        job.append(FAIL_A)
        failures = job.summary()["failures"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["postUrl"], POST_A)
        self.assertIn("data/aa/bb/cc.mp4", failures[0]["fileUrl"])
        self.assertEqual(failures[0]["attempt"], 1)
        self.assertEqual(failures[0]["total"], 3)
        self.assertIn("404", failures[0]["message"])

    def test_no_failures_for_clean_runs(self) -> None:
        job = self.job()
        job.append(f"[downloading] Post URL: {POST_A}")
        job.append("[downloading] 100.00% of 1.00 MiB eta 00:00:00 at 1.0 MB/s")
        self.assertEqual(job.summary()["failures"], [])


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(__file__).resolve().parent.parent / ".build" / "test-tmp" / "history-test"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.previous = server.APP_DATA
        server.APP_DATA = self.folder
        server._history_path().write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        server.APP_DATA = self.previous
        server._history_path()
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    def lines(self, post: str, files: int = 2, failures: int = 0) -> list[str]:
        lines = [
            f"[downloading] Post URL: {post}",
            f"[downloading] Post: 限定・ステッカー {post.rsplit('/', 1)[-1]}",
            f"[downloading] Attachments: {files}",
        ]
        for index in range(files):
            lines.append(f"[downloading] Destination: 'file{index}.png'")
        lines.append("[skip] Already downloaded, size verified (1.00 MiB)")
        for _ in range(failures):
            lines.append(FAIL_A)
        return lines

    def test_parse_groups_lines_per_post(self) -> None:
        records = server.parse_post_records(self.lines(POST_A, files=2) + self.lines(POST_B, files=1, failures=1))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["site"], "kemono.cr")
        self.assertEqual(records[0]["service"], "patreon")
        self.assertEqual(records[0]["creatorId"], "12345")
        self.assertEqual(records[0]["postId"], "67890")
        self.assertEqual(records[0]["files"], 2)
        self.assertEqual(records[0]["failures"], 0)
        self.assertEqual(records[1]["site"], "pawchive.pw")
        self.assertEqual(records[1]["service"], "fanbox")
        self.assertEqual(records[1]["creatorId"], "72927321")
        self.assertEqual(records[1]["failures"], 1)
        self.assertEqual(records[1]["errors"], ["404 Client Error: Not Found"])

    def test_history_dedupes_and_summarises_creators(self) -> None:
        server.append_history(server.parse_post_records(self.lines(POST_A)))
        server.append_history(server.parse_post_records(self.lines(POST_A, files=5, failures=0)))
        server.append_history(server.parse_post_records(self.lines(POST_B, files=1, failures=1)))
        summary = server.history_summary()
        self.assertEqual(summary["posts"], 2)
        keys = {creator["key"]: creator for creator in summary["creators"]}
        self.assertIn("kemono.cr/patreon/12345", keys)
        self.assertEqual(keys["kemono.cr/patreon/12345"]["posts"], 1)
        self.assertEqual(keys["kemono.cr/patreon/12345"]["files"], 5)  # newest record wins
        self.assertEqual(keys["pawchive.pw/fanbox/72927321"]["failures"], 1)
        self.assertEqual(keys["pawchive.pw/fanbox/72927321"]["latest"]["url"], POST_B)

    def test_csv_export_has_a_bom_and_the_author(self) -> None:
        server.append_history(server.parse_post_records(self.lines(POST_A)))
        text = server.history_csv()
        self.assertTrue(text.startswith("\ufeff"), "Excel needs the BOM to read UTF-8")
        self.assertIn("作者", text)
        self.assertIn("12345", text)
        self.assertIn(POST_A, text)

    def test_clear_history_empties_the_file(self) -> None:
        server.append_history(server.parse_post_records(self.lines(POST_A)))
        server.clear_history()
        self.assertEqual(server.load_history(), [])
        self.assertEqual(server.history_summary()["posts"], 0)


if __name__ == "__main__":
    unittest.main()
