"""Tests for HTML report escaping."""

from cso_insight.evaluate import EvaluationReport, MetricResult
from cso_insight.report import render_html_report


def test_html_escapes_title() -> None:
    evaluation = EvaluationReport(
        train_years=[2022, 2023],
        validation_year=2024,
        test_year=2025,
        metrics=[
            MetricResult("m", 0.5, 0.4, 0.6, 10),
        ],
        baselines=[],
        stop_rule_triggered=False,
        stop_rule_detail="",
    )
    html = render_html_report(
        title="<script>",
        summary="test",
        top_frequency=[],
        top_volume=[],
        quality_flags=[],
        evaluation=evaluation,
        figure_paths={},
        provenance="Synthetic fixture data for tests.",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
