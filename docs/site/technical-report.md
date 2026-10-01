# Technical report: CSO Insight

## Abstract

We present an open Python pipeline that ingests public combined sewer overflow (CSO) report-row data, aligns co-reported rainfall, flags implausible values, fits per-outfall log1p rainfall-response models, ranks outfalls descriptively with bootstrap uncertainty on counts and volumes, and evaluates amended hold-out baselines. The frozen analysis plan is amended retrospectively; pre-result registration is unverified, and results were seen before the 2026-10-01 amendment clarified estimands. Rainfall-normalized outfall ranking was not evaluated.

## 1. Problem

Combined sewer systems discharge diluted wastewater during wet weather. Utilities must monitor overflows, report trends, and prioritize outfalls for intervention. Metro Vancouver publishes a real-time overflow map; this demonstration uses Massachusetts data and makes no claim about other local data routes. Analysts need reproducible methods that work on whatever open data exists.

## 2. Related work

- **EPA SWMM** ([epa.gov](https://www.epa.gov/water-research/storm-water-management-model-swmm)): physics-based simulation requiring local network models.
- **PySWMM** ([JOSS 10.21105/joss.02292](https://joss.theoj.org/papers/10.21105/joss.02292)): Python interface to SWMM engines.
- **McGrath et al. (2019)**: network topology and rainfall controls on CSO variability, [doi:10.1029/2019WR025336](https://doi.org/10.1029/2019WR025336).
- **AMEND dashboard** ([openamend.org/dashboard.html](https://openamend.org/dashboard.html)): CSV-backed discharge analysis, external rainfall alignment and reporting-quality views on the Massachusetts feed.
- **Regulatory reporting**: EPA ECHO sewer overflow CSVs (partial US coverage).

AMEND already has Python tests and automated chart regeneration; see its [analysis script](https://github.com/nesanders/MAenvironmentaldata/blob/b0a5c729abb41ba77b24ec0f6df835eee0a5887f/analysis/EEA_DP_CSO_map.py), [tests](https://github.com/nesanders/MAenvironmentaldata/tree/b0a5c729abb41ba77b24ec0f6df835eee0a5887f/tests) and [workflows](https://github.com/nesanders/MAenvironmentaldata/tree/b0a5c729abb41ba77b24ec0f6df835eee0a5887f/.github/workflows) at immutable commit `b0a5c729abb41ba77b24ec0f6df835eee0a5887f` (identified by the independent round 4 review; links pinned here). This package performs no external meteorological join.

This package integrates notification ingestion, QA quarantine, descriptive ranking, cohort accounting and amended hold-out evaluation in one reproducible command. AMEND and this package overlap in report aggregation and plotting. This library complements AMEND's analysis with its packaged typed API, explicit cohort ledger and amended evaluation; hydraulic simulation remains a separate task.

## 3. Data

**Primary:** Massachusetts EEA CSO notifications (`https://openamend.org/data/EEADP_CSO.csv`). See `docs/DATA_MANIFEST.md`.

| Statistic | Value |
|-----------|-------|
| CSO rows | 16,720 |
| Distinct outfall IDs | 171 (169 named plus two synthetic UNKNOWN buckets) |
| Evaluation years | 2022 to 2025 (2026 partial, excluded; 2022 begins July 2) |
| Rows with volume and rainfall (eligible) | see `results/cohort_summary.json` |

Rainfall is co-reported in inches (`rainfallData`); volume in US gallons (`volumnOfEvent`). These are utility-reported fields, not independently verified labels. Both notification and verified reporting stages are retained; matching stages are not reconciled into distinct discharges. All count results concern report rows. Missingness is structured by reporting stage: 8,058 of 8,059 notification-stage rows lack one or both measurements; no verified-stage rows do in this snapshot. The ledger exports period/class denominators, date ranges, and verified-only count sensitivity. UNKNOWN identifiers pool missing outfall IDs by permittee; they are not physical outfalls.

**Metro Vancouver:** Real-time map only via the route reviewed; annual PDF tables. Documented as regional context; not used as primary data.

## 4. Methods

1. **Cleaning:** Convert gallons to m3, inches to mm; parse treatment categories explicitly. Honor AM/PM (12 AM midnight, 12 PM noon); valid unmarked clocks use 24-hour time. Consistent 13-23 PM and 0 AM retain their 24-hour meaning. Ambiguous 0 PM, conflicting 13-23 AM, missing/malformed clocks and unknown markers remain null and are flagged; the separate date is retained. No time-zone or weather-time join is asserted.
2. **Quarantine:** Exclude events with rainfall above 254 mm (10 inches), volume above 37,854 m3 (10 million US gallons), negative values, or duration above 72 h from fitting and headline descriptive totals. These are declared plausibility filters, not verified error labels. Exclusion counts and volume sensitivity are exported to `results/cohort_summary.json`.
3. **Alignment:** Retain eligible events with both volume and rainfall for modelling.
4. **Rainfall response:** Per outfall, fit log1p(volume) ~ rainfall via OLS (minimum 5 pairs).
5. **Descriptive ranking:** Bootstrap resample events (500 draws, seed 42); rank by observed report-row count and observed reported volume with intervals on those metrics (not rank positions, not rainfall-normalized).
6. **Quality flags:** Missingness, implausible values, quarantine status; aggregate flag counts in `results/qa_flags.json` with a unit and definition for every flag. Missingness counts are identifiers with >50% missing within-identifier measurements (78 for each measurement); other flags count report rows. Separate HTML tables prevent mixing units. The full feed contains 16,720 report rows, with 8,058 missing volume or rainfall and 176 unique quarantined rows. Report-row flags overlap; their sum is not a unique exclusion count. Individual identifiers and measurements are withheld.
7. **Evaluation:** Train 2022 to 2023, validation 2024 (pooled with train for fitting), test 2025. Pooled RMSE on identical model-scorable paired report rows; Spearman over outfall union with event-level bootstrap resampling train+validation events while holding 2025 counts fixed.

## 5. Results

See `RESULTS.md` (regenerated by `cso-insight run --root .`).

The mean-volume baseline achieves lower pooled RMSE than the log1p rainfall model on held-out paired events. Spearman correlation compares raw event counts, not rainfall-normalized ranks. Rain threshold is an event-conditional positive rate among events with known rainfall; positive means at or above the 2022-2024 training 75th percentile, with at least three eligible training rainfall observations. Of 1,643 eligible known-rainfall test rows, 1,635 are supported; eight rows across five identifiers default negative and stay in the denominator. Missing test rainfall is excluded. Five rows equal the threshold; the fraction is 395/1,643. It does not measure overflow detection or accuracy on non-event days.

Scoring covers 1,625 of 1,643 eligible paired test reports and 1,625 of 3,075 eligible test reports. Eighteen paired reports across ten IDs have no supported training model. Support exclusions are exported; the baseline is evaluated on the same subset. Minimum five pairs and variable training rainfall are required.

## 6. Limitations

- Not Metro Vancouver data; transfer requires local validation.
- Missing measurements on many rows; descriptive totals reflect reporting coverage.
- Volume cap excludes 156 evaluation-period reports (159 full feed), removing 32.1% of 2022-2025 reported volume after other eligibility rules relative to the same cohort without the volume cap. It can change top-five volume priorities; see capped/uncapped ranks in the cohort ledger.
- Log1p-linear model ignores antecedent moisture and system hydraulics; inverse transform can extrapolate beyond observed volumes.
- Bootstrap intervals treat events as independent; storm-date clustering is not modelled.
- Intervals omit fitting uncertainty and measurement error.
- Notification timestamps may lag actual overflow start.
- 2026 partial year excluded but present in raw feed.
- Preregistration was amended after results were seen.

## 7. Reproducibility

```bash
pip install -r requirements-lock.txt
pip install --no-deps -e .
./scripts/download_data.sh
cso-insight run --root .
```

Preregistration SHA-256: see `docs/PREREGISTRATION.sha256`. Amendment after review: `docs/PREREGISTRATION_AMENDMENT_2026-10-01.md`.

## References

1. McGrath, G., et al. (2019). Network Topology and Rainfall Controls on the Variability of Combined Sewer Overflows and Loads. *Water Resources Research*. https://doi.org/10.1029/2019WR025336
2. EPA SWMM. https://www.epa.gov/water-research/storm-water-management-model-swmm
3. McDonnell et al. (2020). PySWMM. https://doi.org/10.21105/joss.02292
4. Massachusetts EEA CSO feed. https://openamend.org/data/EEADP_CSO.csv
5. AMEND dashboard. https://openamend.org/dashboard.html
6. Metro Vancouver sewer overflow map. https://metrovancouver.org/services/liquid-waste/real-time-sewer-overflow-map

## Regional validation checklist

Before applying these methods to a regional agency: obtain a permitted local feed;
define reporting-stage reconciliation with the data owner; verify units, timestamps,
unknown identifiers and completeness; predeclare filters and storm-level validation;
compare against a simple baseline on the same supported cohort; and validate the
actual decision with utility engineers. This work supplies no firm client reference,
Metro Vancouver validation, or operational forecast.

The frozen plan hash verifies content integrity and does not establish chronology.
See [frozen analysis plan, amended retrospectively](PREREGISTRATION_STATUS.md) for the default wrapper and recorded amendments. Original figure design and
text are CC BY 4.0; factual source aggregates retain the upstream rights boundary.
