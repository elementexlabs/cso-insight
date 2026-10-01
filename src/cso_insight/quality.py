"""Data quality checks and flags."""

from __future__ import annotations

from dataclasses import dataclass

from cso_insight.clean import CleanEvent
from cso_insight.config import MAX_PLAUSIBLE_RAINFALL_MM, MAX_PLAUSIBLE_VOLUME_M3


@dataclass(frozen=True, slots=True)
class QualityFlag:
    """One data quality issue."""

    event_id: str
    outfall_id: str
    flag_type: str
    detail: str


FLAG_DEFINITIONS = {
    "missing_volume": (
        "identifiers",
        "Identifiers with >50% of full-feed report rows missing volume",
    ),
    "missing_rainfall": (
        "identifiers",
        "Identifiers with >50% of full-feed report rows missing rainfall",
    ),
    "negative_volume": ("report rows", "Report rows with converted volume below zero"),
    "negative_rainfall": ("report rows", "Report rows with rainfall below zero"),
    "implausible_rainfall": ("report rows", "Report rows with rainfall above 254 mm"),
    "implausible_volume": ("report rows", "Report rows with volume above 10 million US gallons"),
    "long_duration": ("report rows", "Report rows with duration above 72 hours"),
    "quarantined_from_fit": ("report rows", "Report rows excluded by any plausibility filter"),
    "unresolved_time": (
        "report rows",
        "Report rows with missing, malformed, conflicting or ambiguous clocks",
    ),
}


def quality_counts(flags: list[QualityFlag]) -> dict[str, int]:
    """Return per-type counts with units and definitions provided by FLAG_DEFINITIONS."""
    from collections import Counter

    counts = Counter(f.flag_type for f in flags)
    return dict(sorted(counts.items()))


def flag_quality_issues(events: list[CleanEvent]) -> list[QualityFlag]:
    """Detect gaps, missing measurements, implausible values and inconsistent units."""
    flags: list[QualityFlag] = []
    by_outfall: dict[str, list[CleanEvent]] = {}
    for event in events:
        by_outfall.setdefault(event.outfall_id, []).append(event)

    for outfall_id, group in by_outfall.items():
        missing_volume = sum(1 for e in group if e.volume_m3 is None)
        missing_rain = sum(1 for e in group if e.rainfall_mm is None)
        if missing_volume / len(group) > 0.5:
            flags.append(
                QualityFlag(
                    event_id="",
                    outfall_id=outfall_id,
                    flag_type="missing_volume",
                    detail=f"{missing_volume}/{len(group)} report rows lack volume",
                )
            )
        if missing_rain / len(group) > 0.5:
            flags.append(
                QualityFlag(
                    event_id="",
                    outfall_id=outfall_id,
                    flag_type="missing_rainfall",
                    detail=f"{missing_rain}/{len(group)} report rows lack rainfall",
                )
            )
        for event in group:
            if event.start_time is None:
                flags.append(
                    QualityFlag(event.event_id, outfall_id, "unresolved_time", event.time_status)
                )
            if event.volume_m3 is not None and event.volume_m3 < 0:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="negative_volume",
                        detail="volume below zero after conversion",
                    )
                )
            if event.rainfall_mm is not None and event.rainfall_mm < 0:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="negative_rainfall",
                        detail="rainfall below zero",
                    )
                )
            if event.rainfall_mm is not None and event.rainfall_mm > MAX_PLAUSIBLE_RAINFALL_MM:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="implausible_rainfall",
                        detail=(
                            f"rainfall {event.rainfall_mm:.1f} mm exceeds "
                            f"{MAX_PLAUSIBLE_RAINFALL_MM:.0f} mm plausibility cap"
                        ),
                    )
                )
            if event.volume_m3 is not None and event.volume_m3 > MAX_PLAUSIBLE_VOLUME_M3:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="implausible_volume",
                        detail=(
                            f"volume {event.volume_m3:.1f} m3 exceeds "
                            f"{MAX_PLAUSIBLE_VOLUME_M3:.0f} m3 plausibility cap"
                        ),
                    )
                )
            if event.duration_hours is not None and event.duration_hours > 72:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="long_duration",
                        detail=f"duration {event.duration_hours:.1f} h exceeds 72 h",
                    )
                )
            if not event.fit_eligible:
                flags.append(
                    QualityFlag(
                        event_id=event.event_id,
                        outfall_id=outfall_id,
                        flag_type="quarantined_from_fit",
                        detail="excluded from fitting and headline evaluation",
                    )
                )
    return flags
