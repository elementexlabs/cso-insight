"""Regression tests for publication review fixes (items 1-9)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from conftest import make_event as _event
from cso_insight.baselines import collect_paired_volume_predictions
from cso_insight.clean import clean_records
from cso_insight.cohort import exclusion_reasons
from cso_insight.evaluate import (
    bootstrap_spearman_by_event_resample,
    evaluate,
    spearman_rank_correlation,
)
from cso_insight.ingest import CsoRecord, iter_cso_records
from cso_insight.model import fit_rainfall_response
from cso_insight.pipeline import _model_to_json, verify_preregistration_hash

# Item 1: Spearman must not collapse bootstrap multiplicities or double-average


def test_spearman_preserves_bootstrap_multiplicities() -> None:
    """Dictionary collapse would make duplicate outfall IDs overwrite counts."""
    train_val = [
        _event("1", "O1", 2022),
        _event("2", "O1", 2022),
        _event("3", "O2", 2022),
        _event("4", "O3", 2022),
    ]
    test_scores = {"O1": 5.0, "O2": 1.0, "O3": 3.0}
    rho, low, high, n = bootstrap_spearman_by_event_resample(train_val, test_scores, 50, 0)
    assert rho is not None
    assert n == 3
    assert low < high


def test_spearman_observed_not_bootstrap_mean() -> None:
    """Point estimate must be the direct correlation, not the mean of bootstrap replicates."""
    from cso_insight.baselines import baseline_count_scores

    train_val = [
        _event(str(i), f"O{i % 5}", 2022, volume=10 + i, rain=1.0)
        for i in range(30)
        for _ in range((i % 5) + 1)
    ]
    test = [
        _event(f"t{i}", f"O{i % 5}", 2025, volume=5.0, rain=1.0)
        for i in range(20)
        for _ in range(5 - (i % 5))
    ]
    test_scores = baseline_count_scores(test)
    observed = spearman_rank_correlation(baseline_count_scores(train_val), test_scores)
    rho, _, _, _ = bootstrap_spearman_by_event_resample(train_val, test_scores, 30, 1)
    assert observed is not None
    assert rho is not None
    assert rho == observed


# Item 2: RMSE on identical event cohort, pooled not macro-averaged


def test_rmse_same_event_cohort() -> None:
    train = [_event(f"a{i}", "O1", 2022, 10.0 + i, 5.0 + i * 0.5) for i in range(6)]
    test = [_event(f"t{i}", "O1", 2025, 10.0 + i, 5.0 + i * 0.1) for i in range(6)]
    model_pairs, baseline_pairs = collect_paired_volume_predictions(train, test)
    assert len(model_pairs) == len(baseline_pairs)
    assert len(model_pairs) == 6
    event_ids_model = {p[0] for p in model_pairs}
    event_ids_base = {p[0] for p in baseline_pairs}
    assert event_ids_model == event_ids_base


def test_pooled_rmse_not_macro_average() -> None:
    """Macro-averaging per-outfall RMSE differs from pooled event RMSE."""
    train = [_event(f"a{i}", "O1", 2022, 10.0 + i, 5.0 + i) for i in range(6)]
    train += [_event(f"b{i}", "O2", 2022, 100.0 + i, 6.0 + i) for i in range(6)]
    test = [
        _event("t1", "O1", 2025, 10.0, 8.0),
        _event("t2", "O1", 2025, 12.0, 9.0),
        _event("t3", "O2", 2025, 100.0, 10.0),
        _event("t4", "O2", 2025, 110.0, 11.0),
    ]
    model_pairs, _ = collect_paired_volume_predictions(train, test)
    assert len(model_pairs) == 4
    pooled = float(np.sqrt(np.mean([(a - p) ** 2 for a, p in model_pairs])))
    o1_pairs = [(a, p) for a, p in model_pairs if a < 50]
    o2_pairs = [(a, p) for a, p in model_pairs if a >= 50]
    macro = float(
        np.mean(
            [
                float(np.sqrt(np.mean([(a - p) ** 2 for a, p in o1_pairs]))),
                float(np.sqrt(np.mean([(a - p) ** 2 for a, p in o2_pairs]))),
            ]
        )
    )
    assert pooled != pytest.approx(macro, rel=0.01)


# Item 3: Stop rules enforced


def test_stop_rule_fewer_than_ten_paired_outfalls() -> None:
    events = [_event(f"t{i}", "O1", 2025, 1.0, 1.0) for i in range(150)]
    events += [_event("tr1", "O1", 2022, 1.0, 1.0)]
    report = evaluate(events, bootstrap_samples=5, seed=0)
    assert report.stop_rule_triggered is True
    assert "10" in report.stop_rule_detail


def test_stop_rule_nan_metrics_when_triggered() -> None:
    events = [_event("t1", "O1", 2025, 1.0, 1.0)]
    report = evaluate(events, bootstrap_samples=5, seed=0)
    assert report.stop_rule_triggered is True
    for metric in report.metrics:
        assert math.isnan(metric.value)


# Item 4: Implausible rainfall quarantined from fitting


def test_implausible_rainfall_quarantined(tmp_path: Path) -> None:
    csv_text = (
        "incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,"
        "eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,"
        "reportingType,location,latitude,longitude,waterBody,waterBodyDescription,"
        "volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,"
        "submittedDate,parentIncidentId,Year\n"
        "x,n,2022-06-01,08:00,,Public Notification Report,CSO – UnTreated,CSO,"
        "A,MA1,O1,B,,,,,,,1000,50.0,,,,,,2022.0\n"
    )
    path = tmp_path / "bad.csv"
    path.write_text(csv_text, encoding="utf-8")
    cleaned = clean_records(list(iter_cso_records(path)))
    assert cleaned[0].fit_eligible is False


def test_models_json_serializes_null_r_squared() -> None:
    model = fit_rainfall_response(
        [_event(str(i), "O1", 2022, 10.0 + i, 5.0 + i * 0.3) for i in range(6)],
        "O1",
    )
    assert model is not None
    payload = _model_to_json(model)
    text = json.dumps(payload)
    assert "NaN" not in text
    assert "null" in text or payload["r_squared"] is not None


# Item 5: Treatment and datetime parsing


def test_untreated_not_marked_treated(tmp_path: Path) -> None:
    csv_text = (
        "incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,"
        "eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,"
        "reportingType,location,latitude,longitude,waterBody,waterBodyDescription,"
        "volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,"
        "submittedDate,parentIncidentId,Year\n"
        "x,n,2022-01-01,08:00,,Public Notification Report,CSO – UnTreated,CSO,"
        "A,MA1,O1,B,,,,,,,100,0.5,,,,,,2022.0\n"
    )
    path = tmp_path / "treat.csv"
    path.write_text(csv_text, encoding="utf-8")
    rows = list(iter_cso_records(path))
    assert rows[0].is_treated is False


def test_datetime_preserves_separate_time(tmp_path: Path) -> None:
    csv_text = (
        "incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,"
        "eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,"
        "reportingType,location,latitude,longitude,waterBody,waterBodyDescription,"
        "volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,"
        "submittedDate,parentIncidentId,Year\n"
        "x,n,2025-01-01 00:00:00,14:30,,Public Notification Report,CSO – UnTreated,CSO,"
        "A,MA1,O1,B,,,,,,,100,0.5,,,,,,2025.0\n"
    )
    path = tmp_path / "dt.csv"
    path.write_text(csv_text, encoding="utf-8")
    rows = list(iter_cso_records(path))
    assert rows[0].start_time.hour == 14
    assert rows[0].start_time.minute == 30


# Item 7: Citation file must not contain wrong DOI or author


def test_no_wrong_citation_doi() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    report = Path("docs/technical-report.md").read_text(encoding="utf-8")
    wrong = "10.1016/j.watres.2021.117013"
    assert wrong not in readme
    assert wrong not in report
    assert "Hein, Fuchs and Rieckermann" not in readme
    assert "Hein, Fuchs and Rieckermann" not in report
    assert "McGrath" in readme
    assert "McGrath" in report


def test_amend_name_in_manifest() -> None:
    manifest = Path("docs/DATA_MANIFEST.md").read_text(encoding="utf-8")
    assert "Archive of Massachusetts Environmental Data" in manifest
    assert "Aquatic Monitoring of Environmental Data" not in manifest


def test_readme_describes_amended_evaluation() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "amended" in readme.lower() or "amendment" in readme.lower()
    assert "rainfall-normalized outfall ranking was not evaluated" in readme.lower()


def test_ci_uses_module_pytest() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "run: pytest" not in workflow


def test_helpers_importable_from_conftest() -> None:
    from conftest import make_event

    event = make_event("1", "O1", 2025)
    assert event.outfall_id == "O1"


def test_volume_cap_exclusion_counted() -> None:
    from datetime import datetime

    records = [
        CsoRecord(
            incident_id="big",
            incident_number="n1",
            start_time=datetime(2022, 1, 1),
            event_type="CSO – UnTreated",
            permitee_name="A",
            permitee_id="MA",
            outfall_id="O1",
            municipality="B",
            latitude=None,
            longitude=None,
            volume_gallons=11_000_000.0,
            rainfall_inches=0.5,
            duration_hours=1.0,
            year=2022,
            is_treated=False,
        )
    ]
    cleaned = clean_records(records)
    reasons = exclusion_reasons(records, cleaned)
    assert any(item.reason == "volume_above_cap" for item in reasons)


# Item 8: Data manifest exists with licence information


def test_data_manifest_exists() -> None:
    manifest = Path("docs/DATA_MANIFEST.md")
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "openamend.org" in text
    assert "SHA-256" in text or "sha256" in text.lower()


# Item 9: Citation uses organization author


def test_citation_uses_organization_author() -> None:
    cff = Path("CITATION.cff").read_text(encoding="utf-8")
    import yaml

    assert yaml.safe_load(cff)["authors"] == [{"name": "ElementeX Labs Inc."}]


def test_preregistration_hash_verified(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    prereg = docs / "PREREGISTRATION.md"
    prereg.write_text("# test\n", encoding="utf-8")
    (docs / "PREREGISTRATION.sha256").write_text(
        "wronghash\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_preregistration_hash(tmp_path)
