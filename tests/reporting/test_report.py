from __future__ import annotations

from clash_reporter.config import ScoringConfig
from clash_reporter.models import (
    Capital,
    ClanGames,
    Membership,
    MonthlyDataset,
    MonthlyPlayerSummary,
    RegularWar,
)
from clash_reporter.reporting import render_report
from clash_reporter.reporting.discord_report import listed_members
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


def _member(
    tag: str,
    name: str,
    *,
    eligible_days: int,
    joined_this_month: bool = False,
    departed_this_month: bool = False,
    joined_on: str | None = None,
    left_on: str | None = None,
) -> MonthlyPlayerSummary:
    return MonthlyPlayerSummary(
        player_tag=tag,
        current_display_name=name,
        membership=Membership(
            eligible_days=eligible_days,
            joined_this_month=joined_this_month,
            departed_this_month=departed_this_month,
            joined_on=joined_on,
            left_on=left_on,
        ),
    )


def test_same_window_join_and_leave_omitted_from_both_lists() -> None:
    trial = _member(
        "#LANCE1",
        "Lance",
        eligible_days=2,
        joined_this_month=True,
        departed_this_month=True,
        joined_on="Sep 4",
        left_on="Sep 6",
    )
    joined = _member(
        "#NOVA22",
        "Nova",
        eligible_days=3,
        joined_this_month=True,
        joined_on="Sep 20",
    )
    left = _member(
        "#OAK333",
        "Oak",
        eligible_days=10,
        departed_this_month=True,
        left_on="Sep 8",
    )
    veteran = MonthlyPlayerSummary(
        player_tag="#PINE44",
        current_display_name="Pine",
        membership=Membership(eligible_days=30),
        regular_war=RegularWar(attacks_available=4, attacks_used=4, average_stars=2.0),
        clan_games=ClanGames(points=4000),
        capital=Capital(contribution=1000),
    )
    dataset = MonthlyDataset(
        month_label="September 2026",
        clan_name="Maple Legends",
        regular_wars=4,
        cwl_rounds=7,
        clan_games_completed=True,
        raid_weekends=4,
        players=[trial, joined, left, veteran],
    )
    ranked = rank_players(dataset, ScoringConfig())

    assert {player.player_tag for player in listed_members(ranked.new_members)} == {"#NOVA22"}
    assert {player.player_tag for player in listed_members(ranked.departed_members)} == {"#OAK333"}
    assert {player.summary.player_tag for player in ranked.ranked} == {"#PINE44"}

    report = render_report(dataset, ranked)
    assert "Lance (#LANCE1)" not in report
    assert "Nova (#NOVA22)" in report
    assert "Oak (#OAK333)" in report
    assert "1 ranking-eligible members" in report
    assert "1 new members" in report
    assert "1 departed members" in report
    assert "4 regular wars" in report
    assert "7 CWL rounds" in report
    assert "4 Raid Weekends" in report
    assert "Pine (#PINE44)" in report
