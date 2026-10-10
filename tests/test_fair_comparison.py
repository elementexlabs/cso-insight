"""Hand-made F definitions and the recorded L comparison, with no network."""

import json
from dataclasses import replace
from datetime import datetime

import pytest

from cso_insight.fair_comparison import (
    compare_fair_rows,
    compare_fair_snapshot,
    fair_partition,
    pair_set,
    render_fair_comparison,
)
from cso_insight.ingest import parse_incident_clock, parse_incident_date
from cso_insight.linkage import NOTIFICATION, VERIFIED, SourceRow


def row(ordinal, *, verified=False, **changes):
    raw = {
        "incidentId": f"id-{ordinal}",
        "incidentNumber": f"number-{ordinal}",
        "parentIncidentId": "",
        "permiteeName": "City A",
        "permiteeId": "MA1",
        "outfallId": "O1",
        "eventType": "CSO",
        "location": "Street A",
        "reporterClass": VERIFIED if verified else NOTIFICATION,
        "reportingType": "" if verified else "Initial-Ceased",
        "incidentDate": "2025-01-01",
        "incidentTime": "08:00",
        "amPm": "",
        "latitude": "42.3",
        "longitude": "-71.1",
        "submittedDate": "2025-01-03" if verified else "2025-01-01",
        "volumnOfEvent": "0",
        "rainfallData": " 1.00 ",
        "hours": "1",
        "minutes": "0",
    }
    raw.update(changes)
    day = parse_incident_date(raw["incidentDate"]) if raw["incidentDate"] else None
    clock, status = parse_incident_clock(raw["incidentTime"], raw["amPm"])
    start = datetime.combine(day, clock) if day is not None and clock is not None else None
    return SourceRow(ordinal, raw, day, start, status)


def ordinals(part, rows):
    lookup = {r.key: r.ordinal for r in rows}
    return {tuple(sorted(lookup[k] for k in group)) for group in part.groups}


def test_global_nearest_edge_not_notification_iteration_order():
    rows = [row(1), row(2, incidentTime="08:04"), row(3, verified=True, incidentTime="08:03")]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(1,), (2, 3)}
    assert [d.decision for d in decisions] == ["link", "no-link"]
    assert [d.clock_distance_seconds for d in decisions] == [60, 180]


def test_one_to_one_greedy_selection_and_no_distance_cutoff():
    rows = [
        row(1),
        row(2, incidentTime="08:04"),
        row(3, verified=True, incidentTime="08:03"),
        row(4, verified=True, incidentTime="22:00"),
    ]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(2, 3), (1, 4)}
    assert len(decisions) == 4
    assert len({k for group in part.groups for k in group}) == 4
    assert sum(d.decision == "link" for d in decisions) == 2
    assert all(d.decision in {"link", "no-link"} for d in decisions)


def test_ties_use_notification_then_verified_record_ordinal():
    rows = [row(8), row(2), row(9, verified=True), row(4, verified=True)]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(2, 4), (8, 9)}
    assert decisions[0].notification == rows[1].key
    assert decisions[0].verified == rows[3].key


def test_missing_clocks_sort_last_and_still_receive_a_decision():
    rows = [
        row(1, incidentTime=""),
        row(2),
        row(3, verified=True),
        row(4, verified=True, incidentTime=""),
    ]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(2, 3), (1, 4)}
    assert decisions[0].clock_distance_seconds == 0
    assert all(d.clock_distance_seconds is None for d in decisions[1:])


@pytest.mark.parametrize("verified", [True, False])
def test_same_stage_never_merged(verified):
    rows = [row(1, verified=verified), row(2, verified=verified)]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(1,), (2,)}
    assert decisions == []


@pytest.mark.parametrize(
    "changes",
    [
        {"outfallId": "O2"},
        {"outfallId": "Unknown"},
        {"incidentDate": "2025-01-02"},
        {"incidentDate": ""},
        {"permiteeName": "City B"},
        {"permiteeName": "Unknown", "permiteeId": ""},
        {"reporterClass": "Other Stage"},
    ],
)
def test_incomplete_different_keys_or_other_stage_stay_singleton(changes):
    rows = [row(1), row(2, verified=True, **changes)]
    part, decisions = fair_partition(rows)
    assert ordinals(part, rows) == {(1,), (2,)}
    assert part.excluded == {} and decisions == []


def test_name_normalisation_and_id_fallback():
    rows = [
        row(1, permiteeName=" CITY  A "),
        row(2, verified=True, outfallId=" o1 "),
        row(3, permiteeName="Unknown"),
        row(4, verified=True, permiteeName="", permiteeId=" ma1 "),
    ]
    part, _ = fair_partition(rows)
    assert ordinals(part, rows) == {(1, 2), (3, 4)}


