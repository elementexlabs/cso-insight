"""Tests for configuration and URL validation."""

from pathlib import Path

import pytest

from cso_insight.config import PipelineConfig, validate_url


def test_validate_url_allows_openamend() -> None:
    assert validate_url("https://openamend.org/data/EEADP_CSO.csv")


def test_validate_url_rejects_unknown_host() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("https://evil.example/data.csv")


def test_pipeline_config_from_root(tmp_path: Path) -> None:
    config = PipelineConfig.from_root(tmp_path)
    assert config.raw_dir == tmp_path / "data" / "raw"
