"""Baseline methods for evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cso_insight.clean import CleanEvent
from cso_insight.model import fit_rainfall_response, predict_volume


@dataclass(frozen=True, slots=True)
class BaselineResult:
    """Metadata for one baseline run."""

    name: str
    command: str
    version: str


BASELINE_COUNT = BaselineResult(
    name="event_count_ranking",
    command="rank by raw event count per outfall (no rainfall model)",
    version="cso-insight-baseline/1.0",
)

BASELINE_MEAN_VOLUME = BaselineResult(
    name="mean_volume_per_event",
    command="predict arithmetic mean volume per outfall from train+validation",
    version="cso-insight-baseline/1.0",
)

BASELINE_RAIN_THRESHOLD = BaselineResult(
    name="rainfall_threshold",
    command=(
        "positive when rainfall is at or above training+validation 75th percentile; "
        "fewer than 3 training rainfall observations default negative"
    ),
    version="cso-insight-baseline/1.0",
)


def baseline_count_scores(events: list[CleanEvent]) -> dict[str, float]:
    """Score outfalls by raw event frequency."""
    scores: dict[str, float] = {}
    for event in events:
        scores[event.outfall_id] = scores.get(event.outfall_id, 0.0) + 1.0
    return scores


def baseline_mean_volume_predictions(events: list[CleanEvent], outfall_id: str) -> float:
    """Arithmetic mean volume for outfall on eligible events."""
    volumes = [
        e.volume_m3
        for e in events
        if e.outfall_id == outfall_id and e.volume_m3 is not None and e.fit_eligible
    ]
    if not volumes:
        return 0.0
    return float(np.mean(volumes))


def rainfall_threshold(train: list[CleanEvent], outfall_id: str) -> float | None:
    """Return the eligible training rainfall 75th percentile, supported by >=3 rows."""
    rain = [
        e.rainfall_mm
        for e in train
        if e.outfall_id == outfall_id and e.rainfall_mm is not None and e.fit_eligible
    ]
    return float(np.percentile(rain, 75)) if len(rain) >= 3 else None


def baseline_rainfall_threshold_predict(
    train: list[CleanEvent],
    test: list[CleanEvent],
    outfall_id: str,
) -> list[float]:
    """Event-conditional positive rate: 1.0 at or above training+validation 75th percentile.

    Events with missing rainfall are excluded (unknown, not scored as zero).
    Fewer than three eligible training rainfall observations defaults to negative.
    """
    supported_threshold = rainfall_threshold(train, outfall_id)
    threshold = float("inf") if supported_threshold is None else supported_threshold
    hits: list[float] = []
    for event in test:
        if event.outfall_id != outfall_id:
            continue
        if event.rainfall_mm is None:
            continue
        hits.append(1.0 if event.rainfall_mm >= threshold else 0.0)
    return hits


def model_volume_predictions(
    train: list[CleanEvent],
    test: list[CleanEvent],
    outfall_id: str,
) -> list[tuple[float, float]]:
    """Return (actual, predicted) volume pairs for the rainfall response model."""
    model = fit_rainfall_response(train, outfall_id)
    if model is None:
        return []
    pairs: list[tuple[float, float]] = []
    for event in test:
        if event.outfall_id != outfall_id:
            continue
        if event.volume_m3 is None or event.rainfall_mm is None or not event.fit_eligible:
            continue
        pred = predict_volume(model, event.rainfall_mm)
        pairs.append((event.volume_m3, pred))
    return pairs


def collect_paired_volume_predictions(
    train: list[CleanEvent],
    test: list[CleanEvent],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Collect pooled (actual, predicted) pairs for model and baseline on identical test events."""
    model_pairs: list[tuple[float, float]] = []
    baseline_pairs: list[tuple[float, float]] = []
    for event in test:
        if event.volume_m3 is None or event.rainfall_mm is None or not event.fit_eligible:
            continue
        model = fit_rainfall_response(train, event.outfall_id)
        if model is None:
            continue
        mean_pred = baseline_mean_volume_predictions(train, event.outfall_id)
        model_pairs.append((event.volume_m3, predict_volume(model, event.rainfall_mm)))
        baseline_pairs.append((event.volume_m3, mean_pred))
    return model_pairs, baseline_pairs
