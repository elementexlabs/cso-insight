"""Publication contracts from the independent round 3 review."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from conftest import make_event, sample_records, write_sample_csv
from cso_insight.clean import clean_records
from cso_insight.cohort import build_cohort_summary, write_quality_export
from cso_insight.ingest import load_cso_records
from cso_insight.pipeline import _write_figures
from cso_insight.quality import QualityFlag
from cso_insight.rank import rank_outfalls

ROOT = Path(__file__).resolve().parents[1]


def test_r1_metric_reproduction_contract():
    payload = json.loads((ROOT / "results/evaluation.json").read_text())
    metrics = {m["name"]: m for m in payload["metrics"]}
    baseline = metrics["rmse_mean_volume_baseline_m3"]["value"]
    assert baseline < metrics["rmse_rainfall_model_m3"]["value"]
    assert metrics["rmse_rainfall_model_m3"]["n"] == 1625


def test_r2_configured_linter():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    assert "**PUBLISH**" not in (ROOT / "REPORT.md").read_text()


def test_r3_portable_install():
    lock = (ROOT / "requirements-lock.txt").read_text()
    assert "/Users/" not in lock
    assert "-e " not in lock
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "pip install -r requirements-lock.txt" in workflow
    assert "pip install --no-deps -e ." in workflow


def test_r4_paired_reporting_stages(tmp_path):
    path = write_sample_csv(tmp_path / "stages.csv")
    text = path.read_text()
    # Same incident timestamp/outfall, separate report IDs and stages.
    notification = text.splitlines()[1]
    verified = notification.replace("a1,n1,", "v1,nv1,").replace(
        "Public Notification Report", "Verified Data Report"
    )
    path.write_text(text.splitlines()[0] + "\n" + notification + "\n" + verified + "\n")
    records = load_cso_records(path)
    assert [r.reporter_class for r in records] == [
        "Public Notification Report",
        "Verified Data Report",
    ]
    events = clean_records(records)
    assert events[1].reporter_class == "Verified Data Report"
    summary = build_cohort_summary(records, events, 5, 42)
    assert summary["report_class_sensitivity"]["eligible_counts_by_identifier"]["OUT1"] == {
        "all_classes": 2,
        "verified_only": 1,
    }
    assert summary["estimand"] == "report rows, not distinct discharges"


def test_r5_aggregate_only_disclosure(tmp_path):
    path = tmp_path / "qa.json"
    flags = [QualityFlag("sensitive-row-id", "OUT1", "implausible_volume", "volume 99999 m3")]
    write_quality_export(path, flags)
    text = path.read_text()
    assert "sensitive-row-id" not in text
    assert "99999" not in text
    payload = json.loads(text)
    assert payload["flag_counts"] == {"implausible_volume": 1}
    assert payload["attribution"]["snapshot_sha256"]


def test_r6_denominators_and_timing_status():
    records = sample_records()
    records += [
        replace(
            records[0],
            incident_id="late",
            year=2026,
            volume_gallons=11_000_000,
            rainfall_inches=None,
        )
    ]
    summary = build_cohort_summary(records, clean_records(records), 5, 42)
    assert summary["periods"]["full_feed"]["volume_cap_rows"] == 1
    assert summary["periods"]["evaluation_2022_2025"]["volume_cap_rows"] == 0
    assert summary["periods"]["full_feed"]["missing_volume_or_rainfall_rows"] == 1
    assert summary["identifier_categories"]["named"] == 1
    assert summary["date_coverage_by_year"]["2022"]["first_date"] == "2022-06-01"
    note = (ROOT / "docs/PREREGISTRATION_STATUS.md").read_text()
    assert "does not establish chronology" in note
    assert "well under 12 GB" not in (ROOT / "REPORT.md").read_text()


def test_r7_scoped_prior_art():
    readme = (ROOT / "README.md").read_text()
    assert "Typed Python API with tests | Yes | Partial (PySWMM) | No" not in readme
    assert "AMEND already has tests and automated chart regeneration" in readme
    assert "external meteorological join" in readme


def test_r8_separate_public_history_route():
    script = ROOT / "scripts/prepare_public.py"
    assert script.exists()
    assert "source_identity" in script.read_text()
    assert "public.bundle" in script.read_text()
    assert "original history" in (ROOT / "docs/RELEASE.md").read_text()


def test_r9_observed_points_and_model_support():
    events = [make_event(str(i), "O1", 2022, 10 + i, 1 + i) for i in range(6)]
    events += [make_event("t", "O1", 2025), make_event("unsupported", "O2", 2025)]
    ranks = rank_outfalls(events, "frequency", 1, 19)
    assert {r.outfall_id: r.point_estimate for r in ranks} == {"O1": 7, "O2": 1}
    # Construct records using the same years/identifiers to exercise the actual ledger.
    records = [
        replace(
            sample_records()[0],
            incident_id=e.event_id,
            outfall_id=e.outfall_id,
            year=e.year,
            volume_gallons=e.volume_m3 / 0.00378541,
            rainfall_inches=e.rainfall_mm / 25.4,
        )
        for e in events
    ]
    summary = build_cohort_summary(records, clean_records(records), 5, 42)
    assert summary["model_support"]["scored_rows"] == 1
    assert summary["model_support"]["paired_rows"] == 2
    assert summary["model_support"]["excluded_reason_counts"] == {"no_training_model": 1}


def test_r10_browser_case_study_and_uncertainty(tmp_path, monkeypatch):
    assert len((ROOT / "docs/site/technical-report.md").read_text()) > 3000
    assert len((ROOT / "docs/site/data-manifest.md").read_text()) > 2000
    assert "![Report row counts]" in (ROOT / "docs/site/results.md").read_text()
    calls = []
    from matplotlib.axes import Axes

    original = Axes.barh

    def capture(self, *args, **kwargs):
        calls.append(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "barh", capture)
    ranks = rank_outfalls([make_event("a", "O1", 2022)], "frequency", 5, 42)
    paths = _write_figures(tmp_path, [], [], ranks, ranks)
    assert "rainfall_volume" not in paths
    assert all("xerr" in call for call in calls)


def test_public_snapshot_history_and_hygiene(tmp_path):
    import runpy

    import pytest

    module = runpy.run_path(str(ROOT / "scripts/prepare_public.py"))
    bundle = tmp_path / "public.bundle"
    module["prepare"](ROOT, bundle)
    scan = json.loads(bundle.with_suffix(".scan.json").read_text())
    assert scan["commits"] == 1
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(bundle), str(checkout)], check=True, capture_output=True)
    name, email = module["source_identity"](ROOT)
    identity = f"{name} <{email}>"
    assert scan["identity"] == identity
    assert module["git"](checkout, "branch", "--show-current").strip() == b"publication-r6"
    assert module["git"](checkout, "show", "-s", "--format=%P").strip() == b""
    assert (
        module["git"](checkout, "show", "-s", "--format=%an <%ae>|%cn <%ce>").strip()
        == (identity + "|" + identity).encode()
    )
    assert not (checkout / ".review").exists()
    assert not (checkout / "docs/milestones").exists()
    assert not (checkout / "results/figures/rainfall_volume_scatter.png").exists()
    files = json.loads((checkout / "SOURCE_MANIFEST.json").read_text())
    import hashlib

    for path, digest in files.items():
        assert hashlib.sha256((checkout / path).read_bytes()).hexdigest() == digest
    module["git"](checkout, "remote", "remove", "origin")

    # Actual commit headers, rather than script literals, must enforce both roles.
    import os

    owner_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    for role in ("AUTHOR", "COMMITTER"):
        wrong_env = {
            **owner_env,
            f"GIT_{role}_NAME": "ElementeX Labs Inc.",
            f"GIT_{role}_EMAIL": "publication@elementexlabs.invalid",
        }
        module["git"](checkout, "commit", "--amend", "--reset-author", "--no-edit", env=wrong_env)
        with pytest.raises(ValueError, match="owner's source identity"):
            module["scan_history"](checkout, identity)
    with pytest.raises(ValueError, match="Source author and committer"):
        module["source_identity"](checkout)
    module["git"](checkout, "commit", "--amend", "--reset-author", "--no-edit", env=owner_env)
    assert module["scan_history"](checkout, identity)["commits"] == 1
    module["git"](
        checkout, "commit", "--allow-empty", "-m", "History rejection fixture", env=owner_env
    )
    with pytest.raises(ValueError, match="one parentless commit"):
        module["scan_history"](checkout, identity)
    unsafe = checkout / "unsafe.txt"
    unsafe.write_text("-----BEGIN " + "PRIVATE KEY-----\n")
    module["git"](checkout, "add", "unsafe.txt")
    module["git"](checkout, "commit", "-m", "Scan rejection fixture", env=owner_env)
    with pytest.raises(ValueError, match="Forbidden pattern"):
        module["scan_history"](checkout, identity)


def test_class_sensitivity_with_constant_counts_and_relaxed_cap():
    from cso_insight.cohort import volume_cap_sensitivity
    from cso_insight.evaluate import spearman_rank_correlation

    assert spearman_rank_correlation({"a": 1, "b": 1, "c": 1}, {"a": 1, "b": 2, "c": 3}) is None
    rows = [
        make_event("bad", "O1", 2022, 100, -1, eligible=False),
        make_event("good", "O1", 2022, 10, 1),
    ]
    sensitivity = volume_cap_sensitivity(rows, 5, 42)
    assert sensitivity["uncapped_total_reported_volume_m3"] == 10
