"""Synthetic checks for conservative linkage and declared reviewer modes."""

import csv
import hashlib
import json
from dataclasses import replace
from datetime import datetime

import pytest

from cso_insight.checking import (
    COLUMNS,
    HUMAN_COLUMNS,
    machine_digest,
    read_sheet,
    sample_groups,
    write_sample,
)
from cso_insight.checking import (
    score_sheet as score_original,
)
from cso_insight.cli import main
from cso_insight.linkage import (
    NOTIFICATION,
    VERIFIED,
    SourceRow,
    build_linkage,
    field_provenance,
    link_snapshot,
    load_source_rows,
    number,
    pair_rule,
    timestamp,
    write_linkage,
)


def row(i=1, verified=False, **changes):
    raw = {
        "incidentId": str(i),
        "incidentNumber": str(i),
        "parentIncidentId": "",
        "permiteeId": "MA1",
        "permiteeName": "City A",
        "eventType": "CSO - Untreated",
        "outfallId": "O1",
        "location": "Street A",
        "latitude": "42.3",
        "longitude": "-71.1",
        "reporterClass": VERIFIED if verified else NOTIFICATION,
        "reportingType": "" if verified else "Initial-Ceased",
        "incidentDate": "2025-01-01",
        "incidentTime": "08:00",
        "amPm": "",
        "submittedDate": "2025-01-03" if verified else "2025-01-01",
        "volumnOfEvent": "100",
        "rainfallData": "1",
        "hours": "1",
        "minutes": "0",
    }
    raw.update(changes)
    day = datetime(2025, 1, 1).date()
    return SourceRow(i, raw, day, datetime(2025, 1, 1, 8), "24_hour")


def result(rows):
    return build_linkage(rows, "synthetic")


def test_unique_pair_preserves_partition_and_provenance(tmp_path):
    rows = [row(), row(2, True, volumnOfEvent="200")]
    linked = result(rows)
    assert linked.summary["links"] == 1
    assert linked.summary["candidate_discharge_events"] == 1
    assert linked.summary["conflicting_candidate_events"] == 1
    fields = linked.events[0]["fields"]
    assert fields["volumnOfEvent"]["state"] == "conflicting"
    assert [v["status"] for v in fields["rainfallData"]["values"]] == ["superseded", "current"]
    assert fields["volumnOfEvent"]["values"][0]["value"] == "100"
    local = tmp_path / "local"
    write_linkage(linked, local, tmp_path / "summary.json")
    assert len((local / "source_rows.jsonl").read_text().splitlines()) == 2
    assert "incidentId" not in (tmp_path / "summary.json").read_text()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("permiteeId", "MA2", "permiteeId"),
        ("permiteeName", "City B", "permiteeName"),
        ("outfallId", "O2", "outfallId"),
        ("eventType", "SSO", "eventType"),
        ("latitude", "45", "coordinates"),
        ("longitude", "-80", "coordinates"),
    ],
)
def test_identifier_never_overrides_contradiction(field, value, reason):
    a, b = row(), row(2, True, parentIncidentId="1", **{field: value})
    decision, detail = pair_rule(a, b)
    assert decision == "no link" and reason in detail


def test_date_and_time_window_and_unknown_clock():
    a, b = row(), row(2, True)
    assert pair_rule(a, replace(b, day=datetime(2025, 1, 2).date()))[0] == "no link"
    assert pair_rule(a, replace(b, start=datetime(2025, 1, 1, 8, 16)))[0] == "no link"
    assert pair_rule(a, replace(b, start=datetime(2025, 1, 1, 8, 15)))[0] == "link"
    assert pair_rule(a, replace(b, start=None))[0] == "abstain"
    assert pair_rule(a, row(3))[0] == "no link"
    assert pair_rule(a, row(3, True, submittedDate=""))[0] == "abstain"
    assert pair_rule(a, row(3, True, submittedDate="2024-01-01"))[0] == "abstain"
    assert pair_rule(a, row(3, True, reportingType="New unknown stage"))[0] == "abstain"
    assert pair_rule(a, row(3, True, eventType=""))[0] == "abstain"
    assert pair_rule(row(1, permiteeName="", permiteeId=""), row(2, True))[0] == "abstain"
    assert pair_rule(a, row(3, True, parentIncidentId="1"))[1].startswith("explicit parent")
    assert pair_rule(a, row(3, True, incidentNumber="1"))[1].startswith("same incident")


