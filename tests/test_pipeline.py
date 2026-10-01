"""Tests for pipeline and CLI."""

from pathlib import Path

from conftest import write_sample_csv
from cso_insight.cli import main
from cso_insight.config import PipelineConfig
from cso_insight.pipeline import run_pipeline


def _setup_project(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    prereg_src = Path(__file__).resolve().parents[1] / "docs" / "PREREGISTRATION.md"
    sha_src = Path(__file__).resolve().parents[1] / "docs" / "PREREGISTRATION.sha256"
    (docs / "PREREGISTRATION.md").write_text(prereg_src.read_text(encoding="utf-8"))
    (docs / "PREREGISTRATION.sha256").write_text(sha_src.read_text(encoding="utf-8"))


def test_cli_run_skip_download(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _setup_project(root)
    raw = root / "data" / "raw"
    raw.mkdir(parents=True)
    write_sample_csv(raw / "ma_eea_cso.csv")
    monkeypatch.setattr(
        "cso_insight.pipeline.verify_file_sha256",
        lambda _path, _expected: True,
    )
    assert main(["run", "--root", str(root), "--skip-download"]) == 0


def test_pipeline_on_fixture(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _setup_project(root)
    raw = root / "data" / "raw"
    raw.mkdir(parents=True)
    write_sample_csv(raw / "ma_eea_cso.csv")
    config = PipelineConfig.from_root(root)
    config = PipelineConfig(
        root=config.root,
        raw_dir=config.raw_dir,
        processed_dir=config.processed_dir,
        results_dir=config.results_dir,
        expected_download_sha256=None,
    )
    timings = run_pipeline(config, skip_download=True)
    assert timings["total_s"] >= 0.0
    assert (root / "results" / "evaluation.json").exists()
