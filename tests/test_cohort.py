"""Tests for cohort summary exports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cso_insight.clean import clean_records
from cso_insight.cohort import build_cohort_summary, write_cohort_summary
from cso_insight.ingest import CsoRecord


def _record(
    incident_id: str,
    gallons: float | None,
    inches: float | None,
    year: int = 2022,
) -> CsoRecord:
    return CsoRecord(
        incident_id=incident_id,
        incident_number=incident_id,
        start_time=datetime(year, 6, 1),
        event_type="CSO – UnTreated",
        permitee_name="A",
        permitee_id="MA",
        outfall_id="O1",
        municipality="B",
        latitude=None,
        longitude=None,
        volume_gallons=gallons,
        rainfall_inches=inches,
        duration_hours=1.0,
        year=year,
        is_treated=False,
    )


def test_cohort_summary_includes_volume_sensitivity() -> None:
    records = [
        _record("small", 1000.0, 0.5, 2022),
        _record("big", 11_000_000.0, 0.5, 2023),
        _record("t1", 1000.0, 0.5, 2025),
    ]
    cleaned = clean_records(records)
    summary = build_cohort_summary(records, cleaned, bootstrap_samples=10, seed=0)
    sensitivity = summary["volume_cap_sensitivity"]
    assert isinstance(sensitivity, dict)
    assert sensitivity["volume_removed_by_cap_m3"] > 0.0


def test_write_cohort_summary_roundtrip(tmp_path: Path) -> None:
    records = [_record("a", 1000.0, 0.5)]
    cleaned = clean_records(records)
    summary = build_cohort_summary(records, cleaned, bootstrap_samples=5, seed=0)
    path = tmp_path / "cohort_summary.json"
    write_cohort_summary(path, summary)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["total_cso_rows"] == 1
