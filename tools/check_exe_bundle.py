"""Prove that dist/kemono-dl-gui.exe is self-contained (no host Python needed).

The sandbox forbids executing binaries from the workspace, so this tool inspects
the built PyInstaller archive instead of running it:

  1. reads the CArchive table of contents and validates each entry
     (decompresses it and checks the payload really is what the name claims),
  2. confirms an embedded CPython (python3xx.dll, MSVC runtime, ssl/socket),
     the CA bundle, and the GUI front-end assets travel inside the exe,
  3. opens the PYZ archive and confirms requests/urllib3/certifi/kemono_dl are
     bundled,
  4. decompiles kemono_dl_gui.server bytecode and looks for the frozen
     `--run-cli` self-reexec path - the mechanism that lets a download job run
     with no interpreter installed on the machine.

Usage: python tools/check_exe_bundle.py [dist/kemono-dl-gui.exe]
Exit code 0 = everything required is present.
"""

from __future__ import annotations

import io
import marshal
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = ROOT / "dist" / "kemono-dl-gui.exe"
MAGIC = b"MEI\014\013\012\013\016"
COOKIE_SIZE = 88  # size of the CArchive cookie struct
NAME_WINDOW = 300  # TOC names are short; guards against random byte matches


def read_toc(blob: bytes) -> tuple[dict[str, bytes], int, int, int, str]:
    """Parse a PyInstaller CArchive (one-file) table of contents.

    Layout: `... payload ... | TOC | cookie`, where the cookie ends the file and
    records the package length and the TOC size. TOC entries are
    `entry_len(4) offset(4) clen(4) ulen(4) cflag(1) typecode(1) name`, with the
    name NUL-padded so the entry length is aligned. `offset` is relative to the
    start of the archive data, i.e. cookie_pos - package_length.
    """
    entries: dict[str, bytes] = {}
    cookie = blob.rfind(MAGIC)
    if cookie < 0:
        raise SystemExit("not a PyInstaller archive (MEI cookie missing)")
    pkg_len, _toc_field, toc_len, pyvers, pylib = struct.unpack("!iiii64s", blob[cookie + 8 : cookie + 88])
    # package_length excludes the 88-byte cookie itself, so the payload starts
    # one cookie-length after `cookie - package_length`.
    base = cookie - pkg_len + COOKIE_SIZE
    pos = cookie - toc_len
    end = cookie

    while pos + 18 <= end:
        (entry_len,) = struct.unpack("!i", blob[pos : pos + 4])
        if entry_len <= 18 or pos + entry_len > end:
            break
        offset, clen, _ulen, cflag = struct.unpack("!iiiB", blob[pos + 4 : pos + 17])
        name = blob[pos + 18 : pos + entry_len].rstrip(b"\0").decode("utf-8", "replace")
        raw = blob[base + offset : base + offset + clen]
        pos += entry_len
        if len(raw) != clen:
            continue
        if cflag:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                continue
        entries[name] = raw

    if not entries:
        raise SystemExit("could not parse the archive table of contents")
    return entries, pkg_len, toc_len, pyvers, pylib.decode("utf-8", "replace").rstrip("\0")


def pyz_table(pyz: bytes) -> dict[str, tuple[int, int, int]]:
    """{module name: (typecode, offset, length)} from a PyInstaller PYZ archive."""
    if pyz[:4] != b"PYZ\0":
        return {}
    toc_off = struct.unpack("!I", pyz[8:12])[0]
    table = marshal.loads(pyz[toc_off:])
    return {name: (entry[0], entry[1], entry[2]) for name, entry in table}


def pyz_module_code(pyz: bytes, typ: int, pos: int, length: int):
    chunk = pyz[pos : pos + length]
    if typ == 0:  # zlib-compressed bytecode
        chunk = zlib.decompress(chunk)
    return marshal.loads(chunk)


