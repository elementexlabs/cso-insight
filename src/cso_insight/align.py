"""Align CSO events with co-reported rainfall."""

from __future__ import annotations

from dataclasses import dataclass

from cso_insight.clean import CleanEvent


@dataclass(frozen=True, slots=True)
class AlignedEvent:
    """CSO event with aligned rainfall for modelling."""

    event_id: str
    outfall_id: str
    year: int
    volume_m3: float
    rainfall_mm: float
    start_time: str | None


def align_events(events: list[CleanEvent]) -> list[AlignedEvent]:
    """Keep fit-eligible events where both volume and rainfall are present."""
    aligned: list[AlignedEvent] = []
    for event in events:
        if not event.fit_eligible:
            continue
        if event.volume_m3 is None or event.rainfall_mm is None:
            continue
        aligned.append(
            AlignedEvent(
                event_id=event.event_id,
                outfall_id=event.outfall_id,
                year=event.year,
                volume_m3=event.volume_m3,
                rainfall_mm=event.rainfall_mm,
                start_time=event.start_time,
            )
        )
    return aligned
