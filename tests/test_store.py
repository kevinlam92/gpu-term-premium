"""The panel is read one collection day at a time.

Pooling days was a real bug: once a second day existed, spot was averaged over
both and the commitment leg took the cheaper of the two, so every published
ratio described a market that never existed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpu_term_premium import ratio  # noqa: E402
from gpu_term_premium.store import FIELDS, Store  # noqa: E402

HEADER = ",".join(FIELDS)


def write_day(root, day, spot, commit):
    lines = [HEADER]
    for price_type, price in (("spot", spot), ("commit3y", commit)):
        lines.append(f"{day}T00:00:00+00:00,aws,us-west-2,,g7.2xlarge,rtx_pro_4500,32,"
                     f"{price_type},{price},,,test")
    (root / "panel" / f"dt={day}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_latest_day_only(tmp_path):
    store = Store(tmp_path)
    write_day(tmp_path, "2026-09-17", spot=0.80, commit=1.00)
    write_day(tmp_path, "2026-10-23", spot=1.20, commit=1.00)
    rows = ratio.build(store.load_panel())
    assert len(rows) == 1
    assert rows[0]["term_premium"] == pytest.approx(1.20)  # not the 1.00 a pooled mean gives


def test_explicit_day(tmp_path):
    store = Store(tmp_path)
    write_day(tmp_path, "2026-09-17", spot=0.80, commit=1.00)
    write_day(tmp_path, "2026-10-23", spot=1.20, commit=1.00)
    rows = ratio.build(store.load_panel("2026-09-17"))
    assert rows[0]["term_premium"] == pytest.approx(0.80)
    assert store.panel_days() == ["2026-09-17", "2026-10-23"]


def test_missing_day_raises(tmp_path):
    store = Store(tmp_path)
    write_day(tmp_path, "2026-09-17", spot=0.80, commit=1.00)
    with pytest.raises(FileNotFoundError):
        store.load_panel("2026-10-01")


def test_empty_store(tmp_path):
    assert Store(tmp_path).load_panel() == []
