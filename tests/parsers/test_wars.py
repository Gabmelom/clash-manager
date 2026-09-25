from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from clash_reporter.events import CwlAttack, WarAttack, WarMissedAttacks
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_UNKNOWN_LAYOUT,
    IGNORED_UNSUPPORTED_LOG,
    WARNING_MISSING_WAR_CONTEXT,
    make_event_key,
    parse_all,
)
from clash_reporter.parsers.war_layout import (
    fallback_war_key,
    parse_missed_embed,
    parse_regular_war_embed,
    war_reporting_month,
)
from clash_reporter.parsers.wars import WarsParser
from clash_reporter.window import parse_iso_timestamp

Message = Callable[[str], dict[str, Any]]

WARS_FIXTURES = Path("tests/fixtures/wars")
PARSER = WarsParser()
CONTEXT_ONLY = {"embed-final.json"}


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_every_wars_player_fixture_is_classified(clashperk_message: Message) -> None:
    paths = sorted(WARS_FIXTURES.glob("*.json"))
    assert paths, "expected wars fixtures"
    for path in paths:
        outcome = _parse(clashperk_message(f"wars/{path.name}"))
        if path.name in CONTEXT_ONLY:
            assert outcome.events == []
            assert outcome.diagnostics == []
            continue
        assert outcome.classified, f"{path.name} fell through unclassified"


def test_war_embed_is_context_with_clashperk_war_id(clashperk_message: Message) -> None:
    message = clashperk_message("wars/embed-final.json")
    embed = message["embeds"][0]
    ctx = parse_regular_war_embed(message, embed)
    assert ctx is not None
    assert ctx.war_id == 48213
    assert ctx.clan_tag == "#2QP9VL8C"
    assert ctx.opponent_tag == "#8LQJ2CGU"
    assert ctx.is_ended
    assert ctx.ended_at == parse_iso_timestamp("2026-08-15T07:58:41.620000+00:00")


def test_attack_fixture_parses_stars_and_optional_fields(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("wars/attack.json"))
    assert [type(event).__name__ for event in outcome.events] == ["WarAttack", "WarAttack"]
    aurora, cascade = outcome.events
    assert isinstance(aurora, WarAttack)
    assert aurora.player_name == "Aurora"
    assert aurora.player_tag is None
    assert aurora.stars == 3
    assert aurora.destruction_percent == 100
    assert aurora.attacker_th == 16
    assert aurora.defender_th == 15
    assert aurora.target_position == 5
    assert aurora.war_id_or_key is None
    assert aurora.event_key == make_event_key("1537930703328123654", "WarAttack", "Aurora", 0)
    assert isinstance(cascade, WarAttack)
    assert cascade.player_name == "Cascade"
    assert cascade.stars == 2
    assert cascade.destruction_percent == 71
    assert cascade.attacker_th == 15
    assert cascade.defender_th == 16
    assert cascade.target_position == 4
    assert cascade.event_index == 1
    assert cascade.event_key != aurora.event_key


def test_missing_destruction_and_town_hall_stay_none(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("wars/attack-missing-fields.json"))
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert isinstance(event, WarAttack)
    assert event.player_name == "Cascade"
    assert event.stars == 2
    assert event.destruction_percent is None
    assert event.attacker_th is None
    assert event.defender_th is None
    assert event.destruction_percent != 0
    assert event.attacker_th != 0
    assert event.defender_th != 0


def test_zero_stars_is_observed_zero_not_unknown(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("wars/attack-missing-fields.json"))
    message["content"] = (
        "<:Grey:1449493203618238637><:Grey:1449493203618238637>"
        "<:Grey:1449493203618238637> `0%` <:7:813694740250886164>"
        "<:15:813693003269013594> ‎Cascade <:ArwRight:1449761016324821205>"
        "<:4:813694738921160755><:16:813693003243061289>"
    )
    event = _parse(message).events[0]
    assert isinstance(event, WarAttack)
    assert event.stars == 0
    assert event.destruction_percent == 0
    assert event.stars is not None


def test_missed_attacks_one_event_per_player(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("wars/missed-attacks.json"))
    assert len(outcome.events) == 2
    dune, cascade = outcome.events
    assert isinstance(dune, WarMissedAttacks)
    assert isinstance(cascade, WarMissedAttacks)
    assert dune.player_name == "Dune"
    assert dune.missed_count == 2
    assert cascade.player_name == "Cascade"
    assert cascade.missed_count == 1
    assert dune.player_tag is None
    assert cascade.player_tag is None
    assert dune.event_key != cascade.event_key
    assert dune.event_key == make_event_key("1538094951127718663", "WarMissedAttacks", "Dune", 0)
    assert cascade.event_key == make_event_key(
        "1538094951127718663", "WarMissedAttacks", "Cascade", 1
    )
    # Clan tag in the embed title is not a player identity.
    assert dune.clan_tag == "#2QP9VL8C"
    assert dune.opponent_tag == "#8LQJ2CGU"
    expected = fallback_war_key(
        "#2QP9VL8C",
        "#8LQJ2CGU",
        parse_iso_timestamp("2026-08-15T08:00:12.771000+00:00"),
    )
    assert dune.war_id_or_key == expected
    assert cascade.war_id_or_key == expected
    assert dune.reporting_month == "2026-08"


def test_parse_channel_joins_attacks_and_misses_via_embed(
    clashperk_message: Message,
) -> None:
    outcome = PARSER.parse_channel(
        [
            clashperk_message("wars/embed-final.json"),
            clashperk_message("wars/attack.json"),
            clashperk_message("wars/missed-attacks.json"),
        ]
    )
    keys = {event.war_id_or_key for event in outcome.events}
    assert keys == {"war:48213"}
    months = {event.reporting_month for event in outcome.events}
    assert months == {"2026-08"}
    assert all(event.ended_at is not None for event in outcome.events)


