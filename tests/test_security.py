"""Tests for safe paths."""

from pathlib import Path

import pytest

from cso_insight.config import safe_path


def test_safe_path_allows_relative(tmp_path: Path) -> None:
    result = safe_path(tmp_path, "data/raw/file.csv")
    assert result.is_relative_to(tmp_path.resolve())


def test_safe_path_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../outside.csv")
