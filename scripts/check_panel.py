"""Refuse to publish a thin collection.

Run after ``collect`` and before ``build_chart_data.py``. Fails (exit 1) when
today's panel is missing a cloud, or covers far fewer chip/cloud pairs than the
page currently shows. A vendor API that errors returns zero rows rather than
raising, and without this check the daily job would quietly publish a page with
a whole cloud missing from the cross-cloud figure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_chart_data import build_snapshot  # noqa: E402
from gpu_term_premium.store import Store  # noqa: E402

REQUIRED_CLOUDS = ("aws", "azure", "gcp")
MIN_SHARE = 0.8  # of the chip/cloud pairs currently published


def main() -> int:
    store = Store(ROOT / "data")
    days = store.panel_days()
    if not days:
        print("FAIL no panel at all")
        return 1
    snap = build_snapshot(store.load_panel(days[-1]))
    clouds = {r["cloud"] for r in snap}
    problems = ["no %s readings" % c for c in REQUIRED_CLOUDS if c not in clouds]

    published = ROOT / "data" / "chart_data.json"
    if published.exists():
        before = len(json.loads(published.read_text(encoding="utf-8"))["snapshot"])
        if len(snap) < MIN_SHARE * before:
            problems.append("only %d chip/cloud pairs, page shows %d" % (len(snap), before))

    print("%s: %d chip/cloud pairs across %s" % (days[-1], len(snap), ", ".join(sorted(clouds))))
    for p in problems:
        print("FAIL " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
