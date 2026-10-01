"""One-command pipeline orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from dataclasses import asdict
from pathlib import Path
from typing import cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cso_insight.align import align_events
from cso_insight.attribution import output_attribution
from cso_insight.clean import clean_records, fit_eligible_events
from cso_insight.cohort import build_cohort_summary, write_cohort_summary, write_quality_export
from cso_insight.config import EVALUATION_YEARS, PipelineConfig
from cso_insight.download import download_file, verify_file_sha256
from cso_insight.evaluate import evaluate, write_evaluation
from cso_insight.ingest import load_cso_records
from cso_insight.model import RainfallResponseModel, fit_all_outfalls
from cso_insight.publication import generate_site
from cso_insight.quality import flag_quality_issues
from cso_insight.rank import OutfallRank, rank_outfalls
from cso_insight.report import render_html_report, write_html_report, write_results_md


def verify_preregistration_hash(root: Path) -> str:
    """Verify frozen preregistration digest; return computed hash."""
    prereg_path = root / "docs" / "PREREGISTRATION.md"
    digest = hashlib.sha256(prereg_path.read_bytes()).hexdigest()
    expected_path = root / "docs" / "PREREGISTRATION.sha256"
    if expected_path.exists():
        expected = expected_path.read_text(encoding="utf-8").strip()
        if digest != expected:
            msg = f"Preregistration hash mismatch: {digest} != {expected}"
            raise ValueError(msg)
    return digest


def _model_to_json(model: RainfallResponseModel) -> dict[str, object]:
    payload = asdict(model)
    r_sq = payload.get("r_squared")
    if r_sq is None or (isinstance(r_sq, float) and not math.isfinite(r_sq)):
        payload["r_squared"] = None
    return payload


def _write_figures(
    results_dir: Path,
    aligned_rain: list[float],
    aligned_vol: list[float],
    freq_ranks: list[OutfallRank],
    vol_ranks: list[OutfallRank],
    labels: dict[str, str] | None = None,
) -> dict[str, str]:
    figures_dir = results_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    labels = labels or {}

    # Individual event-pair display is withheld from public outputs.
    scatter_path = figures_dir / "rainfall_volume_scatter.png"
    if scatter_path.exists():
        scatter_path.unlink()
    metadata = {"Description": json.dumps(output_attribution(), sort_keys=True)}

    fig, ax = plt.subplots(figsize=(8, 5))
    top = freq_ranks[:12]
    ax.barh(
        [labels.get(r.outfall_id, r.outfall_id) for r in reversed(top)],
        [r.point_estimate for r in reversed(top)],
        xerr=[
            [max(0, r.point_estimate - r.ci_low) for r in reversed(top)],
            [max(0, r.ci_high - r.point_estimate) for r in reversed(top)],
        ],
    )
    ax.set_xlabel("Observed eligible report row count")
    ax.set_title("Descriptive ranking: report row counts by identifier (2022-2025)")
    freq_path = figures_dir / "top_outfalls_frequency.png"
    fig.text(
        0.01,
        0.01,
        "MassDEP via AMEND; 2022-2025; caps applied; conditional 95% intervals. CC BY design.",
        fontsize=6,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(freq_path, dpi=120, metadata=metadata)
    plt.close(fig)
    paths["top_frequency"] = f"figures/{freq_path.name}"

    fig, ax = plt.subplots(figsize=(8, 5))
    top_v = vol_ranks[:12]
    ax.barh(
        [labels.get(r.outfall_id, r.outfall_id) for r in reversed(top_v)],
        [r.point_estimate for r in reversed(top_v)],
        xerr=[
            [max(0, r.point_estimate - r.ci_low) for r in reversed(top_v)],
            [max(0, r.ci_high - r.point_estimate) for r in reversed(top_v)],
        ],
    )
    ax.set_xlabel("Observed reported volume total (m3)")
    ax.set_title("Descriptive ranking: top outfalls by reported volume (2022-2025)")
    vol_path = figures_dir / "top_outfalls_volume.png"
    fig.text(
        0.01,
        0.01,
        "MassDEP via AMEND; 2022-2025; caps applied; conditional 95% intervals. CC BY design.",
        fontsize=6,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(vol_path, dpi=120, metadata=metadata)
    plt.close(fig)
    paths["top_volume"] = f"figures/{vol_path.name}"

    return paths


def run_pipeline(config: PipelineConfig, skip_download: bool = False) -> dict[str, float]:
    """Execute the full analysis pipeline; return timing stats."""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    verify_preregistration_hash(config.root)

    config.raw_dir.mkdir(parents=True, exist_ok=True)
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    config.results_dir.mkdir(parents=True, exist_ok=True)

    raw_path = config.raw_dir / "ma_eea_cso.csv"
    if skip_download and raw_path.exists():
        if config.expected_download_sha256 is not None and not verify_file_sha256(
            raw_path, config.expected_download_sha256
        ):
            msg = "Cached raw file failed SHA-256 integrity check"
            raise ValueError(msg)
        timings["download_s"] = 0.0
    else:
        t_dl = time.perf_counter()
        digest = download_file(
            config.ma_cso_url,
            raw_path,
            expected_sha256=config.expected_download_sha256,
        )
        timings["download_s"] = time.perf_counter() - t_dl
        (config.processed_dir / "download_sha256.txt").write_text(digest + "\n", encoding="utf-8")

    t_ingest = time.perf_counter()
    records = load_cso_records(raw_path)
    cleaned = clean_records(records)
    eligible = fit_eligible_events(cleaned)
    descriptive = [e for e in eligible if e.year in EVALUATION_YEARS]
    timings["ingest_s"] = time.perf_counter() - t_ingest

    t_analysis = time.perf_counter()
    aligned = align_events(descriptive)
    quality = flag_quality_issues(cleaned)
    models = fit_all_outfalls(descriptive)
    freq_ranks = rank_outfalls(
        descriptive, "frequency", config.bootstrap_samples, config.random_seed
    )
    vol_ranks = rank_outfalls(descriptive, "volume", config.bootstrap_samples, config.random_seed)
    evaluation = evaluate(cleaned, config.bootstrap_samples, config.random_seed)
    cohort_summary = build_cohort_summary(
        records, cleaned, config.bootstrap_samples, config.random_seed
    )
    timings["analysis_s"] = time.perf_counter() - t_analysis

    t_out = time.perf_counter()
    write_evaluation(evaluation, config.results_dir / "evaluation.json")
    write_cohort_summary(config.results_dir / "cohort_summary.json", cohort_summary)
    write_quality_export(config.results_dir / "qa_flags.json", quality, cleaned)
    (config.processed_dir / "events_clean.jsonl").write_text(
        "\n".join(json.dumps(asdict(e)) for e in cleaned),
        encoding="utf-8",
    )
    (config.processed_dir / "models.json").write_text(
        json.dumps({k: _model_to_json(v) for k, v in models.items()}, indent=2),
        encoding="utf-8",
    )
    figure_paths = _write_figures(
        config.results_dir,
        [a.rainfall_mm for a in aligned],
        [a.volume_m3 for a in aligned],
        freq_ranks,
        vol_ranks,
        labels={
            e.outfall_id: f"{e.outfall_id} ({e.municipality or e.permitee_name})"
            for e in descriptive
        },
    )
    support = cast(dict[str, object], cohort_summary["model_support"])
    html_text = render_html_report(
        title="CSO Insight Report",
        summary=(
            "Case study: Massachusetts EEA combined sewer overflow notifications "
            "(Archive of Massachusetts Environmental Data feed). "
            "Evaluation years 2022 to 2025 with 2025 held out; 2022 begins July 2. "
            "Descriptive rankings use fit-eligible notifications only and are not "
            "rainfall-normalized prioritization. "
            "All classes are counted as report rows, not distinct discharges. "
            "UNKNOWN IDs pool reports by permittee and are not established physical outfalls. "
            "The mean-volume baseline beats the rainfall model on pooled RMSE. "
            f"RMSE support: {support['scored_rows']}/{support['paired_rows']} "
            "eligible paired reports "
            f"and {support['scored_rows']}/{support['eligible_test_rows']} eligible test reports."
        ),
        top_frequency=freq_ranks,
        top_volume=vol_ranks,
        quality_flags=quality,
        cohort_summary=cohort_summary,
        evaluation=evaluation,
        figure_paths=figure_paths,
        identifier_labels={
            e.outfall_id: f"{e.outfall_id} ({e.municipality or e.permitee_name})"
            for e in descriptive
        },
        provenance=(
            "Source: openamend.org/data/EEADP_CSO.csv; snapshot SHA-256 "
            f"{config.expected_download_sha256}; fit-eligible events only."
        ),
    )
    write_html_report(config.results_dir / "report.html", html_text)
    hardware = platform.processor() or platform.machine()
    write_results_md(
        config.root / "RESULTS.md",
        evaluation,
        hardware=f"{platform.system()} {hardware}",
        command="cso-insight run --root .",
        cohort_summary=cohort_summary,
    )
    generate_site(config.root)
    timings["output_s"] = time.perf_counter() - t_out
    timings["total_s"] = time.perf_counter() - t0
    (config.results_dir / "timings.json").write_text(
        json.dumps({**timings, "attribution": output_attribution()}, indent=2),
        encoding="utf-8",
    )
    return timings
