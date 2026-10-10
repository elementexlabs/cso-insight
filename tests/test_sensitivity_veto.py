"""Targeted synthetic tolerance and two-veto checks, with no acquisition."""

import json

import pytest

from cso_insight.fair_comparison import fair_partition, pair_set
from cso_insight.linkage import build_linkage, pair_rule
from cso_insight.sensitivity_veto import (
    analyze_rows,
    analyze_snapshot,
    compare_veto,
    group_changes,
    render_analysis,
    write_analysis,
)
from test_fair_comparison import row


@pytest.mark.parametrize("tolerance", [5, 15, 30])
@pytest.mark.parametrize("offset,expected", [(0, "link"), (1, "no link")])
def test_tolerance_inclusive_boundary_and_propagation(tolerance, offset, expected):
    rows = [row(1), row(2, verified=True, incidentTime=f"08:{tolerance:02d}:{offset:02d}")]
    assert pair_rule(*rows, tolerance_minutes=tolerance)[0] == expected
    run = build_linkage(rows, "synthetic", tolerance_minutes=tolerance)
    assert run.summary["links"] == int(expected == "link")
    assert run.groups[0]["pair_decisions"][0]["decision"] == expected
    assert str(tolerance) in run.groups[0]["pair_decisions"][0]["reason"]


@pytest.mark.parametrize("bad", [0, -1, True, 5.5, "15", None])
def test_invalid_tolerance_rejected_even_on_empty_input(bad):
    with pytest.raises(ValueError, match="positive integer"):
        build_linkage([], "synthetic", tolerance_minutes=bad)
    with pytest.raises(ValueError, match="positive integer"):
        pair_rule(row(1), row(2, verified=True), tolerance_minutes=bad)


def test_default_is_exactly_explicit_15_and_parent_path_uses_parameter():
    rows = [row(1), row(2, verified=True, incidentTime="08:16")]
    assert build_linkage(rows, "synthetic") == build_linkage(
        rows, "synthetic", tolerance_minutes=15
    )
    # Different days force explicit parent expansion outside the ordinary candidate block.
    rows = [row(1), row(2, verified=True, parentIncidentId="id-1", incidentDate="2025-01-02")]
    assert build_linkage(rows, "synthetic", tolerance_minutes=5).groups[0]["pair_decisions"]


@pytest.mark.parametrize(
    "changes,expected_reason",
    [
        ({"eventType": "SSO"}, "contradictory eventType"),
        ({"incidentTime": "08:15:01"}, "start times outside 15-minute window"),
        ({"eventType": "SSO", "incidentTime": "08:16"}, "contradictory eventType"),
    ],
)
def test_each_veto_and_precedence(changes, expected_reason):
    rows = [row(1), row(2, verified=True, **changes)]
    assert len(pair_set(fair_partition(rows)[0])) == 1
    v2, candidates = fair_partition(rows, simple_vetoes=True)
    assert pair_set(v2) == set()
    assert candidates[0].decision == "no-link"
    assert candidates[0].reason == expected_reason


@pytest.mark.parametrize(
    "changes",
    [
        {"incidentTime": "08:15"},
        {"incidentTime": ""},
        {"eventType": "unknown"},
        {"eventType": ""},
        {"eventType": " cSo "},
        {"latitude": "999"},
        {"latitude": "45"},
        {"permiteeId": "different"},
        {"submittedDate": "2020-01-01"},
        {"reportingType": "unknown"},
        {"reportingType": "Retracted", "volumnOfEvent": "-2"},
    ],
)
def test_v2_has_no_extra_vetoes(changes):
    rows = [row(1), row(2, verified=True, **changes)]
    v2, decisions = fair_partition(rows, simple_vetoes=True)
    assert len(pair_set(v2)) == 1
    assert decisions[0].decision == "link"


def test_veto_does_not_consume_rows_and_later_edges_can_link():
    rows = [
        row(1),
        row(2, eventType="SSO", incidentTime="08:02"),
        row(3, verified=True, eventType="SSO", incidentTime="08:01"),
        row(4, verified=True, incidentTime="08:10"),
    ]
    v2, decisions = fair_partition(rows, simple_vetoes=True)
    assert pair_set(v2) == {(rows[0].key, rows[3].key), (rows[1].key, rows[2].key)}
    assert decisions[0].reason == "contradictory eventType"
    comparison = compare_veto(rows, build_linkage(rows, "synthetic"))
    assert comparison["agreement"]["both_link"] == 2
    assert comparison["agreement"]["L_only_links"] == 0


def test_wider_window_can_lose_link_to_competition_and_records_directions():
    rows = [row(1), row(2, verified=True), row(3, verified=True, incidentTime="08:20")]
    result = analyze_rows(rows, "synthetic")
    assert [r["decision_groups"]["links"] for r in result["sensitivity"]] == [1, 1, 0]
    changes = result["sensitivity"][2]["changes_against_15_minutes"]
    assert changes["group_decision_transitions"]["link -> abstain"] == 1
    assert len(changes["lost_linked_pairs"]) == 1
    assert changes["rows_with_changed_partner_or_paired_state"] == 2
    assert changes["changed_group_decisions"] == sum(changes["group_decision_transitions"].values())


