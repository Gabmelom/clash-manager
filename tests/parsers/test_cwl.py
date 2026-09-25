from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from clash_reporter.events import (
    CwlAttack,
    CwlLineupChange,
    CwlMissedAttack,
    WarAttack,
    WarMissedAttacks,
)
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_UNKNOWN_LAYOUT,
    IGNORED_UNSUPPORTED_LOG,
    make_event_key,
)
from clash_reporter.parsers.cwl import CwlParser
from clash_reporter.parsers.war_layout import cwl_season_key, parse_cwl_embed
from clash_reporter.parsers.wars import WarsParser
from clash_reporter.window import parse_iso_timestamp

Message = Callable[[str], dict[str, Any]]

CWL_FIXTURES = Path("tests/fixtures/cwl")
PARSER = CwlParser()
CONTEXT_ONLY = {"embed-round.json"}


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_every_cwl_player_fixture_is_classified(clashperk_message: Message) -> None:
    paths = sorted(CWL_FIXTURES.glob("*.json"))
    assert paths, "expected cwl fixtures"
    for path in paths:
        outcome = _parse(clashperk_message(f"cwl/{path.name}"))
        if path.name in CONTEXT_ONLY:
            assert outcome.events == []
            assert outcome.diagnostics == []
            continue
        assert outcome.classified, f"{path.name} fell through unclassified"


def test_cwl_embed_exposes_round_and_is_not_a_regular_war_embed(
    clashperk_message: Message,
) -> None:
    message = clashperk_message("cwl/embed-round.json")
    ctx = parse_cwl_embed(message, message["embeds"][0])
    assert ctx is not None
    assert ctx.is_cwl
    assert ctx.round_number == 3
    assert ctx.war_id == 48220
    assert ctx.ended_at == parse_iso_timestamp("2026-08-08T06:28:00.000000+00:00")


def test_cwl_attack_is_distinct_from_war_attack(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("cwl/attack.json"))
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert isinstance(event, CwlAttack)
    assert not isinstance(event, WarAttack)
    assert event.player_name == "Everest"
    assert event.player_tag is None
    assert event.stars == 3
    assert event.destruction_percent == 100
    assert event.attacker_th == 17
    assert event.defender_th == 17
    assert event.target_position == 1
    assert event.round_number is None
    assert event.event_key == make_event_key("1535322149345696521", "CwlAttack", "Everest", 0)


def test_cwl_missed_attack_carries_round_and_season(
    clashperk_message: Message,
) -> None:
    outcome = _parse(clashperk_message("cwl/missed-attacks.json"))
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert isinstance(event, CwlMissedAttack)
    assert not isinstance(event, WarMissedAttacks)
    assert event.player_name == "Dune"
    assert event.player_tag is None
    assert event.missed_count == 1
    assert event.round_number == 3
    assert event.clan_tag == "#2QP9VL8C"
    ended = parse_iso_timestamp("2026-08-08T06:30:44.088000+00:00")
    assert event.cwl_season_or_key == cwl_season_key("#2QP9VL8C", ended)
    assert event.cwl_season_or_key == "cwl:#2QP9VL8C:2026-08"
    assert event.reporting_month == "2026-08"


def test_cwl_lineup_one_event_per_player(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("cwl/lineup-change.json"))
    assert len(outcome.events) == 2
    added, removed = outcome.events
    assert isinstance(added, CwlLineupChange)
    assert isinstance(removed, CwlLineupChange)
    assert added.player_name == "Dune"
    assert added.change_type == "added"
    assert added.round_number == 2
    assert removed.player_name == "Borealis"
    assert removed.change_type == "removed"
    assert added.event_key != removed.event_key
    assert added.cwl_season_or_key == "cwl:#2QP9VL8C:2026-08"


def test_parse_channel_groups_rounds_into_one_season(
    clashperk_message: Message,
) -> None:
    round_two = deepcopy(clashperk_message("cwl/missed-attacks.json"))
    round_two["id"] = "1535000000000000000"
    round_two["timestamp"] = "2026-08-07T06:30:00.000000+00:00"
    round_two["embeds"][0]["description"] = round_two["embeds"][0]["description"].replace(
        "CWL Round 3", "CWL Round 2"
    )
    outcome = PARSER.parse_channel(
        [
            clashperk_message("cwl/embed-round.json"),
            clashperk_message("cwl/attack.json"),
            clashperk_message("cwl/lineup-change.json"),
            round_two,
            clashperk_message("cwl/missed-attacks.json"),
        ]
    )
    seasons = {
        event.cwl_season_or_key for event in outcome.events if event.cwl_season_or_key is not None
    }
    assert seasons == {"cwl:#2QP9VL8C:2026-08"}
    attacks = [event for event in outcome.events if isinstance(event, CwlAttack)]
    assert len(attacks) == 1
    assert attacks[0].round_number == 3
    assert attacks[0].cwl_season_or_key == "cwl:#2QP9VL8C:2026-08"
    lineups = [event for event in outcome.events if isinstance(event, CwlLineupChange)]
    assert {event.round_number for event in lineups} == {2}


def test_cwl_attack_joins_via_missed_attacks_without_embed(
    clashperk_message: Message,
) -> None:
    outcome = PARSER.parse_channel(
        [
            clashperk_message("cwl/attack.json"),
            clashperk_message("cwl/missed-attacks.json"),
        ]
    )
    event = next(item for item in outcome.events if isinstance(item, CwlAttack))
    assert event.round_number == 3
    assert event.cwl_season_or_key == "cwl:#2QP9VL8C:2026-08"


def test_regular_war_payloads_are_not_cwl_types(clashperk_message: Message) -> None:
    attack = _parse(clashperk_message("wars/attack.json"))
    assert isinstance(attack.events[0], CwlAttack)
    assert not isinstance(attack.events[0], WarAttack)

    missed = _parse(clashperk_message("wars/missed-attacks.json"))
    assert missed.events == []
    assert missed.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert missed.diagnostics[0].detail == "regular_war_missed_attacks"

    embed = _parse(clashperk_message("wars/embed-final.json"))
    assert embed.diagnostics[0].detail == "regular_war_embed"


def test_unknown_embed_names_the_cwl_log_type(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("cwl/unknown-layout.json"))
    assert outcome.events == []
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.reason_code == IGNORED_UNKNOWN_LAYOUT
    assert "cwl_embed_log" in diagnostic.detail


def test_malformed_cwl_message_is_a_diagnostic() -> None:
    outcome = _parse({"id": "1", "timestamp": "nope"})
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED


def test_same_layout_yields_distinct_types_from_each_parser(
    clashperk_message: Message,
) -> None:
    raw = clashperk_message("wars/attack.json")
    war_event = WarsParser().parse(raw).events[0]
    cwl_event = PARSER.parse(raw).events[0]
    assert type(war_event) is WarAttack
    assert type(cwl_event) is CwlAttack
    assert war_event.event_type == "WarAttack"
    assert cwl_event.event_type == "CwlAttack"
