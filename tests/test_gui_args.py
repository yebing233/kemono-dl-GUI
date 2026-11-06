"""Unit tests for the GUI's command builder.

These run without pytest::

    python -m unittest tests.test_gui_args -v

Each test checks that a GUI control maps onto the exact CLI flag documented in
the README, so the interface cannot silently drift away from the downloader.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kemono_dl_gui.args import (  # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateError,
    build_command,
    normalise_config,
    render_template,
    shell_command,
)

TEMPLATE = "{service}/{creator_id}/{post_id}/{filename}"


def base_config(**overrides):
    config = {
        "urls": ["https://kemono.cr/patreon/user/12345"],
        "batchFiles": [],
        "path": "C:/out",
        "templates": {"attachments": TEMPLATE, "content": TEMPLATE, "json": TEMPLATE},
        "templateSplit": False,
        "restrictNames": False,
        "noTmp": False,
        "writeContent": False,
        "writeJson": False,
        "customVars": "",
        "archive": "",
        "dates": {
            "date": {"enabled": False, "type": "published", "value": ""},
            "datebefore": {"enabled": False, "type": "published", "value": ""},
            "dateafter": {"enabled": False, "type": "published", "value": ""},
        },
        "skipExtensions": [],
        "skipAttachments": False,
        "cookies": [],
        "logins": {
            "kemono": {"user": "", "password": ""},
            "coomer": {"user": "", "password": ""},
            "pawchive": {"user": "", "password": ""},
        },
        "favorite": {"kemono": False, "coomer": False, "pawchive": False},
    }
    config.update(overrides)
    return config


class CommandBuilderTests(unittest.TestCase):
    def build(self, **overrides):
        return build_command(base_config(**overrides), "python", "C:/out")

    def test_default_command(self):
        result = self.build()
        self.assertEqual(result.errors, [])
        self.assertEqual(result.argv[:4], ["python", "-u", "-m", "kemono_dl"])
        self.assertIn("--path", result.argv)
        self.assertIn(TEMPLATE, result.argv)
        self.assertIn("https://kemono.cr/patreon/user/12345", result.argv)

    def test_every_boolean_flag(self):
        result = self.build(
            restrictNames=True,
            noTmp=True,
            writeContent=True,
            writeJson=True,
            skipAttachments=True,
            favorite={"kemono": True, "coomer": False, "pawchive": False},
        )
        for flag in (
            "--restrict-names",
            "--no-tmp",
            "--write-content",
            "--write-json",
            "--skip-attachments",
            "--favorite-creators-kemono",
        ):
            self.assertIn(flag, result.argv)

    def test_split_templates_become_typed_outputs(self):
        result = self.build(templateSplit=True)
        outputs = [value for flag, value in zip(result.argv, result.argv[1:]) if flag == "--output"]
        self.assertEqual([value.split(":", 1)[0] for value in outputs], ["attachments", "content", "json"])

    def test_date_filters(self):
        result = self.build(
            dates={
                "date": {"enabled": True, "type": "published", "value": "2024-05-06"},
                "datebefore": {"enabled": True, "type": "edited", "value": "2024-01-02"},
                "dateafter": {"enabled": False, "type": "added", "value": ""},
            }
        )
        self.assertIn("published:20240506", result.argv)
        self.assertIn("edited:20240102", result.argv)
        self.assertNotIn("--dateafter", result.argv)

    def test_invalid_date_is_reported(self):
        result = self.build(
            dates={
                "date": {"enabled": True, "type": "published", "value": "06/05/2024"},
                "datebefore": {"enabled": False, "type": "published", "value": ""},
                "dateafter": {"enabled": False, "type": "published", "value": ""},
            }
        )
        self.assertTrue(result.errors)

    def test_skip_extensions_are_comma_joined(self):
        result = self.build(skipExtensions=["psd", "zip"])
        index = result.argv.index("--skip-extensions")
        self.assertEqual(result.argv[index + 1], "psd,zip")

    def test_logins(self):
        result = self.build(
            logins={
                "kemono": {"user": "u", "password": "p"},
                "coomer": {"user": "", "password": ""},
                "pawchive": {"user": "", "password": ""},
            }
        )
        self.assertIn("--kemono-login", result.argv)
        self.assertEqual(result.argv[result.argv.index("--kemono-login") + 1 :][:2], ["u", "p"])

    def test_login_needs_both_fields(self):
        result = self.build(
            logins={
                "kemono": {"user": "u", "password": ""},
                "coomer": {"user": "", "password": ""},
                "pawchive": {"user": "", "password": ""},
            }
        )
        self.assertTrue(result.errors)

    def test_batch_file_and_favorites_satisfy_url_requirement(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("https://kemono.cr/patreon/user/1\n")
            batch = handle.name
        try:
            result = self.build(urls=[], batchFiles=[batch])
            self.assertEqual(result.errors, [])
            self.assertIn("--batch-file", result.argv)

            favorites = self.build(urls=[], favorite={"kemono": False, "coomer": True, "pawchive": False})
            self.assertEqual(favorites.errors, [])
            self.assertIn("--favorite-creators-coomer", favorites.argv)
        finally:
            Path(batch).unlink(missing_ok=True)

    def test_missing_urls_is_an_error(self):
        result = self.build(urls=[])
        self.assertTrue(result.errors)

    def test_archive_and_cookies(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("cookies")
            cookie_file = handle.name
        try:
            result = self.build(cookies=[cookie_file], archive="C:/out/archive.txt")
            self.assertIn("--cookies", result.argv)
            self.assertIn("--archive", result.argv)
        finally:
            Path(cookie_file).unlink(missing_ok=True)

    def test_frozen_build_uses_run_cli(self):
        result = build_command(base_config(), "C:/app/kemono-dl-gui.exe", "C:/out", frozen=True)
        self.assertEqual(result.argv[:2], ["C:/app/kemono-dl-gui.exe", "--run-cli"])

    def test_passwords_are_masked_in_preview(self):
        result = self.build(
            logins={
                "kemono": {"user": "user0", "password": "hunter2"},
                "coomer": {"user": "", "password": ""},
                "pawchive": {"user": "", "password": ""},
            }
        )
        command = shell_command(result.argv)
        self.assertEqual(command.count("******"), 2)
        self.assertNotIn("hunter2", command)
        self.assertNotIn("user0", command)


class TemplateTests(unittest.TestCase):
    def test_default_template(self):
        path = render_template(TEMPLATE, "C:/out", False, None)
        self.assertTrue(path.replace("\\", "/").endswith("patreon/12345/67890/attachment.png"), path)

    def test_restrict_names_strips_non_ascii(self):
        path = render_template("{service}/{post_title}/{filename}", "C:/out", True, None, {"post_title": "café ☕ 标题"})
        self.assertTrue(all(0x20 <= ord(character) <= 0x7E for character in path), path)

    def test_traversal_cannot_escape_base_path(self):
        path = Path(render_template(TEMPLATE, "C:/out", False, None, {"post_id": "../../etc"}))
        self.assertIn(Path("C:/out"), path.parents)

    def test_unknown_variable_is_rejected(self):
        with self.assertRaises(TemplateError):
            render_template("{nope}/{filename}", "C:/out", False, None)


class AuthorFolderTests(unittest.TestCase):
    """The GUI default names the author folder ``名字 [编号]``."""

    def test_author_name_and_id(self):
        path = render_template(DEFAULT_TEMPLATE, "C:/out", False, None)
        flat = path.replace("\\", "/")
        self.assertTrue(flat.endswith("patreon/Sample Creator [12345]/67890/attachment.png"), flat)

    def test_author_name_only(self):
        path = render_template("{service}/{creator_name}/{post_id}/{filename}", "C:/out", False, None)
        self.assertTrue(path.replace("\\", "/").endswith("patreon/Sample Creator/67890/attachment.png"), path)

    def test_published_date_spec(self):
        path = render_template(
            "{service}/{creator_name} [{creator_id}]/{published:%Y.%m.%d} {post_title}/{filename}",
            "C:/out",
            False,
            None,
        )
        flat = path.replace("\\", "/")
        self.assertIn("/patreon/Sample Creator [12345]/", flat)
        self.assertIn("/attachment.png", flat)
        self.assertRegex(flat, r"/\d{4}\.\d{2}\.\d{2} ")

    def test_restrict_names_keeps_author_folder_readable(self):
        path = render_template("{service}/{creator_name} [{creator_id}]/{post_id}/{filename}", "C:/out", True, None)
        self.assertIn("[12345]", path)


class NormaliseTests(unittest.TestCase):
    def test_defaults(self):
        cfg = normalise_config({}, "C:/out")
        self.assertEqual(cfg["path"], "C:/out")
        self.assertEqual(
            cfg["templates"]["attachments"],
            "{service}/{creator_name} [{creator_id}]/{post_id}/{filename}",
        )
        self.assertEqual(cfg["skip_extensions"], [])


class RequestIntervalTests(unittest.TestCase):
    """``--request-interval`` map from the GUI's 请求间隔 field."""

    def test_default_is_omitted_from_the_command(self):
        result = build_command(base_config(), "python", "C:/out")
        self.assertEqual(result.errors, [])
        self.assertNotIn("--request-interval", result.argv)

    def test_explicit_value_is_forwarded(self):
        config = base_config(requestInterval=0.5)
        result = build_command(config, "python", "C:/out")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.argv[result.argv.index("--request-interval") + 1], "0.5")

    def test_zero_disables_the_delay(self):
        config = base_config(requestInterval=0)
        result = build_command(config, "python", "C:/out")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.argv[result.argv.index("--request-interval") + 1], "0")

    def test_garbage_falls_back_to_the_default(self):
        cfg = normalise_config({"requestInterval": "abc"}, "C:/out")
        self.assertEqual(cfg["request_interval"], 1.0)

    def test_values_are_clamped(self):
        self.assertEqual(normalise_config({"requestInterval": -3}, "C:/out")["request_interval"], 0.0)
        self.assertEqual(normalise_config({"requestInterval": 999}, "C:/out")["request_interval"], 60.0)

    def test_whole_numbers_lose_the_decimal_point(self):
        result = build_command(base_config(requestInterval=2.0), "python", "C:/out")
        self.assertEqual(result.argv[result.argv.index("--request-interval") + 1], "2")


if __name__ == "__main__":
    unittest.main()
