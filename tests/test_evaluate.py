"""Tests for evaluation and baselines."""

from conftest import write_sample_csv
from cso_insight.baselines import baseline_count_scores
from cso_insight.clean import clean_records
from cso_insight.evaluate import evaluate, scoring_sanity_check, spearman_rank_correlation
from cso_insight.ingest import load_cso_records


def test_scoring_sanity_check() -> None:
    scoring_sanity_check()


def test_spearman_perfect() -> None:
    a = {"x": 1.0, "y": 2.0, "z": 3.0}
    b = {"x": 10.0, "y": 20.0, "z": 30.0}
    rho = spearman_rank_correlation(a, b)
    assert rho == 1.0


def test_baseline_count_scores() -> None:
    from conftest import sample_records

    cleaned = clean_records(sample_records())
    scores = baseline_count_scores(cleaned)
    assert scores["OUT1"] == 1.0


def test_evaluate_on_sample(tmp_path) -> None:
    records = load_cso_records(write_sample_csv(tmp_path / "s.csv"))
    cleaned = clean_records(records)
    report = evaluate(cleaned, bootstrap_samples=20, seed=1)
    assert report.test_year == 2025