def test_fallback_without_embed_has_its_own_key(clashperk_message: Message) -> None:
    outcome = PARSER.parse_channel(
        [
            clashperk_message("wars/attack.json"),
            clashperk_message("wars/missed-attacks.json"),
        ]
    )
    expected = fallback_war_key(
        "#2QP9VL8C",
        "#8LQJ2CGU",
        parse_iso_timestamp("2026-08-15T08:00:12.771000+00:00"),
    )
    assert {event.war_id_or_key for event in outcome.events} == {expected}
    attacks = [event for event in outcome.events if isinstance(event, WarAttack)]
    assert attacks
    assert all(event.war_id_or_key == expected for event in attacks)
    assert all(event.reporting_month == "2026-08" for event in outcome.events)


def test_war_that_starts_in_july_is_attributed_to_august_when_it_ends(
    clashperk_message: Message,
) -> None:
    embed = deepcopy(clashperk_message("wars/embed-final.json"))
    attack = deepcopy(clashperk_message("wars/attack.json"))
    missed = deepcopy(clashperk_message("wars/missed-attacks.json"))
    embed["timestamp"] = "2026-07-31T19:30:00.000000+00:00"
    embed["edited_timestamp"] = "2026-08-01T08:00:00.000000+00:00"
    embed["embeds"][0]["timestamp"] = "2026-08-01T08:00:00.000000+00:00"
    attack["timestamp"] = "2026-07-31T22:15:00.000000+00:00"
    missed["timestamp"] = "2026-08-01T08:05:00.000000+00:00"

    ended = parse_iso_timestamp("2026-08-01T08:00:00.000000+00:00")
    assert war_reporting_month(ended) == "2026-08"
    july_start = parse_iso_timestamp("2026-07-31T19:30:00.000000+00:00")
    assert war_reporting_month(july_start) == "2026-07"

    outcome = PARSER.parse_channel([embed, attack, missed])
    assert {event.reporting_month for event in outcome.events} == {"2026-08"}
    assert {event.war_id_or_key for event in outcome.events} == {"war:48213"}
    for event in outcome.events:
        assert event.ended_at is not None
        assert event.ended_at.month == 8


def test_cwl_payloads_are_not_merged_into_regular_war(
    clashperk_message: Message,
) -> None:
    attack = _parse(clashperk_message("cwl/attack.json"))
    assert len(attack.events) == 1
    assert isinstance(attack.events[0], WarAttack)
    assert not isinstance(attack.events[0], CwlAttack)

    missed = _parse(clashperk_message("cwl/missed-attacks.json"))
    assert missed.events == []
    assert missed.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert missed.diagnostics[0].detail == "cwl_missed_attacks"

    lineup = _parse(clashperk_message("cwl/lineup-change.json"))
    assert lineup.diagnostics[0].detail == "cwl_lineup"

    embed = _parse(clashperk_message("cwl/embed-round.json"))
    assert embed.diagnostics[0].detail == "cwl_embed"


def test_unknown_embed_names_the_log_type(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("wars/unknown-layout.json"))
    assert outcome.events == []
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.reason_code == IGNORED_UNKNOWN_LAYOUT
    assert "war_log" in diagnostic.detail


def test_malformed_message_is_a_diagnostic_not_an_exception() -> None:
    for payload in (
        {},
        {"id": "1"},
        {"id": "1", "timestamp": "not-a-date"},
        {"id": "1", "embeds": [], "content": ""},
    ):
        outcome = _parse(payload)
        assert outcome.events == []
        assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED


def test_duplicate_missed_message_deduplicates_all_rows(
    clashperk_message: Message,
) -> None:
    message = clashperk_message("wars/missed-attacks.json")
    combined = parse_all(PARSER, [message, message])
    assert len(combined.events) == 2


def test_attack_without_war_context_is_diagnosed(clashperk_message: Message) -> None:
    outcome = PARSER.parse_channel([clashperk_message("wars/attack.json")])
    attacks = [event for event in outcome.events if isinstance(event, WarAttack)]
    assert attacks
    assert all(event.war_id_or_key is None for event in attacks)
    assert any(item.reason_code == WARNING_MISSING_WAR_CONTEXT for item in outcome.diagnostics)
    # Attack is still emitted; the diagnostic is a join warning, not a drop.


def test_defense_line_is_not_a_clan_attack(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("wars/attack.json"))
    message["content"] = message["content"].replace("ArwRight", "ArwLeft")
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert outcome.diagnostics[0].detail == "war_defense"


def test_reporting_month_helper_uses_end_not_start() -> None:
    start = datetime.fromisoformat("2026-07-31T23:00:00+00:00")
    end = datetime.fromisoformat("2026-08-01T01:00:00+00:00")
    assert war_reporting_month(start) == "2026-07"
    assert war_reporting_month(end) == "2026-08"


def test_cwl_missed_without_round_text_is_not_flagged_cwl(
    clashperk_message: Message,
) -> None:
    message = deepcopy(clashperk_message("cwl/missed-attacks.json"))
    message["embeds"][0]["description"] = message["embeds"][0]["description"].replace(
        " (CWL Round 3)", ""
    )
    parsed = parse_missed_embed(message["embeds"][0])
    assert parsed is not None
    assert parsed.is_cwl is False
    assert parsed.round_number is None
    # WarsParser would then accept it as a regular-war miss; CwlParser rejects
    # it as regular_war_missed_attacks. Channel routing is the V1 guarantee.
    outcome = _parse(message)
    assert len(outcome.events) == 1
    assert isinstance(outcome.events[0], WarMissedAttacks)
