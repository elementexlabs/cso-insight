"""Configuration, constants and validated URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MA_CSO_URL = "https://openamend.org/data/EEADP_CSO.csv"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"openamend.org", "data-donnees.az.ec.gc.ca", "echo.epa.gov"})

# Snapshot hash recorded 2026-10-01 for reproducible regeneration
EXPECTED_DOWNLOAD_SHA256 = "0e8a56ebf1870646431de7c1d326065fbcd9cd27f63132e0790e79eb5ef231c3"

# Hold-out split frozen in preregistration
TRAIN_YEARS = frozenset({2022, 2023})
VALIDATION_YEAR = 2024
TEST_YEAR = 2025
EVALUATION_YEARS = frozenset({2022, 2023, 2024, 2025})

# Plausibility caps applied before fitting and headline descriptive totals.
# Rainfall: 254 mm equals 10 inches, matching the co-reported inch field scale.
# Volume: 37,854 m3 equals 10 million US gallons (round declared upper bound).
# These are suspect-value filters, not verified error labels. See cohort_summary.json.
MAX_PLAUSIBLE_RAINFALL_MM = 254.0
MAX_PLAUSIBLE_VOLUME_M3 = 37854.0

MIN_PAIRED_OUTFALLS = 10

BOOTSTRAP_SAMPLES = 500
RANDOM_SEED = 42

MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 120


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Paths and parameters for the analysis pipeline."""

    root: Path
    raw_dir: Path
    processed_dir: Path
    results_dir: Path
    ma_cso_url: str = DEFAULT_MA_CSO_URL
    bootstrap_samples: int = BOOTSTRAP_SAMPLES
    random_seed: int = RANDOM_SEED
    expected_download_sha256: str | None = EXPECTED_DOWNLOAD_SHA256

    @classmethod
    def from_root(cls, root: Path | None = None) -> PipelineConfig:
        base = root or Path.cwd()
        return cls(
            root=base,
            raw_dir=base / "data" / "raw",
            processed_dir=base / "data" / "processed",
            results_dir=base / "results",
        )


def validate_url(url: str, allowed_hosts: frozenset[str] = ALLOWED_DOWNLOAD_HOSTS) -> str:
    """Return url if host is on the allow list."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        msg = f"URL scheme must be http or https: {url}"
        raise ValueError(msg)
    host = parsed.hostname
    if host is None or host not in allowed_hosts:
        msg = f"Download host not allowed: {host}"
        raise ValueError(msg)
    return url


def safe_path(base: Path, relative: str) -> Path:
    """Resolve relative path and ensure it stays under base."""
    resolved = (base / relative).resolve()
    base_resolved = base.resolve()
    if not resolved.is_relative_to(base_resolved):
        msg = f"Path escapes base directory: {relative}"
        raise ValueError(msg)
    return resolved
