"""Hand-made definitions, shared inputs, conservation and deterministic outputs."""

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from itertools import combinations

import pytest

from cso_insight import comparison
from cso_insight.comparison import (
    Partition,
    compare_rows,
    compare_snapshot,
    group_key,
    key_partition,
    linkage_partition,
    partition_counts,
    write_comparison,
)
from cso_insight.ingest import parse_incident_clock, parse_incident_date
from cso_insight.linkage import NOTIFICATION, VERIFIED, SourceRow, build_linkage


def row(ordinal, *, verified=False, **changes):
    raw = {
        "incidentId": f"id-{ordinal}",
        "incidentNumber": f"number-{ordinal}",
        "parentIncidentId": "",
        "permiteeName": "City A",
        "permiteeId": "MA1",
        "outfallId": "O1",
        "eventType": "CSO",
        "reporterClass": VERIFIED if verified else NOTIFICATION,
        "reportingType": "" if verified else "Initial-Ceased",
        "incidentDate": "2025-01-01",
        "incidentTime": "08:00",
        "amPm": "",
        "latitude": "42.3",
        "longitude": "-71.1",
        "location": "Street A",
        "submittedDate": "2025-01-03" if verified else "2025-01-01",
        "volumnOfEvent": "100",
        "rainfallData": "1",
    }
    raw.update(changes)
    day = None if not raw["incidentDate"] else parse_incident_date(raw["incidentDate"])
    clock, status = parse_incident_clock(raw["incidentTime"], raw["amPm"])
    start = datetime.combine(day, clock) if day is not None and clock is not None else None
    return SourceRow(ordinal, raw, day, start, status)


def test_verified_only_exact_existing_proxy():
    rows = [
        row(1),
        row(2, verified=True),
        row(3, verified=True, permiteeName=" CITY   a ", eventType=" cso ", outfallId="O2"),
        row(4, verified=True, eventType="SSO"),
        row(5, verified=True, incidentDate="2025-01-02"),
        row(6, verified=True, reportingType="Retracted"),
        row(7, verified=True, permiteeName="Unknown", permiteeId=""),
        row(8, verified=True, eventType=""),
        row(9, verified=True, incidentDate=""),
        row(10, verified=True, volumnOfEvent="0"),
    ]
    part = key_partition(rows, "V")
    assert part.groups == (
        (rows[1].key, rows[2].key, rows[9].key),
        (rows[3].key,),
        (rows[4].key,),
    )
    assert part.excluded == {
        rows[0].key: "not a verified report",
        rows[5].key: "explicit retraction",
        **{r.key: "missing required grouping key" for r in rows[6:9]},
    }
    assert group_key(row(1, permiteeName="Unknown", permiteeId=" MA1 "), "V") == (
        "ma1",
        "cso",
        date(2025, 1, 1),
    )
    stats = compare_rows(rows, "synthetic")["methods"]["V"]
    assert stats["groups"] == 3 and stats["source_rows_used"] == 5


def test_simple_key_ignores_all_non_key_evidence():
    rows = [
        row(1),
        row(2, verified=True, eventType="SSO", incidentTime="22:00", submittedDate=""),
        row(3, reporterClass="Unknown", reportingType="Retracted", latitude="999"),
        row(4, permiteeName="City B"),
        row(5, outfallId="O2"),
        row(6, incidentDate="2025-01-02"),
        row(7, outfallId="Other"),
        row(8, permiteeName="", permiteeId=""),
        row(9, incidentDate=""),
        row(10, permiteeName=" city  A ", outfallId=" o1 "),
    ]
    part = key_partition(rows, "S")
    assert part.groups[0] == (rows[0].key, rows[1].key, rows[2].key, rows[9].key)
    assert len(part.groups) == 4 and len(part.excluded) == 3
    assert all(part.excluded[r.key] == "missing required grouping key" for r in rows[6:9])
    with pytest.raises(ValueError, match="V or S"):
        key_partition(rows, "L")


