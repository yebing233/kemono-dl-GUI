r"""不装 git，直接用 GitHub API 把本地目录推上去。

用途：这台机器上没有 git，网页拖拽上传又会跳过 `.github/` 这类点开头的目录，
于是用一个只有标准库的脚本，把工作区里的文件按 git 对象模型直接提交到远端分支。

用法（PowerShell）：

    # 1. 先看一眼会改什么（只读，不需要 token）
    python tools/push_github.py --dry-run

    # 2. 真正推送：token 放在环境变量里，不要写进命令行
    $env:GITHUB_TOKEN = "ghp_xxx"
    python tools/push_github.py -m "GUI 1.0.4: simple mode + pro mode"

    # 3. 用完清掉
    Remove-Item Env:\GITHUB_TOKEN

Token 只需要对目标仓库有 Contents: Read and write 权限（细粒度 token）或 repo 权限（经典 token）。
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
DEFAULT_REPO = "yebing233/kemono-dl-GUI"
DEFAULT_BRANCH = "main"
DEFAULT_SOURCE = str(Path(__file__).resolve().parent.parent)

# 与 .gitignore / 网页上传一致：这些目录和文件不进仓库
SKIP_DIRS = {".git", ".build", "build", "dist", "downloads", "__pycache__", ".venv", "venv", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}
SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def say(message: str = "") -> None:
    """Windows 控制台编码不稳，输出前先兜底。"""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(message.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def request(method: str, path: str, token: str | None, payload: dict | None = None) -> dict:
    url = path if path.startswith("http") else f"{API}{path}"
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "kemono-dl-gui-push",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("message", detail)
        except json.JSONDecodeError:
            message = detail
        raise SystemExit(f"GitHub API 失败：{method} {path} -> HTTP {error.code}：{message}") from None
    except urllib.error.URLError as error:
        raise SystemExit(f"连不上 GitHub：{error.reason}") from None
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def walk(source: Path) -> dict[str, Path]:
    """收集要上传的文件，返回仓库内的相对路径 -> 本地绝对路径。"""
    files: dict[str, Path] = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if relative.name in SKIP_NAMES or relative.suffix in SKIP_SUFFIXES:
            continue
        files[relative.as_posix()] = path
    return files


def blob_sha(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def resolve_token(cli_token: str | None) -> str | None:
    token = cli_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    if not sys.stdin or not sys.stdin.isatty():
        return None
    try:
        entered = getpass.getpass("粘贴 GitHub token（输入不回显，回车确认）：").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return entered or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="push_github.py",
        description="用 GitHub API 把当前目录推送到远端分支（不需要安装 git）。",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/name，默认 {DEFAULT_REPO}")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help=f"目标分支，默认 {DEFAULT_BRANCH}")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="要上传的目录，默认本仓库根目录")
    parser.add_argument("--token", default=None, help="也支持环境变量 GITHUB_TOKEN / GH_TOKEN")
    parser.add_argument("-m", "--message", default="", help="提交信息")
    parser.add_argument("--prune", action="store_true", help="同时删除远端有、本地没有的文件")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要发生的改动")
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.is_dir():
        raise SystemExit(f"找不到目录：{source}")

    token = None if args.dry_run else resolve_token(args.token)
    if not token and not args.dry_run:
        raise SystemExit("没有 token：请设置环境变量 GITHUB_TOKEN，或用 --token 传入。")

    local = walk(source)
    say(f"本地文件：{len(local)} 个（目录 {source}）")

    ref = request("GET", f"/repos/{args.repo}/git/ref/heads/{args.branch}", token)
    head_commit = ref["object"]["sha"]
    commit = request("GET", f"/repos/{args.repo}/git/commits/{head_commit}", token)
    base_tree = commit["tree"]["sha"]
    tree = request("GET", f"/repos/{args.repo}/git/trees/{base_tree}?recursive=1", token)
    remote = {entry["path"]: entry["sha"] for entry in tree.get("tree", []) if entry["type"] == "blob"}
    say(f"远端分支：{args.branch} @ {head_commit[:7]}（{len(remote)} 个文件）")

    added: list[str] = []
    changed: list[str] = []
    unchanged = 0
    local_blobs: dict[str, tuple[Path, bytes, str]] = {}
    for relative, path in local.items():
        data = path.read_bytes()
        sha = blob_sha(data)
        local_blobs[relative] = (path, data, sha)
        if relative not in remote:
            added.append(relative)
        elif remote[relative] != sha:
            changed.append(relative)
        else:
            unchanged += 1

    removed = sorted(set(remote) - set(local)) if args.prune else []

    say("")
    say(f"新增 {len(added)} · 修改 {len(changed)} · 未变 {unchanged} · 删除 {len(removed)}")
    for label, items in (("新增", added), ("修改", changed), ("删除", removed)):
        if not items:
            continue
        say(f"  {label}：")
        for item in items[:40]:
            say(f"    {item}")
        if len(items) > 40:
            say(f"    …… 还有 {len(items) - 40} 个")

    if not (added or changed or removed):
        say("")
        say("远端已经是最新，没有需要提交的内容。")
        return 0

    if args.dry_run:
        say("")
        say("（--dry-run：只读检查完成，没有推送。去掉该参数并提供 token 即会真正提交。）")
        return 0

    say("")
    say("开始上传……")
    entries: list[dict] = []
    touched = added + changed
    for index, relative in enumerate(touched, start=1):
        path, data, sha = local_blobs[relative]
        if relative not in remote:
            created = request(
                "POST",
                f"/repos/{args.repo}/git/blobs",
                token,
                {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
            )
            sha = created["sha"]
        entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": sha})
        if index % 10 == 0 or index == len(touched):
            say(f"  {index}/{len(touched)}")
    for relative in removed:
        entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": None})

    new_tree = request(
        "POST",
        f"/repos/{args.repo}/git/trees",
        token,
        {"base_tree": base_tree, "tree": entries},
    )
    message = args.message or f"Update from local workspace ({len(added)} added, {len(changed)} changed)"
    new_commit = request(
        "POST",
        f"/repos/{args.repo}/git/commits",
        token,
        {"message": message, "tree": new_tree["sha"], "parents": [head_commit]},
    )
    request(
        "PATCH",
        f"/repos/{args.repo}/git/refs/heads/{args.branch}",
        token,
        {"sha": new_commit["sha"], "force": False},
    )

    say("")
    say(f"推送完成：{args.branch} -> {new_commit['sha'][:7]}")
    say(f"提交页面：https://github.com/{args.repo}/commit/{new_commit['sha']}")
    say("如果配了 GitHub Actions，workflow 会自动触发；可在 Actions 页面确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