def test_location_fallback_requires_specific_name_and_coordinates():
    a, b = row(outfallId=""), row(2, True, outfallId="")
    assert pair_rule(a, b)[0] == "link"
    assert pair_rule(a, row(2, True, outfallId="", location="Other"))[0] == "abstain"
    assert pair_rule(a, row(2, True, outfallId="", latitude=""))[0] == "abstain"


def test_ambiguous_components_never_transitively_merge():
    linked = result([row(), row(2), row(3, True), row(4, True)])
    assert linked.summary["links"] == 0
    assert linked.summary["abstentions"] == 2
    assert linked.summary["candidate_discharge_events"] == 4
    assert linked.summary["ambiguous_component_rows"] == 4
    assert all(len(e["source_rows"]) == 1 for e in linked.events)


def test_global_parent_route_keeps_contradictory_date_visible():
    a = row()
    b = replace(row(2, True, parentIncidentId="1"), day=datetime(2025, 1, 2).date())
    linked = result([a, b])
    assert linked.groups[0]["pair_decisions"][0]["reason"] == "different incident dates"
    assert linked.summary["links"] == 0


def test_retraction_zero_missing_and_high_volumes_retained():
    zero = row(volumnOfEvent="0")
    assert not zero.retracted
    high = row(2, True, volumnOfEvent="11000000")
    linked = result([zero, high])
    assert linked.summary["high_volume_review_rows"] == 1
    assert linked.summary["source_report_rows"] == 2
    retract = row(2, True, reportingType="Retracted", volumnOfEvent="0")
    fields = field_provenance([zero, retract])
    assert fields["volumnOfEvent"]["values"][1]["status"] == "retracted"
    missing = row(volumnOfEvent="", rainfallData="nan", hours="-1")
    assert field_provenance([missing])["volumnOfEvent"]["state"] == "missing"
    assert "invalid_rainfallData_review" in missing.flags
    assert "invalid_hours_review" in missing.flags
    assert field_provenance([retract])["volumnOfEvent"]["state"] == "retracted"
    assert result([retract]).summary["regulator_definition_proxy"]["eligible_verified_rows"] == 0


def test_all_types_unknown_and_missing_keys_preserved():
    rows = [
        row(eventType="SSO"),
        row(2, True, eventType="SSO"),
        row(3, True, eventType="Partially Treated"),
        row(4, reporterClass="Unknown", eventType="SSO"),
        replace(row(5, True, permiteeName="", permiteeId="", eventType="SSO"), day=None),
    ]
    linked = result(rows)
    assert linked.summary["source_report_rows"] == 5
    assert linked.summary["cso_source_report_rows"] == 0
    assert linked.summary["regulator_event_count"] is None
    assert linked.summary["regulator_definition_proxy"]["missing_key_rows"] == 1
    assert linked.summary["abstentions"] >= 2


def test_lossless_csv_ingestion_and_gates(tmp_path):
    path = tmp_path / "source.csv"
    raw = row().raw
    raw["incidentDate"] = "bad"
    raw["incidentTime"] = "bad"
    raw["extra"] = " whitespace and\nnewline "
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(raw))
        w.writeheader()
        w.writerow(raw)
    rows = load_source_rows(path)
    assert rows[0].raw == raw
    assert rows[0].day is None and rows[0].start is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() in rows[0].key
    assert link_snapshot(path, pinned=False).summary["source_report_rows"] == 1
    with pytest.raises(ValueError, match="SHA-256"):
        link_snapshot(path)
    path.write_text("a,b\n1,2,3\n")
    with pytest.raises(ValueError, match="Malformed"):
        load_source_rows(path)
    assert number("nan") is None and number("wrong") is None
    assert timestamp("2025-01-01T00:00:00+00:00") is None
    assert timestamp("wrong") is None


