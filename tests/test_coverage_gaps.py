"""Additional tests for coverage gaps."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import sample_records, write_sample_csv
from cso_insight.align import align_events
from cso_insight.baselines import (
    baseline_rainfall_threshold_predict,
    model_volume_predictions,
)
from cso_insight.clean import CleanEvent, clean_records
from cso_insight.cli import main
from cso_insight.config import validate_url
from cso_insight.download import download_file
from cso_insight.evaluate import evaluate, write_evaluation
from cso_insight.ingest import iter_cso_records
from cso_insight.quality import flag_quality_issues
from cso_insight.rank import rank_outfalls, yearly_trend_slope


def test_validate_url_bad_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        validate_url("ftp://openamend.org/data.csv")


def test_download_file_streams(tmp_path: Path) -> None:
    payload = b"col1,col2\n1,2\n"
    response = MagicMock()
    response.read.side_effect = [payload, b""]
    response.geturl.return_value = "https://openamend.org/data/EEADP_CSO.csv"
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    dest = tmp_path / "out.csv"
    with patch("cso_insight.download.urlopen", return_value=response):
        digest = download_file("https://openamend.org/data/EEADP_CSO.csv", dest)
    assert dest.read_bytes() == payload
    assert len(digest) == 64


def test_download_file_size_limit(tmp_path: Path) -> None:
    response = MagicMock()
    response.read.return_value = b"x" * 100
    response.geturl.return_value = "https://openamend.org/data/EEADP_CSO.csv"
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    with patch("cso_insight.download.urlopen", return_value=response):
        with pytest.raises(ValueError, match="size limit"):
            download_file(
                "https://openamend.org/data/EEADP_CSO.csv",
                tmp_path / "x.csv",
                max_bytes=10,
            )


def test_align_skips_incomplete() -> None:
    events = [
        CleanEvent(
            event_id="1",
            outfall_id="O1",
            permitee_name="A",
            municipality="B",
            start_time="2022-01-01",
            year=2022,
            volume_m3=None,
            rainfall_mm=1.0,
            duration_hours=None,
            is_treated=False,
            event_type="CSO",
            fit_eligible=True,
        )
    ]
    assert align_events(events) == []


def test_quality_negative_and_long_duration() -> None:
    events = [
        CleanEvent(
            event_id="1",
            outfall_id="O1",
            permitee_name="A",
            municipality="B",
            start_time="2022-01-01",
            year=2022,
            volume_m3=-1.0,
            rainfall_mm=-0.1,
            duration_hours=100.0,
            is_treated=False,
            event_type="CSO",
            fit_eligible=False,
        )
    ]
    flags = flag_quality_issues(events)
    types = {f.flag_type for f in flags}
    assert "negative_volume" in types
    assert "negative_rainfall" in types
    assert "long_duration" in types


def test_baseline_rainfall_threshold_and_model_pairs(tmp_path: Path) -> None:
    from cso_insight.ingest import load_cso_records

    records = clean_records(load_cso_records(write_sample_csv(tmp_path / "s.csv")))
    train = [r for r in records if r.year != 2025] * 2
    test = [r for r in records if r.year == 2025]
    preds = baseline_rainfall_threshold_predict(train, test, "OUT1")
    assert len(preds) == 1
    pairs = model_volume_predictions(train, test, "OUT1")
    assert len(pairs) == 1


def test_rank_unknown_metric_raises() -> None:
    cleaned = clean_records(sample_records())
    with pytest.raises(ValueError, match="Unknown metric"):
        rank_outfalls(cleaned, "invalid", n_samples=2, seed=0)


def test_yearly_trend_slope_insufficient_data() -> None:
    cleaned = clean_records(sample_records())
    assert yearly_trend_slope(cleaned, "OUT1") is None


def test_yearly_trend_slope_with_years(tmp_path: Path) -> None:
    cleaned = clean_records(sample_records())
    extra = [
        CleanEvent(
            event_id=f"e{i}",
            outfall_id="OUT1",
            permitee_name="A",
            municipality="B",
            start_time=f"20{20 + i}-01-01",
            year=2020 + i,
            volume_m3=1.0,
            rainfall_mm=1.0,
            duration_hours=1.0,
            is_treated=False,
            event_type="CSO",
            fit_eligible=True,
        )
        for i in range(4)
    ]
    assert yearly_trend_slope(cleaned + extra, "OUT1") is not None


def test_write_evaluation(tmp_path: Path) -> None:
    cleaned = clean_records(sample_records())
    report = evaluate(cleaned, bootstrap_samples=5, seed=0)
    path = tmp_path / "eval.json"
    write_evaluation(report, path)
    data = json.loads(path.read_text())
    assert data["test_year"] == 2025


def test_cli_missing_command() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_ingest_parse_fallback_datetime(tmp_path: Path) -> None:
    csv_text = (
        "incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,"
        "eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,"
        "reportingType,location,latitude,longitude,waterBody,waterBodyDescription,"
        "volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,"
        "submittedDate,parentIncidentId,Year\n"
        "x,n,2022-01-01,08:00,,Public Notification Report,CSO - UnTreated,CSO,"
        "A,MA1,O1,B,,,,,,,100,0.5,,,,,,2022.0\n"
    )
    path = tmp_path / "one.csv"
    path.write_text(csv_text, encoding="utf-8")
    rows = list(iter_cso_records(path))
    assert len(rows) == 1


def test_clean_ineligible_paths() -> None:
    from dataclasses import replace
    from datetime import datetime

    from cso_insight.clean import clean_record
    from cso_insight.ingest import CsoRecord

    base = CsoRecord(
        incident_id="1",
        incident_number="n",
        start_time=datetime(2022, 1, 1),
        event_type="CSO – UnTreated",
        permitee_name="A",
        permitee_id="MA",
        outfall_id="O1",
        municipality="B",
        latitude=None,
        longitude=None,
        volume_gallons=1000.0,
        rainfall_inches=0.5,
        duration_hours=1.0,
        year=2022,
        is_treated=False,
    )
    neg = clean_record(replace(base, volume_gallons=-1.0))
    assert neg.fit_eligible is False
    rain = clean_record(replace(base, rainfall_inches=50.0))
    assert rain.fit_eligible is False


def test_ingest_treated_event(tmp_path: Path) -> None:
    csv_text = (
        "incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,"
        "eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,"
        "reportingType,location,latitude,longitude,waterBody,waterBodyDescription,"
        "volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,"
        "submittedDate,parentIncidentId,Year\n"
        "x,n,2022-01-01,08:00,,Public Notification Report,CSO – Treated,CSO,"
        "A,MA1,O1,B,,,,,,,100,0.5,,,,,,2022.0\n"
    )
    path = tmp_path / "t.csv"
    path.write_text(csv_text, encoding="utf-8")
    rows = list(iter_cso_records(path))
    assert rows[0].is_treated is True


def test_evaluate_stop_rule_small_test_set() -> None:
    events = [
        CleanEvent(
            event_id="t1",
            outfall_id="O1",
            permitee_name="A",
            municipality="B",
            start_time="2025-01-01",
            year=2025,
            volume_m3=1.0,
            rainfall_mm=1.0,
            duration_hours=1.0,
            is_treated=False,
            event_type="CSO",
            fit_eligible=True,
        )
    ]
    report = evaluate(events, bootstrap_samples=5, seed=0)
    assert report.stop_rule_triggered is True
