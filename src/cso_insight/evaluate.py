"""Hold-out evaluation and scoring."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import stats

from cso_insight.attribution import output_attribution
from cso_insight.baselines import (
    BASELINE_COUNT,
    BASELINE_MEAN_VOLUME,
    BASELINE_RAIN_THRESHOLD,
    baseline_count_scores,
    baseline_rainfall_threshold_predict,
    collect_paired_volume_predictions,
)
from cso_insight.clean import CleanEvent, fit_eligible_events
from cso_insight.config import MIN_PAIRED_OUTFALLS, TEST_YEAR, TRAIN_YEARS, VALIDATION_YEAR


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One evaluation metric with uncertainty."""

    name: str
    value: float
    ci_low: float
    ci_high: float
    n: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Full evaluation output."""

    train_years: list[int]
    validation_year: int
    test_year: int
    metrics: list[MetricResult]
    baselines: list[dict[str, str]]
    stop_rule_triggered: bool
    stop_rule_detail: str


def split_by_year(
    events: list[CleanEvent],
) -> tuple[list[CleanEvent], list[CleanEvent], list[CleanEvent]]:
    train = [e for e in events if e.year in TRAIN_YEARS]
    validation = [e for e in events if e.year == VALIDATION_YEAR]
    test = [e for e in events if e.year == TEST_YEAR]
    return train, validation, test


def spearman_rank_correlation(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Spearman rho over the union of keys; absent outfalls score zero."""
    if not a or not b:
        return None
    keys = sorted(set(a) | set(b))
    if len(keys) < 3:
        return None
    x = np.array([a.get(k, 0.0) for k in keys], dtype=float)
    y = np.array([b.get(k, 0.0) for k in keys], dtype=float)
    x_rank = stats.rankdata(x)
    y_rank = stats.rankdata(y)
    if float(np.std(x_rank)) == 0 or float(np.std(y_rank)) == 0:
        return None
    rho_matrix = np.corrcoef(x_rank, y_rank)
    return float(rho_matrix[0, 1])