def save_sheet(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def sample_fixture(tmp_path):
    linked = result(
        [
            row(),
            row(2, True),
            row(3, True, outfallId="O2"),
            replace(row(4, outfallId="", location=""), day=datetime(2025, 1, 2).date()),
            replace(row(5, True, outfallId="", location=""), day=datetime(2025, 1, 2).date()),
        ]
    )
    write_sample(linked, tmp_path)
    manifest = tmp_path / "sample_manifest.json"
    (tmp_path / "trusted.sha256").write_text(hashlib.sha256(manifest.read_bytes()).hexdigest())
    return linked, tmp_path / "adjudication.csv", manifest


def score_sheet(sheet, manifest):
    # Capture outside the editable manifest before any test mutation.
    trusted = (manifest.parent / "trusted.sha256").read_text()
    return score_original(sheet, manifest, trusted, review_mode="human")


@pytest.mark.parametrize(
    "mode,label",
    [
        ("human", "assisted, unblinded human check"),
        (
            "ai-agent",
            "assisted, unblinded check by independent AI review agents "
            "directed by Amir Daneshpajouh",
        ),
    ],
)
def test_explicit_and_checker_declared_review_modes(tmp_path, capsys, mode, label):
    _, sheet, manifest = sample_fixture(tmp_path)
    trusted = (manifest.parent / "trusted.sha256").read_text()
    rows = read_sheet(sheet)
    annotate(rows)
    save_sheet(sheet, rows)
    before = sheet.read_bytes()
    assert score_original(sheet, manifest, trusted, review_mode=mode)["review_mode"] == label
    assert (
        main(
            [
                "score-linkage",
                str(sheet),
                "--manifest",
                str(manifest),
                "--manifest-sha256",
                trusted,
                "--review-mode",
                mode,
            ]
        )
        == 0
    )
    explicit = json.loads(capsys.readouterr().out)
    assert explicit["review_mode"] == label
    assert sheet.read_bytes() == before
    for item in rows:
        item["checker_name"] += f" [review-mode={mode}]"
    save_sheet(sheet, rows)
    inferred = score_original(sheet, manifest, trusted)
    assert inferred["review_mode"] == label
    for field in ["status", "sample_automatic_link_precision", "failure_count"]:
        assert inferred[field] == explicit[field]
    assert (
        main(
            ["score-linkage", str(sheet), "--manifest", str(manifest), "--manifest-sha256", trusted]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["review_mode"] == label


@pytest.mark.parametrize(
    "checker_names",
    [
        None,
        ["A reviewer"],
        ["A reviewer [review-mode=human]", "B reviewer"],
        ["A reviewer [review-mode=human]", "B reviewer [review-mode=ai-agent]"],
        ["A reviewer [review-mode=human] [review-mode=ai-agent]"],
        ["A reviewer [review-mode=robot]"],
    ],
)
def test_review_mode_refuses_to_guess(tmp_path, capsys, checker_names):
    _, sheet, manifest = sample_fixture(tmp_path)
    trusted = (manifest.parent / "trusted.sha256").read_text()
    if checker_names is not None:
        rows = read_sheet(sheet)
        annotate(rows)
        for index, item in enumerate(rows):
            item["checker_name"] = checker_names[index % len(checker_names)]
        save_sheet(sheet, rows)
    with pytest.raises(ValueError, match="every checker_name"):
        score_original(sheet, manifest, trusted)
    with pytest.raises(SystemExit) as error:
        main(
            [
                "score-linkage",
                str(sheet),
                "--manifest",
                str(manifest),
                "--manifest-sha256",
                trusted,
            ]
        )
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "Pass --review-mode human or --review-mode ai-agent" in output.err


def test_review_mode_rejects_unsupported_api_value(tmp_path):
    _, sheet, manifest = sample_fixture(tmp_path)
    trusted = (manifest.parent / "trusted.sha256").read_text()
    with pytest.raises(ValueError, match="must be human or ai-agent"):
        score_original(sheet, manifest, trusted, review_mode="robot")


def test_sample_blank_reproducible_and_preserved(tmp_path):
    linked, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    assert all(not r[c] for r in rows for c in HUMAN_COLUMNS)
    assert sample_groups(linked)[0] == sample_groups(linked)[0]
    assert machine_digest(rows) == json.loads(manifest.read_text())["machine_sha256"]
    assert score_sheet(sheet, manifest)["sample_automatic_link_precision"] is None
    assert score_sheet(sheet, manifest)["status"] == "incomplete"
    original = sheet.read_bytes()
    write_sample(linked, tmp_path)
    assert sheet.read_bytes() == original
    rows[0].update(
        human_verdict="unresolved",
        human_note="Synthetic test only",
        checker_name="Test checker",
        checked_date="2026-10-10",
    )
    save_sheet(sheet, rows)
    original = sheet.read_bytes()
    write_sample(linked, tmp_path)
    assert sheet.read_bytes() == original
    assert "Test checker" in (tmp_path / "adjudication.html").read_text()
    assert (
        main(
            [
                "score-linkage",
                str(sheet),
                "--manifest",
                str(manifest),
                "--manifest-sha256",
                (manifest.parent / "trusted.sha256").read_text(),
                "--review-mode",
                "human",
            ]
        )
        == 0
    )


def test_completed_synthetic_scoring_and_failure(tmp_path):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    for r in rows:
        r.update(
            human_verdict="no link",
            human_note="Synthetic wrong link",
            checker_name="Fixture",
            checked_date="2026-10-10",
        )
    save_sheet(sheet, rows)
    score = score_sheet(sheet, manifest)
    assert score["status"] == "complete"
    assert score["sample_automatic_link_precision"] == 0
    assert score["failure_count"] == 1
    for r in rows:
        if r["tool_decision"] == "link":
            r["human_verdict"] = "unresolved"
    save_sheet(sheet, rows)
    assert score_sheet(sheet, manifest)["sample_automatic_link_precision"] is None


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("human_verdict", "wrong", "verdict must"),
        ("checker_name", "", "checker name"),
        ("checked_date", "bad", "Invalid"),
        ("human_note", "", "needs a note"),
        ("tool_decision", "changed", "Machine fields"),
    ],
)
def test_scoring_rejects_invalid_annotations(tmp_path, field, value, message):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    for r in rows:
        r.update(
            human_verdict="unresolved",
            human_note="Synthetic",
            checker_name="Fixture",
            checked_date="2026-10-10",
        )
    rows[0][field] = value
    save_sheet(sheet, rows)
    with pytest.raises(ValueError, match=message):
        score_sheet(sheet, manifest)


def test_sheet_manifest_and_schema_refusals(tmp_path):
    linked, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    rows[0]["checker_name"] = "orphan"
    save_sheet(sheet, rows)
    with pytest.raises(ValueError, match="without a verdict"):
        score_sheet(sheet, manifest)
    rows[0]["tool_reason"] = "edited"
    save_sheet(sheet, rows)
    with pytest.raises(ValueError, match="changed machine"):
        write_sample(linked, tmp_path)
    with pytest.raises(ValueError, match="differs"):
        write_sample(result([row(99)]), tmp_path)
    sheet.write_text("changed\n")
    with pytest.raises(ValueError, match="columns"):
        read_sheet(sheet)
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / "adjudication.csv").write_text("preserve")
    with pytest.raises(ValueError, match="no manifest"):
        write_sample(linked, orphan)


