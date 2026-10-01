"""HTML report generation with accessible markup."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import cast

from cso_insight.cohort import volume_removed_fraction
from cso_insight.evaluate import EvaluationReport
from cso_insight.quality import FLAG_DEFINITIONS, QualityFlag, quality_counts
from cso_insight.rank import OutfallRank


def _esc(text: str | float | int) -> str:
    return html.escape(str(text))


def threshold_support_text(cohort: dict[str, object]) -> str:
    """Keep support/rule wording identical in standalone and Markdown reports."""
    support = cast(dict[str, object], cohort.get("threshold_support", {}))
    return (
        "Rainfall threshold is positive at or above the eligible training+validation "
        "75th percentile (at least three rainfall observations per identifier). "
        f"Of {support.get('known_rainfall_test_rows', 'unavailable')} eligible known-rainfall "
        f"test report rows, {support.get('supported_test_rows', 'unavailable')} have threshold support; "
        f"{support.get('default_negative_test_rows', 'unavailable')} rows across "
        f"{support.get('default_negative_identifier_count', 'unavailable')} identifiers default "
        "negative because support is insufficient. These rows remain in the denominator; "
        "missing rainfall is excluded. This event-conditional fraction does not measure "
        "overflow detection or accuracy on non-event days."
    )


def render_html_report(
    *,
    title: str,
    summary: str,
    top_frequency: list[OutfallRank],
    top_volume: list[OutfallRank],
    quality_flags: list[QualityFlag],
    evaluation: EvaluationReport,
    figure_paths: dict[str, str],
    provenance: str,
    identifier_labels: dict[str, str] | None = None,
    cohort_summary: dict[str, object] | None = None,
) -> str:
    """Build an engineer-readable HTML report."""
    identifier_labels = identifier_labels or {}
    names = {
        "spearman_trainval_vs_test_frequency": "Report-row count stability (Spearman)",
        "rmse_rainfall_model_m3": "Rainfall-model pooled RMSE (m3)",
        "rmse_mean_volume_baseline_m3": "Mean-volume baseline pooled RMSE (m3)",
        "rain_threshold_positive_rate": "Rain-threshold positive fraction (reported rows only)",
    }
    metric_rows = "".join(
        f"<tr><td>{_esc(names.get(m.name, m.name))}</td><td>{m.value:.4f}</td>"
        f"<td>[{m.ci_low:.4f}, {m.ci_high:.4f}]</td><td>{m.n}</td></tr>"
        for m in evaluation.metrics
    )
    freq_rows = "".join(
        f"<tr><td>{r.rank}</td><td>{_esc(identifier_labels.get(r.outfall_id, r.outfall_id))}</td>"
        f"<td>{r.point_estimate:.1f}</td>"
        f"<td>[{r.ci_low:.1f}, {r.ci_high:.1f}]</td></tr>"
        for r in top_frequency[:15]
    )
    vol_rows = "".join(
        f"<tr><td>{r.rank}</td><td>{_esc(identifier_labels.get(r.outfall_id, r.outfall_id))}</td>"
        f"<td>{r.point_estimate:.1f}</td>"
        f"<td>[{r.ci_low:.1f}, {r.ci_high:.1f}]</td></tr>"
        for r in top_volume[:15]
    )
    counts = quality_counts(quality_flags)
    qa_tables = ""
    for unit in ("identifiers", "report rows"):
        rows = "".join(
            f"<tr><td>{_esc(kind)}</td><td>{counts.get(kind, 0)}</td><td>{_esc(definition)}</td></tr>"
            for kind, (flag_unit, definition) in FLAG_DEFINITIONS.items()
            if flag_unit == unit
        )
        qa_tables += (
            f"<h3>QA: {unit}</h3><table><thead><tr><th scope='col'>Flag</th>"
            f"<th scope='col'>Count ({unit})</th><th scope='col'>Definition</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    cohort = cohort_summary or {}
    periods = cast(dict[str, dict[str, object]], cohort.get("periods", {}))
    full = periods.get("full_feed", {})
    qa_note = (
        f"Full-feed denominator: {full.get('rows', 'unavailable')} report rows; "
        f"{full.get('missing_volume_or_rainfall_rows', 'unavailable')} missing volume or rainfall. "
        f"Unique quarantined report rows: {cast(int, full['rows']) - cast(int, full['eligible_rows']) if full else 'unavailable'}. "
        "Report-row flags overlap; their sum is not a count of unique excluded rows. "
        "Missingness and unresolved clocks do not quarantine calendar-year analysis."
    )
    threshold_note = threshold_support_text(cohort)
    captions = {
        "top_frequency": "Observed report-row counts with conditional 95% intervals",
        "top_volume": "Observed reported volume totals (m3) with conditional 95% intervals",
    }
    figures = "".join(
        f'<figure><img src="{_esc(path)}" alt="{_esc(captions.get(name, name))} chart"/>'
        f"<figcaption>{_esc(captions.get(name, name))}. {_esc(provenance)}</figcaption></figure>"
        for name, path in figure_paths.items()
    )
    stop_banner = ""
    if evaluation.stop_rule_triggered:
        stop_banner = f'<aside role="note"><p>Stop rule triggered: {_esc(evaluation.stop_rule_detail)}</p></aside>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{_esc(title)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    table {{ border-collapse: collapse; width: 100%; display: block; overflow-x: auto; margin-bottom: 1.5rem; }}
    th, td {{ border: 1px solid #444; padding: 0.4rem 0.6rem; text-align: left; }}
    th {{ background: #eee; }}
    figure {{ margin: 1rem 0; }}
    img {{ max-width: 100%; height: auto; }}
    a:focus-visible, button:focus-visible {{ outline: 2px solid #005fcc; outline-offset: 2px; }}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(title)}</h1>
    <p>{_esc(summary)}</p>
  </header>
  <main>
    {stop_banner}
    <aside role="note"><p>Frozen analysis plan, amended retrospectively. The hash verifies
    content integrity and does not establish chronology. The first repository commit already
    included results; pre-result registration is unverified. 2024 is pooled with 2022-2023
    for fitting; 2025 is held out. See
    <a href="../docs/PREREGISTRATION_STATUS.md">plan status and recorded amendments</a>.</p></aside>
    <section aria-labelledby="metrics-heading">
      <h2 id="metrics-heading">Hold-out evaluation metrics (test year 2025)</h2>
      <p>Intervals are conditional event-bootstrap ranges. Spearman resamples train+validation
      events while holding 2025 counts fixed. RMSE bootstrap resamples paired test events
      without refitting models. They omit storm dependence, fitting uncertainty and
      measurement error.</p>
      <p>The mean-volume baseline RMSE is lower than the rainfall model on the same paired
      events. This does not demonstrate generalization advantage for the rainfall model.</p>
      <p>{_esc(threshold_note)}</p>
      <table>
        <thead><tr><th scope="col">Metric</th><th scope="col">Value</th>
        <th scope="col">95% interval</th><th scope="col">N</th></tr></thead>
        <tbody>{metric_rows}</tbody>
      </table>
    </section>
    <section aria-labelledby="freq-heading">
      <h2 id="freq-heading">Descriptive ranking: report row count (2022-2025)</h2>
      <p>Point estimates are observed totals. Intervals are on report-count totals, not rank positions. Totals exclude events
      quarantined by plausibility caps (including volume above 10 million US gallons).
      See results/cohort_summary.json for exclusion counts and sensitivity.</p>
      <table>
        <thead><tr><th scope="col">Rank</th><th scope="col">Outfall</th>
        <th scope="col">Observed report rows</th><th scope="col">95% interval on count</th></tr></thead>
        <tbody>{freq_rows}</tbody>
      </table>
    </section>
    <section aria-labelledby="vol-heading">
      <h2 id="vol-heading">Descriptive ranking: observed reported volume (2022-2025)</h2>
      <p>Intervals are on volume totals, not rank positions. Totals exclude quarantined
      high-volume notifications. Missing volume contributes zero.</p>
      <table>
        <thead><tr><th scope="col">Rank</th><th scope="col">Outfall</th>
        <th scope="col">Observed reported volume (m3)</th><th scope="col">95% interval on volume</th></tr></thead>
        <tbody>{vol_rows}</tbody>
      </table>
    </section>
    <section aria-labelledby="quality-heading">
      <h2 id="quality-heading">Aggregate quality flag counts (qa_flags.json)</h2>
      <p>{_esc(qa_note)}</p>
      {qa_tables}
    </section>
    <section aria-labelledby="figures-heading">
      <h2 id="figures-heading">Figures</h2>
      {figures}
    </section>
  </main>
  <footer><p>{_esc(provenance)} Generated by cso-insight (Apache-2.0). Documentation CC BY 4.0.</p></footer>
</body>
</html>"""


