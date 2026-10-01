"""Tests for full evaluation path without stop rules."""

import math

from conftest import make_event as _event
from cso_insight.evaluate import evaluate


def _synthetic_corpus() -> list:
    events = []
    for outfall_idx in range(12):
        outfall = f"O{outfall_idx}"
        for year in (2022, 2023, 2024):
            for j in range(3 + outfall_idx):
                events.append(
                    _event(
                        f"{outfall}-{year}-{j}",
                        outfall,
                        year,
                        volume=10.0 + j + outfall_idx,
                        rain=5.0 + j * 0.2 + outfall_idx * 0.1,
                    )
                )
        for j in range(10 + outfall_idx):
            events.append(
                _event(
                    f"{outfall}-2025-{j}",
                    outfall,
                    2025,
                    volume=12.0 + j,
                    rain=6.0 + j * 0.15,
                )
            )
    return events


def test_evaluate_full_path_no_stop() -> None:
    report = evaluate(_synthetic_corpus(), bootstrap_samples=20, seed=0)
    assert report.stop_rule_triggered is False
    assert all(m.n > 0 for m in report.metrics)
    assert not any(math.isnan(m.value) for m in report.metrics)


def test_baseline_empty_volume_and_missing_rain() -> None:
    from cso_insight.baselines import (
        baseline_mean_volume_predictions,
        baseline_rainfall_threshold_predict,
        model_volume_predictions,
    )

    events = _synthetic_corpus()
    train = [e for e in events if e.year != 2025]
    test = [e for e in events if e.year == 2025]
    assert baseline_mean_volume_predictions(train, "UNKNOWN") == 0.0
    assert baseline_rainfall_threshold_predict(train, test, "UNKNOWN") == []
    assert model_volume_predictions(train, test, "UNKNOWN") == []
