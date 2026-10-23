"""Tidy panel + raw snapshot persistence.

Two layers, deliberately:

* ``raw/``   — every upstream response, gzipped, partitioned by date. Nothing is
  ever recomputed from a summary; a published number can always be traced back
  to the bytes the vendor served.
* ``panel/`` — one tidy CSV per collection date. Append-only.

Journalism, not analytics: the raw layer is the citation.
"""
from __future__ import annotations

import csv
import gzip
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PRICE_TYPES = ("spot", "ondemand", "commit1y", "commit3y")

FIELDS = (
    "asof", "cloud", "region", "zone", "sku", "chip", "vram_gb",
    "price_type", "usd_per_hour", "term_hours", "payment", "source",
)


@dataclass
class Obs:
    """One price observation. ``usd_per_hour`` is always normalised to an
    hourly rate: upfront commitments are divided by their term length."""
    asof: str
    cloud: str
    region: str
    zone: str | None
    sku: str
    chip: str | None
    vram_gb: int | None
    price_type: str
    usd_per_hour: float
    term_hours: int | None
    payment: str | None
    source: str

    def __post_init__(self) -> None:
        if self.price_type not in PRICE_TYPES:
            raise ValueError(f"bad price_type {self.price_type!r}")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)
        (self.root / "panel").mkdir(parents=True, exist_ok=True)

    def _day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def write_raw(self, cloud: str, name: str, payload: object) -> Path:
        d = self.root / "raw" / f"dt={self._day()}"
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        path = d / f"{cloud}__{name}__{stamp}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def append_panel(self, rows: list[Obs]) -> Path:
        path = self.root / "panel" / f"dt={self._day()}.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            for r in rows:
                w.writerow(asdict(r))
        return path

    def panel_days(self) -> list[str]:
        """Collection dates with a panel file, oldest first."""
        return sorted(p.stem.split("=", 1)[1]
                      for p in (self.root / "panel").glob("dt=*.csv"))

    def load_panel(self, day: str | None = None) -> list[dict]:
        """Rows for one collection day, the latest by default.

        Days are never pooled. ``ratio.build`` averages every spot row it is
        given and takes the cheapest commitment, so a multi-day panel would
        blend two markets into one number that no seller ever quoted.
        """
        days = self.panel_days()
        if not days:
            return []
        day = day or days[-1]
        path = self.root / "panel" / f"dt={day}.csv"
        if not path.exists():
            raise FileNotFoundError(f"no panel for {day}; have {', '.join(days)}")
        out: list[dict] = []
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                row["usd_per_hour"] = float(row["usd_per_hour"])
                out.append(row)
        return out
