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


if __name__ == "__main__":
    unittest.main()
