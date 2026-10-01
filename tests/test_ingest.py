"""Tests for ingestion and cleaning."""

import pytest

from conftest import sample_records, write_sample_csv
from cso_insight.clean import clean_records
from cso_insight.ingest import load_cso_records


def test_iter_cso_records_filters_sso(tmp_path) -> None:
    csv_path = write_sample_csv(tmp_path / "sample.csv")
    records = load_cso_records(csv_path)
    assert len(records) == 9
    assert all("CSO" in r.event_type for r in records)


def test_clean_converts_units() -> None:
    cleaned = clean_records(sample_records())
    assert cleaned[0].volume_m3 == pytest.approx(3.78541, rel=1e-3)
    assert cleaned[0].rainfall_mm == pytest.approx(12.7, rel=1e-2)


def test_untreated_parsing(tmp_path) -> None:
    csv_path = write_sample_csv(tmp_path / "sample.csv")
    records = load_cso_records(csv_path)
    assert all(r.is_treated is False for r in records)
