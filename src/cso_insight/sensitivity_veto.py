# Modified 2026-10-10: portable aggregate-only report recipes. Algorithms unchanged.
"""Retrospective tolerance sensitivity and a two-veto stage-aware comparator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

from cso_insight.comparison import LIMIT, linkage_partition, partition_counts
from cso_insight.fair_comparison import DEFINITION, fair_partition, pair_set
from cso_insight.linkage import NOTIFICATION, LinkageResult, SourceRow, build_linkage, link_snapshot

VERSION = "sensitivity-veto/1"
V2_VERSION = "simple-veto/1"
V2_DEFINITION = (
    "F (fair-simple/1) keys, stages, candidate ranking and greedy one-to-one scan, "
    "plus exactly two vetoes on a would-be link before it consumes either row: "
    "both known event types disagree after normalisation, or both parsed starts "
    "have an absolute gap strictly above 900 seconds. Event type takes precedence "
    "if both apply. A veto records no-link and leaves both rows available for later "
    "edges. Missing clocks/types do not veto. No chronology, coordinates, identity "
    "beyond F's keys, taxonomy, parent IDs, retractions or competition veto. No abstention."
)
DECISIONS = ("link", "abstain", "no link", "absent")


def group_changes(baseline: LinkageResult, variant: LinkageResult) -> dict[str, Any]:
    """Count by stable anchor, including changes in standalone-group coverage."""
    before = {str(g["group_id"]): g for g in baseline.groups}
    after = {str(g["group_id"]): g for g in variant.groups}
    lookup = {r.key: r.ordinal for r in baseline.rows}
    transitions = {f"{a} -> {b}": 0 for a in DECISIONS for b in DECISIONS if a != b}
    changed: list[dict[str, object]] = []
    partners = []
    for key in sorted(before.keys() | after.keys(), key=lambda k: lookup[k]):
        a, b = before.get(key), after.get(key)
        da, db = a["decision"] if a else "absent", b["decision"] if b else "absent"
        if da != db:
            transitions[f"{da} -> {db}"] += 1
            changed.append(
                {
                    "anchor_ordinal": lookup[key],
                    "baseline_decision": da,
                    "variant_decision": db,
                    "baseline_reason": a["reason"] if a else None,
                    "variant_reason": b["reason"] if b else None,
                }
            )
        elif da == "link" and a and b:
            if a["tool_matched_verified_row"] != b["tool_matched_verified_row"]:
                partners.append(
                    {
                        "anchor_ordinal": lookup[key],
                        "baseline_partner_ordinal": lookup[str(a["tool_matched_verified_row"])],
                        "variant_partner_ordinal": lookup[str(b["tool_matched_verified_row"])],
                    }
                )
    old, new = pair_set(linkage_partition(baseline)), pair_set(linkage_partition(variant))
    old_members = {k: g for g in linkage_partition(baseline).groups for k in g}
    new_members = {k: g for g in linkage_partition(variant).groups for k in g}
    return {
        "changed_group_decisions": len(changed),
        "group_decision_transitions": transitions,
        "same_decision_link_partner_changes": partners,
        "changed_groups": changed,
        "lost_linked_pairs": [sorted(lookup[k] for k in p) for p in sorted(old - new)],
        "gained_linked_pairs": [sorted(lookup[k] for k in p) for p in sorted(new - old)],
        "rows_with_changed_partner_or_paired_state": sum(
            old_members[k] != new_members[k] for k in old_members
        ),
    }


def compare_veto(rows: list[SourceRow], linked: LinkageResult) -> dict[str, Any]:
    v2, candidates = fair_partition(rows, simple_vetoes=True)
    ledger = linkage_partition(linked)
    lookup = {r.key: r for r in rows}
    anchors = {str(g["group_id"]): g for g in linked.groups}

    def ids(pair: tuple[str, ...]) -> list[int]:
        return sorted(lookup[k].ordinal for k in pair)

    def recorded(pair: tuple[str, str]) -> dict[str, Any]:
        n = next(k for k in pair if lookup[k].get("reporterClass") == NOTIFICATION)
        v = next(k for k in pair if k != n)
        group = anchors[n]
        record = next(
            p for p in cast(list[dict[str, str]], group["pair_decisions"]) if p["source_row"] == v
        )
        decision, reason = record["decision"], record["reason"]
        contradiction = decision == "no link" and (
            reason.startswith("contradictory ")
            or reason in {"different incident dates", "start times outside 15-minute window"}
        )
        if contradiction:
            category = "contradiction"
        elif group["decision"] == "abstain":
            category, reason = "abstain", cast(str, group["reason"])
        elif decision == "abstain":
            category = "abstain"
        else:
            category, reason = "no-link", cast(str, group["reason"])
        return {
            "source_row_ordinals": ids(pair),
            "L_category": category,
            "reason_class": reason,
            "L_pair_decision": decision,
            "L_pair_reason": record["reason"],
            "L_group_decision": group["decision"],
            "L_group_reason": group["reason"],
        }

    v_pairs, l_pairs = pair_set(v2), pair_set(ledger)
    f_pairs = pair_set(fair_partition(rows)[0])
    both = v_pairs & l_pairs
    extra = [recorded(p) for p in sorted(v_pairs - l_pairs, key=ids)]
    candidate_lookup = {tuple(sorted((c.notification, c.verified))): c for c in candidates}
    missing = []
    for pair in sorted(l_pairs - v_pairs, key=ids):
        candidate = candidate_lookup.get(pair)
        group = anchors[next(k for k in pair if lookup[k].get("reporterClass") == NOTIFICATION)]
        missing.append(
            {
                "source_row_ordinals": ids(pair),
                "V2_reason": candidate.reason
                if candidate
                else "F grouping key unavailable/different",
                "L_group_decision": group["decision"],
                "L_group_reason": group["reason"],
                "V2_occupying_pairs": [
                    {
                        "source_row_ordinals": ids((c.notification, c.verified)),
                        "clock_distance_seconds": c.clock_distance_seconds,
                    }
                    for c in candidates
                    if c.decision == "link" and set(pair) & {c.notification, c.verified}
                ],
            }
        )
    categories = ("abstain", "no-link", "contradiction")
    v_single = {g[0] for g in v2.groups if len(g) == 1}
    l_single = {g[0] for g in ledger.groups if len(g) == 1}
    return {
        "version": V2_VERSION,
        "definition": V2_DEFINITION,
        "F_definition": DEFINITION,
        "F_to_V2": {
            "F_pairs_removed": len(f_pairs - v_pairs),
            "alternate_pairs_added": len(v_pairs - f_pairs),
            "alternate_pairs_also_linked_by_L": len((v_pairs - f_pairs) & l_pairs),
            "alternate_pairs_not_linked_by_L": len((v_pairs - f_pairs) - l_pairs),
        },
        "methods": {"V2": partition_counts(v2, rows), "L": partition_counts(ledger, rows)},
        "agreement": {
            "both_link": len(both),
            "share_of_L_links": len(both) / len(l_pairs) if l_pairs else None,
            "share_of_V2_links": len(both) / len(v_pairs) if v_pairs else None,
            "V2_only_links": len(v_pairs - l_pairs),
            "L_only_links": len(l_pairs - v_pairs),
            "both_leave_unpaired_rows": len(v_single & l_single),
            "same_partner_or_both_singleton_rows": 2 * len(both) + len(v_single & l_single),
            "rows_with_different_partner_or_paired_state": len(rows)
            - 2 * len(both)
            - len(v_single & l_single),
            "additional_singletons_under_L_net": len(l_single) - len(v_single),
        },
        "V2_only_by_L_category": {c: sum(e["L_category"] == c for e in extra) for c in categories},
        "V2_only_by_L_reason_class": {
            c: dict(
                sorted(Counter(e["reason_class"] for e in extra if e["L_category"] == c).items())
            )
            for c in categories
        },
        "V2_only_by_recorded_L_pair_decision": dict(
            sorted(Counter(e["L_pair_decision"] for e in extra).items())
        ),
        "V2_only_by_recorded_L_group_decision": dict(
            sorted(Counter(e["L_group_decision"] for e in extra).items())
        ),
        "candidate_decision_counts": dict(sorted(Counter(c.decision for c in candidates).items())),
        "candidate_no_link_reasons": dict(
            sorted(Counter(c.reason for c in candidates if c.decision == "no-link").items())
        ),
        "V2_groups_source_row_ordinals": [ids(g) for g in v2.groups],
        "candidate_decisions": [
            {
                "notification_ordinal": lookup[c.notification].ordinal,
                "verified_ordinal": lookup[c.verified].ordinal,
                "clock_distance_seconds": c.clock_distance_seconds,
                "decision": c.decision,
                "reason": c.reason,
            }
            for c in candidates
        ],
        "all_V2_only_links_with_L_decisions": extra,
        "all_L_only_links_with_V2_reasons": missing,
    }


def analyze_rows(
    rows: list[SourceRow], digest: str, baseline: LinkageResult | None = None
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: r.ordinal)
    if len({r.key for r in rows}) != len(rows) or len({r.ordinal for r in rows}) != len(rows):
        raise ValueError("Duplicate source key or record ordinal")
    if any(r.snapshot_hash != digest for r in rows):
        raise ValueError("Source row snapshot identity mismatch")
    raw_before = json.dumps([r.raw for r in rows], sort_keys=True)
    baseline = baseline or build_linkage(rows, digest)
    sensitivity = []
    for tolerance in (5, 15, 30):
        run = (
            baseline
            if tolerance == 15
            else build_linkage(rows, digest, tolerance_minutes=tolerance)
        )
        sensitivity.append(
            {
                "tolerance_minutes": tolerance,
                "linkage_rule_version": "linkage/2",
                "decision_groups": {
                    k: run.summary[k]
                    for k in ("decision_groups", "links", "abstentions", "no_links")
                },
                "partition": partition_counts(linkage_partition(run), rows),
                "changes_against_15_minutes": group_changes(baseline, run),
            }
        )
    comparison = compare_veto(rows, baseline)
    if raw_before != json.dumps([r.raw for r in rows], sort_keys=True):
        raise ValueError("Source cells changed during analysis")
    return {
        "analysis_version": VERSION,
        "snapshot_sha256": digest,
        "source_rows": len(rows),
        "cso_source_rows": sum("CSO" in r.get("eventType") for r in rows),
        "ordered_source_keys_sha256": hashlib.sha256(
            ("\n".join(r.key for r in rows) + "\n").encode()
        ).hexdigest(),
        "sensitivity": sensitivity,
        "V2_versus_L": comparison,
        "decision_unit": (
            "Literal L decision groups, matched by source anchor. Groups may overlap source rows; "
            "absent is a coverage change, not an L decision. Reason wording alone is not a "
            "changed decision."
        ),
        "provenance": (
            "Applicant-designed, retrospective. F was commissioned after build 3; V2 and "
            "sensitivity were commissioned after the round-4 jury digest. Equal retention "
            "is not an external endorsement."
        ),
        "retention": (
            "All methods reference the same unchanged SourceRow objects. Every raw cell, "
            "including blanks and zeros, is retained by source reference; JSON exports only "
            "ordinals, decisions and generic reasons, not raw cells."
        ),
        "limitations": LIMIT
        + " None of the three tolerances is validated without an incident reference. "
        "No optimum or better setting is selected. No measured review time or workload benefit.",
    }


def analyze_snapshot(path: Path) -> dict[str, Any]:
    frozen = link_snapshot(path)
    return analyze_rows(frozen.rows, str(frozen.summary["snapshot_sha256"]), frozen)


def percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "undefined (no links)"


def entry_sentences(result: dict[str, Any]) -> list[str]:
    runs = result["sensitivity"]
    a = result["V2_versus_L"]["agreement"]
    return [
        f"On the same pinned {result['source_rows']:,} report rows, SpillLedger made "
        f"{runs[0]['decision_groups']['links']:,}, {runs[1]['decision_groups']['links']:,} "
        f"and {runs[2]['decision_groups']['links']:,} links at start-time tolerances of "
        "5, 15 and 30 minutes, respectively; none of these tolerances is validated "
        "without an incident reference.",
        "A retrospective stage-aware simple comparator with known-event-type and "
        f"greater-than-15-minute gap vetoes reproduced {a['both_link']:,} of SpillLedger's "
        f"{runs[1]['decision_groups']['links']:,} default links "
        f"({percent(a['share_of_L_links'])}), with {a['V2_only_links']:,} V2-only links and "
        f"{a['L_only_links']:,} SpillLedger-only links, while both retained every source "
        "row and raw measurement cell.",
        "These analyses describe differences in pairing decisions on an already inspected "
        "snapshot; without an independent incident reference, they establish neither "
        "correctness nor superiority and measure no review-time or water benefit.",
    ]


def render_analysis(result: dict[str, Any]) -> str:
    lines = [
        "# Start-time tolerance sensitivity and simple-veto comparator",
        "",
        "Local only; no push, network, Hub or publication.",
        "",
        f"Snapshot SHA-256: `{result['snapshot_sha256']}`. L `linkage/2`; V2 `{V2_VERSION}`.",
        "",
        result["provenance"],
        "",
        result["limitations"],
        "",
        "## Descriptive sensitivity",
        "",
        "Only the start-time tolerance changes; all other L rules and source rows are identical.",
        "",
        "| Tolerance (minutes) | Links | Abstentions | No-links | Decision groups | "
        "Changed group decisions vs 15 | Lost pairs | Gained pairs | "
        "Rows with changed partner/state |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["sensitivity"]:
        d, c = run["decision_groups"], run["changes_against_15_minutes"]
        values = [
            run["tolerance_minutes"],
            d["links"],
            d["abstentions"],
            d["no_links"],
            d["decision_groups"],
            c["changed_group_decisions"],
            len(c["lost_linked_pairs"]),
            len(c["gained_linked_pairs"]),
            c["rows_with_changed_partner_or_paired_state"],
        ]
        lines.append("| " + " | ".join(f"{v:,}" for v in values) + " |")
    lines.extend(
        [
            "",
            result["decision_unit"],
            "",
            "| Direction from 15-minute run | 5 minutes | 15 minutes | 30 minutes |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    directions = result["sensitivity"][0]["changes_against_15_minutes"][
        "group_decision_transitions"
    ]
    for direction in directions:
        counts = [
            r["changes_against_15_minutes"]["group_decision_transitions"][direction]
            for r in result["sensitivity"]
        ]
        if any(counts):
            lines.append(f"| {direction} | " + " | ".join(f"{n:,}" for n in counts) + " |")
    lines.extend(
        [
            "",
            "All unlisted transition directions are zero. "
            "Same-decision linked-partner changes (5/15/30): "
            + "/".join(
                str(len(r["changes_against_15_minutes"]["same_decision_link_partner_changes"]))
                for r in result["sensitivity"]
            )
            + ". Full changed-anchor and lost/gained-pair ledgers are in JSON.",
            "",
            "Widening the window can introduce competition and turn a link into an abstention; "
            "link counts need not increase monotonically. A window breach is a software rule "
            "outcome, not proof of a physical-incident contradiction.",
            "",
            "## Exact V2 definition",
            "",
            V2_DEFINITION,
            "",
            "F's unchanged base definition:",
            "",
            DEFINITION,
            "",
            "## V2 versus default L",
            "",
            "| Retention / partition metric | V2 | L |",
            "| --- | ---: | ---: |",
        ]
    )
    v = result["V2_versus_L"]
    for label, key in (
        ("Source rows retained", "source_rows_used"),
        ("Source rows excluded", "source_rows_left_out"),
        ("Groups", "groups"),
        ("Linked pairs", "multirow_groups"),
        ("Unpaired rows", "singleton_groups"),
        ("Nonblank volume cells retained", "rows_with_volume_retained"),
        ("Nonblank rainfall cells retained", "rows_with_rainfall_retained"),
    ):
        lines.append(f"| {label} | {v['methods']['V2'][key]:,} | {v['methods']['L'][key]:,} |")
    a = v["agreement"]
    lines.extend(
        [
            "",
            result["retention"],
            "",
            "| Link agreement | Count |",
            "| --- | ---: |",
            f"| Both link | {a['both_link']:,} |",
            f"| Share of L's links | {percent(a['share_of_L_links'])} |",
            f"| Share of V2's links | {percent(a['share_of_V2_links'])} |",
        ]
    )
    for label, key in (
        ("V2 links, L does not", "V2_only_links"),
        ("L links, V2 does not", "L_only_links"),
        ("Both leave unpaired, rows", "both_leave_unpaired_rows"),
        ("Same partner or both singleton, rows", "same_partner_or_both_singleton_rows"),
        ("Different partner or paired state, rows", "rows_with_different_partner_or_paired_state"),
    ):
        lines.append(f"| {label} | {a[key]:,} |")
    lines.extend(
        [
            "",
            "## L's reasons for V2-only links",
            "",
            "The classification matches the F report: pair-level contradictions take "
            "precedence, then a group or pair abstention, then other no-links. These are "
            "comparison categories, not necessarily literal pair decisions. Both levels "
            "and reasons are retained in JSON. The timing category, if present, means "
            "only a breach of the unvalidated rule.",
            "",
            "| L comparison category | V2-only pairs |",
            "| --- | ---: |",
        ]
    )
    lines.extend(f"| {c} | {n:,} |" for c, n in v["V2_only_by_L_category"].items())
    lines.extend(
        ["", "| L category | Recorded reason class | V2-only pairs |", "| --- | --- | ---: |"]
    )
    for category, reasons in v["V2_only_by_L_reason_class"].items():
        lines.extend(f"| {category} | {reason} | {count:,} |" for reason, count in reasons.items())
    lines.extend(["", "| L level | Literal decision | V2-only pairs |", "| --- | --- | ---: |"])
    for level in ("pair", "group"):
        lines.extend(
            f"| {level} | {decision} | {count:,} |"
            for decision, count in v[f"V2_only_by_recorded_L_{level}_decision"].items()
        )
    lines.extend(
        [
            "",
            "A literal pair link inside an abstaining group is a compatible edge blocked by "
            "competition; it is not an accepted L link. Remaining differences describe what "
            "L's further checks change, without establishing that they improve correctness "
            "or effort.",
            "",
            "| V2 candidate no-link reason | Candidate edges |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {reason} | {count:,} |" for reason, count in v["candidate_no_link_reasons"].items()
    )
    lines.extend(
        [
            "",
            "Candidate-edge veto counts are not F-only-link counts: vetoes occur during the "
            "scan, before row consumption, and can permit different later matches. Full V2 "
            "candidate, partition and disagreement ledgers are in JSON.",
            "",
            f"Relative to F, V2 removes {v['F_to_V2']['F_pairs_removed']:,} selected pairs "
            f"and adds {v['F_to_V2']['alternate_pairs_added']:,} alternate pairs: "
            f"{v['F_to_V2']['alternate_pairs_also_linked_by_L']:,} also linked by L and "
            f"{v['F_to_V2']['alternate_pairs_not_linked_by_L']:,} declined by L. "
            "V2 is a new greedy scan with vetoes, rather than a filter of F's final links.",
            "",
            "## Reproduction and targeted verification",
            "",
            "```sh",
            "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "
            "python3 "
            "-m cso_insight.release_cli --compare --input "
            "/path/to/rights-held.csv",
            "```",
            "",
            "Run from this worktree. The loader validates the pinned hash, required schema, "
            "18,759 source rows and 16,720 CSO rows. Outputs have no timestamps. Targeted "
            "fixtures and byte-deterministic production reproduction are recorded in the "
            "CEO inbox receipt; no full gate is run.",
            "",
            "## Three entry sentences",
            "",
        ]
    )
    lines.extend(f"{i}. {s}" for i, s in enumerate(entry_sentences(result), 1))
    return "\n".join(lines) + "\n"


def write_analysis(result: dict[str, Any], directory: Path) -> None:
    (directory / "CSO_SENSITIVITY_AND_VETO.md").write_text(
        render_analysis(result), encoding="utf-8"
    )
    (directory / "cso_sensitivity_and_veto.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
