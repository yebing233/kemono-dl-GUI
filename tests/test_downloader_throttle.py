"""请求限速（--request-interval）的行为约束。

pawchive 的文件服务器（DDoS-Guard）明确要求「每秒不超过 1 个请求、同时最多 5 个下载」，
所以下载器默认在每次文件服务器请求前等一会儿；这些测试固定住三件事：

* 默认值与非法值都会落到安全区间；
* 间隔为 0 时完全不睡；
* 全新下载只发一次请求（不额外浪费一次 HEAD 探测）。
"""

from __future__ import annotations

import shutil
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from kemono_dl import downloader


def workdir() -> Path:
    """``tempfile`` is unusable in the development sandbox, so keep scratch files here."""
    path = Path(__file__).resolve().parent.parent / ".build" / "test-tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class IntervalSettingTests(unittest.TestCase):
    def tearDown(self) -> None:
        downloader.set_request_interval(1.0)

    def test_default_is_one_second(self) -> None:
        self.assertEqual(downloader.REQUEST_INTERVAL, 1.0)

    def test_zero_disables_the_delay(self) -> None:
        downloader.set_request_interval(0)
        self.assertEqual(downloader.REQUEST_INTERVAL, 0.0)

    def test_negative_is_clamped_to_zero(self) -> None:
        downloader.set_request_interval(-5)
        self.assertEqual(downloader.REQUEST_INTERVAL, 0.0)

    def test_garbage_falls_back_to_one_second(self) -> None:
        downloader.set_request_interval("not-a-number")
        self.assertEqual(downloader.REQUEST_INTERVAL, 1.0)

    def test_nan_falls_back_to_one_second(self) -> None:
        downloader.set_request_interval(float("nan"))
        self.assertEqual(downloader.REQUEST_INTERVAL, 1.0)


class ThrottleTests(unittest.TestCase):
    def tearDown(self) -> None:
        downloader.set_request_interval(1.0)

    def test_throttle_waits_between_two_calls(self) -> None:
        downloader.set_request_interval(0.25)
        downloader._last_request = 0.0
        downloader._throttle()  # first call never waits
        started = time.monotonic()
        downloader._throttle()
        self.assertGreaterEqual(time.monotonic() - started, 0.2)

    def test_zero_interval_does_not_sleep(self) -> None:
        downloader.set_request_interval(0)
        with mock.patch.object(time, "sleep") as sleeper:
            downloader._throttle()
            downloader._throttle()
        sleeper.assert_not_called()

    def test_throttle_is_applied_before_the_requests(self) -> None:
        downloader.set_request_interval(0)
        with mock.patch.object(downloader, "_throttle") as throttle:
            downloader.get_remote_size(mock.Mock(head=mock.Mock(side_effect=OSError("no head"))), "http://x/y")
        self.assertGreaterEqual(throttle.call_count, 1)


class RequestCountTests(unittest.TestCase):
    """A fresh download must not spend an extra request on a size probe."""

    def setUp(self) -> None:
        downloader.set_request_interval(0)
        self.folder = workdir()
        self.target = self.folder / "file.bin"

    def tearDown(self) -> None:
        downloader.set_request_interval(1.0)
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_fresh_download_probes_no_size(self) -> None:
        session = mock.Mock()
        response = mock.MagicMock()
        response.status_code = 200
        response.headers = {"content-length": "4"}
        response.iter_content.return_value = [b"data"]
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        session.get.return_value = response
        with mock.patch.object(downloader, "get_remote_size") as probe:
            status = downloader.download_file(session, "http://server/file.bin", str(self.target))
        probe.assert_not_called()
        self.assertEqual(status, downloader.STATUS_DOWNLOADED)
        self.assertEqual(self.target.read_bytes(), b"data")

    def test_existing_file_probes_the_size(self) -> None:
        self.target.write_bytes(b"data")
        session = mock.Mock()
        with mock.patch.object(downloader, "get_remote_size", return_value=4) as probe:
            status = downloader.download_file(session, "http://server/file.bin", str(self.target))
        probe.assert_called_once()
        self.assertEqual(status, downloader.STATUS_SKIPPED)
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
