"""Frozen-build entry point.

PyInstaller needs a plain script as the entry; this just hands over to
``kemono_dl_gui.__main__`` which also implements the ``--run-cli`` mode used to
run downloads inside the packaged executable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kemono_dl_gui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
