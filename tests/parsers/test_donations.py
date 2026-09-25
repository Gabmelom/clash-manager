from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date
from typing import Any

from clash_reporter.config import ScoringConfig
from clash_reporter.events import DonationSummary
from clash_reporter.models import Donations, MonthlyDataset, MonthlyPlayerSummary
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_UNKNOWN_LAYOUT,
    parse_all,
)
from clash_reporter.parsers.donations import DonationsParser
from clash_reporter.scoring import rank_players
from clash_reporter.scoring.metrics import score_player

Message = Callable[[str], dict[str, Any]]

PARSER = DonationsParser()


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_daily_donation_fixture(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("donations/daily.json"))
    assert len(outcome.events) == 3
    by_name = {event.player_name: event for event in outcome.events}
    aurora = by_name["Aurora"]
    assert isinstance(aurora, DonationSummary)
    assert aurora.donated == 8420
    assert aurora.received == 5210
    assert aurora.player_tag is None
    assert aurora.interval == "daily"
    assert aurora.summary_date == date(2026, 8, 14)
    assert by_name["Dune"].donated == 0
    assert by_name["Dune"].received == 1200
    assert any(item.reason_code == IGNORED_MISSING_PLAYER_TAG for item in outcome.diagnostics)


def test_monthly_donation_fixture_uses_same_layout(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("donations/monthly-summary.json"))
    assert [event.player_name for event in outcome.events] == ["Aurora", "Cascade", "Dune"]
    assert all(event.interval == "monthly" for event in outcome.events)
    assert outcome.events[0].summary_date == date(2026, 7, 28)


def test_donations_do_not_feed_the_score(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("donations/daily.json"))
    assert any(isinstance(event, DonationSummary) for event in outcome.events)

    config = ScoringConfig()
    assert not hasattr(config, "weight_donations")
    assert "donations" in MonthlyPlayerSummary.model_fields
    assert config.total_weight() == (
        config.weight_reliability
        + config.weight_war_performance
        + config.weight_clan_games
        + config.weight_capital
    )

    player = MonthlyPlayerSummary(
        player_tag="#A00000",
        current_display_name="Aurora",
        donations=Donations(donated=9000, received=1),
    )
    bare = MonthlyPlayerSummary(player_tag="#A00000", current_display_name="Aurora")
    breakdown = score_player(player, config, min_contribution=0, max_contribution=1)
    bare_breakdown = score_player(bare, config, min_contribution=0, max_contribution=1)
    assert breakdown == bare_breakdown
    assert not hasattr(breakdown, "donations")
    ranked = rank_players(MonthlyDataset(month_label="August 2026", players=[player]), config)
    assert ranked.ranked == []


def test_donations_cannot_change_rankings(sample_dataset: MonthlyDataset) -> None:
    config = ScoringConfig()
    before = [player.score.overall for player in rank_players(sample_dataset, config).ranked]
    boosted = sample_dataset.model_copy(deep=True)
    for player in boosted.players:
        player.donations = Donations(donated=50_000, received=50_000)
    after = [player.score.overall for player in rank_players(boosted, config).ranked]
    assert before == after


def test_unknown_layout_is_a_diagnostic(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/join.json"))
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNKNOWN_LAYOUT


def test_malformed_donation_message_is_a_diagnostic() -> None:
    outcome = _parse({})
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED


def test_name_without_tag_is_not_invented(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("donations/daily.json"))
    outcome = _parse(message)
    assert all(event.player_tag is None for event in outcome.events)
    assert all(event.player_name for event in outcome.events)


def test_duplicate_daily_log_is_deduplicated(clashperk_message: Message) -> None:
    message = clashperk_message("donations/daily.json")
    combined = parse_all(PARSER, [message, message])
    assert len(combined.events) == 3
