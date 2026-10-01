"""Download public CSO datasets with size and host checks."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from cso_insight.config import DOWNLOAD_TIMEOUT_S, MAX_DOWNLOAD_BYTES, validate_url


def _stream_to_file(
    url: str,
    destination: Path,
    max_bytes: int,
) -> str:
    """Stream download to destination; return SHA-256 hex digest."""
    validate_url(url)
    digest = hashlib.sha256()
    total = 0
    request = Request(url, headers={"User-Agent": "cso-insight/0.1"})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
        final_url = response.geturl()
        validate_url(final_url)
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    msg = f"Download exceeds size limit ({max_bytes} bytes)"
                    raise ValueError(msg)
                digest.update(chunk)
                handle.write(chunk)
    return digest.hexdigest()


def download_file(
    url: str,
    destination: Path,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    expected_sha256: str | None = None,
) -> str:
    """Download to a temporary file, verify hash, then atomically replace destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=destination.parent,
        prefix=".download-",
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        digest = _stream_to_file(url, tmp_path, max_bytes)
        if expected_sha256 is not None and digest != expected_sha256.lower():
            msg = f"Download SHA-256 {digest} does not match expected {expected_sha256.lower()}"
            raise ValueError(msg)
        tmp_path.replace(destination)
        return digest
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def verify_file_sha256(path: Path, expected_sha256: str) -> bool:
    """Return True when path contents match the expected digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256.lower()
