"""Clan roster fills unmatched names and never invents a tag."""

from __future__ import annotations

from datetime import UTC, datetime

from clash_reporter.aggregation.activity import ActivityCoverage, attribute_activity
from clash_reporter.aggregation.monthly_summary import build_monthly_dataset
from clash_reporter.events import MemberJoined, MemberLeft, SourceMetadata, WarAttack
from clash_reporter.roster import RosterMember
from clash_reporter.window import month_window

WINDOW = month_window(2026, 8, timezone="America/Toronto")
AURORA = "#2Y0LRPV8Q"
QUARRY = "#QY0QRRRY"
OTHER = "#8QCU29VJ0"
WHEN = datetime(2026, 8, 10, 16, tzinfo=UTC)


def _source(message_id: str) -> SourceMetadata:
    return SourceMetadata(
        channel_id="1",
        message_id=message_id,
        message_timestamp=WHEN,
        message_edited_timestamp=None,
        parser_name="test",
        parser_version="1",
    )


def _join(tag: str, name: str, message_id: str) -> MemberJoined:
    return MemberJoined(
        player_tag=tag,
        player_name=name,
        occurred_at=WHEN,
        source=_source(message_id),
    )


def _attack(name: str, message_id: str) -> WarAttack:
    return WarAttack(
        player_name=name,
        occurred_at=WHEN,
        source=_source(message_id),
        stars=3,
        destruction_percent=100,
        war_id_or_key="war:1",
        reporting_month="2026-08",
    )


def test_roster_fills_a_unique_unmatched_name() -> None:
    events = [_join(AURORA, "Aurora", "1"), _attack("Quarry", "2")]
    result = attribute_activity(events, roster=(RosterMember(tag=QUARRY, name="Quarry"),))
    quarry = next(event for event in result.events if getattr(event, "player_name", "") == "Quarry")
    assert quarry.player_tag == QUARRY
    assert result.unmatched_names == ()
    assert result.ambiguous_names == ()


def test_roster_duplicate_names_stay_unassigned() -> None:
    events = [_attack("Twin", "2")]
    roster = (
        RosterMember(tag=QUARRY, name="Twin"),
        RosterMember(tag=OTHER, name="Twin"),
    )
    result = attribute_activity(events, roster=roster)
    attack = result.events[0]
    assert attack.player_tag is None
    assert result.unmatched_names == ()
    assert result.ambiguous_names == ("Twin",)


def test_unknown_name_is_not_invented() -> None:
    result = attribute_activity([_attack("Ghost", "2")], roster=(RosterMember(QUARRY, "Quarry"),))
    assert result.events[0].player_tag is None
    assert result.unmatched_names == ("Ghost",)


def test_discord_tag_wins_over_a_different_roster_tag() -> None:
    events = [_join(AURORA, "Aurora", "1"), _attack("Aurora", "2")]
    roster = (RosterMember(tag=OTHER, name="Aurora"),)
    result = attribute_activity(events, roster=roster)
    attack = next(event for event in result.events if event.event_type == "WarAttack")
    assert attack.player_tag == AURORA


def test_departed_player_still_uses_the_discord_leave_tag() -> None:
    leave = MemberLeft(
        player_tag=QUARRY,
        player_name="Quarry",
        occurred_at=WHEN,
        source=_source("leave"),
    )
    result = attribute_activity([leave, _attack("Quarry", "2")], roster=())
    attack = next(event for event in result.events if event.event_type == "WarAttack")
    assert attack.player_tag == QUARRY


def test_directional_mark_still_matches_the_roster_name() -> None:
    result = attribute_activity(
        [_attack("\u200eQuarry", "2")],
        roster=(RosterMember(tag=QUARRY, name="Quarry"),),
    )
    assert result.events[0].player_tag == QUARRY


def test_roster_member_with_activity_is_present_all_month() -> None:
    dataset = build_monthly_dataset(
        [_join(AURORA, "Aurora", "1"), _attack("Quarry", "2")],
        WINDOW,
        coverage=ActivityCoverage(wars=True),
        clan_roster=(RosterMember(tag=QUARRY, name="Quarry"),),
    )
    quarry = next(player for player in dataset.players if player.player_tag == QUARRY)
    assert quarry.current_display_name == "Quarry"
    assert quarry.membership.joined_this_month is False
    assert quarry.membership.departed_this_month is False
    assert quarry.membership.eligible_days == 31
    assert quarry.regular_war.attacks_used == 1
    aurora = next(player for player in dataset.players if player.player_tag == AURORA)
    assert aurora.membership.joined_this_month is True
