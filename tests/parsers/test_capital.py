from __future__ import annotations

import ast
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from clash_reporter.events import (
    CapitalContribution,
    CapitalRaidAttack,
    CapitalWeeklySummaryRow,
)
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_UNKNOWN_LAYOUT,
    parse_all,
)
from clash_reporter.parsers.capital import CapitalParser, raid_weekend_key
from clash_reporter.window import parse_iso_timestamp

Message = Callable[[str], dict[str, Any]]

PARSER = CapitalParser()
CAPITAL_PY = Path("src/clash_reporter/parsers/capital.py")


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_contribution_keeps_raw_amount(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("capital/contribution.json"))
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert isinstance(event, CapitalContribution)
    assert event.player_tag == "#2Y0LRPV8Q"
    assert event.player_name == "Aurora"
    assert event.amount == 1200
    assert event.source.parser_name == "capital"
    assert event.occurred_at == parse_iso_timestamp("2026-08-09T23:18:07.640000+00:00")


def test_large_contribution_is_not_normalized(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("capital/contribution.json"))
    message["embeds"][0]["description"] = (
        "<:CapitalGold:973413525261279272> Contributed **2,500,000** Capital Gold"
    )
    event = _parse(message).events[0]
    assert isinstance(event, CapitalContribution)
    assert event.amount == 2_500_000


def test_capital_parser_source_has_no_scoring_normalization() -> None:
    source = CAPITAL_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CAPITAL_PY))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.startswith("clash_reporter.scoring"):
                imported.add("clash_reporter.scoring")
    assert "clash_reporter.scoring" not in imported
    assert "clan_games_cap" not in source
    assert "min_contribution" not in source


def test_raid_attack_has_weekend_key_and_raw_loot(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("capital/raid-attack.json"))
    event = outcome.events[0]
    assert isinstance(event, CapitalRaidAttack)
    assert event.player_tag == "#9YLG2PJRQ"
    assert event.player_name == "Cascade"
    assert event.looted == 22443
    assert event.attacks_used == 6
    assert event.attacks_available == 6
    assert event.raid_weekend_key == "2026-08-07"
    occurred = parse_iso_timestamp("2026-08-10T18:02:55.012000+00:00")
    assert event.occurred_at == occurred
    assert raid_weekend_key(occurred) == "2026-08-07"


def test_weekly_raid_summary_is_validation_not_primary(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("capital/weekly-summary.json"))
    assert outcome.events
    assert all(isinstance(event, CapitalWeeklySummaryRow) for event in outcome.events)
    assert not any(isinstance(event, CapitalRaidAttack) for event in outcome.events)
    assert not any(isinstance(event, CapitalContribution) for event in outcome.events)
    by_name = {event.player_name: event for event in outcome.events}
    cascade = by_name["Cascade"]
    assert cascade.kind == "raid"
    assert cascade.amount == 22443
    assert cascade.attacks_used == 6
    assert cascade.attacks_available == 6
    assert cascade.player_tag is None
    assert cascade.raid_weekend_key == "2026-08-07"
    assert by_name["Dune"].amount == 0


def test_weekly_contribution_summary_keeps_raw_totals(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("capital/weekly-contributions.json"))
    by_name = {event.player_name: event for event in outcome.events}
    assert by_name["Aurora"].kind == "contribution"
    assert by_name["Aurora"].amount == 1200
    assert by_name["Dune"].amount == 0
    assert by_name["Aurora"].raid_weekend_key == "2026-08-07"
    assert all(event.player_tag is None for event in outcome.events)


def test_weekly_rows_parse_comma_grouped_amounts(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("capital/weekly-contributions.json"))
    message["embeds"][0]["description"] = (
        "**Clan Capital Contributions**\n```\n"
        "\u200e # TOTAL NAME\n"
        "\u200e 1  1,200  Aurora\n"
        "\u200e 2 22,443  Cascade\n"
        "```"
    )
    by_name = {event.player_name: event for event in _parse(message).events}
    assert by_name["Aurora"].amount == 1200
    assert by_name["Cascade"].amount == 22443


def test_weekly_raid_rows_parse_comma_grouped_loot(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("capital/weekly-summary.json"))
    message["embeds"][0]["description"] = (
        "**Clan Capital Raids**\n```\n"
        "\u200e # LOOTED HITS  NAME\n"
        "\u200e 1  22,443  6/6  Cascade\n"
        "```"
    )
    event = _parse(message).events[0]
    assert event.player_name == "Cascade"
    assert event.amount == 22443
    assert event.attacks_used == 6


def test_contribution_without_tag_does_not_invent_one(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("capital/contribution.json"))
    message["embeds"][0]["title"] = "\u200eAurora"
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MISSING_PLAYER_TAG
    assert outcome.diagnostics[0].player_name == "Aurora"


def test_malformed_capital_message_is_a_diagnostic() -> None:
    outcome = _parse({})
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED


def test_unknown_layout_is_a_diagnostic(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/join.json"))
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNKNOWN_LAYOUT


def test_duplicate_contribution_is_deduplicated(clashperk_message: Message) -> None:
    message = clashperk_message("capital/contribution.json")
    combined = parse_all(PARSER, [message, message])
    assert len(combined.events) == 1
