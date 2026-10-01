"""Event detection and grouping."""

from __future__ import annotations

from dataclasses import dataclass

from cso_insight.clean import CleanEvent


@dataclass(frozen=True, slots=True)
class OutfallEventSummary:
    """Aggregated event statistics for one outfall in one calendar year."""

    outfall_id: str
    year: int
    event_count: int
    total_volume_m3: float
    mean_rainfall_mm: float | None
    treated_fraction: float


def summarize_by_outfall_year(events: list[CleanEvent]) -> list[OutfallEventSummary]:
    """Aggregate events by outfall and year."""
    buckets: dict[tuple[str, int], list[CleanEvent]] = {}
    for event in events:
        key = (event.outfall_id, event.year)
        buckets.setdefault(key, []).append(event)

    summaries: list[OutfallEventSummary] = []
    for (outfall_id, year), group in sorted(buckets.items()):
        volumes = [e.volume_m3 for e in group if e.volume_m3 is not None]
        rains = [e.rainfall_mm for e in group if e.rainfall_mm is not None]
        treated = sum(1 for e in group if e.is_treated)
        summaries.append(
            OutfallEventSummary(
                outfall_id=outfall_id,
                year=year,
                event_count=len(group),
                total_volume_m3=sum(volumes) if volumes else 0.0,
                mean_rainfall_mm=(sum(rains) / len(rains)) if rains else None,
                treated_fraction=treated / len(group) if group else 0.0,
            )
        )
    return summaries