def rmse(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return float("nan")
    arr_a = np.array(actual, dtype=float)
    arr_p = np.array(predicted, dtype=float)
    return float(np.sqrt(np.mean((arr_a - arr_p) ** 2)))


def bootstrap_percentile_ci(
    values: list[float],
    n_samples: int,
    seed: int,
) -> tuple[float, float, float]:
    """Bootstrap mean and 95% percentile interval from replicate statistics."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    samples = [
        float(np.mean(rng.choice(arr, size=len(arr), replace=True))) for _ in range(n_samples)
    ]
    low, high = np.percentile(samples, [2.5, 97.5])
    return float(np.mean(arr)), float(low), float(high)


def bootstrap_spearman_by_event_resample(
    train_val: list[CleanEvent],
    test_scores: dict[str, float],
    n_samples: int,
    seed: int,
) -> tuple[float | None, float, float, int]:
    """Event-level bootstrap: resample train+val events, correlate with fixed test counts."""
    if not train_val:
        return None, float("nan"), float("nan"), 0
    observed = spearman_rank_correlation(
        baseline_count_scores(train_val),
        test_scores,
    )
    n_outfalls = len(set(baseline_count_scores(train_val)) | set(test_scores))
    if observed is None:
        return None, float("nan"), float("nan"), n_outfalls

    rng = np.random.default_rng(seed)
    replicates: list[float] = []
    n_events = len(train_val)
    for _ in range(n_samples):
        indices = rng.integers(0, n_events, size=n_events)
        sample: list[CleanEvent] = [train_val[i] for i in indices]
        rho = spearman_rank_correlation(baseline_count_scores(sample), test_scores)
        if rho is not None:
            replicates.append(rho)
    if not replicates:
        return observed, float("nan"), float("nan"), n_outfalls
    low, high = np.percentile(replicates, [2.5, 97.5])
    return observed, float(low), float(high), n_outfalls


def bootstrap_pooled_rmse_by_event_resample(
    pairs: list[tuple[float, float]],
    n_samples: int,
    seed: int,
) -> tuple[float, float, float, int]:
    """Event-level bootstrap for pooled RMSE; n is the number of paired events."""
    if not pairs:
        return float("nan"), float("nan"), float("nan"), 0
    observed = rmse([a for a, _ in pairs], [p for _, p in pairs])
    rng = np.random.default_rng(seed)
    replicates: list[float] = []
    n_pairs = len(pairs)
    for _ in range(n_samples):
        indices = rng.integers(0, n_pairs, size=n_pairs)
        sample_pairs: list[tuple[float, float]] = [pairs[i] for i in indices]
        replicates.append(rmse([a for a, _ in sample_pairs], [p for _, p in sample_pairs]))
    low, high = np.percentile(replicates, [2.5, 97.5])
    return observed, float(low), float(high), n_pairs


def count_paired_outfalls(events: list[CleanEvent]) -> int:
    """Outfalls with at least one paired volume+rainfall observation."""
    outfalls: set[str] = set()
    for event in events:
        if event.fit_eligible and event.volume_m3 is not None and event.rainfall_mm is not None:
            outfalls.add(event.outfall_id)
    return len(outfalls)


def scoring_sanity_check() -> None:
    """Verify perfect system scores 1.0 and empty scores 0 for rank correlation helper."""
    perfect_a = {"a": 3.0, "b": 2.0, "c": 1.0}
    perfect_b = {"a": 30.0, "b": 20.0, "c": 10.0}
    rho = spearman_rank_correlation(perfect_a, perfect_b)
    if rho is None or abs(rho - 1.0) > 1e-9:
        msg = "Sanity check failed: perfect ranking should score 1.0"
        raise RuntimeError(msg)
    empty: dict[str, float] = {}
    if spearman_rank_correlation(perfect_a, empty) is not None:
        msg = "Sanity check failed: fewer than three outfalls should return None"
        raise RuntimeError(msg)


def _nan_metric(name: str) -> MetricResult:
    return MetricResult(name, float("nan"), float("nan"), float("nan"), 0)


def evaluate(
    events: list[CleanEvent],
    bootstrap_samples: int = 500,
    seed: int = 42,
) -> EvaluationReport:
    """Run preregistered hold-out evaluation."""
    scoring_sanity_check()
    eligible = fit_eligible_events(events)
    train, validation, test = split_by_year(eligible)
    train_val = train + validation

    stop = False
    stop_details: list[str] = []

    if len(test) < 100:
        stop = True
        stop_details.append(f"Test year {TEST_YEAR} has only {len(test)} events (<100 stop rule)")

    paired_outfalls = count_paired_outfalls(train_val)
    if paired_outfalls < MIN_PAIRED_OUTFALLS:
        stop = True
        stop_details.append(
            f"Only {paired_outfalls} outfalls have paired volume+rainfall in train+validation "
            f"(<{MIN_PAIRED_OUTFALLS} stop rule)"
        )

    if stop:
        return EvaluationReport(
            train_years=sorted(TRAIN_YEARS),
            validation_year=VALIDATION_YEAR,
            test_year=TEST_YEAR,
            metrics=[
                _nan_metric("spearman_trainval_vs_test_frequency"),
                _nan_metric("rmse_rainfall_model_m3"),
                _nan_metric("rmse_mean_volume_baseline_m3"),
                _nan_metric("rain_threshold_positive_rate"),
            ],
            baselines=[
                asdict(BASELINE_COUNT),
                asdict(BASELINE_MEAN_VOLUME),
                asdict(BASELINE_RAIN_THRESHOLD),
            ],
            stop_rule_triggered=True,
            stop_rule_detail="; ".join(stop_details),
        )

    test_scores = baseline_count_scores(test)
    rho, rho_low, rho_high, n_outfalls = bootstrap_spearman_by_event_resample(
        train_val,
        test_scores,
        bootstrap_samples,
        seed,
    )
    if rho is None:
        stop = True
        stop_details.append("Spearman correlation undefined (fewer than three outfalls)")

    model_pairs, baseline_pairs = collect_paired_volume_predictions(train_val, test)
    rmse_m, rmse_m_low, rmse_m_high, n_model = bootstrap_pooled_rmse_by_event_resample(
        model_pairs, bootstrap_samples, seed + 1
    )
    rmse_b, rmse_b_low, rmse_b_high, n_baseline = bootstrap_pooled_rmse_by_event_resample(
        baseline_pairs, bootstrap_samples, seed + 2
    )

    if not np.isfinite(rmse_m_low) or not np.isfinite(rmse_m_high):
        stop = True
        stop_details.append("Bootstrap RMSE CI undefined for rainfall model")
    if not np.isfinite(rmse_b_low) or not np.isfinite(rmse_b_high):
        stop = True
        stop_details.append("Bootstrap RMSE CI undefined for mean-volume baseline")

    threshold_hits: list[float] = []
    for outfall_id in sorted({e.outfall_id for e in test}):
        preds = baseline_rainfall_threshold_predict(train_val, test, outfall_id)
        threshold_hits.extend(preds)
    acc_mean, acc_low, acc_high = bootstrap_percentile_ci(
        threshold_hits, bootstrap_samples, seed + 3
    )

    metrics = [
        MetricResult(
            "spearman_trainval_vs_test_frequency",
            rho if rho is not None else float("nan"),
            rho_low,
            rho_high,
            n_outfalls,
        ),
        MetricResult(
            "rmse_rainfall_model_m3",
            rmse_m,
            rmse_m_low,
            rmse_m_high,
            n_model,
        ),
        MetricResult(
            "rmse_mean_volume_baseline_m3",
            rmse_b,
            rmse_b_low,
            rmse_b_high,
            n_baseline,
        ),
        MetricResult(
            "rain_threshold_positive_rate",
            acc_mean,
            acc_low,
            acc_high,
            len(threshold_hits),
        ),
    ]

    return EvaluationReport(
        train_years=sorted(TRAIN_YEARS),
        validation_year=VALIDATION_YEAR,
        test_year=TEST_YEAR,
        metrics=metrics,
        baselines=[
            asdict(BASELINE_COUNT),
            asdict(BASELINE_MEAN_VOLUME),
            asdict(BASELINE_RAIN_THRESHOLD),
        ],
        stop_rule_triggered=stop,
        stop_rule_detail="; ".join(stop_details),
    )


def write_evaluation(report: EvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "attribution": output_attribution(),
        "train_years": report.train_years,
        "validation_year": report.validation_year,
        "test_year": report.test_year,
        "metrics": [asdict(m) for m in report.metrics],
        "baselines": report.baselines,
        "stop_rule_triggered": report.stop_rule_triggered,
        "stop_rule_detail": report.stop_rule_detail,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
