"""Tests for ranking."""

from conftest import write_sample_csv
from cso_insight.clean import clean_records
from cso_insight.ingest import load_cso_records
from cso_insight.rank import rank_outfalls


def test_rank_outfalls_frequency(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    ranks = rank_outfalls(cleaned, "frequency", n_samples=10, seed=0)
    assert ranks[0].rank == 1
    assert ranks[0].ci_low <= ranks[0].point_estimate <= ranks[0].ci_high
