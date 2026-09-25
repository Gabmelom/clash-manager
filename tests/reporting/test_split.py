from __future__ import annotations

import pytest

from clash_reporter.config import ScoringConfig
from clash_reporter.discord_client import discord_content_length
from clash_reporter.models import Membership, MonthlyDataset, MonthlyPlayerSummary, RegularWar
from clash_reporter.reporting import render_report, split_report
from clash_reporter.reporting.discord_report import SECTION_HEADERS
from clash_reporter.reporting.split import ReportSplitError
from clash_reporter.scoring import rank_players


def test_short_report_stays_one_message(sample_dataset: MonthlyDataset) -> None:
    report = render_report(sample_dataset, rank_players(sample_dataset, ScoringConfig()))
    assert split_report(report) == [report]


def test_long_report_splits_under_the_limit_without_orphaned_headers(
    sample_dataset: MonthlyDataset,
) -> None:
    players = [
        MonthlyPlayerSummary(
            player_tag=f"#P{index:04d}",
            current_display_name=f"Player {index}",
            membership=Membership(eligible_days=31),
            regular_war=RegularWar(
                wars_participated=8,
                attacks_available=16,
                attacks_used=8,
                attacks_missed=8,
                average_stars=1.2,
            ),
        )
        for index in range(40)
    ]
    dataset = sample_dataset.model_copy(update={"players": players})
    report = render_report(dataset, rank_players(dataset, ScoringConfig()), top_n=40)
    assert len(report) > 2000

    chunks = split_report(report)
    assert len(chunks) > 1
    for chunk in chunks:
        assert discord_content_length(chunk) <= 2000
        assert chunk.split("\n")[-1] not in SECTION_HEADERS

    def body(text: str) -> list[str]:
        return [line for line in text.split("\n") if line and line not in SECTION_HEADERS]

    assert [line for chunk in chunks for line in body(chunk)] == body(report)

    for chunk in chunks:
        lines = [line for line in chunk.split("\n") if line]
        for index, line in enumerate(lines):
            if line.startswith("   "):
                assert index > 0
                assert lines[index - 1] not in SECTION_HEADERS


def test_header_is_not_parked_without_its_first_entry() -> None:
    filler = "summary line that fills the opening message " * 3
    review_entry = "Player X (#CCC)\n- 3 regular war attacks missed\n- 71% attack usage"
    report = "\n".join(
        [
            "🏰 Clan Monthly Report - August 2026",
            "",
            filler.strip(),
            "",
            "🏆 Top Performers",
            "1. Player A (#AAA) - 91.4",
            "   War: 100% attacks used | 2.71 avg stars",
            "",
            "⚠️ Needs Review",
            review_entry,
        ]
    )
    opening = "\n".join(
        [
            "🏰 Clan Monthly Report - August 2026",
            "",
            filler.strip(),
            "",
            "🏆 Top Performers",
            "1. Player A (#AAA) - 91.4",
            "   War: 100% attacks used | 2.71 avg stars",
        ]
    )
    limit = discord_content_length(opening) + 10
    chunks = split_report(report, limit=limit)
    assert len(chunks) == 2
    assert chunks[0] == opening
    assert chunks[1].startswith("⚠️ Needs Review\nPlayer X")
    assert all(discord_content_length(chunk) <= limit for chunk in chunks)
    assert "⚠️ Needs Review" not in chunks[0]


def test_split_counts_emoji_as_utf16_code_units() -> None:
    """Python len would pack two trophy lines; Discord's UTF-16 count must not."""
    entries = [f"{index}. {'🏆' * 10}" for index in range(1, 8)]
    report = "🏆 Top Performers\n" + "\n".join(entries)
    chunks = split_report(report, limit=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert discord_content_length(chunk) <= 50
        assert len(chunk) < discord_content_length(chunk)


def test_oversized_entry_is_refused() -> None:
    report = "🏆 Top Performers\n" + "1. " + ("x" * 50)
    with pytest.raises(ReportSplitError, match="mid-entry"):
        split_report(report, limit=40)
