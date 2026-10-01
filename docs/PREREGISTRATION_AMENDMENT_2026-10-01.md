# Preregistration amendment (2026-10-01)

**Status:** Results had already been computed before this amendment was written.

## What changed

1. **RMSE estimand:** Clarified that both the rainfall model and mean-volume baseline are scored on the **same pooled test events** with paired volume and rainfall. RMSE is **pooled across events** (not macro-averaged per outfall). Bootstrap resampling unit remains individual CSO events.

2. **Spearman estimand:** Clarified that the point estimate is the **direct observed** Spearman correlation over the union of outfalls (absent outfalls score zero). Bootstrap resamples **train+validation events** to quantify ranking uncertainty.

3. **Plausibility quarantine:** Events with rainfall above 254 mm (10 inches), volume above 37,854 m3 (10 million US gallons), or other implausible values are excluded from fitting and headline descriptive totals under documented rules added after data-quality review. Exclusion counts and sensitivity are exported to `results/cohort_summary.json`.

4. **Rain threshold metric:** Missing test rainfall is excluded (unknown), not imputed as zero.

## Why

Independent publication review found the original implementation averaged per-outfall RMSE on different cohorts, double-bootstrapped Spearman replicates, and did not enforce stop rules.

## Frozen preregistration

The original `docs/PREREGISTRATION.md` and its SHA-256 remain unchanged. This amendment supplements it.
