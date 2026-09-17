"""The term premium.

    term_premium = spot_price / three_year_committed_price     (same SKU)

Read it as: what the hourly market charges for capacity, as a multiple of what
the seller accepts to lock that same capacity away for three years.

    > 1.0   hourly buyers outbid committed buyers. Normal for scarce silicon.
    < 1.0   the seller is renting today, with no commitment, below the price it
            charges customers who commit for three years. That is not a
            discount schedule; it is inventory that will not move.

Why a ratio rather than a price:

* **Scale-invariant.** Numerator and denominator are the same SKU, so GPU count,
  vCPU, RAM and disk all cancel. No hardware spec table is needed, and none can
  be got wrong.
* **Cross-cloud comparable.** A dollar figure compares an AWS g7e to an Azure
  NC144ds only if you trust your normalisation. A ratio compares each seller to
  *its own* committed book, so it survives the clouds packaging chips
  differently.
* **Currency- and discount-neutral.** Enterprise discounts and FX apply to both
  legs.

Known limits, stated because the number invites overreach:

* AWS spot is administered-smoothed, not an auction, and has been since
  November 2017. This is not an order book.
* GCP spot is administered outright. Its *level* carries little capacity
  information; only its changes do. See collectors/gcp.py.
* The commitment leg is a list price. Large buyers negotiate below it, which
  biases the ratio **upward** -- so a reading below 1.0 is conservative.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

COMMIT_LEG = "commit3y"


def _key(row):
    return (row["cloud"], row["region"], row["sku"])


def build(panel, commit_leg=COMMIT_LEG):
    """Collapse a tidy panel into one term-premium row per (cloud, region, sku).

    Spot is averaged across zones: each zone is a separate capacity pool, and an
    unweighted mean of pools is the honest regional summary when pool sizes are
    not published. ``spot_min`` keeps the cheapest pool, which is the number a
    cost-driven buyer actually faces.
    """
    legs = defaultdict(lambda: defaultdict(list))
    meta = {}
    for row in panel:
        legs[_key(row)][row["price_type"]].append(row["usd_per_hour"])
        meta[_key(row)] = (row.get("chip"), row.get("vram_gb"))

    out = []
    for key, by_type in legs.items():
        spots = by_type.get("spot") or []
        commits = by_type.get(commit_leg) or []
        if not spots or not commits:
            continue
        cloud, region, sku = key
        chip, vram = meta[key]
        spot_mean = st.mean(spots)
        commit = min(commits)  # cheapest commitment = strongest form of the test
        ondemand = min(by_type["ondemand"]) if by_type.get("ondemand") else None
        out.append({
            "cloud": cloud,
            "region": region,
            "sku": sku,
            "chip": chip,
            "vram_gb": vram,
            "zones": len(spots),
            "spot_mean": round(spot_mean, 4),
            "spot_min": round(min(spots), 4),
            "commit3y": round(commit, 4),
            "ondemand": round(ondemand, 4) if ondemand else None,
            "term_premium": round(spot_mean / commit, 4),
            "term_premium_min": round(min(spots) / commit, 4),
            "inverted": spot_mean < commit,
        })
    out.sort(key=lambda r: (r["cloud"], r["chip"] or "", r["region"], r["sku"]))
    return out


def size_ladder(panel, price_type="spot"):
    """Price per size within a family, to test the 'bigger is cheaper' claim.

    A monotone ladder (2xl < 4xl < 8xl) is the norm: more vCPU and RAM around
    the same GPU costs more. An inversion at one rung is a fragmented pool --
    a shape nobody is asking for -- which is a weaker and more local claim than
    an idle fleet. Reporting the whole ladder makes the difference visible
    instead of resting on a single pair.
    """
    import re

    def family(sku):
        m = re.match(r"([a-z0-9\-]+?)\.(\d*)x?large", sku or "")
        return (m.group(1), m.group(2) or "1") if m else (sku, "")

    groups = defaultdict(lambda: defaultdict(list))
    for row in panel:
        if row["price_type"] != price_type:
            continue
        fam, size = family(row["sku"])
        groups[(row["cloud"], row["region"], fam)][size].append(row["usd_per_hour"])

    out = []
    for (cloud, region, fam), sizes in groups.items():
        if len(sizes) < 2:
            continue
        rungs = sorted(sizes.items(), key=lambda kv: int(kv[0] or 1))
        means = [(s, round(st.mean(v), 4)) for s, v in rungs]
        monotone = all(b[1] >= a[1] for a, b in zip(means, means[1:]))
        out.append({
            "cloud": cloud, "region": region, "family": fam,
            "ladder": means, "monotone": monotone,
        })
    out.sort(key=lambda r: (r["cloud"], r["family"], r["region"]))
    return out


def format_table(rows):
    if not rows:
        return "(no rows: need both a spot and a commit3y leg for the same SKU)"
    hdr = ("cloud", "region", "sku", "chip", "spot", "cheapest", "3yr", "ratio")
    widths = (6, 12, 34, 14, 8, 9, 8, 7)
    lines = ["".join(h.ljust(w) for h, w in zip(hdr, widths))]
    lines.append("-" * sum(widths))
    for r in rows:
        cells = (
            r["cloud"], r["region"], r["sku"][:33], (r["chip"] or "?")[:13],
            "%.3f" % r["spot_mean"], "%.3f" % r["spot_min"],
            "%.3f" % r["commit3y"], "%.2f" % r["term_premium"],
        )
        line = "".join(str(c).ljust(w) for c, w in zip(cells, widths))
        lines.append(line + ("  <-- BELOW 3yr" if r["inverted"] else ""))
    return "\n".join(lines)
