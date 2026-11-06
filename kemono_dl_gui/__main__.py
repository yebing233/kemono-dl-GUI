"""``python -m kemono_dl_gui`` entry point.

The packaged ``kemono-dl-gui.exe`` uses the same module: when it is started with
``--run-cli`` it behaves exactly like ``python -m kemono_dl``.  That is how the
GUI downloads things inside the frozen build — it re-launches itself as a
command line child process, so no Python installation is required on the user's
machine.
"""

from __future__ import annotations

import argparse
import io
import os
import sys


def _ensure_std_streams() -> None:
    """Force UTF-8 on ``sys.stdout``/``sys.stderr`` (recreate them when missing).

    The packaged executable is a GUI (``console=False``) application and the
    PyInstaller bootloader starts the interpreter with ``use_environment = 0``,
    so ``PYTHONUTF8`` / ``PYTHONIOENCODING`` inherited from the GUI are ignored.
    CPython therefore builds ``sys.stdout`` from the pipe handed over by the GUI
    with the *Windows ANSI code page* (GBK/cp936 on zh-CN systems), and printing
    anything outside that code page — e.g. a Japanese post title containing
    U+30FB — kills the download with ``UnicodeEncodeError``.

    Reconfiguring the existing stream (and falling back to wrapping fd 1/2) keeps
    the log pane lossless for every language.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        stream = getattr(sys, name, None)
        if stream is not None:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="replace")
                    continue
                except (AttributeError, ValueError, OSError):
                    pass
        try:
            os.fstat(fd)
        except OSError:
            setattr(sys, name, io.StringIO())
        else:
            setattr(
                sys,
                name,
                io.TextIOWrapper(
                    io.FileIO(fd, "w", closefd=False),
                    encoding="utf-8",
                    errors="replace",
                    write_through=True,
                    line_buffering=True,
                ),
            )


def _env_int(name: str, fallback: int) -> int:
    """Read an integer from the environment, ignoring junk values."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def run_cli(argv: list[str]) -> int:
    """Forward ``argv`` to ``kemono_dl.__main__.main()``."""
    from kemono_dl.__main__ import main as cli_main

    previous = sys.argv
    sys.argv = ["kemono-dl", *argv]
    try:
        cli_main()
    except SystemExit as exc:  # argparse --help / --version
        code = exc.code
        return code if isinstance(code, int) else 0
    finally:
        sys.argv = previous
    return 0


def main() -> int:
    _ensure_std_streams()
    argv = sys.argv[1:]
    if argv and argv[0] == "--run-cli":
        return run_cli(argv[1:])

    parser = argparse.ArgumentParser(prog="kemono-dl-gui", description="kemono-dl GUI · 本地图形界面")
    parser.add_argument(
        "--host",
        default=os.environ.get("KEMONO_DL_GUI_HOST", "127.0.0.1"),
        help="监听地址，默认仅本机 127.0.0.1；容器/远程部署用 0.0.0.0（也可用 KEMONO_DL_GUI_HOST）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("KEMONO_DL_GUI_PORT", 8765),
        help="监听端口，0 表示自动选择可用端口（也可用 KEMONO_DL_GUI_PORT）",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=bool(os.environ.get("KEMONO_DL_GUI_NO_BROWSER")),
        help="启动后不自动打开浏览器（KEMONO_DL_GUI_NO_BROWSER=1 等效）",
    )
    args = parser.parse_args(argv)

    from .server import run

    run(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
