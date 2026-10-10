"""Release behaviour on original synthetic records only."""

import inspect
import json

import pytest

from cso_insight.linkage import build_linkage
from cso_insight.release_cli import main
from cso_insight.synthetic import synthetic_rows


def test_synthetic_offsets_have_expected_candidate_partitions():
    rows = synthetic_rows()
    assert all(r.snapshot_hash == "synthetic-demo" for r in rows)
    settings = (
        [(15, 2), (30, 3)]
        if "tolerance_minutes" in inspect.signature(build_linkage).parameters
        else [(15, 2)]
    )
    for tolerance, expected in settings:
        output = (
            build_linkage(rows, "synthetic-demo", tolerance_minutes=tolerance)
            if "tolerance_minutes" in inspect.signature(build_linkage).parameters
            else build_linkage(rows, "synthetic-demo")
        )
        assert sum(len(g["source_rows"]) == 2 for g in output.events) == expected
        assert sum(len(g["source_rows"]) for g in output.events) == 6


def test_demo_prints_aggregates_without_source_cells(capsys):
    assert main([]) == 0
    text = capsys.readouterr().out
    result = json.loads(text)
    assert (result["source_rows"], result["linked_pairs"], result["unpaired_rows"]) == (6, 2, 2)
    assert "SYNTHETIC-" not in text
    assert "incidentId" not in text
    assert "2099" not in text


def test_comparison_demo_when_module_available(capsys):
    pytest.importorskip("cso_insight.fair_comparison")
    assert main(["--compare"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["original_simple"]["linked_pairs"] == 3
    assert result["two_veto_simple"]["linked_pairs"] == 2
    assert result["two_veto_simple"]["spillledger_only"] == 0