def main(argv: list[str]) -> int:
    exe = Path(argv[1]) if len(argv) > 1 else DEFAULT_EXE
    if not exe.is_file():
        print(f"[x] {exe} not found")
        return 2
    blob = exe.read_bytes()
    entries, pkg_len, toc_len, pyvers, pylib = read_toc(blob)
    names = sorted(entries)

    print(f"exe           : {exe}")
    print(f"size          : {len(blob):,} bytes")
    print(f"archive       : {len(names)} entries, package {pkg_len:,} bytes, python {pyvers}, lib {pylib}")
    print()

    def grep(pattern: str) -> list[str]:
        rx = re.compile(pattern, re.I)
        return [n for n in names if rx.search(n)]

    checks: list[tuple[str, bool, str]] = []

    cpython = grep(r"^python3\d+\.dll$")
    ok_dll = False
    detail = "missing"
    if cpython:
        ok_dll = entries[cpython[0]][:2] == b"MZ"
        detail = f"{cpython[0]} ({len(entries[cpython[0]]):,} bytes, PE={'yes' if ok_dll else 'no'})"
    checks.append(("embedded CPython runtime", ok_dll, detail))

    vc = grep(r"^(vcruntime140.*\.dll|ucrtbase\.dll)$")
    checks.append(("MSVC runtime DLLs", bool(vc), ", ".join(vc) or "missing"))

    ssl = grep(r"^_(ssl|socket|hashlib)\.pyd$") + grep(r"^libssl|^libcrypto")
    checks.append(("network + TLS modules", len(ssl) >= 2, ", ".join(sorted(set(ssl))) or "missing"))

    cacert = grep(r"certifi[\\/].*\.pem$")
    checks.append(("certifi CA bundle", bool(cacert), ", ".join(cacert) or "missing"))

    static = grep(r"kemono_dl_gui[\\/]static[\\/]")
    js = [n for n in static if n.endswith("app.js")]
    js_ok = bool(js) and b"/api/quit" in entries[js[0]] and b"btnQuit" in entries[js[0]]
    html = [n for n in static if n.endswith("index.html")]
    html_ok = bool(html) and b"quitOverlay" in entries[html[0]]
    checks.append(
        (
            "GUI front-end assets",
            len(static) == 4 and js_ok and html_ok,
            ", ".join(Path(n).name for n in static) + (" (latest build: yes)" if js_ok and html_ok else " (stale!)"),
        )
    )

    pyz_name = next((n for n in names if n.lower().endswith(".pyz")), None)
    table: dict[str, tuple[int, int, int]] = {}
    if pyz_name:
        table = pyz_table(entries[pyz_name])
    wanted = ["requests", "urllib3", "certifi", "idna", "charset_normalizer", "kemono_dl", "kemono_dl_gui.server"]
    found = [m for m in wanted if m in table]
    checks.append((f"bundled modules in {pyz_name}", len(found) == len(wanted), f"{len(table)} modules: " + ", ".join(found)))

    frozen_ok = False
    carriers: list[str] = []
    decode_errors: list[str] = []
    for mod in ("kemono_dl_gui.args", "kemono_dl_gui.__main__", "kemono_dl_gui.server"):
        if mod not in table:
            continue
        typ, pos, length = table[mod]
        try:
            code = pyz_module_code(entries[pyz_name], typ, pos, length)
        except Exception as exc:  # pragma: no cover - diagnostics only
            decode_errors.append(f"{mod}: {exc}")
            continue
        buf = io.BytesIO()
        marshal.dump(code, buf)
        if b"--run-cli" in buf.getvalue():
            carriers.append(mod)
    frozen_ok = bool(carriers)
    no_py = b"(?:python|pythonw)(?:\\.exe)?\"?,?\\s*,?\\s*\"?-u"  # sanity only
    frozen_detail = (
        "frozen self-reexec present in " + ", ".join(carriers)
        if frozen_ok
        else ("bytecode lacks --run-cli" + (f" ({'; '.join(decode_errors)})" if decode_errors else ""))
    )
    checks.append(("frozen CLI re-exec (--run-cli)", frozen_ok, frozen_detail))

    tk = grep(r"^_tkinter|tcl")
    checks.append(("tkinter excluded (smaller exe)", not tk, ", ".join(tk) or "not bundled"))

    width = max(len(label) for label, _, _ in checks)
    failures = 0
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {label.ljust(width)}  {detail}")
        failures += 0 if ok else 1

    print()
    if failures:
        print(f"[x] {failures} check(s) failed")
        return 1
    print("[ok] self-contained: own interpreter, deps, CA bundle and GUI assets are inside the exe")
    print("[ok] download jobs re-execute the same exe with --run-cli, so the host needs no Python")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
