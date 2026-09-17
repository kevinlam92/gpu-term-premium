"""Canonical chip registry.

One physical Nvidia part maps to many SKU names across clouds. The registry is
pattern-based on purpose: new SKUs appear constantly, and a tool that silently
drops what it cannot classify is useless for reporting. Anything unmatched is
surfaced by ``collect --report-unmapped`` rather than discarded.

``gpus`` is optional. The headline metric (spot / 3-year commitment for the same
SKU) is scale-invariant, so GPU count cancels. It is only needed to compare
dollars-per-GPU-hour *across* chips.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chip:
    key: str
    name: str
    vram_gb: int
    launched: str  # YYYY-MM, for vintage/decay analysis
    aws: tuple[str, ...] = ()
    azure: tuple[str, ...] = ()
    gcp: tuple[str, ...] = ()

    def matches(self, cloud: str, sku: str) -> bool:
        return any(re.fullmatch(p, sku, re.I) for p in getattr(self, cloud, ()))


REGISTRY: tuple[Chip, ...] = (
    Chip(
        key="rtx_pro_4500",
        name="RTX PRO 4500 Blackwell",
        vram_gb=32,
        launched="2026-03",
        aws=(r"g7\.\d*x?large",),
    ),
    Chip(
        key="rtx_pro_6000",
        name="RTX PRO 6000 Blackwell Server Edition",
        vram_gb=96,
        launched="2026-03",
        aws=(r"g7e\.\d*x?large",),
        azure=(r"Standard_NC\d+l?ds_xl_RTXPRO6000BSE_v6",),
    ),
    Chip(
        key="l40s",
        name="L40S",
        vram_gb=48,
        launched="2023-10",
        aws=(r"g6e\.\d*x?large",),
    ),
    Chip(
        key="l4",
        name="L4",
        vram_gb=24,
        launched="2023-03",
        aws=(r"g6\.\d*x?large", r"g6f\.\d*x?large"),
        gcp=(r"g2-standard-\d+",),
    ),
    Chip(
        key="a10g",
        name="A10G",
        vram_gb=24,
        launched="2021-11",
        aws=(r"g5\.\d*x?large",),
    ),
    Chip(
        key="h100",
        name="H100 SXM",
        vram_gb=80,
        launched="2023-03",
        aws=(r"p5\.\d*x?large",),
        azure=(r"Standard_ND96i?sr?_H100_v5",),
        gcp=(r"a3-highgpu-\d+g", r"a3-megagpu-\d+g"),
    ),
    Chip(
        key="h200",
        name="H200 SXM",
        vram_gb=141,
        launched="2024-09",
        aws=(r"p5e\.\d*x?large", r"p5en\.\d*x?large"),
        azure=(r"Standard_ND96i?sr?_H200_v5",),
        gcp=(r"a3-ultragpu-\d+g",),
    ),
    Chip(
        key="b200",
        name="B200",
        vram_gb=180,
        launched="2025-06",
        aws=(r"p6-b200\.\d*x?large",),
        azure=(r"Standard_ND96i?sr?_B200_v6",),
        gcp=(r"a4-highgpu-\d+g",),
    ),
    Chip(
        key="b300",
        name="B300",
        vram_gb=288,
        launched="2026-01",
        aws=(r"p6-b300\.\d*x?large",),
        gcp=(r"a4x-highgpu-\d+g",),
    ),
)

BY_KEY = {c.key: c for c in REGISTRY}


def classify(cloud: str, sku: str) -> Chip | None:
    for chip in REGISTRY:
        if chip.matches(cloud, sku):
            return chip
    return None


def patterns_for(cloud: str) -> list[str]:
    out: list[str] = []
    for chip in REGISTRY:
        out.extend(getattr(chip, cloud, ()))
    return out
