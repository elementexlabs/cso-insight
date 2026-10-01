"""Typed records and CSV ingestion."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CsoRecord:
    """One CSO notification row from the Massachusetts EEA feed."""

    incident_id: str
    incident_number: str
    start_time: datetime | None
    event_type: str
    permitee_name: str
    permitee_id: str
    outfall_id: str
    municipality: str
    latitude: float | None
    longitude: float | None
    volume_gallons: float | None
    rainfall_inches: float | None
    duration_hours: float | None
    year: int
    is_treated: bool
    reporter_class: str = "Unknown reporting class"
    incident_date: date | None = None
    time_status: str = "24_hour"


def _parse_float(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date_part(date_text: str) -> date:
    text = date_text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return datetime.fromisoformat(text.split()[0]).date()


def _parse_time_part(time_text: str, am_pm: str = "") -> tuple[time | None, str]:
    """No marker means 24-hour clock; unresolved/conflicting clocks remain unknown."""
    text = time_text.strip()
    marker = am_pm.strip().upper()
    if not text:
        return None, "missing_clock"
    if marker not in {"", "AM", "PM"}:
        return None, "malformed_meridiem"
    parsed = None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt).time()
            break
        except ValueError:
            continue
    if parsed is None:
        return None, "malformed_clock"
    if not marker:
        return parsed, "24_hour"
    hour = parsed.hour
    if hour == 0 and marker == "PM":
        return None, "ambiguous_zero_pm"
    if hour > 12 and marker == "AM":
        return None, "conflicting_meridiem"
    if hour == 0 or hour > 12:
        return parsed, "24_hour"
    hour = hour % 12 + (12 if marker == "PM" else 0)
    return parsed.replace(hour=hour), "12_hour"


def _parse_datetime(date_text: str, time_text: str, am_pm: str = "") -> datetime | None:
    """Combine separate date and clock fields, without inventing unresolved times."""
    clock, _ = _parse_time_part(time_text, am_pm)
    return datetime.combine(_parse_date_part(date_text), clock) if clock is not None else None


def _parse_treatment(event_type: str) -> bool:
    """Parse treatment category from the eventType field."""
    normalized = event_type.lower().replace(" ", "").replace("-", "")
    normalized = normalized.replace("\u2013", "").replace("\u2014", "")
    if "untreated" in normalized:
        return False
    return "treated" in normalized


def _duration_hours(hours_text: str, minutes_text: str) -> float | None:
    hours = _parse_float(hours_text)
    minutes = _parse_float(minutes_text)
    if hours is None and minutes is None:
        return None
    return (hours or 0.0) + (minutes or 0.0) / 60.0


def iter_cso_records(path: Path) -> Iterator[CsoRecord]:
    """Stream CSO rows from the Massachusetts CSV."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            event_type = (row.get("eventType") or "").strip()
            if "CSO" not in event_type:
                continue
            year_text = (row.get("Year") or "").strip()
            year = int(float(year_text)) if year_text else 0
            yield CsoRecord(
                incident_id=(row.get("incidentId") or "").strip(),
                incident_number=(row.get("incidentNumber") or "").strip(),
                start_time=_parse_datetime(
                    row.get("incidentDate") or "",
                    row.get("incidentTime") or "",
                    row.get("amPm") or "",
                ),
                event_type=event_type,
                permitee_name=(row.get("permiteeName") or "").strip(),
                permitee_id=(row.get("permiteeId") or "").strip(),
                outfall_id=(row.get("outfallId") or "").strip(),
                municipality=(row.get("municipality") or "").strip(),
                latitude=_parse_float(row.get("latitude") or ""),
                longitude=_parse_float(row.get("longitude") or ""),
                volume_gallons=_parse_float(row.get("volumnOfEvent") or ""),
                rainfall_inches=_parse_float(row.get("rainfallData") or ""),
                duration_hours=_duration_hours(row.get("hours") or "", row.get("minutes") or ""),
                year=year,
                is_treated=_parse_treatment(event_type),
                incident_date=_parse_date_part(row.get("incidentDate") or ""),
                time_status=_parse_time_part(row.get("incidentTime") or "", row.get("amPm") or "")[
                    1
                ],
                reporter_class=(row.get("reporterClass") or "Unknown reporting class").strip(),
            )


def load_cso_records(path: Path) -> list[CsoRecord]:
    """Load all CSO records into memory (dataset is bounded)."""
    return list(iter_cso_records(path))
