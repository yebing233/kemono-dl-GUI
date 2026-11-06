"""Static check for the GUI front-end: every ``$('id')`` used by app.js must exist.

Run after editing the markup or the scripts::

    python tools/check_ui.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "kemono_dl_gui" / "static"


def main() -> int:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    js_ids = set(re.findall(r"""\$\(\s*['"]([\w-]+)['"]\s*\)""", js))
    js_ids |= set(re.findall(r"""getElementById\(\s*['"]([\w-]+)['"]\s*\)""", js))

    problems = []
    missing = sorted(js_ids - html_ids)
    if missing:
        problems.append(f"app.js references {len(missing)} id(s) that index.html does not define: {', '.join(missing)}")

    unused = sorted(html_ids - js_ids)
    # ids only used as CSS hooks or aria targets are fine; report them as info only
    print(f"index.html ids: {len(html_ids)} | app.js lookups: {len(js_ids)}")
    if unused:
        print(f"ids not looked up from app.js (informational): {', '.join(unused)}")

    # CSS classes referenced by the markup should at least appear in styles.css
    used_classes = set()
    for attribute in re.findall(r'class="([^"]+)"', html):
        used_classes.update(part for part in attribute.split() if part and not part.startswith("__"))
    known = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    unknown = sorted(used_classes - known)
    if unknown:
        print(f"classes without a CSS rule (informational): {', '.join(unknown)}")

    for endpoint in re.findall(r"""api\(\s*'(/api/[^']+)'""", js):
        print(f"endpoint used: {endpoint}")

    if problems:
        for problem in problems:
            print("ERROR " + problem)
        return 1
    print("OK  markup/script identifiers are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
