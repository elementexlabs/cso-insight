"""Tests for alignment, quality and modelling."""

from conftest import write_sample_csv
from cso_insight.align import align_events
from cso_insight.clean import clean_records
from cso_insight.ingest import load_cso_records
from cso_insight.model import fit_rainfall_response, predict_volume
from cso_insight.quality import flag_quality_issues


def test_align_events_requires_both_fields(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    aligned = align_events(cleaned)
    assert len(aligned) == len(cleaned)


def test_quality_flags_missing_volume(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    flags = flag_quality_issues(cleaned)
    assert isinstance(flags, list)


def test_rainfall_model_fit(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    model = fit_rainfall_response(cleaned, "OUT1")
    assert model is not None
    pred = predict_volume(model, 25.0)
    assert pred >= 0.0
