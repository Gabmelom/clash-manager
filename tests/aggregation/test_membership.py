from __future__ import annotations

from datetime import UTC, datetime

from clash_reporter.aggregation.membership import reconstruct_membership
from clash_reporter.aggregation.monthly_summary import (
    MEMBERS_ONLY_NOTE,
    build_monthly_dataset,
    latest_display_name,
)
from clash_reporter.config import ScoringConfig
from clash_reporter.events import (
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
    SourceMetadata,
)
from clash_reporter.scoring import rank_players
from clash_reporter.window import month_window

TORONTO = "America/Toronto"
AUGUST = month_window(2026, 8, timezone=TORONTO)
MARCH = month_window(2026, 3, timezone=TORONTO)

AURORA = "#2Y0LRPV8Q"
BOREALIS = "#8QCU29VJ0"
CASCADE = "#9YLG2PJRQ"
DUNE = "#2P0CQ9LUR"


def utc(year: int, month: int, day: int, hour: int = 16, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _source(message_id: str, at: datetime) -> SourceMetadata:
    return SourceMetadata(
        channel_id="400000000000000001",
        message_id=message_id,
        message_timestamp=at,
        message_edited_timestamp=None,
        parser_name="members",
        parser_version="1",
    )


def joined(tag: str, name: str, at: datetime, message_id: str) -> MemberJoined:
    return MemberJoined(
        player_tag=tag, player_name=name, occurred_at=at, source=_source(message_id, at)
    )


def left(tag: str, name: str, at: datetime, message_id: str) -> MemberLeft:
    return MemberLeft(
        player_tag=tag, player_name=name, occurred_at=at, source=_source(message_id, at)
    )


def renamed(
    tag: str, old_name: str, new_name: str, at: datetime, message_id: str
) -> PlayerNameChanged:
    return PlayerNameChanged(
        player_tag=tag,
        old_name=old_name,
        new_name=new_name,
        occurred_at=at,
        source=_source(message_id, at),
    )


def role_changed(
    tag: str, name: str, new_role: str, at: datetime, message_id: str
) -> PlayerRoleChanged:
    return PlayerRoleChanged(
        player_tag=tag,
        player_name=name,
        new_role=new_role,
        occurred_at=at,
        source=_source(message_id, at),
    )


def _members_month_events():
    return [
        joined(AURORA, "Aurora", utc(2026, 8, 3, 18, 12), "join-aurora"),
        renamed(AURORA, "Aurora", "AuroraPrime", utc(2026, 8, 22, 9, 33), "rename-aurora"),
        left(BOREALIS, "Borealis", utc(2026, 8, 19, 16), "leave-borealis"),
        role_changed(CASCADE, "Cascade", "Elder", utc(2026, 8, 11, 14, 5), "role-cascade"),
        left(DUNE, "Dune", utc(2026, 8, 8), "dune-leave"),
        joined(DUNE, "Dune", utc(2026, 8, 15), "dune-join"),
    ]


def test_join_mid_month_counts_from_join_day() -> None:
    at = utc(2026, 8, 3, 18, 12)
    roster = reconstruct_membership([joined(AURORA, "Aurora", at, "join-aurora")], AUGUST)
    player = roster.players[AURORA]
    assert player.joined_this_month is True
    assert player.departed_this_month is False
    assert player.joined_on == "Aug 3"
    assert player.left_on is None
    assert player.eligible_days == 29


def test_leave_mid_month_counts_from_window_start() -> None:
    roster = reconstruct_membership(
        [left(BOREALIS, "Borealis", utc(2026, 8, 19, 16), "leave-borealis")],
        AUGUST,
    )
    player = roster.players[BOREALIS]
    assert player.joined_this_month is False
    assert player.departed_this_month is True
    assert player.left_on == "Aug 19"
    assert player.joined_on is None
    assert player.eligible_days == 19


def test_leave_then_rejoin_unions_interval_days() -> None:
    roster = reconstruct_membership(
        [
            left(DUNE, "Dune", utc(2026, 8, 8), "dune-leave"),
            joined(DUNE, "Dune", utc(2026, 8, 15), "dune-join"),
        ],
        AUGUST,
    )
    player = roster.players[DUNE]
    assert player.joined_this_month is False
    assert player.departed_this_month is False
    assert player.joined_on is None
    assert player.left_on is None
    assert len(player.intervals) == 2
    assert player.eligible_days == 25


def test_player_present_entire_window_with_no_join_event() -> None:
    roster = reconstruct_membership(
        [renamed(CASCADE, "CascadeOld", "Cascade", utc(2026, 8, 11, 14, 5), "cascade-name")],
        AUGUST,
    )
    player = roster.players[CASCADE]
    assert player.joined_this_month is False
    assert player.departed_this_month is False
    assert player.eligible_days == 31
    assert player.joined_on is None
    assert player.left_on is None


def test_role_change_without_join_is_present_all_month() -> None:
    roster = reconstruct_membership(
        [role_changed(CASCADE, "Cascade", "Elder", utc(2026, 8, 11), "cascade-role")],
        AUGUST,
    )
    assert roster.players[CASCADE].eligible_days == 31


def test_eligible_days_uses_report_timezone_not_utc() -> None:
    # 02:41 UTC on 19 Aug is still 22:41 on 18 Aug in America/Toronto (EDT, UTC-4).
    leave_at = datetime(2026, 8, 19, 2, 41, 9, tzinfo=UTC)
    roster = reconstruct_membership(
        [left(BOREALIS, "Borealis", leave_at, "leave-late-utc")],
        AUGUST,
    )
    player = roster.players[BOREALIS]
    assert player.left_on == "Aug 18"
    assert player.eligible_days == 18


def test_event_before_toronto_window_is_excluded() -> None:
    early_join = joined(AURORA, "Aurora", datetime(2026, 8, 1, 2, tzinfo=UTC), "too-early")
    roster = reconstruct_membership([early_join], AUGUST)
    assert AURORA not in roster.players


def test_dst_month_still_counts_calendar_days_not_hours() -> None:
    roster = reconstruct_membership(
        [renamed(CASCADE, "Old", "Cascade", utc(2026, 3, 20), "march-name")],
        MARCH,
    )
    assert roster.players[CASCADE].eligible_days == 31


def test_duplicate_join_while_in_clan_is_a_warning() -> None:
    roster = reconstruct_membership(
        [
            joined(AURORA, "Aurora", utc(2026, 8, 3), "join-1"),
            joined(AURORA, "Aurora", utc(2026, 8, 10), "join-2"),
        ],
        AUGUST,
    )
    assert roster.players[AURORA].eligible_days == 29
    assert any(item.code == "duplicate_join" for item in roster.warnings)


def test_name_change_during_month_updates_display_name() -> None:
    events = _members_month_events()
    aurora_events = [event for event in events if event.player_tag == AURORA]
    assert latest_display_name(aurora_events) == "AuroraPrime"
    dataset = build_monthly_dataset(events, AUGUST)
    aurora = next(player for player in dataset.players if player.player_tag == AURORA)
    assert aurora.current_display_name == "AuroraPrime"


def test_players_are_keyed_by_tag_and_sorted() -> None:
    dataset = build_monthly_dataset(_members_month_events(), AUGUST)
    tags = [player.player_tag for player in dataset.players]
    assert tags == sorted(tags)
    assert set(tags) == {AURORA, BOREALIS, CASCADE, DUNE}


def test_activity_metrics_stay_missing_not_zero() -> None:
    dataset = build_monthly_dataset(_members_month_events(), AUGUST)
    assert dataset.regular_wars == 0
    assert dataset.cwl_rounds == 0
    assert dataset.clan_games_completed is False
    assert MEMBERS_ONLY_NOTE in dataset.data_notes
    for player in dataset.players:
        assert player.regular_war.attacks_available is None
        assert player.regular_war.attacks_used is None
        assert player.regular_war.attacks_missed is None
        assert player.regular_war.total_stars is None
        assert player.regular_war.average_stars is None
        assert player.cwl.attacks_available is None
        assert player.cwl.attacks_missed is None
        assert player.clan_games.points is None
        assert player.capital.contribution is None
        assert player.capital.raid_attacks is None


def test_empty_war_month_does_not_flag_anyone_for_review() -> None:
    dataset = build_monthly_dataset(_members_month_events(), AUGUST)
    ranked = rank_players(dataset, ScoringConfig())
    assert ranked.ranked, "expected ranking-eligible members from membership alone"
    assert ranked.review == []
    for player in ranked.ranked:
        assert player.review_reasons == []
        assert player.summary.regular_war.attacks_missed is None
        assert player.summary.capital.contribution is None


def test_departed_and_full_month_membership_flags() -> None:
    dataset = build_monthly_dataset(_members_month_events(), AUGUST)
    by_tag = {player.player_tag: player for player in dataset.players}
    assert by_tag[AURORA].membership.joined_this_month is True
    assert by_tag[BOREALIS].membership.departed_this_month is True
    assert by_tag[CASCADE].membership.joined_this_month is False
    assert by_tag[CASCADE].membership.departed_this_month is False
    assert by_tag[CASCADE].membership.eligible_days == 31
    assert by_tag[DUNE].membership.joined_this_month is False
    assert by_tag[DUNE].membership.departed_this_month is False