def write_html_report(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def write_results_md(
    path: Path,
    evaluation: EvaluationReport,
    hardware: str,
    command: str,
    cohort_summary: dict[str, object] | None = None,
) -> None:
    spearman = next(
        (m for m in evaluation.metrics if m.name == "spearman_trainval_vs_test_frequency"),
        None,
    )
    rmse_model = next((m for m in evaluation.metrics if m.name == "rmse_rainfall_model_m3"), None)
    rmse_base = next(
        (m for m in evaluation.metrics if m.name == "rmse_mean_volume_baseline_m3"),
        None,
    )
    volume_note = ""
    if cohort_summary is not None:
        fraction = volume_removed_fraction(cohort_summary)
        if fraction is not None:
            volume_note = (
                "Descriptive volume totals exclude notifications above a 10 million gallon "
                f"plausibility cap; cohort_summary.json reports a "
                f"{fraction * 100:.1f}% volume reduction from that filter."
            )
    spearman_text = (
        f"Spearman {spearman.value:.4f}"
        if spearman and not evaluation.stop_rule_triggered
        else "Spearman unavailable"
    )
    rmse_text = ""
    if (
        rmse_model
        and rmse_base
        and not evaluation.stop_rule_triggered
        and not math.isnan(rmse_model.value)
        and not math.isnan(rmse_base.value)
    ):
        rmse_text = (
            f" the simple mean-volume baseline beats the log1p rainfall model on pooled RMSE "
            f"({rmse_base.value:.1f} vs {rmse_model.value:.1f} m3)."
        )
    summary_parts = [
        "Massachusetts EEA CSO notifications (2022 to 2025 hold-out on 2025) show stable",
        f"report-row counts across identifiers ({spearman_text}) but{rmse_text or ' baseline comparisons are unavailable.'}",
    ]
    if volume_note:
        summary_parts.append(volume_note.strip())
    else:
        summary_parts.append(
            "Descriptive volume totals exclude notifications above a declared plausibility cap."
        )
    lines = [
        "# Results",
        "",
        "## Case study summary",
        "",
        *summary_parts,
        "",
        "## Headline metrics",
        "",
        "Hold-out test year 2025. Spearman n counts identifiers, including UNKNOWN permittee buckets.",
        "RMSE n counts model-scorable paired report rows; multiple reports may describe one discharge.",
        threshold_support_text(cohort_summary or {}),
        "Intervals are conditional event-bootstrap ranges, not storm-blocked inference.",
        "",
    ]
    for metric in evaluation.metrics:
        lines.append(
            f"- **{metric.name}**: {metric.value:.4f} "
            f"(95% CI [{metric.ci_low:.4f}, {metric.ci_high:.4f}], n={metric.n})"
        )
    if cohort_summary is not None:
        periods = cast(dict[str, dict[str, object]], cohort_summary.get("periods", {}))
        full = periods.get("full_feed", {})
        period = periods.get("evaluation_2022_2025", {})
        support = cast(dict[str, object], cohort_summary.get("model_support", {}))
        lines.extend(
            [
                "",
                "## Cohort flow",
                "",
                "| Stage | Report rows |",
                "|---|---:|",
                f"| CSO feed (all classes) | {full.get('rows', 0)} |",
                f"| Eligible across full feed | {full.get('eligible_rows', 0)} |",
                f"| Eligible 2022-2025 | {period.get('eligible_rows', 0)} |",
                f"| Eligible 2025 | {support.get('eligible_test_rows', 0)} |",
                f"| Eligible paired 2025 | {support.get('paired_rows', 0)} |",
                f"| Model-scorable paired 2025 (same rows for baseline) | {support.get('scored_rows', 0)} |",
                "",
                "| Reporting class (full feed) | Rows | Missing volume or rain |",
                "|---|---:|---:|",
            ]
        )
        classes = cast(dict[str, dict[str, object]], full.get("by_report_class", {}))
        for name, values in classes.items():
            lines.append(
                f"| {name} | {values['rows']} | {values['missing_volume_or_rainfall_rows']} |"
            )
        lines.extend(
            [
                "",
                "Reporting stages are retained separately; the estimand is report rows, not distinct discharges.",
                f"Volume-cap exclusions: {period.get('volume_cap_rows', 0)} evaluation-period reports; "
                f"{full.get('volume_cap_rows', 0)} across the full feed.",
                "The volume-cap sensitivity uses 2022-2025 volume after other eligibility filters,",
                "relative to the same cohort with the volume cap relaxed. The cohort ledger records",
                "unknown identifier buckets and model-support exclusions by identifier.",
                "",
            ]
        )
    if cohort_summary is not None:
        sensitivity = cast(dict[str, object], cohort_summary.get("volume_cap_sensitivity", {}))
        capped = cast(list[dict[str, object]], sensitivity.get("top5_volume_outfalls_with_cap", []))
        uncapped = cast(
            list[dict[str, object]], sensitivity.get("top5_volume_outfalls_without_cap", [])
        )
        lines.extend(
            [
                "## Volume-cap sensitivity",
                "",
                "| Observed volume rank | With cap | Without volume cap |",
                "|---|---|---|",
            ]
        )
        for i, (left, right) in enumerate(zip(capped, uncapped, strict=True), start=1):
            lines.append(f"| {i} | {left['outfall_id']} | {right['outfall_id']} |")
        lines.extend(
            [
                "",
                "Removing high-volume reports changes priorities; the uncapped leader can disappear",
                "from the capped top five. These filters flag suspect values and do not verify errors.",
            ]
        )
    if evaluation.stop_rule_triggered:
        lines.extend(["", f"**Stop rule**: {evaluation.stop_rule_detail}"])
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            f"```bash\n{command}\n```",
            "",
            f"Hardware: {hardware}",
            "",
            "## Baselines",
            "",
        ]
    )
    for baseline in evaluation.baselines:
        lines.append(f"- {baseline['name']}: {baseline['command']} ({baseline['version']})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
