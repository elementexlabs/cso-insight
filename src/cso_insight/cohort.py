"""Cohort accounting, exclusion summaries and cutoff sensitivity."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from cso_insight.attribution import output_attribution
from cso_insight.baselines import baseline_count_scores, rainfall_threshold
from cso_insight.clean import CleanEvent, clean_records
from cso_insight.config import (
    EVALUATION_YEARS,
    MAX_PLAUSIBLE_RAINFALL_MM,
    MAX_PLAUSIBLE_VOLUME_M3,
)
from cso_insight.evaluate import spearman_rank_correlation
from cso_insight.ingest import CsoRecord
from cso_insight.model import fit_all_outfalls
from cso_insight.quality import FLAG_DEFINITIONS, QualityFlag, flag_quality_issues, quality_counts
from cso_insight.rank import rank_outfalls


@dataclass(frozen=True, slots=True)
class ExclusionReason:
    """One quarantine reason with counts and volume impact."""

    reason: str
    row_count: int
    reported_volume_m3: float


def _volume_m3(record: CsoRecord) -> float:
    if record.volume_gallons is None:
        return 0.0
    return record.volume_gallons * 0.00378541


def _rainfall_mm(record: CsoRecord) -> float | None:
    if record.rainfall_inches is None:
        return None
    return record.rainfall_inches * 25.4


def exclusion_reasons(records: list[CsoRecord], cleaned: list[CleanEvent]) -> list[ExclusionReason]:
    """Count rows excluded from fit-eligible cohort by reason."""
    by_id = {event.event_id: event for event in cleaned}
    counts: dict[str, tuple[int, float]] = {
        "negative_volume": (0, 0.0),
        "negative_rainfall": (0, 0.0),
        "rainfall_above_cap": (0, 0.0),
        "volume_above_cap": (0, 0.0),
        "duration_above_72h": (0, 0.0),
    }
    for record in records:
        event = by_id.get(record.incident_id or record.incident_number)
        if event is None or event.fit_eligible:
            continue
        volume = _volume_m3(record)
        rainfall = _rainfall_mm(record)
        if volume < 0:
            key = "negative_volume"
        elif rainfall is not None and rainfall < 0:
            key = "negative_rainfall"
        elif rainfall is not None and rainfall > MAX_PLAUSIBLE_RAINFALL_MM:
            key = "rainfall_above_cap"
        elif volume > MAX_PLAUSIBLE_VOLUME_M3:
            key = "volume_above_cap"
        elif record.duration_hours is not None and record.duration_hours > 72:
            key = "duration_above_72h"
        else:
            continue
        count, total = counts[key]
        counts[key] = (count + 1, total + max(volume, 0.0))

    return [
        ExclusionReason(reason=reason, row_count=count, reported_volume_m3=total)
        for reason, (count, total) in counts.items()
        if count > 0
    ]


def volume_cap_sensitivity(
    cleaned: list[CleanEvent],
    bootstrap_samples: int,
    seed: int,
) -> dict[str, object]:
    """Compare descriptive volume rankings with and without the volume cap."""
    eval_events = [event for event in cleaned if event.year in EVALUATION_YEARS]
    capped = [event for event in eval_events if event.fit_eligible]
    uncapped = [
        event
        for event in eval_events
        if (event.volume_m3 is None or event.volume_m3 >= 0)
        and (event.rainfall_mm is None or 0 <= event.rainfall_mm <= MAX_PLAUSIBLE_RAINFALL_MM)
        and (event.duration_hours is None or event.duration_hours <= 72)
    ]
    capped_volume = sum(event.volume_m3 or 0.0 for event in capped)
    uncapped_volume = sum(event.volume_m3 or 0.0 for event in uncapped)
    capped_rank = rank_outfalls(capped, "volume", bootstrap_samples, seed)[:5]
    uncapped_rank = rank_outfalls(uncapped, "volume", bootstrap_samples, seed)[:5]
    return {
        "capped_total_reported_volume_m3": capped_volume,
        "uncapped_total_reported_volume_m3": uncapped_volume,
        "volume_removed_by_cap_m3": uncapped_volume - capped_volume,
        "volume_removed_fraction": (
            (uncapped_volume - capped_volume) / uncapped_volume if uncapped_volume else 0.0
        ),
        "top5_volume_outfalls_with_cap": [
            {"outfall_id": rank.outfall_id, "point_estimate_m3": rank.point_estimate}
            for rank in capped_rank
        ],
        "top5_volume_outfalls_without_cap": [
            {"outfall_id": rank.outfall_id, "point_estimate_m3": rank.point_estimate}
            for rank in uncapped_rank
        ],
    }


def volume_removed_fraction(summary: dict[str, object]) -> float | None:
    """Return the fraction of descriptive volume removed by the volume cap."""
    sensitivity_obj = summary.get("volume_cap_sensitivity")
    if not isinstance(sensitivity_obj, dict):
        return None
    raw_fraction = cast(object | None, sensitivity_obj.get("volume_removed_fraction"))
    if isinstance(raw_fraction, (int, float)):
        return float(raw_fraction)
    return None


def _period_counts(events: list[CleanEvent]) -> dict[str, object]:
    return {
        "rows": len(events),
        "eligible_rows": sum(e.fit_eligible for e in events),
        "volume_cap_rows": sum((e.volume_m3 or 0) > MAX_PLAUSIBLE_VOLUME_M3 for e in events),
        "missing_volume_or_rainfall_rows": sum(
            e.volume_m3 is None or e.rainfall_mm is None for e in events
        ),
        "by_report_class": {
            cls: {
                "rows": sum(e.reporter_class == cls for e in events),
                "missing_volume_or_rainfall_rows": sum(
                    e.reporter_class == cls and (e.volume_m3 is None or e.rainfall_mm is None)
                    for e in events
                ),
                "eligible_rows": sum(e.reporter_class == cls and e.fit_eligible for e in events),
            }
            for cls in sorted({e.reporter_class for e in events})
        },
    }


def model_support_summary(events: list[CleanEvent]) -> dict[str, object]:
    """Use the same training fit rule as the pooled RMSE scorer."""
    eligible = [e for e in events if e.fit_eligible]
    models = fit_all_outfalls([e for e in eligible if e.year in {2022, 2023, 2024}])
    test = [e for e in eligible if e.year == 2025]
    paired = [e for e in test if e.volume_m3 is not None and e.rainfall_mm is not None]
    skipped = [e for e in paired if e.outfall_id not in models]
    return {
        "eligible_test_rows": len(test),
        "paired_rows": len(paired),
        "scored_rows": len(paired) - len(skipped),
        "excluded_reason_counts": {"no_training_model": len(skipped)},
        "excluded_counts_by_identifier": dict(
            sorted(Counter(e.outfall_id for e in skipped).items())
        ),
        "rule": "Five training+validation pairs and variable rain; same rows for baseline.",
    }


def threshold_support_summary(events: list[CleanEvent]) -> dict[str, object]:
    """Ledger for the exact eligible, known-rainfall cohort scored by the threshold rule."""
    train = [e for e in events if e.fit_eligible and e.year in {2022, 2023, 2024}]
    test = [e for e in events if e.fit_eligible and e.year == 2025 and e.rainfall_mm is not None]
    thresholds = {key: rainfall_threshold(train, key) for key in {e.outfall_id for e in test}}
    unsupported = [e for e in test if thresholds[e.outfall_id] is None]
    return {
        "unit": "report rows",
        "known_rainfall_test_rows": len(test),
        "supported_test_rows": len(test) - len(unsupported),
        "default_negative_test_rows": len(unsupported),
        "default_negative_identifier_count": len({e.outfall_id for e in unsupported}),
        "default_negative_rows_by_identifier": dict(
            sorted(Counter(e.outfall_id for e in unsupported).items())
        ),
        "rule": (
            "At or above training+validation 75th percentile; >=3 eligible rainfall "
            "observations required; otherwise default negative. Missing test rainfall "
            "excluded."
        ),
    }


def report_class_sensitivity(events: list[CleanEvent]) -> dict[str, object]:
    eligible = [e for e in events if e.fit_eligible and e.year in EVALUATION_YEARS]
    verified = [e for e in eligible if e.reporter_class == "Verified Data Report"]

    def rho(rows: list[CleanEvent]) -> float | None:
        return spearman_rank_correlation(
            baseline_count_scores([e for e in rows if e.year != 2025]),
            baseline_count_scores([e for e in rows if e.year == 2025]),
        )

    all_counts = baseline_count_scores(eligible)
    verified_counts = baseline_count_scores(verified)
    return {
        "eligible_counts_by_identifier": {
            key: {"all_classes": int(value), "verified_only": int(verified_counts.get(key, 0))}
            for key, value in sorted(all_counts.items())
        },
        "observed_spearman_all_classes": rho(eligible),
        "observed_spearman_verified_only": rho(verified),
        "note": "Sensitivity only; stages have not been reconciled into physical discharges.",
    }


def build_cohort_summary(
    records: list[CsoRecord],
    cleaned: list[CleanEvent],
    bootstrap_samples: int,
    seed: int,
) -> dict[str, object]:
    """Machine-readable cohort and exclusion ledger."""
    eligible = [event for event in cleaned if event.fit_eligible]
    eval_eligible = [event for event in eligible if event.year in EVALUATION_YEARS]
    test_2025 = [event for event in eligible if event.year == 2025]
    paired_test = [
        event
        for event in test_2025
        if event.volume_m3 is not None and event.rainfall_mm is not None
    ]
    exclusions = exclusion_reasons(records, cleaned)
    total_reported_volume = sum(_volume_m3(record) for record in records)
    eligible_volume = sum(event.volume_m3 or 0.0 for event in eval_eligible)
    dates = {
        year: sorted(
            {
                day.isoformat()
                for r in records
                if r.year == year
                if (day := r.incident_date or (r.start_time.date() if r.start_time else None))
                is not None
            }
        )
        for year in sorted({r.year for r in records})
    }
    return {
        "attribution": output_attribution(),
        "estimand": "report rows, not distinct discharges",
        "periods": {
            "full_feed": _period_counts(cleaned),
            "evaluation_2022_2025": _period_counts(
                [e for e in cleaned if e.year in EVALUATION_YEARS]
            ),
            "test_2025": _period_counts([e for e in cleaned if e.year == 2025]),
        },
        "identifier_categories": {
            "named": len(
                {e.outfall_id for e in eval_eligible if not e.outfall_id.startswith("UNKNOWN_")}
            ),
            "unknown_buckets": sorted(
                {e.outfall_id for e in eval_eligible if e.outfall_id.startswith("UNKNOWN_")}
            ),
        },
        "date_coverage_by_year": {
            str(year): {
                "rows": sum(r.year == year for r in records),
                "first_date": dates[year][0] if dates[year] else None,
                "last_date": dates[year][-1] if dates[year] else None,
            }
            for year in sorted({r.year for r in records})
        },
        "report_class_sensitivity": report_class_sensitivity(cleaned),
        "model_support": model_support_summary(cleaned),
        "threshold_support": threshold_support_summary(cleaned),
        "time_status_report_rows": dict(sorted(Counter(r.time_status for r in records).items())),
        "total_cso_rows": len(records),
        "fit_eligible_rows": len(eligible),
        "evaluation_year_eligible_rows": len(eval_eligible),
        "test_year_2025_eligible_rows": len(test_2025),
        "test_year_2025_paired_rows": len(paired_test),
        "total_reported_volume_m3": total_reported_volume,
        "evaluation_eligible_reported_volume_m3": eligible_volume,
        "volume_cap_m3": MAX_PLAUSIBLE_VOLUME_M3,
        "volume_cap_gallons": MAX_PLAUSIBLE_VOLUME_M3 / 0.00378541,
        "exclusions_by_reason": [asdict(item) for item in exclusions],
        "volume_cap_sensitivity": volume_cap_sensitivity(cleaned, bootstrap_samples, seed),
        "estimand_note": (
            "All reporting classes retained; multiple reports may describe one physical overflow. "
            "Descriptive rankings and headline evaluation use fit-eligible report rows only. "
            "Events above the volume cap are excluded from these totals, not relabelled."
        ),
    }


def write_cohort_summary(path: Path, payload: dict[str, object]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_quality_export(
    path: Path, flags: list[QualityFlag], events: list[CleanEvent] | None = None
) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "attribution": output_attribution(),
                "flag_counts": quality_counts(flags),
                "flag_definitions": {
                    kind: {"unit": unit, "definition": definition}
                    for kind, (unit, definition) in FLAG_DEFINITIONS.items()
                },
                "full_feed": {
                    "report_rows": len(events) if events is not None else None,
                    "identifiers": len({e.outfall_id for e in events})
                    if events is not None
                    else None,
                    "missing_volume_or_rainfall_report_rows": sum(
                        e.volume_m3 is None or e.rainfall_mm is None for e in events
                    )
                    if events is not None
                    else None,
                    "unique_quarantined_report_rows": sum(not e.fit_eligible for e in events)
                    if events is not None
                    else None,
                },
                "note": (
                    "Identifier missingness flags and report-row flags have separate units. "
                    "Report-row flags overlap; their sum is not the unique excluded-row count. "
                    "Missingness and unresolved clocks do not quarantine calendar-year analysis."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def summarize_from_records(
    records: list[CsoRecord],
    bootstrap_samples: int,
    seed: int,
) -> tuple[dict[str, object], list[QualityFlag]]:
    cleaned = clean_records(records)
    flags = flag_quality_issues(cleaned)
    summary = build_cohort_summary(records, cleaned, bootstrap_samples, seed)
    return summary, flags