@pytest.mark.parametrize(
    "change,decision",
    [
        ({}, "link"),
        ({"incidentTime": "08:15"}, "link"),
        ({"incidentTime": "08:16"}, "no link"),
        ({"incidentTime": ""}, "abstain"),
        ({"submittedDate": "2024-01-01"}, "abstain"),
        ({"latitude": "999"}, "abstain"),
        ({"eventType": "SSO"}, "no link"),
    ],
)
def test_linkage_reuses_frozen_pair_rules(change, decision):
    rows = [row(1), row(2, verified=True, **change)]
    result = compare_rows(rows, "synthetic")
    stats = result["methods"]
    assert stats["S"]["groups"] == 1
    assert stats["V"]["source_rows_used"] == 1
    assert stats["L"]["groups"] == (1 if decision == "link" else 2)
    linked = build_linkage(rows, "synthetic")
    assert linked.groups[0]["decision"] == decision
    assert result["linkage_decisions"]["links"] == (decision == "link")
    assert result["disagreements"]["row_pairs_S_merges_L_keeps_apart"] == (decision != "link")
    assert result["disagreements"]["candidate_row_pairs_S_forces_under_L_group_abstention"] == (
        decision == "abstain"
    )


def test_linkage_abstains_on_competing_component_without_transitive_merge():
    rows = [row(1), row(2), row(3, verified=True)]
    result = compare_rows(rows, "synthetic")
    assert result["methods"]["L"]["groups"] == 3
    assert result["linkage_decisions"]["abstentions"] == 2
    assert result["disagreements"]["row_pairs_S_merges_L_keeps_apart"] == 3
    assert result["disagreements"]["cross_stage_row_pairs_S_merges_L_keeps_apart"] == 2
    assert result["disagreements"]["candidate_row_pairs_S_forces_under_L_group_abstention"] == 2
    assert result["disagreements"]["forced_pairs_by_L_pair_level_decision"] == {"link": 2}
    assert result["disagreements"]["distinct_rows_in_those_forced_pairs"] == 3


def test_location_fallback_can_link_rows_simple_key_omits():
    rows = [row(1, outfallId=""), row(2, verified=True, outfallId="")]
    result = compare_rows(rows, "synthetic")
    assert result["methods"]["S"]["source_rows_used"] == 0
    assert result["methods"]["L"]["groups"] == 1
    assert result["disagreements"]["L_linked_pairs_S_omits_at_least_one_row"] == 1
    assert result["examples"][0]["methods"]["S"]["example_rows_left_out"] == [1, 2]


def test_missing_evidence_is_not_resolved_by_assigning_a_key():
    rows = [row(1, outfallId="", location=""), row(2, verified=True, incidentTime="")]
    result = compare_rows(rows, "synthetic")
    assert result["unresolved"]["rows_omitted_by_V_and_S_and_singleton_L_abstention"] == 1
    assert result["unresolved"]["source_row_ordinals_for_those_cases"] == [1]
    assert result["unresolved"]["missing_reference_scope_source_rows"] == 2
    assert "none of this measures accuracy" in result["limitations"]


def test_identical_row_objects_offered_to_all_methods(monkeypatch):
    original_key, original_linkage = comparison.key_partition, comparison.build_linkage
    received = []

    def key_capture(rows, method):
        received.append((method, rows))
        return original_key(rows, method)

    def linkage_capture(rows, digest):
        received.append(("L", rows))
        return original_linkage(rows, digest)

    monkeypatch.setattr(comparison, "key_partition", key_capture)
    monkeypatch.setattr(comparison, "build_linkage", linkage_capture)
    source = [row(2, verified=True), row(1)]
    before = json.dumps([r.raw for r in source], sort_keys=True)
    result = compare_rows(source, "synthetic")
    assert {method for method, _ in received} == {"V", "S", "L"}
    assert all(items is received[0][1] for _, items in received)
    assert all(
        item is original for item, original in zip(received[0][1], source[::-1], strict=True)
    )
    assert before == json.dumps([r.raw for r in source], sort_keys=True)
    assert result["common_input"]["source_rows"] == 2
    signature = hashlib.sha256(("\n".join(r.key for r in source[::-1]) + "\n").encode()).hexdigest()
    assert result["common_input"]["ordered_source_keys_sha256"] == signature


