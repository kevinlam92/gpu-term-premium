"""GCP collector: Cloud Billing Catalog API.

GCP is the odd one out, and the difference is the whole point of collecting it.

AWS and Azure spot prices move with pool load. **GCP Spot prices are
administered** -- Google resets them on roughly a monthly cadence by decision,
not by market. So a GCP spot level is not a capacity reading, and treating it as
one is the single easiest way to get this analysis wrong.

What GCP is good for instead: the *timing and size of a price change*. An
administered cut is a dated decision a human signed off on, which is arguably
stronger evidence of soft demand than a market print. Collect the level, diff it
over time, and report the changes -- not the level.

Convenient upside: the catalog exposes commitment pricing natively as usageType
``Commit1Yr`` / ``Commit3Yr``, so no term-length arithmetic is needed.

Needs an API key (no OAuth): set ``GCP_BILLING_API_KEY``. Without one the
collector is skipped rather than failing the run.
"""
from __future__ import annotations

import os
import re
import time

import requests

from ..store import Obs, utcnow

COMPUTE_SERVICE = "services/6F81-5844-456A"  # Compute Engine
BASE = "https://cloudbilling.googleapis.com/v1"

USAGE_MAP = {
    "OnDemand": "ondemand",
    "Preemptible": "spot",
    "Commit1Yr": "commit1y",
    "Commit3Yr": "commit3y",
}

# The catalog names the accelerator in free text, e.g.
# "Nvidia H100 80GB GPU attached to Spot Preemptible VMs running in Americas".
CHIP_PATTERNS = (
    ("h100", r"h100"),
    ("h200", r"h200"),
    ("b200", r"b200"),
    ("l4", r"\bl4\b"),
    ("a10g", r"\ba10\b"),
)
VRAM = {"h100": 80, "h200": 141, "b200": 180, "l4": 24, "a10g": 24}


def _chip_from_description(desc):
    low = desc.lower()
    if "gpu" not in low:
        return None
    for key, pat in CHIP_PATTERNS:
        if re.search(pat, low):
            return key
    return None


def _fetch_skus(api_key, max_pages=60):
    url = "%s/%s/skus" % (BASE, COMPUTE_SERVICE)
    params = {"key": api_key, "pageSize": 5000}
    out = []
    pages = 0
    token = None
    while pages < max_pages:
        if token:
            params["pageToken"] = token
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        out.extend(body.get("skus", []))
        token = body.get("nextPageToken")
        pages += 1
        if not token:
            break
        time.sleep(0.2)
    return out


def _unit_price(sku):
    """Latest tiered rate, converted from nanos to dollars."""
    infos = sku.get("pricingInfo") or []
    if not infos:
        return None
    tiers = infos[-1].get("pricingExpression", {}).get("tieredRates") or []
    if not tiers:
        return None
    unit = tiers[-1].get("unitPrice", {})
    return int(unit.get("units", 0)) + int(unit.get("nanos", 0)) / 1e9


def collect(store, regions, api_key=None):
    api_key = api_key or os.environ.get("GCP_BILLING_API_KEY")
    if not api_key:
        print("  gcp: no GCP_BILLING_API_KEY set, skipping")
        return []
    try:
        skus = _fetch_skus(api_key)
    except requests.HTTPError as exc:
        print("  gcp: catalog fetch failed: %s" % exc)
        return []
    store.write_raw("gcp", "compute-skus", skus)

    now = utcnow()
    wanted = set(regions)
    obs = []
    for sku in skus:
        cat = sku.get("category", {})
        if cat.get("resourceGroup") != "GPU":
            continue
        price_type = USAGE_MAP.get(cat.get("usageType"))
        if not price_type:
            continue
        desc = sku.get("description", "")
        chip = _chip_from_description(desc)
        if not chip:
            continue
        price = _unit_price(sku)
        if not price or price <= 0:
            continue
        for region in sku.get("serviceRegions", []):
            if wanted and region not in wanted:
                continue
            obs.append(Obs(
                asof=now, cloud="gcp", region=region, zone=None,
                sku=sku.get("skuId", ""), chip=chip, vram_gb=VRAM.get(chip),
                price_type=price_type, usd_per_hour=price,
                term_hours=None, payment=None,
                source="gcp:billing-catalog|" + desc[:80],
            ))
    return obs
