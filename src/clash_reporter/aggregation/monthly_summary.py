"""Build a ``MonthlyDataset`` from members events.

Activity families that have no parser yet (regular war, CWL, Clan Games,
capital, donations) are left missing: optional numeric fields stay ``None``.
``RegularWar.wars_participated`` and ``Cwl.rounds_in_lineup`` stay at the
model default of ``0`` because those fields are non-optional ints; the
dataset ``data_notes`` record that those counts were not parsed.
"""

from __future__ import annotations

from collections.abc import Sequence

from clash_reporter.aggregation.membership import (
    MembershipRoster,
    PlayerMembership,
    reconstruct_membership,
)
from clash_reporter.events import (
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
)
from clash_reporter.models import (
    Capital,
    ClanGames,
    Cwl,
    Membership,
    MonthlyDataset,
    MonthlyPlayerSummary,
    RegularWar,
)
from clash_reporter.parsers.base import DomainEvent, IgnoredMessage
from clash_reporter.window import ReportingWindow

__all__ = ["MEMBERS_ONLY_NOTE", "build_monthly_dataset", "latest_display_name"]

MEMBERS_ONLY_NOTE = (
    "Members-only normalize (partial #11): war, CWL, Clan Games, capital, and "
    "donation parsers are not wired. Per-player attack, Clan Games, and capital "
    "metrics are missing (null), not observed zeros."
)


def latest_display_name(events: Sequence[DomainEvent]) -> str | None:
    """Display name from the latest in-window event that carries one.

    Chronological last-write-wins: a later join, leave, or role change overwrites
    an earlier name-change, matching the name ClashPerk put on that later log.
    """
    name: str | None = None
    for event in sorted(events, key=lambda item: (item.occurred_at, item.event_key)):
        if isinstance(event, PlayerNameChanged) and event.new_name:
            name = event.new_name
        elif isinstance(event, MemberJoined | MemberLeft) and event.player_name:
            name = event.player_name
        elif isinstance(event, PlayerRoleChanged) and event.player_name:
            name = event.player_name
    return name


def build_monthly_dataset(
    events: Sequence[DomainEvent],
    window: ReportingWindow,
    *,
    diagnostics: Sequence[IgnoredMessage] = (),
    unused_channels: Sequence[str] = (),
    extra_notes: Sequence[str] = (),
    clan_name: str = "Clan",
) -> MonthlyDataset:
    """Players keyed by tag, membership filled, activity metrics left missing."""
    member_events = [
        event
        for event in events
        if isinstance(event, MemberJoined | MemberLeft | PlayerNameChanged | PlayerRoleChanged)
    ]
    roster = reconstruct_membership(member_events, window)
    events_by_tag = _events_by_tag(events, window)
    players = [
        _player_summary(membership, events_by_tag.get(tag, ()))
        for tag, membership in roster.players.items()
    ]
    notes = _data_notes(diagnostics, unused_channels, roster, events_by_tag)
    notes.extend(extra_notes)
    return MonthlyDataset(
        month_label=window.month_label,
        clan_name=clan_name,
        regular_wars=0,
        cwl_rounds=0,
        clan_games_completed=False,
        raid_weekends=0,
        players=players,
        data_notes=notes,
    )


def _events_by_tag(
    events: Sequence[DomainEvent], window: ReportingWindow
) -> dict[str, list[DomainEvent]]:
    grouped: dict[str, list[DomainEvent]] = {}
    for event in events:
        if not window.contains(event.occurred_at):
            continue
        tag = event.player_tag
        if tag is None:
            continue
        grouped.setdefault(tag, []).append(event)
    return grouped


def _player_summary(
    membership: PlayerMembership, events: Sequence[DomainEvent]
) -> MonthlyPlayerSummary:
    name = latest_display_name(events)
    warnings: list[str] = []
    if name is None:
        warnings.append("display name missing; using player tag")
        name = membership.player_tag
    if len(membership.intervals) > 1:
        warnings.append(
            "left and rejoined during the month; ranking uses presence at month "
            "start/end, not mid-month gaps"
        )
    return MonthlyPlayerSummary(
        player_tag=membership.player_tag,
        current_display_name=name,
        membership=Membership(
            eligible_days=membership.eligible_days,
            joined_this_month=membership.joined_this_month,
            departed_this_month=membership.departed_this_month,
            left_on=membership.left_on,
            joined_on=membership.joined_on,
        ),
        regular_war=RegularWar(),
        cwl=Cwl(),
        clan_games=ClanGames(points=None),
        capital=Capital(contribution=None, raid_attacks=None),
        warnings=warnings,
    )


def _data_notes(
    diagnostics: Sequence[IgnoredMessage],
    unused_channels: Sequence[str],
    roster: MembershipRoster,
    events_by_tag: dict[str, list[DomainEvent]],
) -> list[str]:
    notes = [MEMBERS_ONLY_NOTE]
    if diagnostics:
        notes.append(_summarize_diagnostics(diagnostics))
    for name in unused_channels:
        notes.append(
            f"{name}.json is present but not parsed; that log family's parser is not wired yet."
        )
    inferred = sum(
        1
        for tag in roster.players
        if not any(isinstance(event, MemberJoined) for event in events_by_tag.get(tag, ()))
    )
    if inferred:
        notes.append(
            f"{inferred} player(s) had no join event in the window and were treated "
            "as present from the start of the month."
        )
    for warning in roster.warnings:
        notes.append(f"{warning.player_tag}: {warning.detail}")
    return notes


def _summarize_diagnostics(diagnostics: Sequence[IgnoredMessage]) -> str:
    counts: dict[str, int] = {}
    for item in diagnostics:
        counts[item.reason_code] = counts.get(item.reason_code, 0) + 1
    parts = [f"{count} {code}" for code, count in sorted(counts.items())]
    return "Ignored #cp-members messages: " + ", ".join(parts) + "."
