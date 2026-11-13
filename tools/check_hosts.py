"""Check whether this machine can reach the kemono / pawchive file servers.

Thin wrapper around :mod:`kemono_dl_gui.hosts` so source checkouts can run the
same checks without building the exe.  The packaged exe exposes the identical
diagnostic as ``kemono-dl-gui.exe --check-hosts``.

Usage::

    python tools/check_hosts.py
    python tools/check_hosts.py https://pawchive.pw/fanbox/user/71376915/post/12779605
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kemono_dl_gui.hosts import check

if __name__ == "__main__":
    raise SystemExit(check(sys.argv[1:]))
