"""Executable-mode regression for directly documented shell commands."""

import re
import runpy
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def directly_invoked_scripts(root):
    documents = list(root.glob("README*"))
    documents += list((root / "docs").rglob("*.md"))
    documents += list((root / ".github").rglob("*.yml"))
    documents += list((root / ".github").rglob("*.yaml"))
    return {
        match
        for document in documents
        for match in re.findall(r"\./([\w./-]+\.sh)\b", document.read_text())
    }


def assert_executable_contract(root):
    scripts = directly_invoked_scripts(root)
    assert scripts, "No directly invoked shell scripts found in the published contract"
    for path in sorted(scripts):
        script = root / path
        assert script.is_file(), path
        assert stat.S_IMODE(script.stat().st_mode) & 0o111 == 0o111, path
        entry = subprocess.check_output(["git", "-C", str(root), "ls-tree", "HEAD", path])
        assert entry.startswith(b"100755 "), (path, entry)


def test_documented_shell_scripts_are_executable():
    assert_executable_contract(ROOT)


def test_public_snapshot_preserves_documented_executables(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/prepare_public.py"))
    bundle = tmp_path / "public.bundle"
    module["prepare"](ROOT, bundle)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(bundle), str(checkout)], check=True, capture_output=True)
    assert directly_invoked_scripts(checkout) == directly_invoked_scripts(ROOT)
    assert_executable_contract(checkout)
    # Refusal of the frozen destination exercises direct execution without acquisition.
    result = subprocess.run(
        [str(checkout / "scripts/download_data.sh"), str(checkout / "data/raw/ma_eea_cso.csv")],
        capture_output=True,
    )
    assert result.returncode == 1
    assert b"Refusing to overwrite the frozen snapshot" in result.stderr
