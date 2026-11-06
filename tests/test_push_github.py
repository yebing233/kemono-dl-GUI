"""tools/push_github.py 的自检：git 对象算法与忽略规则。"""

from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import push_github  # noqa: E402


class LocalTmp:
    """沙箱里 tempfile 会在清理由谁创建上踩 PermissionError，自己造目录更稳。"""

    def __enter__(self) -> Path:
        self.path = REPO_ROOT / ".build" / "test-tmp" / uuid.uuid4().hex
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc_info) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
        parent = self.path.parent
        try:
            parent.rmdir()
        except OSError:
            pass


class BlobShaTests(unittest.TestCase):
    def test_empty_blob_matches_git(self) -> None:
        self.assertEqual(push_github.blob_sha(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_hello_blob_matches_git(self) -> None:
        self.assertEqual(push_github.blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_sha_is_stable_and_content_dependent(self) -> None:
        same = push_github.blob_sha("中文内容".encode("utf-8"))
        self.assertEqual(same, push_github.blob_sha("中文内容".encode("utf-8")))
        self.assertNotEqual(same, push_github.blob_sha(b"other"))


class WalkTests(unittest.TestCase):
    def test_skips_build_dirs_and_logs(self) -> None:
        with LocalTmp() as root:
            (root / "keep.txt").write_text("a", encoding="utf-8")
            (root / "notes.log").write_text("b", encoding="utf-8")
            for skipped in ("dist", ".build", "downloads", "__pycache__"):
                folder = root / skipped
                folder.mkdir()
                (folder / "inside.txt").write_text("c", encoding="utf-8")
            (root / "pkg").mkdir()
            (root / "pkg" / "mod.pyc").write_text("d", encoding="utf-8")
            (root / "pkg" / "mod.py").write_text("e", encoding="utf-8")

            found = sorted(push_github.walk(root))

        self.assertEqual(found, ["keep.txt", "pkg/mod.py"])

    def test_keeps_dot_prefixed_entries(self) -> None:
        """网页拖拽上传会漏掉的点开头文件，脚本必须收进来。"""
        with LocalTmp() as root:
            (root / ".gitignore").write_text("dist/", encoding="utf-8")
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "build-gui.yml").write_text("name: x", encoding="utf-8")

            found = sorted(push_github.walk(root))

        self.assertEqual(found, [".github/workflows/build-gui.yml", ".gitignore"])


class ArgumentTests(unittest.TestCase):
    def test_default_source_is_repo_root(self) -> None:
        self.assertEqual(Path(push_github.DEFAULT_SOURCE), REPO_ROOT)

    def test_default_target_is_the_fork_repo(self) -> None:
        self.assertEqual(push_github.DEFAULT_REPO, "yebing233/kemono-dl-GUI")
        self.assertEqual(push_github.DEFAULT_BRANCH, "main")


if __name__ == "__main__":
    unittest.main()
