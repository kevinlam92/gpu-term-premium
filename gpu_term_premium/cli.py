"""Command line entry point.

    python -m gpu_term_premium collect --clouds aws azure
    python -m gpu_term_premium report
    python -m gpu_term_premium ladder
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

from . import ratio
from .store import FIELDS, Store

DEFAULT_REGIONS = {
    "aws": ["us-west-2", "us-east-1", "us-east-2"],
    "azure": ["westus2", "eastus", "eastus2"],
    "gcp": ["us-central1", "us-west1", "us-east4"],
}


def cmd_collect(args):
    store = Store(args.data)
    obs = []
    if "aws" in args.clouds:
        from .collectors import aws
        regions = args.regions or DEFAULT_REGIONS["aws"]
        print("aws: %s" % ", ".join(regions))
        obs += aws.collect(store, regions, profile=args.profile, days=args.days)
    if "azure" in args.clouds:
        from .collectors import azure
        regions = args.regions or DEFAULT_REGIONS["azure"]
        print("azure: %s" % ", ".join(regions))
        obs += azure.collect(store, regions)
    if "gcp" in args.clouds:
        from .collectors import gcp
        regions = args.regions or DEFAULT_REGIONS["gcp"]
        print("gcp: %s" % ", ".join(regions))
        obs += gcp.collect(store, regions)

    path = store.append_panel(obs)
    by_cloud = {}
    for o in obs:
        by_cloud[o.cloud] = by_cloud.get(o.cloud, 0) + 1
    print("\nwrote %d observations -> %s" % (len(obs), path))
    for cloud, n in sorted(by_cloud.items()):
        print("  %-6s %d" % (cloud, n))
    return 0


def cmd_report(args):
    store = Store(args.data)
    panel = store.load_panel()
    if not panel:
        print("no panel data; run collect first")
        return 1
    rows = ratio.build(panel)
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
    elif args.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    else:
        print(ratio.format_table(rows))
        inv = [r for r in rows if r["inverted"]]
        print("\n%d of %d SKU/region pairs price spot BELOW their 3-year rate."
              % (len(inv), len(rows)))
        for r in inv:
            print("  %s %s %s  ratio %.2f"
                  % (r["cloud"], r["region"], r["sku"], r["term_premium"]))
    return 0


def cmd_ladder(args):
    store = Store(args.data)
    panel = store.load_panel()
    if not panel:
        print("no panel data; run collect first")
        return 1
    for row in ratio.size_ladder(panel):
        flag = "" if row["monotone"] else "   <-- INVERTED"
        rungs = "  ".join("%sxl=%.3f" % (s, p) for s, p in row["ladder"])
        print("%-6s %-12s %-10s %s%s"
              % (row["cloud"], row["region"], row["family"], rungs, flag))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="gpu_term_premium")
    p.add_argument("--data", default="data", help="storage root (default: data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="fetch prices and append to the panel")
    c.add_argument("--clouds", nargs="+", default=["aws", "azure"],
                   choices=["aws", "azure", "gcp"])
    c.add_argument("--regions", nargs="+", help="override default regions")
    c.add_argument("--profile", help="AWS profile name")
    c.add_argument("--days", type=int, default=90, help="spot history lookback")
    c.set_defaults(func=cmd_collect)

    r = sub.add_parser("report", help="term premium per SKU")
    r.add_argument("--json", action="store_true")
    r.add_argument("--csv", action="store_true")
    r.set_defaults(func=cmd_report)

    l = sub.add_parser("ladder", help="within-family size ladder monotonicity")
    l.set_defaults(func=cmd_ladder)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
