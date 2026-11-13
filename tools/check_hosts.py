"""Check whether this machine can reach the kemono / pawchive file servers.

Downloads fail with ``Connection reset``/``403``/``404`` for two very different
reasons: the file really is gone from the server, or the network here cannot
reach that particular host.  This script separates the two by probing every
mirror host and printing what came back.

Usage::

    python tools/check_hosts.py
    python tools/check_hosts.py https://pawchive.pw/fanbox/user/71376915/post/12779605
"""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

USER_AGENT = "kemono-dl-gui check_hosts (+https://github.com/yebing233/kemono-dl-GUI)"

PAWCHIVE_MIRRORS = [
    "https://file.pawchive.pw",
    "https://n1.pawchive.pw",
    "https://n2.pawchive.pw",
    "https://n3.pawchive.pw",
    "https://n4.pawchive.pw",
]

SITE_HOSTS = [
    "https://pawchive.pw",
    "https://kemono.cr",
    "https://coomer.st",
]


def _dns(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return f"DNS 失败：{exc}"
    addresses = sorted({info[4][0] for info in infos})
    return "DNS " + ", ".join(addresses[:3])


def _probe(url: str, timeout: float = 15.0) -> dict:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    result = {"url": url, "host": host, "dns": _dns(host)}
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result["status"] = response.status
            result["ok"] = True
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        # 404 from a bare host just means "no such file", the host itself is fine.
        result["ok"] = exc.code not in (403, 429, 503)
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        result["status"] = None
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def _api_get(url: str, timeout: float = 20.0) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/css"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload)


def _post_targets(post_url: str) -> list[str]:
    """Return file URLs for one post, preferring the node the API hands out."""
    parts = post_url.rstrip("/").split("/")
    try:
        post_id = parts[-1]
        creator_id = parts[-3]
        service = parts[-5]
    except IndexError:
        return []
    api = f"https://pawchive.pw/api/v1/{service}/user/{creator_id}/post/{post_id}"
    data = _api_get(api)
    attachments = data.get("attachments") or []
    urls = []
    for attachment in attachments[:20]:
        server = (attachment.get("server") or "").rstrip("/")
        path = attachment.get("path") or ""
        name = quote(attachment.get("name") or "", safe="")
        if not path:
            continue
        for host in [server, *PAWCHIVE_MIRRORS]:
            if host.startswith("http") and f"{host}/data{path}" not in urls:
                urls.append(f"{host}/data{path}?f={name}")
                break
    return urls


def main(argv: list[str]) -> int:
    targets = [("站点", url) for url in SITE_HOSTS]
    targets += [("文件服务器", url) for url in PAWCHIVE_MIRRORS]
    for post_url in argv:
        try:
            urls = _post_targets(post_url)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
            print(f"[跳过] {post_url} → 读取帖子失败：{type(exc).__name__}: {exc}")
            continue
        if not urls:
            print(f"[跳过] {post_url} → 这个帖子没有可探测的附件")
        for url in urls:
            targets.append(("帖子附件", url))

    rows = []
    for label, url in targets:
        result = _probe(url)
        result["label"] = label
        rows.append(result)
        status = result.get("status") or "—"
        verdict = "通" if result["ok"] else "不通"
        detail = result.get("error", "")
        print(f"[{verdict}] {label:<10} {result['host']:<22} {status} {result['seconds']}s {detail}".rstrip())
        print(f"        {result['dns']}")

    blocked = [row["host"] for row in rows if not row["ok"]]
    print()
    if blocked:
        print("以下主机在这台机器上不通：" + ", ".join(sorted(set(blocked))))
        print("→ 换网络 / 关掉代理或加速器 / 加代理后再试；不是程序的问题。")
        return 1
    print("所有主机都可以访问：如果下载仍然失败，多半是那个文件已经在服务器上被删了（404）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