def test_narrower_window_no_link_and_group_abstention_changes():
    rows = [row(1), row(2, verified=True, incidentTime="08:10")]
    result = analyze_rows(rows, "synthetic")
    assert (
        result["sensitivity"][0]["changes_against_15_minutes"]["group_decision_transitions"][
            "link -> no link"
        ]
        == 1
    )
    rows.append(row(3, verified=True, incidentTime="08:04"))
    result = analyze_rows(rows, "synthetic")
    assert (
        result["sensitivity"][0]["changes_against_15_minutes"]["group_decision_transitions"][
            "abstain -> link"
        ]
        == 1
    )


def test_absent_group_is_coverage_change_and_partner_changes_are_separate():
    rows = [row(1), row(2, verified=True)]
    old = build_linkage(rows, "synthetic")
    new = build_linkage(rows, "synthetic")
    new.groups.append({"group_id": rows[1].key, "decision": "no link", "reason": "fixture"})
    assert group_changes(old, new)["group_decision_transitions"]["absent -> no link"] == 1
    rows.append(row(3, verified=True, incidentTime="08:20"))
    old = build_linkage(rows, "synthetic")
    new = build_linkage(rows, "synthetic")
    new.groups[0]["tool_matched_verified_row"] = rows[2].key
    changes = group_changes(old, new)
    assert len(changes["same_decision_link_partner_changes"]) == 1
    assert changes["changed_group_decisions"] == 0


@pytest.mark.parametrize(
    "rows,reason,pair_decision",
    [
        ([row(1, incidentTime=""), row(2, verified=True)], "date or clock unresolved", "abstain"),
        (
            [row(1), row(2, verified=True, submittedDate="")],
            "later verified submission not established",
            "abstain",
        ),
        (
            [row(1), row(2), row(3, verified=True)],
            "multiple plausible cross-stage matches; no forced merge",
            "link",
        ),
        ([row(1), row(2, verified=True, latitude="45")], "contradictory coordinates", "no link"),
    ],
)
def test_remaining_l_reasons_and_literal_decisions(rows, reason, pair_decision):
    result = analyze_rows(rows, "synthetic")["V2_versus_L"]
    extra = result["all_V2_only_links_with_L_decisions"][0]
    assert extra["reason_class"] == reason
    assert extra["L_pair_decision"] == pair_decision
    assert sum(result["V2_only_by_L_category"].values()) == result["agreement"]["V2_only_links"]


def test_l_only_location_fallback_and_zero_link_denominators():
    rows = [row(1, outfallId=""), row(2, verified=True, outfallId="")]
    result = analyze_rows(rows, "synthetic")
    assert result["V2_versus_L"]["agreement"]["L_only_links"] == 1
    assert (
        result["V2_versus_L"]["all_L_only_links_with_V2_reasons"][0]["V2_reason"]
        == "F grouping key unavailable/different"
    )
    empty = analyze_rows([], "synthetic")
    assert empty["V2_versus_L"]["agreement"]["share_of_L_links"] is None
    assert "undefined (no links)" in render_analysis(empty)


def test_determinism_conservation_and_raw_cell_retention(tmp_path):
    rows = [
        row(1),
        row(2, verified=True, incidentTime="08:10", volumnOfEvent=" 0 "),
        row(3, eventType="SSO"),
        row(4, verified=True),
        row(5, incidentTime=""),
        row(6, outfallId=""),
        row(7, reporterClass="Other"),
    ]
    original = json.dumps([r.raw for r in rows])
    first = analyze_rows(rows, "synthetic")
    second = analyze_rows(list(reversed(rows)), "synthetic")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert render_analysis(first) == render_analysis(second)
    assert json.dumps([r.raw for r in rows]) == original
    for run in first["sensitivity"]:
        counts = run["partition"]
        assert counts["source_rows_used"] == 7 and counts["source_rows_left_out"] == 0
        assert counts["rows_with_volume_retained"] == 7
        assert counts["groups"] + counts["multirow_groups"] == 7
        assert (
            sum(run["decision_groups"][k] for k in ("links", "abstentions", "no_links"))
            == run["decision_groups"]["decision_groups"]
        )
    v2 = first["V2_versus_L"]
    assert sorted(n for g in v2["V2_groups_source_row_ordinals"] for n in g) == list(range(1, 8))
    assert all(m["source_rows_used"] == 7 for m in v2["methods"].values())
    write_analysis(first, tmp_path)
    assert json.loads((tmp_path / "cso_sensitivity_and_veto.json").read_text()) == first
    assert (tmp_path / "CSO_SENSITIVITY_AND_VETO.md").read_text() == render_analysis(first)


def test_bad_snapshot_and_duplicate_rows_rejected(tmp_path):
    with pytest.raises(ValueError, match="identity mismatch"):
        analyze_rows([row(1)], "wrong")
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_rows([row(1), row(1)], "synthetic")
    source = tmp_path / "wrong.csv"
    source.write_text("incidentId\n1\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        analyze_snapshot(source)