def test_strata_quotas_and_no_replacement(tmp_path):
    rows = []
    for i in range(60):
        # One block per date so each successful link is an independent group.
        day = datetime(2025, 1, 1).date().fromordinal(739252 + i)
        rows.extend([replace(row(2 * i + 1), day=day), replace(row(2 * i + 2, True), day=day)])
    rows.extend(row(1000 + i, reporterClass="Unknown") for i in range(40))
    rows.extend(replace(row(2000 + i, True), day=None) for i in range(40))
    sampled, metadata = sample_groups(result(rows))
    assert len(sampled) == 100
    assert len({r["group_id"] for r in sampled}) == 100
    assert metadata["sample_strata"]["easy_pairs"] >= 40


def test_html_escapes_all_source_fields(tmp_path):
    linked = result([row(permiteeName="<script>alert(1)</script>")])
    write_sample(linked, tmp_path)
    text = (tmp_path / "adjudication.html").read_text()
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("eventType", ""),
        ("submittedDate", ""),
        ("reportingType", "new taxonomy"),
        ("permiteeName", "Unknown"),
        ("location", "Other"),
        ("latitude", "100"),
        ("longitude", "500"),
    ],
)
def test_incomplete_singletons_abstain(verified, field, value):
    changes = {field: value}
    if field == "permiteeName":
        changes["permiteeId"] = "Unknown"
    if field == "location":
        changes["outfallId"] = ""
    linked = result([row(verified=verified, **changes)])
    assert linked.summary["abstentions"] == 1
    assert linked.summary["no_links"] == 0
    assert linked.summary["candidate_discharge_events"] == 1


