"""Regression receipts for publication review round 4, findings 2 through 8."""

import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import make_event
from cso_insight.baselines import BASELINE_RAIN_THRESHOLD, baseline_rainfall_threshold_predict
from cso_insight.clean import clean_records
from cso_insight.cohort import build_cohort_summary, write_quality_export
from cso_insight.ingest import load_cso_records
from cso_insight.quality import flag_quality_issues

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "clock,marker,hour,status",
    [
        ("1:11", "PM", 13, "12_hour"),
        ("12:00", "AM", 0, "12_hour"),
        ("12:00", "PM", 12, "12_hour"),
        ("14:30:15", "", 14, "24_hour"),
        ("08:00", "", 8, "24_hour"),
        ("14:30", "PM", 14, "24_hour"),
        ("0:15", "AM", 0, "24_hour"),
        ("0:15", "PM", None, "ambiguous_zero_pm"),
        ("14:30", "AM", None, "conflicting_meridiem"),
        ("1:11", "unknown", None, "malformed_meridiem"),
        ("not a clock", "", None, "malformed_clock"),
        ("", "", None, "missing_clock"),
    ],
)
def test_r2_clock_contract(tmp_path, clock, marker, hour, status):
    path = tmp_path / "clock.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["incidentId", "incidentDate", "incidentTime", "amPm", "eventType", "Year"],
        )
        writer.writeheader()
        writer.writerow(
            dict(
                incidentId="fixture",
                incidentDate="2025-01-01",
                incidentTime=clock,
                amPm=marker,
                eventType="CSO",
                Year="2025",
            )
        )
    records = load_cso_records(path)
    record = records[0]
    if hour is None:
        assert record.start_time is None
    else:
        assert record.start_time.hour == hour
    assert record.time_status == status
    cleaned = clean_records(records)
    assert cleaned[0].incident_date == "2025-01-01"
    assert cleaned[0].fit_eligible  # clock uncertainty does not change calendar-year analysis
    flags = flag_quality_issues(cleaned)
    assert any(f.flag_type == "unresolved_time" for f in flags) == (hour is None)
    assert (
        build_cohort_summary(records, cleaned, 2, 42)["date_coverage_by_year"]["2025"]["first_date"]
        == "2025-01-01"
    )


def helper_fixture(tmp_path):
    root = tmp_path / "fixture"
    (root / "scripts").mkdir(parents=True)
    helper = root / "scripts/download_data.sh"
    helper.write_bytes((ROOT / "scripts/download_data.sh").read_bytes())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/bash\nwhile [ "$1" != "-o" ]; do shift; done\nshift\n'
        'printf changed > "$1"\nexit "${FAKE_CURL_EXIT:-0}"\n'
    )
    curl.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    return root, helper, env


@pytest.mark.parametrize("failure", ["hash", "network", "frozen"])
def test_r3_download_preserves_snapshot(tmp_path, failure):
    root, helper, env = helper_fixture(tmp_path)
    frozen = root / "data/raw/ma_eea_cso.csv"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"retained snapshot")
    target = frozen if failure == "frozen" else root / "data/raw/acquisition.csv"
    target.write_bytes(b"retained snapshot")
    if failure == "network":
        env["FAKE_CURL_EXIT"] = "22"
    result = subprocess.run(["bash", str(helper), str(target)], env=env, capture_output=True)
    assert result.returncode != 0
    assert target.read_bytes() == b"retained snapshot"
    assert frozen.read_bytes() == b"retained snapshot"
    assert not list(target.parent.glob(".download-*"))
    assert b"DATA_MANIFEST.md" in result.stderr


