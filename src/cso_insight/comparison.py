# Modified 2026-10-10: portable aggregate-only report recipes. Algorithms unchanged.
"""Local same-record grouping comparison; no incident-reference inference."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from cso_insight.config import EXPECTED_DOWNLOAD_SHA256
from cso_insight.linkage import (
    NOTIFICATION,
    RULE_VERSION,
    VERIFIED,
    LinkageResult,
    SourceRow,
    build_linkage,
    known,
    load_source_rows,
    normal,
    number,
    permittee,
)

VERSION = "same-record/1"
DEFINITIONS = {
    "V": (
        "Verified Data Report rows only, excluding explicit retractions; group by "
        "(normalised permittee name with ID fallback, normalised event type, incident "
        "calendar date). Omit rows missing any key. This is the existing verified-row "
        "proxy, not an official incident count."
    ),
    "S": (
        "All stages and event types; group by (normalised permittee name with ID "
        "fallback, normalised outfallId, incident calendar date). Omit rows missing "
        "any key. Ignore event type, clocks, submission chronology, coordinates, "
        "stage, parent IDs and retraction tokens."
    ),
    "L": (
        "Unchanged linkage/2 on all source rows: only unique reciprocal compatible "
        "notification/verified pairs merge; competing viable components and missing "
        "evidence abstain. Every unpaired row remains a singleton. Known contradictions "
        "refuse a pair. See docs/LINKAGE.md for the complete frozen rules."
    ),
}
S_JUSTIFICATION = (
    "The permittee/outfall/date key is a transparent location-day grouping that "
    "deliberately ignores timing and cross-stage ambiguity."
)
LIMIT = (
    "Without an independent incident reference, none of this measures accuracy, "
    "recall, superiority, physical discharge counts or water benefits. The existing "
    "automated, assisted, unblinded review passes are not an incident reference."
)


@dataclass(frozen=True)
class Partition:
    """Disjoint grouped rows and explicit exclusions from the common input."""

    method: str
    groups: tuple[tuple[str, ...], ...]
    excluded: dict[str, str]

    @property
    def membership(self) -> dict[str, int]:
        return {key: i for i, group in enumerate(self.groups) for key in group}


def group_key(row: SourceRow, method: str) -> tuple[str, str, date] | None:
    identity = permittee(row)
    field = "eventType" if method == "V" else "outfallId"
    value = row.get(field)
    if not identity or not known(value) or row.day is None:
        return None
    return identity, normal(value), row.day


def key_partition(rows: list[SourceRow], method: str) -> Partition:
    if method not in {"V", "S"}:
        raise ValueError("Key partition requires V or S")
    buckets: dict[tuple[str, str, date], list[str]] = defaultdict(list)
    excluded: dict[str, str] = {}
    for row in rows:
        if method == "V" and row.get("reporterClass") != VERIFIED:
            excluded[row.key] = "not a verified report"
        elif method == "V" and row.retracted:
            excluded[row.key] = "explicit retraction"
        elif (key := group_key(row, method)) is None:
            excluded[row.key] = "missing required grouping key"
        else:
            buckets[key].append(row.key)
    groups = tuple(sorted(tuple(sorted(values)) for values in buckets.values()))
    return Partition(method, groups, dict(sorted(excluded.items())))


def linkage_partition(linked: LinkageResult) -> Partition:
    groups = tuple(
        sorted(tuple(sorted(cast(list[str], event["source_rows"]))) for event in linked.events)
    )
    return Partition("L", groups, {})


def partition_counts(partition: Partition, rows: list[SourceRow]) -> dict[str, object]:
    keys = {row.key for row in rows}
    members = [key for group in partition.groups for key in group]
    used = set(members)
    excluded = set(partition.excluded)
    if (
        len(members) != len(used)
        or used & excluded
        or used | excluded != keys
        or any(not group for group in partition.groups)
    ):
        raise ValueError(f"{partition.method} does not reconcile to the common source rows")
    lookup = {row.key: row for row in rows}
    counts: dict[str, object] = {
        "groups": len(partition.groups),
        "source_rows_offered": len(rows),
        "source_rows_used": len(used),
        "source_rows_left_out": len(excluded),
        "exclusion_reasons": dict(sorted(Counter(partition.excluded.values()).items())),
        "used_by_report_class": dict(
            sorted(Counter(lookup[key].get("reporterClass") for key in used).items())
        ),
        "singleton_groups": sum(len(group) == 1 for group in partition.groups),
        "multirow_groups": sum(len(group) > 1 for group in partition.groups),
        "largest_group_rows": max(map(len, partition.groups), default=0),
        "within_group_row_pairs": sum(choose_two(len(group)) for group in partition.groups),
    }
    for label, field in (("volume", "volumnOfEvent"), ("rainfall", "rainfallData")):
        present = {row.key for row in rows if row.get(field)}
        usable = {
            row.key for row in rows if (value := number(row.get(field))) is not None and value >= 0
        }
        counts[f"rows_with_{label}_retained"] = len(used & present)
        counts[f"rows_with_{label}_left_out"] = len(excluded & present)
        counts[f"rows_with_valid_numeric_{label}_retained"] = len(used & usable)
        counts[f"groups_with_{label}"] = sum(bool(set(g) & present) for g in partition.groups)
    volume = {row.key for row in rows if row.get("volumnOfEvent")}
    rain = {row.key for row in rows if row.get("rainfallData")}
    counts["rows_with_both_measurements_retained"] = len(used & volume & rain)
    counts["groups_with_both_measurements"] = sum(
        bool(set(g) & volume) and bool(set(g) & rain) for g in partition.groups
    )
    return counts


def choose_two(n: int) -> int:
    return n * (n - 1) // 2


def split_pairs(group: tuple[str, ...], membership: dict[str, int]) -> int:
    same = Counter(membership[key] for key in group if key in membership)
    return choose_two(len(group)) - sum(choose_two(n) for n in same.values())


def compare_rows(rows: list[SourceRow], digest: str) -> dict[str, object]:
    """Offer the identical sorted row objects to all three fixed methods."""
    rows = sorted(rows, key=lambda row: row.ordinal)
    if len({row.key for row in rows}) != len(rows):
        raise ValueError("Duplicate source row keys")
    if any(row.snapshot_hash != digest for row in rows):
        raise ValueError("Source row snapshot identity mismatch")
    linked = build_linkage(rows, digest)
    partitions = {"V": key_partition(rows, "V"), "S": key_partition(rows, "S")}
    partitions["L"] = linkage_partition(linked)
    membership = {method: part.membership for method, part in partitions.items()}
    lookup = {row.key: row for row in rows}
    counts = {method: partition_counts(part, rows) for method, part in partitions.items()}
    # Require exact agreement with the built verified proxy and linkage units.
    proxy = cast(dict[str, object], linked.summary["regulator_definition_proxy"])
    if (
        counts["V"]["groups"] != proxy["groups"]
        or counts["V"]["source_rows_used"] != proxy["eligible_verified_rows"]
    ):
        raise ValueError("Verified-only comparator diverges from the frozen proxy")
    if counts["L"]["groups"] != linked.summary["candidate_discharge_events"]:
        raise ValueError("Linkage partition diverges from frozen candidate events")

    s_splits = [
        group for group in partitions["S"].groups if split_pairs(group, membership["L"]) > 0
    ]
    split_keys = {key for group in s_splits for key in group}
    l_pairs: list[tuple[str, ...]] = [group for group in partitions["L"].groups if len(group) == 2]
    l_s_excluded = [g for g in l_pairs if any(k not in membership["S"] for k in g)]
    l_s_separate = [
        g
        for g in l_pairs
        if all(k in membership["S"] for k in g) and membership["S"][g[0]] != membership["S"][g[1]]
    ]
    l_v_unseen = [g for g in l_pairs if any(k not in membership["V"] for k in g)]
    abstentions = [group for group in linked.groups if group["decision"] == "abstain"]
    forced_pairs: dict[tuple[str, str], str] = {}
    forced_groups: set[str] = set()
    merged_anchors: set[str] = set()
    for decision_group in abstentions:
        anchor = str(decision_group["group_id"])
        s_group = membership["S"].get(anchor)
        if s_group is not None and len(partitions["S"].groups[s_group]) > 1:
            merged_anchors.add(anchor)
        for pair in cast(list[dict[str, str]], decision_group["pair_decisions"]):
            other = pair["source_row"]
            if s_group is not None and s_group == membership["S"].get(other):
                first, second = sorted((anchor, other))
                forced_pairs[(first, second)] = pair["decision"]
                forced_groups.add(anchor)
    forced_rows = {key for pair in forced_pairs for key in pair}
    cross_stage_split_pairs = 0
    for group in s_splits:
        n = sum(lookup[key].get("reporterClass") == NOTIFICATION for key in group)
        v = sum(lookup[key].get("reporterClass") == VERIFIED for key in group)
        together = Counter(membership["L"][key] for key in group)
        # L has only cross-stage pairs, so every size-two subgroup subtracts one.
        cross_stage_split_pairs += n * v - sum(size == 2 for size in together.values())
    abstention_anchors = {str(g["group_id"]) for g in abstentions}
    unkeyed = sorted(set(partitions["V"].excluded) & set(partitions["S"].excluded))
    stranded = [
        key
        for key in unkeyed
        if key in abstention_anchors and len(partitions["L"].groups[membership["L"][key]]) == 1
    ]
    disagreements = {
        "S_groups_spanning_multiple_L_events": len(s_splits),
        "source_rows_in_those_S_groups": len(split_keys),
        "row_pairs_S_merges_L_keeps_apart": sum(split_pairs(g, membership["L"]) for g in s_splits),
        "cross_stage_row_pairs_S_merges_L_keeps_apart": cross_stage_split_pairs,
        "L_linked_pairs_with_a_row_V_omits": len(l_v_unseen),
        "distinct_rows_in_those_L_pairs": len({key for g in l_v_unseen for key in g}),
        "L_linked_pairs_S_omits_at_least_one_row": len(l_s_excluded),
        "L_linked_pairs_S_places_in_separate_groups": len(l_s_separate),
        "L_linked_pairs_S_also_groups": len(l_pairs) - len(l_s_excluded) - len(l_s_separate),
        "L_abstention_groups_with_candidate_pairs_S_forces": len(forced_groups),
        "candidate_row_pairs_S_forces_under_L_group_abstention": len(forced_pairs),
        "distinct_rows_in_those_forced_pairs": len(forced_rows),
        "forced_pairs_by_L_pair_level_decision": dict(
            sorted(Counter(forced_pairs.values()).items())
        ),
        "L_abstention_anchors_in_multirow_S_groups": len(merged_anchors),
        "within_V_pairs_L_keeps_apart": sum(
            split_pairs(g, membership["L"]) for g in partitions["V"].groups
        ),
    }
    examples = select_examples(partitions, membership, lookup, s_splits, l_s_excluded, forced_pairs)
    return {
        "comparison_version": VERSION,
        "snapshot_sha256": digest,
        "common_input": {
            "source_rows": len(rows),
            "cso_source_rows": sum("CSO" in r.get("eventType") for r in rows),
            "ordered_source_keys_sha256": hashlib.sha256(
                ("\n".join(r.key for r in rows) + "\n").encode()
            ).hexdigest(),
            "same_rows_offered_to": ["V", "S", "L"],
            "event_type_counts": dict(sorted(Counter(r.get("eventType") for r in rows).items())),
        },
        "definitions": DEFINITIONS,
        "simple_key_justification": S_JUSTIFICATION,
        "measurement_definition": (
            "Rows with volume/rainfall means a nonblank retained source cell, counted once "
            "per partition; finite nonnegative numeric counts are separate. Zero is present. "
            "No stage values are summed or selected as truth. Groups with both measurements "
            "may have volume and rainfall on different member rows."
        ),
        "methods": counts,
        "linkage_decisions": {
            key: linked.summary[key]
            for key in (
                "rule_version",
                "decision_groups",
                "links",
                "no_links",
                "abstentions",
                "ambiguous_component_rows",
                "unmerged_source_rows",
                "conflicting_candidate_events",
            )
        },
        "disagreements": disagreements,
        "unresolved": {
            "L_abstention_groups_by_reason": dict(
                sorted(Counter(str(g["reason"]) for g in abstentions).items())
            ),
            "rows_omitted_by_V_and_S_and_singleton_L_abstention": len(stranded),
            "source_row_ordinals_for_those_cases": [lookup[k].ordinal for k in stranded],
            "missing_reference_scope_source_rows": len(rows),
            "reference_limit": (
                "No method establishes physical identity for any source row. Key agreement "
                "is not resolution of ambiguous identity. Original incident logs and revision/"
                "retraction histories are absent; the 15-minute tolerance is unvalidated."
            ),
        },
        "examples": examples,
        "limitations": LIMIT,
        "disclosure": (
            "Local identifier-only comparison in docs/milestones, excluded by the existing "
            "public snapshot helper. No raw cells, measurements or personal data are exported."
        ),
    }


def select_examples(
    partitions: dict[str, Partition],
    membership: dict[str, dict[str, int]],
    lookup: dict[str, SourceRow],
    s_splits: list[tuple[str, ...]],
    l_s_excluded: list[tuple[str, ...]],
    forced_pairs: dict[tuple[str, str], str],
) -> list[dict[str, object]]:
    """Up to ten deterministic, diverse concrete groups; no sampled performance claim."""
    examples: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()

    def example_size(group: tuple[str, ...]) -> tuple[int, int, tuple[str, ...]]:
        context_rows = sum(
            len(part.groups[i])
            for method, part in partitions.items()
            for i in {membership[method][key] for key in group if key in membership[method]}
        )
        return len(group), context_rows, group

    # Prefer small complete contexts, retaining every intersecting group member.
    categories = [
        ("S merges rows L keeps apart", sorted(s_splits, key=example_size), 4),
        (
            "L abstains on a candidate pair S forces",
            sorted(
                {partitions["S"].groups[membership["S"][a]] for a, _ in forced_pairs},
                key=example_size,
            ),
            3,
        ),
        (
            "L links a notification V omits; S lacks a key",
            sorted(l_s_excluded, key=example_size),
            3,
        ),
    ]
    fallback: list[tuple[str, ...]] = [g for g in partitions["L"].groups if len(g) == 2]
    categories.append(("L links a notification V omits", sorted(fallback, key=example_size), 10))
    for label, candidates, quota in categories:
        added = 0
        for group in candidates:
            if group in seen:
                continue
            seen.add(group)
            decisions: dict[str, object] = {}
            for method, part in partitions.items():
                ids = sorted(
                    {membership[method][key] for key in group if key in membership[method]}
                )
                decisions[method] = {
                    "groups_intersecting_example": [
                        [lookup[key].ordinal for key in part.groups[i]] for i in ids
                    ],
                    "example_rows_left_out": [
                        lookup[k].ordinal for k in group if k in part.excluded
                    ],
                }
            examples.append(
                {
                    "example": len(examples) + 1,
                    "difference": label,
                    "source_row_ordinals": [lookup[key].ordinal for key in group],
                    "notification_row_ordinals": [
                        lookup[k].ordinal
                        for k in group
                        if lookup[k].get("reporterClass") == NOTIFICATION
                    ],
                    "verified_row_ordinals": [
                        lookup[k].ordinal
                        for k in group
                        if lookup[k].get("reporterClass") == VERIFIED
                    ],
                    "methods": decisions,
                }
            )
            added += 1
            if added == quota or len(examples) == 10:
                break
        if len(examples) == 10:
            break
    return examples


def compare_snapshot(path: Path) -> dict[str, object]:
    """Production path accepts only the frozen bytes, schema and row counts."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_DOWNLOAD_SHA256:
        raise ValueError("Comparison snapshot SHA-256 mismatch")
    rows = load_source_rows(path)
    required = {
        "incidentId",
        "incidentNumber",
        "parentIncidentId",
        "reporterClass",
        "reportingType",
        "eventType",
        "permiteeName",
        "permiteeId",
        "outfallId",
        "location",
        "latitude",
        "longitude",
        "incidentDate",
        "incidentTime",
        "amPm",
        "submittedDate",
        "volumnOfEvent",
        "rainfallData",
    }
    if (
        len(rows) != 18759
        or sum("CSO" in r.get("eventType") for r in rows) != 16720
        or not required <= rows[0].raw.keys()
    ):
        raise ValueError("Comparison snapshot headers or row counts mismatch")
    return compare_rows(rows, digest)


