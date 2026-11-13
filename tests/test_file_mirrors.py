import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kemono_dl.kemono_dl import PAWCHIVE_MIRRORS, pawchive_file_urls
from kemono_dl.models import Attachment


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


if __name__ == "__main__":
    unittest.main()