@pytest.mark.parametrize(
    "change,category,reason",
    [
        ({"eventType": "SSO"}, "contradiction", "contradictory eventType"),
        ({"permiteeId": "MA2"}, "contradiction", "contradictory permiteeId"),
        ({"incidentTime": "22:00"}, "contradiction", "start times outside 15-minute window"),
        ({"latitude": "45"}, "contradiction", "contradictory coordinates"),
        ({"latitude": "999"}, "abstain", "invalid coordinates; human review required"),
        ({"incidentTime": ""}, "abstain", "date or clock unresolved"),
        ({"submittedDate": ""}, "abstain", "later verified submission not established"),
        ({"reportingType": "unrecognised"}, "abstain", "unknown reporting-stage taxonomy"),
    ],
)
def test_f_does_not_veto_other_evidence_and_reports_recorded_l_reasons(change, category, reason):
    rows = [row(1), row(2, verified=True, **change)]
    result = compare_fair_rows(rows, "synthetic")
    assert result["agreement"]["F_only_links"] == 1
    assert result["F_only_by_L_category"][category] == 1
    assert result["F_only_by_L_reason_class"][category] == {reason: 1}
    example = result["examples"][f"F_only_L_{category}"][0]
    assert example["L_pair_decision"] == ("no link" if category == "contradiction" else "abstain")


def test_competing_match_records_locally_compatible_pair_and_group_abstention():
    rows = [row(1), row(2), row(3, verified=True)]
    result = compare_fair_rows(rows, "synthetic")
    example = result["examples"]["F_only_L_abstain"][0]
    assert example["source_row_ordinals"] == [1, 3]
    assert example["L_pair_decision"] == "link"
    assert example["L_group_decision"] == "abstain"
    assert result["agreement"]["additional_singletons_under_L_net"] == 2


def test_pair_contradiction_preserved_inside_abstaining_group():
    rows = [
        row(1),
        row(2, verified=True, eventType="SSO"),
        row(3, verified=True, incidentTime="08:01"),
        row(4, verified=True, incidentTime="08:02"),
    ]
    result = compare_fair_rows(rows, "synthetic")
    example = result["examples"]["F_only_L_contradiction"][0]
    assert example["L_group_decision"] == "abstain"
    assert example["L_pair_reason"] == "contradictory eventType"


def test_l_location_fallback_explains_l_only_link():
    rows = [row(1, outfallId=""), row(2, verified=True, outfallId="")]
    result = compare_fair_rows(rows, "synthetic")
    assert result["agreement"]["L_only_links"] == 1
    assert "location and coordinates" in result["examples"]["L_only"][0]["F_reason"]


def test_closer_contradiction_can_displace_l_links_and_preserves_explanation():
    rows = [
        row(1),
        row(2, eventType="SSO", incidentTime="08:02"),
        row(3, verified=True, eventType="SSO", incidentTime="08:01"),
        row(4, verified=True, incidentTime="08:10"),
    ]
    result = compare_fair_rows(rows, "synthetic")
    assert result["agreement"]["L_only_links"] == 2
    assert result["agreement"]["F_only_links"] == 2
    for example in result["examples"]["L_only"]:
        assert example["F_reason"] == "row already paired"
        assert len(example["F_occupying_pairs"]) == 2
        assert all(
            e["L_pair_reason"] == "contradictory eventType" for e in example["F_occupying_pairs"]
        )


def test_conservation_raw_cells_and_input_order_determinism():
    rows = [
        row(1),
        row(2, verified=True, volumnOfEvent="-2"),
        row(3, incidentTime=""),
        row(4, verified=True),
        row(5, outfallId=""),
        row(6, reporterClass="Other"),
        row(7, reportingType="Retracted"),
    ]
    raw = json.dumps([r.raw for r in rows])
    first = compare_fair_rows(rows, "synthetic")
    second = compare_fair_rows(list(reversed(rows)), "synthetic")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert render_fair_comparison(first) == render_fair_comparison(second)
    assert json.dumps([r.raw for r in rows]) == raw
    flat = [n for group in first["F_groups_source_row_ordinals"] for n in group]
    assert sorted(flat) == list(range(1, 8))
    assert first["methods"]["F"]["source_rows_used"] == 7
    assert first["methods"]["F"]["rows_with_volume_retained"] == 7
    assert first["methods"]["F"]["rows_with_rainfall_retained"] == 7
    assert first["methods"]["F"]["source_rows_left_out"] == 0
    assert pair_set(fair_partition(rows)[0])


def test_shared_link_and_both_singleton_agreement():
    result = compare_fair_rows([row(1), row(2, verified=True), row(3, outfallId="O2")], "synthetic")
    assert result["agreement"]["both_link"] == 1
    assert result["agreement"]["share_of_L_links"] == 1
    assert result["agreement"]["same_partner_or_both_singleton_rows"] == 3
    assert result["examples"]["L_only"] == []


def test_duplicate_keys_ordinals_and_wrong_snapshot_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        fair_partition([row(1), row(1, verified=True)])
    with pytest.raises(ValueError, match="Duplicate"):
        fair_partition([row(1), replace(row(1), snapshot_hash="different")])
    with pytest.raises(ValueError, match="identity mismatch"):
        compare_fair_rows([row(1)], "wrong")


def test_production_rejects_unpinned_source(tmp_path):
    source = tmp_path / "not_pinned.csv"
    source.write_text("incidentId\n1\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        compare_fair_snapshot(source)
