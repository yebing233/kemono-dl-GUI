import contextlib
import io
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kemono_dl.kemono_dl import PAWCHIVE_MIRRORS, pawchive_file_urls
from kemono_dl.models import Attachment
from kemono_dl_gui import hosts


class PawchiveMirrorTests(unittest.TestCase):
    def test_preferred_node_comes_first(self):
        attachment = Attachment(
            name="clip.mp4",
            path="/aa/bb/cc.mp4",
            server="https://n3.pawchive.pw",
        )
        urls = pawchive_file_urls(attachment)
        self.assertEqual(urls[0], "https://n3.pawchive.pw/data/aa/bb/cc.mp4?f=clip.mp4")
        self.assertIn("https://file.pawchive.pw/data/aa/bb/cc.mp4?f=clip.mp4", urls)

    def test_every_mirror_is_offered_once(self):
        urls = pawchive_file_urls(Attachment(name="a.png", path="/a.png"))
        hosts = [url.split("/data")[0] for url in urls]
        self.assertEqual(len(hosts), len(set(hosts)))
        self.assertEqual(len(hosts), len(PAWCHIVE_MIRRORS))

    def test_falls_back_when_server_is_missing_or_foreign(self):
        for server in (None, "", "https://n1.kemono.cr"):
            urls = pawchive_file_urls(Attachment(name="a.png", path="/a.png", server=server))
            self.assertEqual(urls[0], "https://file.pawchive.pw/data/a.png?f=a.png")

    def test_file_name_is_url_quoted(self):
        urls = pawchive_file_urls(
            Attachment(name="1分ループ(本編).mp4", path="/x/y.mp4", server="https://n2.pawchive.pw")
        )
        self.assertTrue(urls[0].endswith("?f=1%E5%88%86%E3%83%AB%E3%83%BC%E3%83%97%28%E6%9C%AC%E7%B7%A8%29.mp4"))
        self.assertNotIn(" ", urls[0])


class HostCheckTests(unittest.TestCase):
    def test_post_target_uses_the_api_node(self):
        original = hosts.api_get
        hosts.api_get = lambda url, timeout=20.0: {
            "attachments": [
                {"name": "a b.mp4", "path": "/aa/bb.mp4", "server": "https://n2.pawchive.pw"},
                {"name": "no-path.png", "path": ""},
                {"name": "c.gif", "path": "/cc.gif", "server": None},
            ]
        }
        try:
            urls = hosts.post_targets("https://pawchive.pw/fanbox/user/71376915/post/12779605")
        finally:
            hosts.api_get = original
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://n2.pawchive.pw/data/aa/bb.mp4?f=a%20b.mp4")
        self.assertEqual(urls[1], "https://file.pawchive.pw/data/cc.gif?f=c.gif")

    def test_the_cli_flag_is_wired(self):
        source = (Path(__file__).resolve().parent.parent / "kemono_dl_gui" / "__main__.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('argv[0] == "--check-hosts"', source)
        self.assertIn("from .hosts import check", source)

    def test_a_dead_file_is_not_a_network_problem(self):
        original_probe = hosts.probe
        original_targets = hosts.post_targets
        hosts.probe = lambda url, timeout=15.0: {"url": url, "host": "x", "dns": "", "ok": True, "status": 404, "seconds": 0.0}
        hosts.post_targets = lambda post_url, limit=20: ["https://n1.pawchive.pw/data/a.mp4"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = hosts.check(["https://pawchive.pw/fanbox/user/1/post/2"])
        finally:
            hosts.probe = original_probe
            hosts.post_targets = original_targets
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()