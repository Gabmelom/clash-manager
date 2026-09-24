from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from clash_reporter.events import MemberJoined, MemberLeft, PlayerNameChanged, PlayerRoleChanged
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_UNKNOWN_LAYOUT,
    IGNORED_UNSUPPORTED_LOG,
    make_event_key,
    parse_all,
)
from clash_reporter.parsers.members import MembersParser
from clash_reporter.window import parse_iso_timestamp

Message = Callable[[str], dict[str, Any]]

MEMBERS_FIXTURES = Path("tests/fixtures/members")
PARSER = MembersParser()


def _parse(message: dict[str, Any]):
    return PARSER.parse(message)


def test_every_members_fixture_is_classified(clashperk_message: Message) -> None:
    paths = sorted(MEMBERS_FIXTURES.glob("*.json"))
    assert paths, "expected members fixtures"
    for path in paths:
        outcome = _parse(clashperk_message(f"members/{path.name}"))
        assert outcome.classified, f"{path.name} fell through unclassified"


def test_join_fixture(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/join.json"))
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert isinstance(event, MemberJoined)
    assert event.player_tag == "#2Y0LRPV8Q"
    assert event.player_name == "Aurora"
    assert event.occurred_at == parse_iso_timestamp("2026-08-03T18:12:44.281000+00:00")
    assert event.source.channel_id == "400000000000000001"
    assert event.source.message_id == "1533900443745917698"
    assert event.source.parser_name == "members"
    assert event.source.parser_version == "1"
    assert event.source.message_edited_timestamp is None
    assert event.event_key == make_event_key("1533900443745917698", "MemberJoined", "#2Y0LRPV8Q")


def test_leave_fixture(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/leave.json"))
    event = outcome.events[0]
    assert isinstance(event, MemberLeft)
    assert event.player_tag == "#8QCU29VJ0"
    assert event.player_name == "Borealis"
    assert event.occurred_at == parse_iso_timestamp("2026-08-19T02:41:09.553000+00:00")


def test_leave_then_joined_another_clan_is_still_leave(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/leave.json"))
    message["embeds"][0]["footer"]["text"] = "Left Maple Legends [42/50] \nJoined Northern Lights"
    event = _parse(message).events[0]
    assert isinstance(event, MemberLeft)
    assert event.player_tag == "#8QCU29VJ0"


def test_name_change_fixture(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/name-change.json"))
    event = outcome.events[0]
    assert isinstance(event, PlayerNameChanged)
    assert event.player_tag == "#2Y0LRPV8Q"
    assert event.old_name == "AuroraBorealis"
    assert event.new_name == "Aurora"


def test_role_change_fixture_old_role_is_unknown(clashperk_message: Message) -> None:
    outcome = _parse(clashperk_message("members/role-change.json"))
    event = outcome.events[0]
    assert isinstance(event, PlayerRoleChanged)
    assert event.player_tag == "#9YLG2PJRQ"
    assert event.new_role == "Elder"
    assert event.old_role is None


def test_demotion_emits_role_changed(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/role-change.json"))
    message["embeds"][0]["description"] = "Was Demoted to **Member**"
    event = _parse(message).events[0]
    assert isinstance(event, PlayerRoleChanged)
    assert event.new_role == "Member"
    assert event.old_role is None


def test_player_tags_extracted_from_every_members_fixture(clashperk_message: Message) -> None:
    expected = {
        "join.json": "#2Y0LRPV8Q",
        "leave.json": "#8QCU29VJ0",
        "name-change.json": "#2Y0LRPV8Q",
        "role-change.json": "#9YLG2PJRQ",
    }
    for name, tag in expected.items():
        event = _parse(clashperk_message(f"members/{name}")).events[0]
        assert event.player_tag == tag


def test_parsing_the_same_message_twice_deduplicates(clashperk_message: Message) -> None:
    message = clashperk_message("members/join.json")
    first = _parse(message)
    second = _parse(message)
    assert first.events[0].event_key == second.events[0].event_key
    combined = parse_all(PARSER, [message, message])
    assert len(combined.events) == 1
    assert combined.events[0].event_key == first.events[0].event_key


def test_malformed_message_is_a_diagnostic_not_an_exception() -> None:
    for payload in (
        {},
        {"id": "1"},
        {"id": "1", "timestamp": "not-a-date"},
        {"id": "1", "embeds": []},
    ):
        outcome = _parse(payload)
        assert outcome.events == []
        assert outcome.diagnostics[0].reason_code == IGNORED_MALFORMED


def test_unknown_layout_is_a_diagnostic(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/join.json"))
    message["embeds"][0]["footer"]["text"] = "Maple Legends"
    message["embeds"][0]["description"] = "something ClashPerk has never posted"
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNKNOWN_LAYOUT


def test_name_without_tag_is_a_warning_not_an_invented_event(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/name-change.json"))
    message["embeds"][0]["title"] = "\u200eAurora"
    outcome = _parse(message)
    assert outcome.events == []
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.reason_code == IGNORED_MISSING_PLAYER_TAG
    assert diagnostic.player_name == "Aurora"
    assert diagnostic.player_tag is None


def test_join_without_tag_does_not_invent_one_from_the_button(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/join.json"))
    message["embeds"][0]["title"] = "\u200eAurora"
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_MISSING_PLAYER_TAG


@pytest.mark.parametrize(
    ("fixture", "detail"),
    [
        ("capital/contribution.json", "capital"),
        ("capital/raid-attack.json", "capital"),
    ],
)
def test_capital_logs_on_members_are_unsupported(
    clashperk_message: Message, fixture: str, detail: str
) -> None:
    outcome = _parse(clashperk_message(fixture))
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert outcome.diagnostics[0].detail == detail


def test_town_hall_upgrade_is_unsupported_not_a_join(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/name-change.json"))
    message["embeds"][0]["description"] = (
        "Town Hall was upgraded to 16 with 8.21% remaining troop upgrades."
    )
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert outcome.diagnostics[0].detail == "town_hall_upgrade"


@pytest.mark.parametrize(
    "description",
    ["**Opted in** for clan wars.", "**Opted out** of clan wars."],
)
def test_war_preference_is_unsupported_not_a_join(
    clashperk_message: Message, description: str
) -> None:
    message = deepcopy(clashperk_message("members/name-change.json"))
    message["embeds"][0]["description"] = description
    outcome = _parse(message)
    assert outcome.events == []
    assert outcome.diagnostics[0].reason_code == IGNORED_UNSUPPORTED_LOG
    assert outcome.diagnostics[0].detail == "war_preference"


def test_join_title_with_letter_o_in_tag(clashperk_message: Message) -> None:
    message = deepcopy(clashperk_message("members/join.json"))
    message["embeds"][0]["title"] = "\u200eAurora (#PccVqqGO)"
    event = _parse(message).events[0]
    assert event.player_tag == "#PCCVQQG0"