def example_table(result: dict[str, object]) -> str:
    lines = [
        (
            "| Example | Difference | Source row IDs | V groups; omitted | S groups; omitted | "
            "L groups; omitted |"
        ),
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for example in cast(list[dict[str, object]], result["examples"]):
        cells: list[str] = []
        decisions = cast(dict[str, dict[str, list[object]]], example["methods"])
        for method in ("V", "S", "L"):
            info = decisions[method]
            groups = (
                " / ".join(str(group) for group in info["groups_intersecting_example"]) or "none"
            )
            cells.append(f"{groups}; omit {info['example_rows_left_out']}")
        lines.append(
            (
                f"| {example['example']} | {example['difference']} | "
                f"{example['source_row_ordinals']} | "
            )
            + " | ".join(cells)
            + " |"
        )
    return "\n".join(lines)


def entry_sentences(result: dict[str, object]) -> list[str]:
    methods = cast(dict[str, dict[str, int]], result["methods"])
    decisions = cast(dict[str, int], result["linkage_decisions"])
    differences = cast(dict[str, int], result["disagreements"])
    n = cast(dict[str, int], result["common_input"])["source_rows"]
    return [
        (
            f"On the same pinned {n:,} report rows, verified-only grouping formed "
            f"{methods['V']['groups']:,} groups from {methods['V']['source_rows_used']:,} "
            f"rows, simple permittee/outfall/date grouping formed {methods['S']['groups']:,} "
            f"groups from {methods['S']['source_rows_used']:,} rows, and SpillLedger formed "
            f"{methods['L']['groups']:,} candidate events while retaining all {n:,} rows."
        ),
        (
            f"SpillLedger linked {decisions['links']:,} unique notification/verified pairs "
            f"that verified-only grouping cannot represent, and abstained in "
            f"{differences['L_abstention_groups_with_candidate_pairs_S_forces']:,} decision "
            f"groups containing "
            f"{differences['candidate_row_pairs_S_forces_under_L_group_abstention']:,} "
            f"candidate row pairs the simple key would group together."
        ),
        (
            "These are grouping and evidence-retention differences, not measured accuracy or "
            "superiority; the existing automated review passes provide no independent incident "
            "reference."
        ),
    ]


def render_report(result: dict[str, object]) -> str:
    methods = cast(dict[str, dict[str, object]], result["methods"])
    common = cast(dict[str, int], result["common_input"])
    lines = [
        "# Local same-record discharge grouping comparison",
        "",
        "Local only; no publication or remote action.",
        "",
        (
            f"Snapshot SHA-256: `{result['snapshot_sha256']}`. Comparison `{VERSION}`; linkage "
            f"`{RULE_VERSION}`."
        ),
        "",
        (
            f"All three methods receive the identical complete {common['source_rows']:,}-row "
            f"snapshot, including {common['cso_source_rows']:,} CSO rows and the other source "
            "labels. V and S then apply their disclosed "
            "eligibility rules. This retrospective descriptive comparison is not a held-out "
            "performance evaluation."
        ),
        "",
        LIMIT,
        "",
        "## Fixed definitions",
        "",
    ]
    lines.extend(f"- **{method}:** {definition}" for method, definition in DEFINITIONS.items())
    lines.extend(
        [
            "",
            S_JUSTIFICATION,
            "",
            "## Counts and retained evidence",
            "",
            (
                "| Method | Groups or candidate events | Rows used | Rows left out | Rows with "
                "volume retained | Rows with rainfall retained | Rows with both retained |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for method, stats in methods.items():
        values = [
            stats[key]
            for key in (
                "groups",
                "source_rows_used",
                "source_rows_left_out",
                "rows_with_volume_retained",
                "rows_with_rainfall_retained",
                "rows_with_both_measurements_retained",
            )
        ]
        lines.append(f"| {method} | " + " | ".join(f"{value:,}" for value in values) + " |")
    lines.extend(["", str(result["measurement_definition"]), ""])
    for method, stats in methods.items():
        lines.append(
            f"{method}: excluded {stats['exclusion_reasons']}; used report classes "
            f"{stats['used_by_report_class']}. Finite nonnegative volume/rainfall rows "
            f"retained: "
            f"{stats['rows_with_valid_numeric_volume_retained']:,}/"
            f"{stats['rows_with_valid_numeric_rainfall_retained']:,}. "
            f"Volume/rainfall rows left out: "
            f"{stats['rows_with_volume_left_out']:,}/{stats['rows_with_rainfall_left_out']:,}. "
            f"Groups with volume/rainfall/both: "
            f"{stats['groups_with_volume']:,}/{stats['groups_with_rainfall']:,}/{stats['groups_with_both_measurements']:,}."
        )
        lines.append("")
    decisions = cast(dict[str, object], result["linkage_decisions"])
    lines.extend(
        [
            (
                f"L's {decisions['links']:,} linked pairs plus "
                f"{decisions['unmerged_source_rows']:,} singleton rows form "
                f"{methods['L']['groups']:,} disjoint candidate events. Its "
                f"{decisions['decision_groups']:,} decision groups overlap and are a different "
                f"unit: {decisions['links']:,} links + {decisions['no_links']:,} no-links + "
                f"{decisions['abstentions']:,} abstentions. Ambiguous-component rows: "
                f"{decisions['ambiguous_component_rows']:,}; candidate events with conflicting "
                f"fields: {decisions['conflicting_candidate_events']:,}. A singleton or "
                f"no-link is not proof that a separate physical incident occurred."
            ),
            "",
            "## Decision differences",
            "",
            "| Metric | Count |",
            "| --- | ---: |",
        ]
    )
    differences = cast(dict[str, object], result["disagreements"])
    for key, value in differences.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            (
                "Row-pair counts are unordered source-row pairs, not incidents. S-to-L counts "
                "include same-stage pairs; the cross-stage subset is reported separately. A "
                "forced pair means S places both rows in one group while the containing L "
                "decision group abstains; the pair-level decision breakdown distinguishes "
                "missing evidence, locally compatible pairs blocked by competition, and "
                "contradictions inside an abstaining group. Anchor counts also include "
                "singleton decision groups. V cannot represent cross-stage pairs because it "
                "ignores notification rows. V's coarser key also groups distinct verified "
                "reports together; that is a definition difference, not a finding of error."
            ),
            "",
            "## Ten concrete disagreement groups",
            "",
            (
                "IDs below are one-based CSV record ordinals under the pinned hash, not line "
                "numbers or physical incident IDs. Every cell shows the complete intersecting "
                "method groups; omitted rows are explicit. Examples are deterministic small "
                "witnesses, selected for variety rather than statistical representativeness. "
                "No raw measurements or personal data are shown."
            ),
            "",
            example_table(result),
            "",
            "## Cases no method can resolve",
            "",
        ]
    )
    unresolved = cast(dict[str, object], result["unresolved"])
    lines.extend(
        [
            str(unresolved["reference_limit"]),
            "",
            (
                f"{unresolved['rows_omitted_by_V_and_S_and_singleton_L_abstention']:,} rows "
                f"lack both V and S eligibility and remain singleton L abstentions. Their "
                f"ordinals are in the JSON. L abstention reasons (overlapping decision-group "
                f"unit):"
            ),
            "",
            "| Reason | Decision groups |",
            "| --- | ---: |",
        ]
    )
    for reason, n in cast(dict[str, int], unresolved["L_abstention_groups_by_reason"]).items():
        lines.append(f"| {reason} | {n:,} |")
    lines.extend(
        [
            "",
            (
                "V/S assigning a key does not resolve L's ambiguity, conflicts or missing "
                "clocks. Resolving physical identity, revisions and retractions requires a "
                "permitted independent incident reference. The supplied snapshot has blank "
                "parent IDs and no usable revision/retraction history. No "
                "tolerance-sensitivity result is claimed."
            ),
            "",
            "## Reproduction",
            "",
            (
                "Use the existing environment by absolute path, from this worktree, without "
                "downloading:"
            ),
            "",
            "```sh",
            ("PYTHONPATH=src python3 -m cso_insight.release_cli --compare \\"),
            ("  --input /path/to/rights-held.csv"),
            "```",
            "",
            (
                "The command verifies the pinned hash, schema and row counts, loads the source "
                "once, and recomputes unchanged linkage/2 directly. JSON and Markdown contain "
                "no timestamp or environment-dependent fields. Source cells and the original "
                "checking sheets are untouched. Detailed outputs stay under docs/milestones, "
                "excluded by the existing public snapshot helper. The script does not run the "
                "CSO baseline pipeline."
            ),
            "",
            "## Three entry sentences",
            "",
        ]
    )
    lines.extend(f"{i}. {sentence}" for i, sentence in enumerate(entry_sentences(result), 1))
    return "\n".join(lines) + "\n"


def write_comparison(result: dict[str, object], report: Path, machine: Path) -> None:
    for path in (report, machine):
        path.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report.write_text(render_report(result), encoding="utf-8")
