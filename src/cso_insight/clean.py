"""Data cleaning and unit normalization."""

from __future__ import annotations

from dataclasses import dataclass

from cso_insight.config import MAX_PLAUSIBLE_RAINFALL_MM, MAX_PLAUSIBLE_VOLUME_M3
from cso_insight.ingest import CsoRecord

GALLONS_TO_CUBIC_METRES = 0.00378541
INCHES_TO_MM = 25.4


@dataclass(frozen=True, slots=True)
class CleanEvent:
    """Normalized CSO event ready for modelling."""

    event_id: str
    outfall_id: str
    permitee_name: str
    municipality: str
    start_time: str | None
    year: int
    volume_m3: float | None
    rainfall_mm: float | None
    duration_hours: float | None
    is_treated: bool
    event_type: str
    fit_eligible: bool
    reporter_class: str = "Unknown reporting class"
    time_status: str = "24_hour"
    incident_date: str | None = None


def _is_fit_eligible(
    volume_m3: float | None,
    rainfall_mm: float | None,
    duration_hours: float | None,
) -> bool:
    if volume_m3 is not None and volume_m3 < 0:
        return False
    if rainfall_mm is not None and rainfall_mm < 0:
        return False
    if rainfall_mm is not None and rainfall_mm > MAX_PLAUSIBLE_RAINFALL_MM:
        return False
    if volume_m3 is not None and volume_m3 > MAX_PLAUSIBLE_VOLUME_M3:
        return False
    return not (duration_hours is not None and duration_hours > 72)


def clean_record(record: CsoRecord) -> CleanEvent:
    """Normalize one CSO record."""
    outfall = record.outfall_id or f"UNKNOWN_{record.permitee_id}"
    volume_m3 = (
        record.volume_gallons * GALLONS_TO_CUBIC_METRES
        if record.volume_gallons is not None
        else None
    )
    rainfall_mm = (
        record.rainfall_inches * INCHES_TO_MM if record.rainfall_inches is not None else None
    )
    eligible = _is_fit_eligible(volume_m3, rainfall_mm, record.duration_hours)
    return CleanEvent(
        event_id=record.incident_id or record.incident_number,
        outfall_id=outfall,
        permitee_name=record.permitee_name,
        municipality=record.municipality,
        start_time=record.start_time.isoformat(sep=" ") if record.start_time else None,
        time_status=record.time_status,
        incident_date=(
            record.incident_date.isoformat()
            if record.incident_date
            else record.start_time.date().isoformat()
            if record.start_time
            else None
        ),
        year=record.year,
        volume_m3=volume_m3,
        rainfall_mm=rainfall_mm,
        duration_hours=record.duration_hours,
        is_treated=record.is_treated,
        event_type=record.event_type,
        fit_eligible=eligible,
        reporter_class=record.reporter_class,
    )


def clean_records(records: list[CsoRecord]) -> list[CleanEvent]:
    return [clean_record(r) for r in records]


def fit_eligible_events(events: list[CleanEvent]) -> list[CleanEvent]:
    """Return events that pass plausibility checks for fitting and evaluation."""
    return [e for e in events if e.fit_eligible]
