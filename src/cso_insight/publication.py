"""Generate browser pages from canonical reports and computed artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path


def generate_site(root: Path) -> None:
    site = root / "docs" / "site"
    site.mkdir(parents=True, exist_ok=True)
    for source, target in [
        ("technical-report.md", "technical-report.md"),
        ("DATA_MANIFEST.md", "data-manifest.md"),
        ("LICENSE-CC-BY-4.0.txt", "licence.md"),
        ("PREREGISTRATION_STATUS.md", "PREREGISTRATION_STATUS.md"),
        ("PREREGISTRATION.md", "PREREGISTRATION.md"),
        ("PREREGISTRATION.sha256", "PREREGISTRATION.sha256"),
        ("PREREGISTRATION_AMENDMENT_2026-10-01.md", "PREREGISTRATION_AMENDMENT_2026-10-01.md"),
        ("ANALYSIS_AMENDMENT_R5_2026-10-01.md", "ANALYSIS_AMENDMENT_R5_2026-10-01.md"),
    ]:
        path = root / "docs" / source
        if path.exists():
            (site / target).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    figures = site / "figures"
    figures.mkdir(exist_ok=True)
    for name in ("top_outfalls_frequency.png", "top_outfalls_volume.png"):
        shutil.copyfile(root / "results" / "figures" / name, figures / name)
    results = (root / "RESULTS.md").read_text(encoding="utf-8")
    results += (
        "\n## Descriptive totals and uncertainty\n\n"
        "![Report row counts](figures/top_outfalls_frequency.png)\n\n"
        "![Reported volume totals](figures/top_outfalls_volume.png)\n\n"
        "MassDEP via AMEND, pinned snapshot; 2022-2025 eligible report rows. "
        "Points are observed totals; bars show conditional bootstrap intervals on metrics, "
        "not rank positions. Counts can include multiple reporting stages of one discharge. "
        "Volume caps can change priorities: inspect the capped/uncapped top-five comparison "
        "in the cohort ledger. Original figure design CC BY 4.0; upstream rights retained.\n"
    )
    (site / "results.md").write_text(results, encoding="utf-8")
