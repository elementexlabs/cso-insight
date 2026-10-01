# Preregistration: CSO Insight evaluation

Frozen: 2026-10-01 (before any pipeline results)

## Question

How well does a rainfall-normalized per-outfall model rank CSO outfalls and predict overflow volume compared to simple baselines on hold-out years?

## Data

- **Primary dataset:** Massachusetts EEA combined sewer overflow notifications CSV (`https://openamend.org/data/EEADP_CSO.csv`).
- **Events included:** Rows where `eventType` contains "CSO".
- **Rainfall:** Co-reported `rainfallData` field (inches, converted to mm). No model-assisted relabelling.
- **Volume:** Co-reported `volumnOfEvent` field (US gallons, converted to m3).

## Splits (fixed before results)

| Split | Years | Purpose |
|-------|-------|---------|
| Train | 2022, 2023 | Fit rainfall-response models and ranking |
| Validation | 2024 | Model selection (not used for final headline metrics) |
| Test | 2025 | Headline hold-out metrics |

Rows from 2026 are excluded from evaluation splits (partial year).

## Methods

1. Clean and normalize units (gallons to m3, inches to mm).
2. Align events where both volume and rainfall are present.
3. Fit log-linear rainfall response per outfall (minimum 5 paired observations).
4. Rank outfalls by bootstrap resampling of events (500 samples, seed 42) for frequency and total volume.
5. Flag data quality: >50% missing volume or rainfall per outfall, negative values, duration >72 h.

## Baselines (official simple rules)

| ID | Rule | Implementation |
|----|------|----------------|
| B1 | Event count ranking | Count raw events per outfall on test year |
| B2 | Mean volume | Predict constant mean volume per outfall from train+validation |
| B3 | Rainfall threshold | Predict overflow when rainfall exceeds training 75th percentile for that outfall |

## Metrics

| Metric | Definition | Unit |
|--------|------------|------|
| `spearman_trainval_vs_test_frequency` | Spearman correlation between train+validation frequency ranks and test-year counts | dimensionless |
| `rmse_rainfall_model_m3` | RMSE of rainfall-response volume predictions on test events with paired data | m3 |
| `rmse_mean_volume_baseline_m3` | RMSE of B2 on same test events | m3 |
| `rain_threshold_positive_rate` | Fraction of B3 positive predictions on test events | proportion |

All metrics reported with bootstrap 95% intervals (500 resamples, seed 42).

## Scoring integrity tests

- Perfect rank agreement must score Spearman rho = 1.0.
- Empty comparison must return no score.

## Stop rules

1. If test-year events < 100, stop and report (do not claim generalization).
2. If fewer than 10 outfalls have paired volume+rainfall in train+validation, stop.
3. If bootstrap RMSE CIs are undefined (NaN), stop.

## Uncertainty

Bootstrap resampling unit = **individual CSO events** (not outfalls alone), preserving per-outfall structure within each resample.

## What we will not do

- Tune splits after seeing test metrics.
- Label data with this package's parsers and call it manual ground truth.
- Compare model rerun to itself as inter-rater agreement.

## Expected outputs

- `results/evaluation.json`
- `results/report.html`
- `RESULTS.md`
- Figures under `results/figures/`

## Hardware

Apple M3 Ultra, local execution only.
