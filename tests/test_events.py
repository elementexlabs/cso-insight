"""Tests for events and alignment modules."""

from conftest import write_sample_csv
from cso_insight.align import align_events
from cso_insight.clean import clean_records
from cso_insight.events import summarize_by_outfall_year
from cso_insight.ingest import load_cso_records


def test_summarize_by_outfall_year(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    summaries = summarize_by_outfall_year(cleaned)
    assert any(s.outfall_id == "OUT1" for s in summaries)


def test_align_events_count(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    assert len(align_events(cleaned)) == len(cleaned)
