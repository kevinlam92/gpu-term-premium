"""Tests for the metric and for the three normalisation traps.

Each trap here produced a plausible-looking wrong number during development, so
they are pinned rather than trusted.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpu_term_premium import ratio  # noqa: E402
from gpu_term_premium.chips import classify  # noqa: E402
from gpu_term_premium.collectors.azure import TERM_HOURS  # noqa: E402


def row(cloud, region, sku, price_type, price, chip="rtx_pro_4500", vram=32):
    return {
        "cloud": cloud, "region": region, "sku": sku, "chip": chip,
        "vram_gb": vram, "price_type": price_type, "usd_per_hour": price,
        "zone": "", "asof": "", "term_hours": "", "payment": "", "source": "",
    }


def test_inversion_detected():
    panel = [
        row("aws", "us-west-2", "g7.2xlarge", "spot", 0.74),
        row("aws", "us-west-2", "g7.2xlarge", "commit3y", 0.9475),
    ]
    out = ratio.build(panel)
    assert len(out) == 1
    assert out[0]["inverted"] is True
    assert abs(out[0]["term_premium"] - 0.7810) < 1e-3


def test_no_inversion_for_scarce_chip():
    panel = [
        row("aws", "us-west-2", "g7e.2xlarge", "spot", 2.406, chip="rtx_pro_6000"),
        row("aws", "us-west-2", "g7e.2xlarge", "commit3y", 1.2645, chip="rtx_pro_6000"),
    ]
    out = ratio.build(panel)
    assert out[0]["inverted"] is False
    assert out[0]["term_premium"] > 1.9


def test_spot_averaged_across_zones_not_events():
    """Four zones, one of which is far cheaper. The mean must weight zones
    equally; a mean over raw events would let a chatty zone dominate."""
    panel = [row("aws", "us-west-2", "g7.2xlarge", "spot", p)
             for p in (0.79, 0.81, 0.87, 0.64)]
    panel.append(row("aws", "us-west-2", "g7.2xlarge", "commit3y", 0.9475))
    out = ratio.build(panel)
    assert out[0]["zones"] == 4
    assert abs(out[0]["spot_mean"] - 0.7775) < 1e-4
    assert abs(out[0]["spot_min"] - 0.64) < 1e-9


def test_ratio_is_scale_invariant():
    """The headline metric must not depend on GPU count, so a SKU with 8 GPUs
    priced 8x gives the same ratio as a 1-GPU SKU. This is why no hardware spec
    table is needed."""
    small = ratio.build([
        row("aws", "us-west-2", "g7.2xlarge", "spot", 0.74),
        row("aws", "us-west-2", "g7.2xlarge", "commit3y", 0.9475),
    ])[0]
    big = ratio.build([
        row("aws", "us-west-2", "g7.48xlarge", "spot", 0.74 * 8),
        row("aws", "us-west-2", "g7.48xlarge", "commit3y", 0.9475 * 8),
    ])[0]
    assert abs(small["term_premium"] - big["term_premium"]) < 1e-9


def test_cheapest_commitment_wins():
    """Several payment options may be returned. Using the cheapest is the
    strongest form of the test -- a dearer one would flatter the thesis."""
    panel = [
        row("aws", "us-west-2", "g7.2xlarge", "spot", 0.90),
        row("aws", "us-west-2", "g7.2xlarge", "commit3y", 1.2096),
        row("aws", "us-west-2", "g7.2xlarge", "commit3y", 0.9475),
    ]
    out = ratio.build(panel)
    assert abs(out[0]["commit3y"] - 0.9475) < 1e-9
    assert out[0]["inverted"] is True


def test_sku_without_both_legs_is_dropped():
    panel = [row("aws", "us-west-2", "g7.2xlarge", "spot", 0.74)]
    assert ratio.build(panel) == []


def test_azure_reservation_is_a_lump_sum_not_an_hourly_rate():
    """Trap 1: the API reports a whole-term total while labelling it '1 Hour'.
    127195 USD over three years is 4.84/hr, not 127195/hr."""
    assert TERM_HOURS["3 Years"] == 26280
    assert abs(127195.0 / TERM_HOURS["3 Years"] - 4.8399) < 1e-3
    assert abs(61670.0 / TERM_HOURS["1 Year"] - 7.0399) < 1e-3


def test_size_ladder_flags_inversion():
    panel = [
        row("aws", "us-west-2", "g7.2xlarge", "spot", 0.740),
        row("aws", "us-west-2", "g7.4xlarge", "spot", 0.620),
        row("aws", "us-west-2", "g7.8xlarge", "spot", 0.994),
    ]
    out = ratio.size_ladder(panel)
    assert len(out) == 1
    assert out[0]["monotone"] is False
    assert out[0]["ladder"] == [("2", 0.74), ("4", 0.62), ("8", 0.994)]


def test_size_ladder_monotone_family_not_flagged():
    panel = [
        row("aws", "us-east-2", "g7e.2xlarge", "spot", 1.915, chip="rtx_pro_6000"),
        row("aws", "us-east-2", "g7e.4xlarge", "spot", 2.698, chip="rtx_pro_6000"),
    ]
    out = ratio.size_ladder(panel)
    assert out[0]["monotone"] is True


def test_registry_matches_real_skus_and_rejects_cpu_types():
    assert classify("aws", "g7.2xlarge").key == "rtx_pro_4500"
    assert classify("aws", "g7e.48xlarge").key == "rtx_pro_6000"
    assert classify("aws", "p6-b200.48xlarge").key == "b200"
    assert classify("azure", "Standard_NC264lds_xl_RTXPRO6000BSE_v6").key == "rtx_pro_6000"
    # g7 and g7e must not collide
    assert classify("aws", "g7e.2xlarge").key != classify("aws", "g7.2xlarge").key
    assert classify("aws", "m5.large") is None
    assert classify("aws", "c7i.4xlarge") is None