def test_counts_reconcile_measurements_without_summing_or_dropping_flags():
    rows = [
        row(1, volumnOfEvent="", rainfallData=""),
        row(2, verified=True, volumnOfEvent="0", rainfallData="0"),
        row(3, verified=True, incidentDate="2025-01-02", volumnOfEvent="nan", rainfallData="-1"),
        row(4, verified=True, outfallId="", volumnOfEvent="11000000", rainfallData="2"),
    ]
    result = compare_rows(rows, "synthetic")
    for stats in result["methods"].values():
        assert stats["source_rows_used"] + stats["source_rows_left_out"] == 4
        assert stats["rows_with_volume_retained"] + stats["rows_with_volume_left_out"] == 3
        assert stats["rows_with_rainfall_retained"] + stats["rows_with_rainfall_left_out"] == 3
    linked_stats = result["methods"]["L"]
    assert linked_stats["rows_with_valid_numeric_volume_retained"] == 2
    assert linked_stats["rows_with_valid_numeric_rainfall_retained"] == 2
    assert result["methods"]["S"]["rows_with_volume_retained"] == 2


@pytest.mark.parametrize("bad", ["duplicate", "gap", "overlap", "foreign", "empty"])
def test_partition_conservation_rejects_invalid_memberships(bad):
    rows = [row(1), row(2)]
    a, b = [r.key for r in rows]
    parts = {
        "duplicate": Partition("X", ((a,), (a,), (b,)), {}),
        "gap": Partition("X", ((a,),), {}),
        "overlap": Partition("X", ((a,), (b,)), {b: "excluded"}),
        "foreign": Partition("X", ((a,), (b,), ("foreign",)), {}),
        "empty": Partition("X", ((a,), (b,), ()), {}),
    }
    with pytest.raises(ValueError, match="reconcile"):
        partition_counts(parts[bad], rows)


def test_input_identity_rejects_duplicate_and_mixed_snapshot_keys():
    with pytest.raises(ValueError, match="Duplicate"):
        compare_rows([row(1), row(1)], "synthetic")
    with pytest.raises(ValueError, match="identity mismatch"):
        compare_rows([replace(row(1), snapshot_hash="other")], "synthetic")


def test_pair_counts_match_independent_exhaustive_enumeration():
    rows = [
        row(1),
        row(2),
        row(3, verified=True),
        row(4, incidentDate="2025-01-02"),
        row(5, verified=True, incidentDate="2025-01-02"),
        row(6, verified=True, incidentDate="2025-01-02", outfallId="O2"),
    ]
    result = compare_rows(rows, "synthetic")
    l_membership = linkage_partition(build_linkage(rows, "synthetic")).membership
    s = key_partition(rows, "S")
    pairs = {
        (a, b)
        for g in s.groups
        for a, b in combinations(g, 2)
        if l_membership[a] != l_membership[b]
    }
    lookup = {r.key: r for r in rows}
    cross = {
        pair
        for pair in pairs
        if {lookup[k].get("reporterClass") for k in pair} == {NOTIFICATION, VERIFIED}
    }
    assert result["disagreements"]["row_pairs_S_merges_L_keeps_apart"] == len(pairs)
    assert result["disagreements"]["cross_stage_row_pairs_S_merges_L_keeps_apart"] == len(cross)


def test_deterministic_output_and_ten_complete_identifier_only_examples(tmp_path):
    rows = []
    for i in range(12):
        day = f"2025-01-{i + 1:02}"
        rows.extend(
            [row(2 * i + 1, incidentDate=day), row(2 * i + 2, verified=True, incidentDate=day)]
        )
    result = compare_rows(rows, "synthetic")
    assert result == compare_rows(list(reversed(rows)), "synthetic")
    assert len(result["examples"]) == 10
    for example in result["examples"]:
        assert len(example["notification_row_ordinals"]) == 1
        assert len(example["verified_row_ordinals"]) == 1
        assert example["methods"]["L"]["groups_intersecting_example"] == [
            example["source_row_ordinals"]
        ]
    a, b = tmp_path / "report.md", tmp_path / "machine.json"
    write_comparison(result, a, b)
    before = (a.read_bytes(), b.read_bytes())
    write_comparison(compare_rows(rows, "synthetic"), a, b)
    assert before == (a.read_bytes(), b.read_bytes())
    assert json.loads(b.read_text()) == result
    assert "11000000" not in b.read_text()
    assert "City A" not in b.read_text()


def test_production_pin_rejects_changed_input_before_loading(tmp_path, monkeypatch):
    path = tmp_path / "changed.csv"
    path.write_text("wrong snapshot")

    def forbidden_load(_):
        raise AssertionError("Unpinned bytes must never be loaded")

    monkeypatch.setattr(comparison, "load_source_rows", forbidden_load)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        compare_snapshot(path)
    assert path.read_text() == "wrong snapshot"
