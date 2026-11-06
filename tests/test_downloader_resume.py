"""断点续传 / 已下载校验：downloader 的行为约束。

覆盖：本地文件大小与远端一致时直接跳过、只有部分文件时用 Range 续传、
服务端忽略 Range 时重新从头写（避免拼接出坏文件）、416 收尾、下载不完整时
保留 .tmp 并抛错交给调用方重连重试。
"""

from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from kemono_dl import downloader

PAYLOAD = bytes(range(256)) * 40  # 10240 字节
CHUNK = 1024


def setUpModule() -> None:
    """The default 1 s politeness delay would make this suite crawl."""
    downloader.set_request_interval(0)


def tearDownModule() -> None:
    downloader.set_request_interval(1.0)


def workdir() -> Path:
    path = Path(__file__).resolve().parent.parent / ".build" / "test-tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class FakeResponse:
    def __init__(self, body: bytes = b"", status_code: int = 200, headers: dict | None = None) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def iter_content(self, chunk_size: int = 8192):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index : index + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class FakeSession:
    """A tiny HTTP server: honours Range unless told otherwise."""

    def __init__(
        self,
        payload: bytes = PAYLOAD,
        honour_range: bool = True,
        expose_size: bool = True,
        truncated: int | None = None,
    ) -> None:
        self.payload = payload
        self.honour_range = honour_range
        self.expose_size = expose_size
        self.truncated = truncated
        self.get_calls: list[str | None] = []
        self.head_calls = 0

    def head(self, url, allow_redirects=True, timeout=None):
        self.head_calls += 1
        if not self.expose_size:
            raise RuntimeError("405 HEAD not supported")
        return FakeResponse(b"", 200, {"content-length": str(len(self.payload))})

    def get(self, url, stream=False, allow_redirects=True, headers=None, timeout=None):
        requested = (headers or {}).get("Range")
        self.get_calls.append(requested)
        start = 0
        end: int | None = None
        if requested and self.honour_range:
            first, _, last = requested.split("=", 1)[1].partition("-")
            start = int(first or 0)
            end = int(last) if last else None
            if start >= len(self.payload):
                return FakeResponse(b"", 416, {"content-range": f"bytes */{len(self.payload)}"})
            body = self.payload[start : (end + 1) if end is not None else len(self.payload)]
            return FakeResponse(
                body,
                206,
                {
                    "content-length": str(len(body)),
                    "content-range": f"bytes {start}-{start + len(body) - 1}/{len(self.payload)}",
                },
            )

        body = self.payload if self.truncated is None else self.payload[: self.truncated]
        headers_out = {"content-length": str(len(self.payload))} if self.expose_size else {}
        return FakeResponse(body, 200, headers_out)


class SkipExistingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = workdir()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.target = self.folder / "post" / "file.bin"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(downloader, "PROGRESS_INTERVAL", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_file_with_matching_size(self) -> None:
        self.target.write_bytes(PAYLOAD)
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_SKIPPED)
        self.assertEqual(session.get_calls, [], "a complete file must not be re-downloaded")
        self.assertEqual(self.target.read_bytes(), PAYLOAD)

    def test_skips_when_remote_size_is_unknown(self) -> None:
        self.target.write_bytes(b"whatever")
        session = FakeSession(expose_size=False, honour_range=False)

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_SKIPPED)
        self.assertNotIn(None, session.get_calls, "an unknown size must not trigger a full download")

    def test_local_file_larger_than_remote_is_kept(self) -> None:
        self.target.write_bytes(PAYLOAD + b"extra")
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_SKIPPED)
        self.assertEqual(self.target.stat().st_size, len(PAYLOAD) + 5)

    def test_overwrite_forces_a_fresh_download(self) -> None:
        self.target.write_bytes(b"stale")
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target), overwrite=True)

        self.assertEqual(result, downloader.STATUS_DOWNLOADED)
        self.assertEqual(self.target.read_bytes(), PAYLOAD)


class ResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = workdir()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.target = self.folder / "file.bin"
        patcher = mock.patch.object(downloader, "PROGRESS_INTERVAL", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_resumes_from_tmp_with_range(self) -> None:
        partial = self.folder / "file.bin.tmp"
        partial.write_bytes(PAYLOAD[:4096])
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_RESUMED)
        self.assertEqual(session.get_calls, ["bytes=4096-"])
        self.assertEqual(self.target.read_bytes(), PAYLOAD)
        self.assertFalse(partial.exists())

    def test_restarts_when_server_ignores_range(self) -> None:
        partial = self.folder / "file.bin.tmp"
        partial.write_bytes(PAYLOAD[:4096])
        session = FakeSession(honour_range=False)

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_DOWNLOADED)
        self.assertEqual(self.target.read_bytes(), PAYLOAD, "bytes must not be appended twice")

    def test_partial_final_file_is_promoted_to_resume(self) -> None:
        self.target.write_bytes(PAYLOAD[:1024])
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_RESUMED)
        self.assertEqual(session.get_calls, ["bytes=1024-"])
        self.assertEqual(self.target.read_bytes(), PAYLOAD)

    def test_416_finishes_a_complete_tmp(self) -> None:
        partial = self.folder / "file.bin.tmp"
        partial.write_bytes(PAYLOAD)
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target))

        self.assertEqual(result, downloader.STATUS_RESUMED)
        self.assertEqual(self.target.read_bytes(), PAYLOAD)
        self.assertFalse(partial.exists())

    def test_incomplete_body_keeps_tmp_and_raises(self) -> None:
        session = FakeSession(truncated=2048)  # 声明 10240，实际只给 2048

        with self.assertRaises(IOError):
            downloader.download_file(session, "http://x/file.bin", str(self.target))

        partial = self.folder / "file.bin.tmp"
        self.assertTrue(partial.exists(), "the partial file must survive for the next reconnect")
        self.assertEqual(partial.stat().st_size, 2048)
        self.assertFalse(self.target.exists())

    def test_no_tmp_mode_writes_the_target_directly(self) -> None:
        session = FakeSession()

        result = downloader.download_file(session, "http://x/file.bin", str(self.target), temp_file=False)

        self.assertEqual(result, downloader.STATUS_DOWNLOADED)
        self.assertEqual(self.target.read_bytes(), PAYLOAD)
        self.assertFalse((self.folder / "file.bin.tmp").exists())


class RemoteSizeTests(unittest.TestCase):
    def test_head_content_length_wins(self) -> None:
        session = FakeSession()
        self.assertEqual(downloader.get_remote_size(session, "http://x/file.bin"), len(PAYLOAD))

    def test_range_probe_fallback(self) -> None:
        class Headless(FakeSession):
            def head(self, url, allow_redirects=True, timeout=None):
                raise RuntimeError("405")

        session = Headless()
        self.assertEqual(downloader.get_remote_size(session, "http://x/file.bin"), len(PAYLOAD))

    def test_unknown_size_returns_zero(self) -> None:
        class Blind(FakeSession):
            def head(self, url, allow_redirects=True, timeout=None):
                raise RuntimeError("405")

            def get(self, url, stream=False, allow_redirects=True, headers=None, timeout=None):
                return FakeResponse(b"", 200, {})

        self.assertEqual(downloader.get_remote_size(Blind(), "http://x/file.bin"), 0)


if __name__ == "__main__":
    unittest.main()
