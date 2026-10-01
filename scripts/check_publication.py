"""Validate generated publication artifacts without reprinting source records."""

import json
import math
from pathlib import Path

root = Path(__file__).resolve().parents[1]
evaluation = json.loads((root / "results/evaluation.json").read_text())
cohort = json.loads((root / "results/cohort_summary.json").read_text())
results = (root / "RESULTS.md").read_text()
site_results = (root / "docs/site/results.md").read_text()
assert site_results.startswith(results), "Browser metric/cohort copy is stale"
for source, target in [
    ("technical-report.md", "technical-report.md"),
    ("DATA_MANIFEST.md", "data-manifest.md"),
    ("LICENSE-CC-BY-4.0.txt", "licence.md"),
    ("PREREGISTRATION_STATUS.md", "PREREGISTRATION_STATUS.md"),
    ("PREREGISTRATION.md", "PREREGISTRATION.md"),
    ("PREREGISTRATION.sha256", "PREREGISTRATION.sha256"),
    ("PREREGISTRATION_AMENDMENT_2026-10-01.md", "PREREGISTRATION_AMENDMENT_2026-10-01.md"),
    ("ANALYSIS_AMENDMENT_R5_2026-10-01.md", "ANALYSIS_AMENDMENT_R5_2026-10-01.md"),
]:
    assert (root / "docs" / source).read_bytes() == (root / "docs/site" / target).read_bytes()
for metric in evaluation["metrics"]:
    assert f"**{metric['name']}**: {metric['value']:.4f}" in results
support = cohort["model_support"]
rmse_ns = [m["n"] for m in evaluation["metrics"] if m["name"].startswith("rmse_")]
assert all(n == support["scored_rows"] for n in rmse_ns)
assert (
    support["scored_rows"] + sum(support["excluded_reason_counts"].values())
    == support["paired_rows"]
)
assert support["paired_rows"] <= support["eligible_test_rows"]
for name in ["evaluation", "cohort_summary", "qa_flags", "timings"]:
    payload = json.loads((root / "results" / f"{name}.json").read_text())
    assert payload["attribution"]["snapshot_sha256"]
qa = json.loads((root / "results/qa_flags.json").read_text())
assert set(qa) == {"attribution", "flag_counts", "flag_definitions", "full_feed", "note"}
assert set(qa["flag_counts"]) <= set(qa["flag_definitions"])
assert all(
    v["unit"] in {"identifiers", "report rows"} and v["definition"]
    for v in qa["flag_definitions"].values()
)
assert qa["full_feed"]["report_rows"] == cohort["total_cso_rows"]
threshold = cohort["threshold_support"]
assert (
    threshold["supported_test_rows"] + threshold["default_negative_test_rows"]
    == threshold["known_rainfall_test_rows"]
)
assert (
    next(m["n"] for m in evaluation["metrics"] if m["name"] == "rain_threshold_positive_rate")
    == threshold["known_rainfall_test_rows"]
)
assert f"{threshold['supported_test_rows']:,}" in (root / "README.md").read_text()
assert "amended retrospectively" in (root / "results/report.html").read_text()
assert not (root / "results/figures/rainfall_volume_scatter.png").exists()
for metric in evaluation["metrics"]:
    assert math.isfinite(metric["value"]), (
        "Stopped/nonfinite result requires explicit publication review"
    )
print("PASS: generated metrics, cohort support, canonical browser pages and aggregate disclosure")

# Active prose counters must agree with the generated cohort; historical milestones are excluded.
readme = (root / "README.md").read_text()
full = cohort["periods"]["full_feed"]
period = cohort["periods"]["evaluation_2022_2025"]
assert f"{cohort['total_cso_rows']:,} CSO rows" in readme
assert (
    f"{period['volume_cap_rows']} evaluation-period reports; "
    f"{full['volume_cap_rows']} across the full feed" in readme
)
assert f"{support['scored_rows']:,}/{support['paired_rows']:,}" in readme
assert f"{support['scored_rows']:,}/{support['eligible_test_rows']:,}" in readme
categories = cohort["identifier_categories"]
named = categories["named"]
assert (
    f"{named + len(categories['unknown_buckets'])} evaluation identifiers include {named} named IDs"
    in readme
)
assert f"{100 * cohort['volume_cap_sensitivity']['volume_removed_fraction']:.1f}%" in readme
print("PASS: active README cohort denominators and cap sensitivity")
