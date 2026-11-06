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
    """Restore ``sys.stdout``/``sys.stderr`` in a windowed (console=False) build.

    The packaged executable is built as a GUI application, so CPython leaves the
    text streams as ``None`` unless the parent redirected them.  When the GUI
    starts a download it *does* redirect them to a pipe — recreate the wrappers
    around those handles so the downloader's output reaches the log pane.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name, None) is not None:
            continue
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
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，0 表示自动选择可用端口")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args(argv)

    from .server import run

    run(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
