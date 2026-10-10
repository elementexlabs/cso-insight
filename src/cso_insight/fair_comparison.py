# Modified 2026-10-10: portable aggregate-only report recipes. Algorithms unchanged.
"""Evidence-preserving greedy cross-stage comparator on frozen local source rows."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cso_insight.comparison import LIMIT, Partition, group_key, linkage_partition, partition_counts
from cso_insight.linkage import (
    NOTIFICATION,
    VERIFIED,
    SourceRow,
    build_linkage,
    evidence_issue,
    known,
    link_snapshot,
    normal,
)

VERSION = "fair-simple/1"
DEFINITION = (
    "Keep every row and raw cell. Block on whitespace-normalised, case-insensitive "
    "permittee name (ID fallback when name is blank/unknown/other/n/a/none), outfall ID "
    "and parsed incident calendar date. Missing required keys never match. Within each "
    "block enumerate only Public Notification Report / Verified Data Report pairs. "
    "Sort by absolute start-clock distance in seconds, then notification record ordinal, "
    "then verified record ordinal. A missing/unparseable/ambiguous clock ranks after "
    "every finite distance, with the same ordinal tie-break. Scan this order once: link "
    "if both rows are still free; otherwise record no-link (row already paired). "
    "There is no distance cutoff or abstention. Do not use event type, coordinates, "
    "submission chronology, incident identifiers, reportingType or retraction flags "
    "to veto a pair. All unpaired rows, including missing-key and other-stage rows, "
    "remain singletons. Preserve every measurement separately through source references; "
    "never sum cells, choose a stage's value as truth, or merge same-stage rows."
)


@dataclass(frozen=True)
class Candidate:
    notification: str
    verified: str
    clock_distance_seconds: float | None
    decision: str
    reason: str


def fair_partition(
    rows: list[SourceRow], *, simple_vetoes: bool = False
) -> tuple[Partition, list[Candidate]]:
    """Global nearest available edge per block; never maximum-cardinality optimisation."""
    if len({r.key for r in rows}) != len(rows) or len({r.ordinal for r in rows}) != len(rows):
        raise ValueError("Duplicate source key or record ordinal")
    buckets: dict[tuple[object, ...], list[SourceRow]] = defaultdict(list)
    for row in rows:
        if (key := group_key(row, "S")) is not None:
            buckets[key].append(row)
    used: set[str] = set()
    groups: list[tuple[str, ...]] = []
    decisions: list[Candidate] = []
    # All ranking fields are intrinsic to the rows, never caller iteration order.
    edges: list[tuple[float, int, int, SourceRow, SourceRow]] = []
    for block in buckets.values():
        notifications = [r for r in block if r.get("reporterClass") == NOTIFICATION]
        verified = [r for r in block if r.get("reporterClass") == VERIFIED]
        for n in notifications:
            for v in verified:
                gap = (
                    abs((n.start - v.start).total_seconds())
                    if n.start is not None and v.start is not None
                    else float("inf")
                )
                edges.append((gap, n.ordinal, v.ordinal, n, v))
    for gap, _, _, n, v in sorted(edges, key=lambda edge: edge[:3]):
        selected = n.key not in used and v.key not in used
        reason = "nearest available cross-stage pair" if selected else "row already paired"
        if selected and simple_vetoes:
            if (
                known(n.get("eventType"))
                and known(v.get("eventType"))
                and normal(n.get("eventType")) != normal(v.get("eventType"))
            ):
                selected, reason = False, "contradictory eventType"
            elif gap != float("inf") and gap > 15 * 60:
                selected, reason = False, "start times outside 15-minute window"
        decisions.append(
            Candidate(
                n.key,
                v.key,
                None if gap == float("inf") else gap,
                "link" if selected else "no-link",
                reason,
            )
        )
        if selected:
            used.update((n.key, v.key))
            groups.append(tuple(sorted((n.key, v.key))))
    groups.extend((r.key,) for r in rows if r.key not in used)
    return Partition("V2" if simple_vetoes else "F", tuple(sorted(groups)), {}), decisions


def pair_set(partition: Partition) -> set[tuple[str, str]]:
    return {(group[0], group[1]) for group in partition.groups if len(group) == 2}


def compare_fair_rows(rows: list[SourceRow], digest: str) -> dict[str, object]:
    rows = sorted(rows, key=lambda r: r.ordinal)
    if any(r.snapshot_hash != digest for r in rows):
        raise ValueError("Source row snapshot identity mismatch")
    before = json.dumps([r.raw for r in rows], sort_keys=True)
    f, candidates = fair_partition(rows)
    linked = build_linkage(rows, digest)
    ledger = linkage_partition(linked)
    lookup = {r.key: r for r in rows}
    anchors = {str(g["group_id"]): g for g in linked.groups}
    f_pairs, l_pairs = pair_set(f), pair_set(ledger)
    both, f_only, l_only = f_pairs & l_pairs, f_pairs - l_pairs, l_pairs - f_pairs
    candidate_lookup = {tuple(sorted((c.notification, c.verified))): c for c in candidates}

    def ids(keys: tuple[str, ...]) -> list[int]:
        return sorted(lookup[key].ordinal for key in keys)

    def recorded(pair: tuple[str, str]) -> dict[str, object]:
        n = next(key for key in pair if lookup[key].get("reporterClass") == NOTIFICATION)
        v = next(key for key in pair if lookup[key].get("reporterClass") == VERIFIED)
        group = anchors[n]
        record = next(
            (
                p
                for p in cast(list[dict[str, str]], group["pair_decisions"])
                if p["source_row"] == v
            ),
            None,
        )
        if record is None:
            raise ValueError("F pair absent from L's recorded candidate block")
        pair_decision, pair_reason = record["decision"], record["reason"]
        # Contradiction is a report category; L literally records 'no link'.
        contradiction = pair_decision == "no link" and (
            pair_reason.startswith("contradictory ")
            or pair_reason in {"different incident dates", "start times outside 15-minute window"}
        )
        if contradiction:
            category, reason = "contradiction", pair_reason
        elif group["decision"] == "abstain":
            category, reason = "abstain", str(group["reason"])
        elif pair_decision == "abstain":
            category, reason = "abstain", pair_reason
        else:
            category, reason = "no-link", str(group["reason"])
        return {
            "source_row_ordinals": ids(pair),
            "notification_ordinal": lookup[n].ordinal,
            "verified_ordinal": lookup[v].ordinal,
            "L_category": category,
            "reason_class": reason,
            "L_group_decision": group["decision"],
            "L_group_reason": group["reason"],
            "L_pair_decision": pair_decision,
            "L_pair_reason": pair_reason,
        }

    extra = [recorded(pair) for pair in sorted(f_only, key=ids)]
    missing: list[dict[str, object]] = []
    for pair in sorted(l_only, key=ids):
        candidate = candidate_lookup.get(pair)
        reason = (
            candidate.reason
            if candidate is not None
            else "F key unavailable/different; L can use specific location and coordinates"
        )
        occupied = [
            c
            for c in candidates
            if c.decision == "link" and ({c.notification, c.verified} & set(pair))
        ]
        missing.append(
            {
                "source_row_ordinals": ids(pair),
                "F_reason": reason,
                "L_pair_clock_distance_seconds": candidate.clock_distance_seconds
                if candidate is not None
                else None,
                "F_occupying_pairs": [
                    {
                        **recorded(
                            cast(tuple[str, str], tuple(sorted((c.notification, c.verified))))
                        ),
                        "F_clock_distance_seconds": c.clock_distance_seconds,
                    }
                    for c in occupied
                ],
            }
        )
    categories = ("abstain", "no-link", "contradiction")
    examples: dict[str, list[dict[str, object]]] = {
        f"F_only_L_{category}": [e for e in extra if e["L_category"] == category][:10]
        for category in categories
    }
    examples["L_only"] = missing[:10]
    counts = {"F": partition_counts(f, rows), "L": partition_counts(ledger, rows)}
    if before != json.dumps([r.raw for r in rows], sort_keys=True):
        raise ValueError("Source cells changed during comparison")
    f_single = {g[0] for g in f.groups if len(g) == 1}
    l_single = {g[0] for g in ledger.groups if len(g) == 1}
    reasons = {
        category: dict(
            sorted(
                Counter(
                    str(e["reason_class"]) for e in extra if e["L_category"] == category
                ).items()
            )
        )
        for category in categories
    }
    exceptions = []
    for r in rows:
        flags = list(r.flags)
        if group_key(r, "S") is None:
            flags.append("F missing grouping key; singleton")
        if r.start is None:
            flags.append("F clock unresolved; ranks last")
        if r.get("reporterClass") not in {NOTIFICATION, VERIFIED}:
            flags.append("F other reporting stage; singleton")
        if issue := evidence_issue(r):
            flags.append(f"L evidence issue: {issue}")
        if flags:
            exceptions.append({"source_row_ordinal": r.ordinal, "flags": flags})
    return {
        "comparison_version": VERSION,
        "linkage_rule_version": linked.summary["rule_version"],
        "snapshot_sha256": digest,
        "source_rows": len(rows),
        "cso_source_rows": sum("CSO" in r.get("eventType") for r in rows),
        "ordered_source_keys_sha256": hashlib.sha256(
            ("\n".join(r.key for r in rows) + "\n").encode()
        ).hexdigest(),
        "F_definition": DEFINITION,
        "methods": counts,
        "agreement": {
            "both_link": len(both),
            "share_of_L_links": len(both) / len(l_pairs) if l_pairs else None,
            "share_of_F_links": len(both) / len(f_pairs) if f_pairs else None,
            "F_only_links": len(f_only),
            "L_only_links": len(l_only),
            "both_leave_unpaired_rows": len(f_single & l_single),
            "F_unpaired_rows": len(f_single),
            "L_unpaired_rows": len(l_single),
            "same_partner_or_both_singleton_rows": 2 * len(both) + len(f_single & l_single),
            "rows_with_different_partner_or_paired_state": len(rows)
            - 2 * len(both)
            - len(f_single & l_single),
            "additional_singletons_under_L_net": len(l_single) - len(f_single),
            "L_singleton_rows_F_pairs": len(l_single - f_single),
            "F_singleton_rows_L_pairs": len(f_single - l_single),
        },
        "F_only_by_L_category": {c: sum(e["L_category"] == c for e in extra) for c in categories},
        "F_only_by_L_reason_class": reasons,
        "F_only_by_recorded_L_pair_decision": dict(
            sorted(Counter(str(e["L_pair_decision"]) for e in extra).items())
        ),
        "F_only_by_recorded_L_group_decision": dict(
            sorted(Counter(str(e["L_group_decision"]) for e in extra).items())
        ),
        "L_decision_groups": {
            key: linked.summary[key]
            for key in ("decision_groups", "links", "no_links", "abstentions")
        },
        "F_candidate_decision_counts": dict(
            sorted(Counter(c.decision for c in candidates).items())
        ),
        "F_groups_source_row_ordinals": [ids(g) for g in f.groups],
        "F_candidate_decisions": [
            {
                "notification_ordinal": lookup[c.notification].ordinal,
                "verified_ordinal": lookup[c.verified].ordinal,
                "clock_distance_seconds": c.clock_distance_seconds,
                "decision": c.decision,
                "reason": c.reason,
            }
            for c in candidates
        ],
        "row_exception_ledger": exceptions,
        "all_F_only_links_with_L_decisions": extra,
        "all_L_only_links_with_F_reasons": missing,
        "examples": examples,
        "limitations": LIMIT,
        "retention": (
            "Both partitions reference the identical SourceRow objects and unchanged pinned "
            "CSV; every raw measurement cell, including blanks and zeros, is retained. "
            "The JSON exports only ordinals, generic decisions and exceptions; it does not "
            "copy raw cells. Source keys reconstruct as snapshot_sha256:row-{ordinal:06d}."
        ),
    }


def compare_fair_snapshot(path: Path) -> dict[str, object]:
    frozen = link_snapshot(path)
    return compare_fair_rows(frozen.rows, str(frozen.summary["snapshot_sha256"]))


def render_fair_comparison(result: dict[str, object]) -> str:
    """Render only aggregate counts and identifier-only witnesses."""
    a = cast(dict[str, int | float | None], result["agreement"])
    methods = cast(dict[str, dict[str, int]], result["methods"])
    extra = cast(dict[str, int], result["F_only_by_L_category"])
    lines = [
        "# Fair stage-aware simple comparator",
        "",
        "Local only; no push or publication.",
        "",
        f"Snapshot SHA-256: `{result['snapshot_sha256']}`. F `{VERSION}`; L `linkage/2`.",
        "",
        str(result["limitations"]),
        "",
        "## Exact F definition",
        "",
        DEFINITION,
        "",
        "This is greedy nearest-edge matching, not a global minimum-total-distance assignment. "
        "Spreadsheet rebuild: retain a source sheet with one-based CSV record ordinals; "
        "make a candidate sheet of cross-stage pairs whose complete normalised keys match; "
        "compute absolute clock differences (blank clocks sort last); sort by distance, "
        "notification ordinal and verified ordinal; scan downward and accept a pair only "
        "when neither ordinal has already been accepted. Assign every remaining source row "
        "its own group. Candidate no-links and row exceptions remain visible in the JSON.",
        "",
        "## Agreement and retention",
        "",
        "| Metric | F | L |",
        "| --- | ---: | ---: |",
    ]
    for label, key in (
        ("Source rows retained", "source_rows_used"),
        ("Source rows excluded", "source_rows_left_out"),
        ("Groups", "groups"),
        ("Linked pairs", "multirow_groups"),
        ("Unpaired rows", "singleton_groups"),
        ("Nonblank volume cells retained", "rows_with_volume_retained"),
        ("Nonblank rainfall cells retained", "rows_with_rainfall_retained"),
    ):
        lines.append(f"| {label} | {methods['F'][key]:,} | {methods['L'][key]:,} |")
    lines.extend(
        [
            "",
            str(result["retention"]),
            "",
            "| Link agreement | Count |",
            "| --- | ---: |",
            f"| Both link | {a['both_link']:,} |",
            f"| Share of L's links | {float(a['share_of_L_links'] or 0):.2%} |",
            f"| Share of F's links | {float(a['share_of_F_links'] or 0):.2%} |",
            f"| F links, L does not | {a['F_only_links']:,} |",
            f"| L links, F does not | {a['L_only_links']:,} |",
            f"| Both leave the row unpaired | {a['both_leave_unpaired_rows']:,} |",
            "| Same partner or both singleton, source rows | "
            f"{a['same_partner_or_both_singleton_rows']:,} |",
            "",
            "## F-only links and L's recorded reasons",
            "",
            "Categories are mutually exclusive. A recorded pair-level no-link for contradictory "
            "identity/location or a clock outside L's window is classified as contradiction "
            "even if its containing group abstains. Otherwise an abstaining group or pair is "
            "abstain; remaining refusals are no-link. Contradiction is this report's category; "
            "L records it literally as no link. JSON retains both group and pair decisions "
            "and reasons, including locally compatible pairs blocked by competition.",
            "",
            "| L category | F-only pairs |",
            "| --- | ---: |",
        ]
    )
    lines.extend(f"| {c} | {extra[c]:,} |" for c in extra)
    lines.extend(["", "| L category | Reason class | Pairs |", "| --- | --- | ---: |"])
    for category, reasons in cast(
        dict[str, dict[str, int]], result["F_only_by_L_reason_class"]
    ).items():
        for reason, count in reasons.items():
            lines.append(f"| {category} | {reason} | {count:,} |")
    lines.extend(
        [
            "",
            "For the same F-only pairs, the literal recorded decisions are:",
            "",
            "| L level | Recorded decision | F-only pairs |",
            "| --- | --- | ---: |",
        ]
    )
    for level in ("pair", "group"):
        literal = cast(dict[str, int], result[f"F_only_by_recorded_L_{level}_decision"])
        for decision, count in literal.items():
            lines.append(f"| {level} | {decision} | {count:,} |")
    lines.extend(
        [
            "",
            "The literal pair links are compatible pairs blocked by group competition. "
            "A literal group link can concern another verified row; it is not a link of the "
            "F-only pair. Category counts above use the complete pair and group context.",
        ]
    )
    lines.extend(
        [
            "",
            "## Identifier-only disagreement examples",
            "",
            "One-based CSV record ordinals under the pinned hash, not physical incident IDs. "
            "Ten per type where available; an empty category has no examples. Selection is "
            "deterministic by ordinal, not representative sampling. All disagreements are in JSON.",
        ]
    )
    for category, examples in cast(dict[str, list[dict[str, object]]], result["examples"]).items():
        lines.extend(["", f"### {category}", ""])
        if not examples:
            lines.append("No cases (0); no examples can be supplied.")
            continue
        lines.extend(
            [
                "| Row ordinals | L group decision | L pair decision | Reason class / F reason |",
                "| --- | --- | --- | --- |",
            ]
        )
        for e in examples:
            lines.append(
                f"| {e['source_row_ordinals']} | {e.get('L_group_decision', 'link')} | "
                f"{e.get('L_pair_decision', 'link')} | "
                f"{e.get('reason_class', e.get('F_reason', ''))} |"
            )
        if category == "L_only":
            lines.extend(
                [
                    "",
                    "Every L-only pair was displaced by an earlier selected F pair. "
                    "The table below traces those occupying pairs, their clock distance and "
                    "L's recorded refusal. A later displaced edge can have a shorter distance "
                    "than an occupying pair selected after the first endpoint was consumed.",
                    "",
                    "| L pair (distance seconds) | Occupying F pair (distance seconds) | "
                    "L refusal of occupying pair |",
                    "| --- | --- | --- |",
                ]
            )
            for e in examples:
                for occupying in cast(list[dict[str, object]], e["F_occupying_pairs"]):
                    lines.append(
                        f"| {e['source_row_ordinals']} "
                        f"({e['L_pair_clock_distance_seconds']}) | "
                        f"{occupying['source_row_ordinals']} "
                        f"({occupying['F_clock_distance_seconds']}) | "
                        f"{occupying['reason_class']} |"
                    )
    total = cast(int, result["source_rows"])
    same = int(a["same_partner_or_both_singleton_rows"] or 0)
    lines.extend(
        [
            "",
            "## What the comparison shows",
            "",
            f"F reproduces {a['both_link']:,} of L's {methods['L']['multirow_groups']:,} links "
            f"({float(a['share_of_L_links'] or 0):.2%}). The methods give the same partner or "
            f"both-singleton state to {same:,}/{total:,} rows ({same / total:.2%}). "
            "Agreement on most decisions is a valid result; it does not establish correctness.",
            "",
            f"F chooses {a['F_only_links']:,} additional pairings L declines. Those are "
            f"{a['F_only_links']:,} concrete extra pairing cases a reviewer would examine to "
            "reconcile L with F, rather than automatically accepting F's choice. "
            f"L keeps {a['L_singleton_rows_F_pairs']:,} rows singleton that F pairs, "
            f"and F keeps {a['F_singleton_rows_L_pairs']:,} rows singleton that L pairs. "
            "The net increase in singleton rows under L is "
            f"{a['additional_singletons_under_L_net']:,}. "
            "Pair cases, singleton rows, overlapping L decision groups and physical incidents "
            "are different units. This comparison measures no review minutes or actual workload.",
            "",
            f"L-only links: {a['L_only_links']:,}. "
            + (
                "There is no missed L link to explain on this snapshot."
                if not a["L_only_links"]
                else "Their occupying F pairs and recorded reasons are retained above and "
                "in JSON. On this snapshot, all were blocked by an already paired row; "
                "F does not veto contradictory event types before choosing the closest pair."
            ),
            "",
            "The test isolates decision logic with equal source and measurement retention. "
            "Caution about competing matches, missing evidence, chronology and known "
            "contradictions changes decisions, but cannot show which choice identifies the "
            "same physical discharge. There is no incident reference, accuracy, superiority, "
            "time-saving or water-benefit result. V remains a coarser verified-only reporting "
            "proxy; it is not the comparator used here.",
            "",
            "## Reproduction and tests",
            "",
            "```sh",
            "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "
            "python3 "
            "-m cso_insight.release_cli --compare --input "
            "/path/to/rights-held.csv",
            "```",
            "",
            "Run from this worktree. The production loader enforces the pinned hash, required "
            "schema, 18,759 source rows and 16,720 CSO rows. Outputs contain no timestamps. "
            "Hand-made fixtures cover one-to-one, nearest clocks, missing clocks, ordinal "
            "ties, same-stage isolation, exact keys, evidence preservation, conservation and "
            "recorded L reasons. Targeted results and byte-deterministic reproduction are "
            "recorded in the CEO inbox receipt; no full gate is run.",
            "",
            "## Three entry sentences",
            "",
            f"1. On the same pinned {total:,} report rows, an evidence-preserving stage-aware "
            f"simple comparator reproduced {a['both_link']:,} of SpillLedger's "
            f"{methods['L']['multirow_groups']:,} links ({float(a['share_of_L_links'] or 0):.2%}), "
            "with both methods retaining every source row and measurement cell.",
            f"2. The simple comparator chose {a['F_only_links']:,} additional pairings "
            f"SpillLedger declined: {extra['abstain']:,} abstentions, "
            f"{extra['no-link']:,} other no-links and {extra['contradiction']:,} recorded "
            "contradictions under the comparison's disclosed classification.",
            "3. These results show where caution changes pairing decisions and identifies "
            "cases for review; without an independent incident reference, they do not show "
            "which method is right or measure accuracy, review time or water benefits.",
            "",
        ]
    )
    return "\n".join(lines)


def write_fair_comparison(result: dict[str, object], markdown: Path, machine: Path) -> None:
    markdown.write_text(render_fair_comparison(result), encoding="utf-8")
    machine.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
