"""Reachability checks for the kemono / pawchive hosts.

The exe ships without Python on the target machine, so this lives inside the
package (stdlib only) and is exposed as ``kemono-dl-gui.exe --check-hosts``.
``tools/check_hosts.py`` is a thin wrapper for source checkouts.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote

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


def resolve(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return f"DNS 失败：{exc}"
    addresses = sorted({info[4][0] for info in infos})
    return "DNS " + ", ".join(addresses[:3])


def probe(url: str, timeout: float = 15.0) -> dict:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    result: dict = {"url": url, "host": host, "dns": resolve(host)}
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result["status"] = response.status
            result["ok"] = True
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        # A bare host answering 404 just means "no such file", the host is fine.
        result["ok"] = exc.code not in (403, 429, 503)
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        result["status"] = None
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def api_get(url: str, timeout: float = 20.0) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/css"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload)


def post_targets(post_url: str, limit: int = 20) -> list[str]:
    """File URLs for one post, using the node the API hands out."""
    parts = post_url.rstrip("/").split("/")
    try:
        post_id = parts[-1]
        creator_id = parts[-3]
        service = parts[-5]
    except IndexError:
        return []
    api = f"https://pawchive.pw/api/v1/{service}/user/{creator_id}/post/{post_id}"
    data = api_get(api)
    attachments = data.get("attachments") or []
    urls: list[str] = []
    for attachment in attachments[:limit]:
        server = (attachment.get("server") or "").rstrip("/")
        path = attachment.get("path") or ""
        if not path:
            continue
        name = quote(attachment.get("name") or "", safe="")
        host = server if server.startswith("http") else PAWCHIVE_MIRRORS[0]
        urls.append(f"{host}/data{path}?f={name}")
    return urls


def check(post_urls: list[str] | None = None) -> int:
    """Probe every host (and the attachments of ``post_urls``); return an exit code."""
    targets: list[tuple[str, str]] = [("站点", url) for url in SITE_HOSTS]
    targets += [("文件服务器", url) for url in PAWCHIVE_MIRRORS]
    for post_url in post_urls or []:
        try:
            urls = post_targets(post_url)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
            print(f"[跳过] {post_url} → 读取帖子失败：{type(exc).__name__}: {exc}")
            continue
        if not urls:
            print(f"[跳过] {post_url} → 这个帖子没有可探测的附件")
        targets += [("帖子附件", url) for url in urls]

    blocked: list[str] = []
    dead_files = 0
    for label, url in targets:
        result = probe(url)
        status = result.get("status") or "—"
        verdict = "通" if result["ok"] else "不通"
        print(
            f"[{verdict}] {label:<10} {result['host']:<22} {status} "
            f"{result['seconds']}s {result.get('error', '')}".rstrip()
        )
        print(f"        {result['dns']}")
        if not result["ok"]:
            blocked.append(result["host"])
        elif label == "帖子附件" and result.get("status") == 404:
            dead_files += 1

    print()
    if blocked:
        print("以下主机在这台机器上不通：" + ", ".join(sorted(set(blocked))))
        print("→ 换网络 / 关掉代理或加速器 / 让代理走对线路后再试；这不是程序的问题。")
        return 1
    if dead_files:
        print(f"主机都通，但有 {dead_files} 个附件返回 404：文件在服务器上已被删除，重试也没用。")
        return 2
    print("所有主机都可以访问：如果下载仍然失败，多半是那个文件已经在服务器上被删了（404）。")
    return 0
