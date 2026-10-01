# CSO Insight documentation

**Buyer decision: Are these public overflow reports reliable enough to guide outfall priorities or justify a rainfall model?**

This work sample follows intake, QA, cohort accounting and baseline evaluation. Better reporting and local validation come before deployment.

## Case study summary

Massachusetts EEA CSO notifications (Archive of Massachusetts Environmental Data feed) with 2025 held out. Report-row counts across identifiers are stable; reporting stages are not reconciled into physical discharges. The mean-volume baseline beats the rainfall model on pooled RMSE. Descriptive totals exclude notifications above a 10 million gallon plausibility cap.

Regenerate metrics and open the HTML report:

```bash
cso-insight run --root .
open results/report.html
```

## Quick links

- [Quick start](quickstart.md)
- [Technical report](technical-report.md)
- [Data manifest](data-manifest.md)
- [Results](results.md)
- [Frozen analysis plan, amended retrospectively](PREREGISTRATION_STATUS.md)

## What it does

1. Downloads public CSO notification CSVs (hash-pinned snapshot).
2. Aligns co-reported rainfall and volume.
3. Flags implausible values and quarantines them from fitting.
4. Fits per-outfall log1p rainfall-response models.
5. Produces descriptive rankings with bootstrap intervals on counts and volumes.
6. Exports cohort and aggregate QA ledgers.
7. Evaluates amended hold-out baselines on 2025.

Evaluation note: the frozen analysis plan was amended retrospectively; pre-result registration is unverified. Rainfall-normalized ranking was not evaluated.