@pytest.mark.parametrize("verified", [False, True])
def test_missing_clock_or_date_singleton_abstains(verified):
    for changes in ({"start": None}, {"day": None}):
        linked = result([replace(row(verified=verified), **changes)])
        assert linked.summary["abstentions"] == 1
    assert result([row(verified=verified)]).summary["no_links"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", "-91"),
        ("latitude", "91"),
        ("longitude", "-181"),
        ("longitude", "181"),
        ("latitude", "nan"),
        ("longitude", "bad"),
    ],
)
def test_impossible_coordinates_abstain_even_with_outfall(field, value):
    a, b = row(**{field: value}), row(2, True, **{field: value})
    assert f"invalid_{field}_review" in a.flags
    assert pair_rule(a, b)[0] == "abstain"
    linked = result([a, b])
    assert linked.summary["links"] == 0
    assert linked.summary["invalid_coordinate_review_rows"] == 2
    assert linked.summary["source_report_rows"] == 2


def annotate(rows, verdict="no link"):
    for item in rows:
        item.update(
            human_verdict=verdict,
            human_note="Synthetic check only",
            checker_name="Fixture",
            checked_date="2026-10-10",
        )


def test_scoring_identifies_exact_pair_and_normalises_human_cells(tmp_path):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    annotate(rows)
    automatic = next(r for r in rows if r["tool_decision"] == "link")
    automatic["human_verdict"] = " link "
    automatic["human_matched_verified_row"] = " " + automatic["tool_matched_verified_row"] + " "
    automatic["checker_name"] = " Fixture "
    automatic["checked_date"] = " 2026-10-10 "
    automatic["human_note"] = ""
    save_sheet(sheet, rows)
    score = score_sheet(sheet, manifest)
    assert score["sample_automatic_link_precision"] == 1
    assert score["checkers_and_dates"] == [("Fixture", "2026-10-10")]
    # A different listed verified row is a wrong automatic edge, even with 'link'.
    automatic["human_matched_verified_row"] = "synthetic:row-000003"
    automatic["human_note"] = "Different listed row is the match"
    save_sheet(sheet, rows)
    score = score_sheet(sheet, manifest)
    assert score["sample_automatic_link_precision"] == 0
    assert score["failure_count"] == 1
    automatic["human_matched_verified_row"] = "unlisted"
    save_sheet(sheet, rows)
    with pytest.raises(ValueError, match="exact listed"):
        score_sheet(sheet, manifest)


@pytest.mark.parametrize("verdict", ["no link", "unresolved"])
def test_scoring_normalises_other_verdicts(tmp_path, verdict):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    annotate(rows, " " + verdict + " ")
    save_sheet(sheet, rows)
    score = score_sheet(sheet, manifest)
    assert score["status"] == "complete"
    if verdict == "unresolved":
        assert score["human_unresolved_groups"] == len(rows)
        assert score["sample_automatic_link_precision"] is None
    else:
        assert score["failure_count"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_version", "made-up"),
        ("snapshot_sha256", "fabricated"),
        ("sampling", {"seed": 0}),
    ],
)
def test_trusted_receipt_rejects_manifest_mutations(tmp_path, field, value):
    _, sheet, manifest = sample_fixture(tmp_path)
    content = json.loads(manifest.read_text())
    content[field] = value
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="trusted build-receipt"):
        score_sheet(sheet, manifest)


def test_trusted_receipt_rejects_joint_manifest_sheet_edits(tmp_path):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    rows[0]["tool_reason"] = "fabricated but self-consistent"
    save_sheet(sheet, rows)
    content = json.loads(manifest.read_text())
    content["machine_rows"][0]["tool_reason"] = rows[0]["tool_reason"]
    content["machine_sha256"] = machine_digest(rows)
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="trusted build-receipt"):
        score_sheet(sheet, manifest)


@pytest.mark.parametrize("partial", [False, True])
def test_incomplete_sheet_has_no_final_human_metrics(tmp_path, partial):
    _, sheet, manifest = sample_fixture(tmp_path)
    rows = read_sheet(sheet)
    if partial:
        automatic = next(r for r in rows if r["tool_decision"] == "link")
        annotate([automatic], "no link")
        save_sheet(sheet, rows)
    score = score_sheet(sheet, manifest)
    assert score["status"] == "incomplete"
    assert score["checked_groups"] == int(partial)
    assert score["sample_abstention_rate"] is not None
    for field in [
        "sample_automatic_link_precision",
        "failure_count",
        "failure_group_ids",
        "automatic_links_checked",
        "automatic_links_unresolved",
        "human_unresolved_groups",
        "checkers_and_dates",
    ]:
        assert score[field] is None
