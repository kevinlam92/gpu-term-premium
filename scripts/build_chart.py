"""Inline chart_data.json into the template and emit the standalone page.

Written twice, to the same bytes: ``chart/chart.html`` is the working copy, and
``docs/index.html`` is what GitHub Pages serves off the default branch. Pages is
configured from /docs rather than an Actions workflow so the page rebuilds with
an ordinary push and needs no workflow permissions.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("chart/chart.html", "docs/index.html")


def main():
    data = (ROOT / "data" / "chart_data.json").read_text(encoding="utf-8")
    tpl = (ROOT / "chart" / "template.html").read_text(encoding="utf-8")
    if "__DATA__" not in tpl:
        print("template has no __DATA__ placeholder")
        return 1
    out = tpl.replace("__DATA__", json.dumps(json.loads(data), separators=(",", ":")))
    for rel in TARGETS:
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")
        print("wrote %s (%d KB)" % (dest, len(out) // 1024))
    # Pages would otherwise run the file through Jekyll, which strips anything
    # it mistakes for a template tag.
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
