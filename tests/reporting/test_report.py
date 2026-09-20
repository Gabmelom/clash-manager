from __future__ import annotations

from clash_reporter.config import ScoringConfig
from clash_reporter.models import MonthlyDataset
from clash_reporter.reporting import render_report
from clash_reporter.scoring import rank_players


def test_report_contains_expected_sections(sample_dataset: MonthlyDataset) -> None:
    ranked = rank_players(sample_dataset, ScoringConfig())
    report = render_report(sample_dataset, ranked)
    assert "Maple Legends Monthly Report - August 2026" in report
    assert "🏆 Top Performers" in report
    assert "⚠️ Needs Review" in report
    assert "🆕 New Members" in report
    assert "👋 Departed Members" in report
    assert "ℹ️ Data notes" in report
    assert "Aurora (#AAA111)" in report


def test_report_is_deterministic(sample_dataset: MonthlyDataset) -> None:
    config = ScoringConfig()
    first = render_report(sample_dataset, rank_players(sample_dataset, config))
    second = render_report(sample_dataset, rank_players(sample_dataset, config))
    assert first == second
