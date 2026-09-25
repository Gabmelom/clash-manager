from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from clash_reporter.config import ScoringConfig
from clash_reporter.events import ClanGamesResult
from clash_reporter.models import (
    ClanGames,
    Membership,
    MonthlyDataset,
    MonthlyPlayerSummary,
    RegularWar,
)
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_MISSING_ROWS,
    IGNORED_UNKNOWN_LAYOUT,
    make_event_key,
    parse_all,
)
from clash_reporter.parsers.clan_games import CLASHPERK_LEADERBOARD_ROW_CAP, ClanGamesParser
from clash_reporter.scoring import rank_players
from clash_reporter.window import month_window, parse_iso_timestamp

Message = Callable[[str], dict[str, Any]]

PARSER = ClanGamesParser()
AUGUST = month_window(2026, 8, timezone="America/Toronto")
SEPTEMBER = month_window(2026, 9, timezone="America/Toronto")


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_leaderboard_fixture(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("clan-games/final-leaderboard.json"))
    assert len(outcome.events) == 4
    by_name = {event.player_name: event for event in outcome.events}
    assert isinstance(by_name["Aurora"], ClanGamesResult)
    assert by_name["Aurora"].points == 4000
    assert by_name["Cascade"].points == 4000
    assert by_name["Everest"].points == 2650
    assert by_name["Dune"].points == 0
    dune = by_name["Dune"]
    assert dune.player_tag is None
    assert dune.occurrence_key == "2026-08"
    assert dune.message_edited_at == parse_iso_timestamp("2026-08-28T10:30:14.096000+00:00")
    assert dune.occurred_at == dune.message_edited_at
    assert dune.source.parser_name == "clan_games"
    assert dune.event_key == make_event_key(dune.source.message_id, "ClanGamesResult", "", 3)
    assert any(item.reason_code == IGNORED_MISSING_PLAYER_TAG for item in outcome.diagnostics)
    assert not any(item.reason_code == IGNORED_MISSING_ROWS for item in outcome.diagnostics)


def test_explicit_zero_is_zero_not_none(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("clan-games/final-leaderboard.json"))
    dune = next(event for event in outcome.events if event.player_name == "Dune")
    assert dune.points == 0
    assert dune.points is not None


def test_missing_clan_games_message_leaves_points_unknown() -> None:
    outcome = _parse({})
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED
    points = next(
        (event.points for event in outcome.events if isinstance(event, ClanGamesResult)),
        None,
    )
    assert points is None


def test_inaccessible_clan_games_embed_leaves_points_unknown(
    clashperk_message: Message,
) -> None:
    message = deepcopy(clashperk_message("clan-games/final-leaderboard.json"))
    message["embeds"] = []
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED
    points = next(
        (event.points for event in outcome.events if isinstance(event, ClanGamesResult)),
        None,
    )
    assert points is None


def test_zero_points_is_a_review_signal_missing_points_is_not() -> None:
    config = ScoringConfig()
    war = RegularWar(wars_participated=5, attacks_available=10, attacks_used=7, attacks_missed=0)
    membership = Membership(eligible_days=31)
    zero = MonthlyPlayerSummary(
        player_tag="#Z00000",
        current_display_name="Dune",
        membership=membership,
        regular_war=war,
        clan_games=ClanGames(points=0),
    )
    missing = MonthlyPlayerSummary(
        player_tag="#Z00001",
        current_display_name="Ghost",
        membership=membership,
        regular_war=war,
        clan_games=ClanGames(points=None),
    )
    ranked = rank_players(
        MonthlyDataset(month_label="August 2026", players=[zero, missing]), config
    )
    by_tag = {player.summary.player_tag: player for player in ranked.ranked}
    assert any("Clan Games" in reason for reason in by_tag["#Z00000"].review_reasons)
    assert not any("Clan Games" in reason for reason in by_tag["#Z00001"].review_reasons)
    assert by_tag["#Z00000"].review_reasons
    assert not by_tag["#Z00001"].review_reasons


def test_cross_month_uses_edit_timestamp_not_creation(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("clan-games/cross-month-leaderboard.json"))
    event = outcome.events[0]
    created = parse_iso_timestamp("2026-08-22T06:00:08.233000+00:00")
    edited = parse_iso_timestamp("2026-09-01T10:30:14.096000+00:00")
    assert event.source.message_timestamp == created
    assert event.message_edited_at == edited
    assert event.occurred_at == edited
    assert AUGUST.contains(created)
    assert not AUGUST.contains(event.occurred_at)
    assert SEPTEMBER.contains(event.occurred_at)
    assert event.occurrence_key == "2026-08"


def test_truncated_leaderboard_is_a_diagnostic_not_silent(
    clashperk_message: Message,
) -> None:
    outcome = _parse(clashperk_message("clan-games/truncated-leaderboard.json"))
    assert [event.player_name for event in outcome.events] == ["Aurora", "Cascade"]
    missing = [item for item in outcome.diagnostics if item.reason_code == IGNORED_MISSING_ROWS]
    assert missing
    assert "truncated" in missing[0].detail
    assert "2" in missing[0].detail


def test_unclosed_code_fence_is_missing_rows(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("clan-games/final-leaderboard.json"))
    description = message["embeds"][0]["description"]
    message["embeds"][0]["description"] = description.replace("```\n<:", "\n<:", 1)
    outcome = _parse(message)
    assert outcome.events
    assert any(item.reason_code == IGNORED_MISSING_ROWS for item in outcome.diagnostics)


def test_capped_leaderboard_is_missing_rows(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("clan-games/final-leaderboard.json"))
    lines = ["‎ # POINTS   NAME"]
    lines.extend(f"‎{index:2d}   4000   Player{index}" for index in range(1, 56))
    fence = "```\n" + "\n".join(lines) + "\n```"
    message["embeds"][0]["description"] = (
        "**[Clan Games Scoreboard (2026-08)](https://clashperk.com/faq)**\n" + fence
    )
    message["embeds"][0]["footer"]["text"] = "Points: 240000 [Avg: 4000.00]"
    outcome = _parse(message)
    assert len(outcome.events) == CLASHPERK_LEADERBOARD_ROW_CAP
    assert any(item.reason_code == IGNORED_MISSING_ROWS for item in outcome.diagnostics)


def test_parser_does_not_cap_points(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("clan-games/final-leaderboard.json"))
    message["embeds"][0]["description"] = message["embeds"][0]["description"].replace(
        "4000   Aurora", "9000   Aurora", 1
    )
    event = next(item for item in _parse(message).events if item.player_name == "Aurora")
    assert event.points == 9000


def test_unknown_layout_is_a_diagnostic(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/join.json"))
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNKNOWN_LAYOUT


def test_duplicate_message_is_deduplicated(clashperk_message: Message) -> None:
    message = clashperk_message("clan-games/final-leaderboard.json")
    combined = parse_all(PARSER, [message, message])
    assert len(combined.events) == 4
