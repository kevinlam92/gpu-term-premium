"""Emit the JSON the chart embeds.

Two series, one metric:

* ``history`` -- daily term premium over 90 days, AWS only. It is the only cloud
  that serves price history; Azure and GCP expose current prices with no archive
  anywhere upstream, so their series begin the day collection started.
* ``snapshot`` -- today's term premium per chip per cloud, the cross-cloud cut.

Run after ``collect``. Reads the raw archive rather than the tidy panel, because
the panel keeps only the latest print per AZ while the chart needs the full
90-day path.
"""
from __future__ import annotations

import gzip
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpu_term_premium import ratio  # noqa: E402
from gpu_term_premium.chips import BY_KEY  # noqa: E402
from gpu_term_premium.store import Store  # noqa: E402

# The families the chart argues about, in categorical slot order.
FOCUS = [
    ("g7.2xlarge", "g7.2xlarge (32GB)"),
    ("g7.4xlarge", "g7.4xlarge (32GB)"),
    ("g7e.2xlarge", "g7e.2xlarge (96GB)"),
    ("g6e.2xlarge", "g6e.2xlarge (L40S)"),
]


def latest_raw(day_dir: Path, pattern: str) -> dict:
    """Newest matching archive for the day (collect may have run twice)."""
    files = sorted(day_dir.glob(pattern))
    if not files:
        return {}
    with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
        return json.load(fh)


def build_history(day_dir: Path, region: str) -> dict:
    spot = latest_raw(day_dir, "aws__%s__spot__*.json.gz" % region)
    plans = latest_raw(day_dir, "aws__%s__savingsplans__*.json.gz" % region)

    commit = {}
    for sku, rows in plans.items():
        three = [float(r["rate"]) for r in rows if r["years"] == 3]
        if three:
            commit[sku] = min(three)

    out = {}
    for sku, label in FOCUS:
        hist = spot.get(sku) or []
        if not hist or sku not in commit:
            continue
        # Daily mean across AZs: reduce to one price per AZ per day first, so a
        # volatile AZ cannot dominate the day's figure.
        per_day_az = defaultdict(dict)
        for h in hist:
            day = h["ts"][:10]
            az = h["az"]
            prev = per_day_az[day].get(az)
            if prev is None or h["ts"] > prev["ts"]:
                per_day_az[day][az] = h
        # Carry the last known price forward: spot history records *changes*, so
        # an AZ that did not reprice on a given day still has a live price.
        days = sorted(per_day_az)
        carried: dict[str, float] = {}
        points = []
        for day in days:
            for az, h in per_day_az[day].items():
                carried[az] = h["price"]
            if not carried:
                continue
            points.append({
                "d": day,
                "spot": round(st.mean(carried.values()), 4),
                "tp": round(st.mean(carried.values()) / commit[sku], 4),
            })
        out[sku] = {
            "label": label,
            "commit3y": round(commit[sku], 4),
            "points": points,
        }
    return out


def build_snapshot(panel) -> list:
    rows = ratio.build(panel)
    grouped = defaultdict(list)
    for r in rows:
        if not r["chip"]:
            continue
        grouped[(r["chip"], r["cloud"])].append(r["term_premium"])
    out = []
    for (chip, cloud), vals in grouped.items():
        meta = BY_KEY.get(chip)
        out.append({
            "chip": chip,
            "name": meta.name if meta else chip,
            "vram_gb": meta.vram_gb if meta else None,
            "launched": meta.launched if meta else None,
            "cloud": cloud,
            "n": len(vals),
            "median": round(st.median(vals), 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        })
    out.sort(key=lambda r: (-(r["vram_gb"] or 0), r["cloud"]))
    return out


def main() -> int:
    store = Store(ROOT / "data")
    days = sorted((ROOT / "data" / "raw").glob("dt=*"))
    if not days:
        print("no raw archive; run collect first")
        return 1
    day_dir = days[-1]

    payload = {
        "asof": day_dir.name.split("=", 1)[1],
        "history_region": "us-west-2",
        "history": build_history(day_dir, "us-west-2"),
        "snapshot": build_snapshot(store.load_panel()),
    }
    dest = ROOT / "data" / "chart_data.json"
    dest.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    hist_pts = sum(len(v["points"]) for v in payload["history"].values())
    print("wrote %s" % dest)
    print("  history: %d skus, %d points" % (len(payload["history"]), hist_pts))
    print("  snapshot: %d chip/cloud pairs" % len(payload["snapshot"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
