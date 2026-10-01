"""Tests for download helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cso_insight.download import download_file, verify_file_sha256


def test_download_rejects_bad_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        download_file("https://evil.example/x.csv", tmp_path / "x.csv")


def test_download_hash_mismatch(tmp_path: Path) -> None:
    payload = b"data"
    response = MagicMock()
    response.read.side_effect = [payload, b""]
    response.geturl.return_value = "https://openamend.org/data/EEADP_CSO.csv"
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    dest = tmp_path / "out.csv"
    with patch("cso_insight.download.urlopen", return_value=response):
        with pytest.raises(ValueError, match="SHA-256"):
            download_file(
                "https://openamend.org/data/EEADP_CSO.csv",
                dest,
                expected_sha256="deadbeef",
            )


def test_verify_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    assert verify_file_sha256(
        path, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert not verify_file_sha256(path, "0" * 64)
