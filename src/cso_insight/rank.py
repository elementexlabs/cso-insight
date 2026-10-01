"""Outfall ranking with bootstrap uncertainty."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cso_insight.clean import CleanEvent
from cso_insight.events import OutfallEventSummary, summarize_by_outfall_year


@dataclass(frozen=True, slots=True)
class OutfallRank:
    """Ranked outfall with bootstrap intervals."""

    outfall_id: str
    rank: int
    metric: str
    point_estimate: float
    ci_low: float
    ci_high: float


def _bootstrap_outfall_metric(
    events: list[CleanEvent],
    metric: str,
    n_samples: int,
    seed: int,
) -> dict[str, tuple[float, float, float]]:
    """Bootstrap resample events (unit = event) for each outfall metric."""
    rng = np.random.default_rng(seed)
    outfalls = sorted({e.outfall_id for e in events})
    if not events:
        return {}

    results: dict[str, list[float]] = {o: [] for o in outfalls}
    for _ in range(n_samples):
        indices = rng.integers(0, len(events), size=len(events))
        sample: list[CleanEvent] = [events[i] for i in indices]
        summaries = summarize_by_outfall_year(sample)
        by_outfall: dict[str, OutfallEventSummary] = {}
        for summary in summaries:
            existing = by_outfall.get(summary.outfall_id)
            if existing is None:
                by_outfall[summary.outfall_id] = summary
            else:
                by_outfall[summary.outfall_id] = OutfallEventSummary(
                    outfall_id=summary.outfall_id,
                    year=summary.year,
                    event_count=existing.event_count + summary.event_count,
                    total_volume_m3=existing.total_volume_m3 + summary.total_volume_m3,
                    mean_rainfall_mm=summary.mean_rainfall_mm,
                    treated_fraction=summary.treated_fraction,
                )
        for outfall_id in outfalls:
            bucket = by_outfall.get(outfall_id)
            if bucket is None:
                value = 0.0
            elif metric == "frequency":
                value = float(bucket.event_count)
            elif metric == "volume":
                value = float(bucket.total_volume_m3)
            else:
                msg = f"Unknown metric: {metric}"
                raise ValueError(msg)
            results[outfall_id].append(value)

    output: dict[str, tuple[float, float, float]] = {}
    for outfall_id, values in results.items():
        arr = np.array(values, dtype=float)
        output[outfall_id] = (
            float(
                sum(
                    1 if metric == "frequency" else (e.volume_m3 or 0.0)
                    for e in events
                    if e.outfall_id == outfall_id
                )
            ),
            float(np.percentile(arr, 2.5)),
            float(np.percentile(arr, 97.5)),
        )
    return output


def rank_outfalls(
    events: list[CleanEvent],
    metric: str,
    n_samples: int = 500,
    seed: int = 42,
) -> list[OutfallRank]:
    """Rank outfalls by frequency or total volume with bootstrap CIs."""
    estimates = _bootstrap_outfall_metric(events, metric, n_samples, seed)
    ranked = sorted(estimates.items(), key=lambda item: item[1][0], reverse=True)
    ranks: list[OutfallRank] = []
    for index, (outfall_id, (point, low, high)) in enumerate(ranked, start=1):
        ranks.append(
            OutfallRank(
                outfall_id=outfall_id,
                rank=index,
                metric=metric,
                point_estimate=point,
                ci_low=low,
                ci_high=high,
            )
        )
    return ranks


def yearly_trend_slope(events: list[CleanEvent], outfall_id: str) -> float | None:
    """OLS slope of annual event counts for one outfall."""
    summaries = summarize_by_outfall_year([e for e in events if e.outfall_id == outfall_id])
    if len(summaries) < 3:
        return None
    years = np.array([s.year for s in summaries], dtype=float)
    counts = np.array([s.event_count for s in summaries], dtype=float)
    slope, _intercept = np.polyfit(years, counts, deg=1)
    return float(slope)