def test_r3_download_verified_swap(tmp_path):
    root, helper, env = helper_fixture(tmp_path)
    pin = "0e8a56ebf1870646431de7c1d326065fbcd9cd27f63132e0790e79eb5ef231c3"
    helper.write_text(helper.read_text().replace(pin, hashlib.sha256(b"changed").hexdigest()))
    target = root / "acquisition.csv"
    target.write_bytes(b"previous")
    result = subprocess.run(["bash", str(helper), str(target)], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == b"changed"


def test_r4_quality_units(tmp_path):
    rows = [
        make_event("missing", "O1", 2025, None, None),
        make_event("cap", "O2", 2025, 100000, 1, eligible=False),
    ]
    path = tmp_path / "qa.json"
    write_quality_export(path, flag_quality_issues(rows), rows)
    qa = json.loads(path.read_text())
    assert qa["flag_definitions"]["missing_volume"]["unit"] == "identifiers"
    assert qa["flag_definitions"]["implausible_volume"]["unit"] == "report rows"
    assert all(v["definition"] for v in qa["flag_definitions"].values())
    assert qa["full_feed"]["report_rows"] == 2
    assert qa["full_feed"]["unique_quarantined_report_rows"] == 1
    report = (ROOT / "results/report.html").read_text()
    assert "QA: identifiers" in report and "QA: report rows" in report


def test_r5_threshold_policy():
    from cso_insight.cohort import threshold_support_summary

    train = [make_event(str(i), "O1", 2022, 1, 2) for i in range(3)]
    test = [
        make_event("equal", "O1", 2025, 1, 2),
        make_event("unsupported", "O2", 2025, 1, 3),
        make_event("unknown", "O1", 2025, 1, None),
    ]
    assert baseline_rainfall_threshold_predict(train, test, "O1") == [1.0]
    assert baseline_rainfall_threshold_predict(train, test, "O2") == [0.0]
    assert "at or above" in BASELINE_RAIN_THRESHOLD.command
    support = threshold_support_summary(train + test)
    assert support["known_rainfall_test_rows"] == 2
    assert support["supported_test_rows"] == 1
    assert support["default_negative_test_rows"] == 1
    assert support["default_negative_identifier_count"] == 1


def test_r6_plan_wrapper():
    plan = (ROOT / "docs/PREREGISTRATION.md").read_bytes()
    assert (
        hashlib.sha256(plan).hexdigest()
        == "500f3e0a55d2478436e2bfcdd8eb35575e3be871b844415a744cab2d98926af8"
    )
    readme = (ROOT / "README.md").read_text()
    assert (
        "[Frozen analysis plan, amended retrospectively](docs/PREREGISTRATION_STATUS.md)" in readme
    )
    wrapper = (ROOT / "docs/PREREGISTRATION_STATUS.md").read_text()
    assert "2024 is pooled" in wrapper
    assert "[Archived original](PREREGISTRATION.md)" in wrapper
    assert "amended retrospectively" in (ROOT / "results/report.html").read_text()


def test_r7_organizational_schema():
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text())
    assert cff["authors"] == [{"name": "ElementeX Labs Inc."}]
    text = (ROOT / "tests/test_publication_fixes.py").read_text()
    assert "not in cff" not in text
    import runpy

    module = runpy.run_path(str(ROOT / "scripts/prepare_public.py"))
    name, email = module["source_identity"](ROOT)
    metadata = module["git"](ROOT, "show", "-s", "--format=%an <%ae>|%cn <%ce>", "HEAD")
    assert metadata.decode().strip() == f"{name} <{email}>|{name} <{email}>"


def test_r8_bibliography_and_overlap():
    report = (ROOT / "docs/technical-report.md").read_text()
    assert "McGrath, G.," in report
    assert "overlap in report aggregation and plotting" in report
    assert "does not replace hydraulic simulation or duplicate" not in report
    commit = "b0a5c729abb41ba77b24ec0f6df835eee0a5887f"
    assert f"/blob/{commit}/analysis/EEA_DP_CSO_map.py" in report
    assert f"/blob/{commit}/analysis/EEA_DP_CSO_map.py" in (ROOT / "README.md").read_text()
