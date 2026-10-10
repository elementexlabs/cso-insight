"""Aggregate-only release entry point. No downloader or detailed page export."""

import argparse
import json
from pathlib import Path
from typing import cast

from cso_insight.linkage import build_linkage, load_source_rows
from cso_insight.synthetic import synthetic_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline candidate record linkage")
    parser.add_argument("--input", type=Path, help="Rights-held local CSV; never downloaded")
    parser.add_argument("--tolerance", type=int, default=15)
    parser.add_argument("--compare", action="store_true", help="Requires comparison candidate")
    args = parser.parse_args(argv)
    rows = load_source_rows(args.input) if args.input else synthetic_rows()
    digest = rows[0].snapshot_hash if rows else "empty-local-input"
    linked = build_linkage(rows, digest, tolerance_minutes=args.tolerance)
    pairs = sum(len(cast(list[str], group["source_rows"])) == 2 for group in linked.events)
    result: dict[str, object] = {
        "input_kind": "local rights-held input"
        if args.input
        else "original synthetic illustration",
        "source_rows": len(rows),
        "linked_pairs": pairs,
        "unpaired_rows": len(rows) - 2 * pairs,
        "candidate_records": len(linked.events),
        "tolerance_minutes": args.tolerance,
        "limit": "Software partitions, not confirmed discharges or measured accuracy.",
    }
    if args.compare:
        try:
            from cso_insight.comparison import linkage_partition
            from cso_insight.fair_comparison import fair_partition, pair_set
        except ImportError:
            parser.error("Use the comparison release candidate for --compare")
        current = pair_set(linkage_partition(linked))
        for label, veto in [("original_simple", False), ("two_veto_simple", True)]:
            partition, _ = fair_partition(rows, simple_vetoes=veto)
            pairs_other = pair_set(partition)
            result[label] = {
                "linked_pairs": len(pairs_other),
                "shared_links": len(current & pairs_other),
                "comparator_only": len(pairs_other - current),
                "spillledger_only": len(current - pairs_other),
            }
        result["comparison_window"] = (
            "Two-veto comparator fixed at 15 minutes; other SpillLedger windows "
            "are descriptive sensitivity."
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
