"""Rainfall-to-overflow response models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cso_insight.clean import CleanEvent


@dataclass(frozen=True, slots=True)
class RainfallResponseModel:
    """Simple log1p-linear rainfall response fit for one outfall."""

    outfall_id: str
    intercept: float
    rainfall_slope: float
    n_obs: int
    r_squared: float | None


def fit_rainfall_response(
    events: list[CleanEvent], outfall_id: str
) -> RainfallResponseModel | None:
    """Fit log1p(volume) ~ rainfall for eligible events with both measurements."""
    subset = [
        e
        for e in events
        if e.outfall_id == outfall_id
        and e.fit_eligible
        and e.volume_m3 is not None
        and e.rainfall_mm is not None
    ]
    if len(subset) < 5:
        return None
    x = np.array([e.rainfall_mm for e in subset], dtype=float)
    y = np.log1p(np.array([e.volume_m3 for e in subset], dtype=float))
    if float(np.std(x)) < 1e-9:
        return None
    slope, intercept = np.polyfit(x, y, deg=1)
    r_matrix = np.corrcoef(x, y)
    r_value = float(r_matrix[0, 1])
    r_squared = float(r_value * r_value) if np.isfinite(r_value) else None
    return RainfallResponseModel(
        outfall_id=outfall_id,
        intercept=float(intercept),
        rainfall_slope=float(slope),
        n_obs=len(subset),
        r_squared=r_squared,
    )


def predict_volume(model: RainfallResponseModel, rainfall_mm: float) -> float:
    """Predict overflow volume (m3) from rainfall."""
    log_vol = model.intercept + model.rainfall_slope * rainfall_mm
    return float(np.expm1(log_vol))


def fit_all_outfalls(events: list[CleanEvent]) -> dict[str, RainfallResponseModel]:
    """Fit models for every outfall with enough eligible data."""
    outfalls = sorted({e.outfall_id for e in events if e.fit_eligible})
    models: dict[str, RainfallResponseModel] = {}
    for outfall_id in outfalls:
        model = fit_rainfall_response(events, outfall_id)
        if model is not None:
            models[outfall_id] = model
    return models
