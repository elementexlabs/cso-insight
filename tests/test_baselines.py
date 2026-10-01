"""Tests for baselines edge cases."""

from conftest import sample_records
from cso_insight.baselines import model_volume_predictions
from cso_insight.clean import clean_records


def test_model_volume_predictions_no_model() -> None:
    cleaned = clean_records(sample_records())
    pairs = model_volume_predictions(cleaned, cleaned, "UNKNOWN")
    assert pairs == []
