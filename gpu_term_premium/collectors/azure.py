"""Azure collector: Retail Prices API (anonymous, no subscription needed).

One response carries all four legs -- Consumption, Spot, and Reservation at 1yr
and 3yr -- which makes Azure the cleanest of the three clouds to instrument.

Three traps this handles, all of which produce plausible-looking wrong numbers:

1. Reservation rows quote a **lump sum for the whole term** while still
   reporting unitOfMeasure "1 Hour". Taking retailPrice at face value overstates
   the commitment rate by four to five orders of magnitude. Divided by term
   hours here.
2. ``DevTestConsumption`` rows are a subscription-gated discount, not a market
   price. Excluded -- including them would roughly halve the apparent spot rate.
3. Spot is distinguished only by " Spot" in meterName; armSkuName is identical
   to the on-demand row.
"""
from __future__ import annotations

import time
import urllib.parse

import requests

from ..chips import classify, patterns_for
from ..store import Obs, utcnow

BASE = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"  # exposes savingsPlan + reservationTerm
TERM_HOURS = {"1 Year": 8760, "3 Years": 26280}
USER_AGENT = "gpu-term-premium/0.1 (research; +price-transparency)"


def _fetch_all(flt, max_pages=100):
    """Page through an OData filter. The API caps at 100 items per page."""
    url = BASE + "?" + urllib.parse.urlencode(
        {"$filter": flt, "api-version": API_VERSION}
    )
    items = []
    pages = 0
    while url and pages < max_pages:
        resp = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("Items", []))
        url = body.get("NextPageLink")
        pages += 1
        if url:
            time.sleep(0.2)  # be a polite anonymous caller
    return items


def _sku_filter(region, needle):
    return (
        "serviceName eq 'Virtual Machines' "
        "and armRegionName eq '%s' "
        "and contains(armSkuName, '%s')" % (region, needle)
    )


def _needles():
    """Coarse substrings to pull candidate SKUs, refined by the registry.

    The API has no regex support, so this over-fetches on purpose and lets
    chips.classify() do the precise matching.
    """
    out = set()
    for pat in patterns_for("azure"):
        # Standard_NC\d+l?ds_xl_RTXPRO6000BSE_v6 -> RTXPRO6000BSE
        for token in ("RTXPRO6000BSE", "H100", "H200", "B200", "GB200"):
            if token.lower() in pat.lower():
                out.add(token)
    return sorted(out) or ["H100"]


def collect(store, regions, needles=None):
    obs = []
    now = utcnow()
    needles = needles or _needles()
    for region in regions:
        raw_region = []
        for needle in needles:
            try:
                items = _fetch_all(_sku_filter(region, needle))
            except requests.HTTPError as exc:
                print("  azure %s/%s failed: %s" % (region, needle, exc))
                continue
            raw_region.extend(items)
            for it in items:
                # Trap 2: dev/test rates are not market rates.
                if it.get("type") == "DevTestConsumption":
                    continue
                sku = it.get("armSkuName") or ""
                chip = classify("azure", sku)
                if not chip:
                    continue
                meter = it.get("meterName", "")
                price = float(it.get("retailPrice") or 0.0)
                if price <= 0:
                    continue
                kind = it.get("type")
                term = it.get("reservationTerm")
                if kind == "Reservation" and term in TERM_HOURS:
                    hours = TERM_HOURS[term]
                    # Trap 1: retailPrice is the whole-term lump sum.
                    price_type = "commit%dy" % (1 if term == "1 Year" else 3)
                    obs.append(Obs(
                        asof=now, cloud="azure", region=region, zone=None,
                        sku=sku, chip=chip.key, vram_gb=chip.vram_gb,
                        price_type=price_type, usd_per_hour=price / hours,
                        term_hours=hours, payment="All Upfront",
                        source="azure:retail-prices",
                    ))
                elif kind == "Consumption":
                    # Trap 3: spot is flagged in meterName, not in armSkuName.
                    is_spot = "spot" in meter.lower()
                    obs.append(Obs(
                        asof=now, cloud="azure", region=region, zone=None,
                        sku=sku, chip=chip.key, vram_gb=chip.vram_gb,
                        price_type="spot" if is_spot else "ondemand",
                        usd_per_hour=price, term_hours=None, payment=None,
                        source="azure:retail-prices",
                    ))
        store.write_raw("azure", region, raw_region)
    return obs
