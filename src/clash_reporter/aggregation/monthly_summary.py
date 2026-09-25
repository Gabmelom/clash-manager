"""Build a ``MonthlyDataset`` from parsed events.

Membership still comes only from member logs. Activity metrics are filled from
war, CWL, Clan Games, capital, and donation events when those channels were
parsed. A family that was not parsed stays missing (``None``), and the dataset
notes say so. Observed zeros stay ``0``.
"""

from __future__ import annotations

from collections.abc import Sequence

from clash_reporter.aggregation.activity import (
    ActivityCoverage,
    attribute_activity,
    clan_totals,
    miss_log_keys,
    player_activity,
)
from clash_reporter.aggregation.membership import (
    MembershipRoster,
    PlayerMembership,
    reconstruct_membership,
)
from clash_reporter.events import (
    MemberEvent,
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
)
from clash_reporter.models import Membership, MonthlyDataset, MonthlyPlayerSummary
from clash_reporter.parsers.base import DomainEvent, IgnoredMessage
from clash_reporter.window import ReportingWindow

__all__ = [
    "MEMBERS_ONLY_NOTE",
    "MISSING_CHANNEL_NOTE",
    "build_monthly_dataset",
    "event_in_window",
    "latest_display_name",
]

MEMBERS_ONLY_NOTE = (
    "Members-only normalize (partial #11): war, CWL, Clan Games, capital, and "
    "donation parsers are not wired. Per-player attack, Clan Games, and capital "
    "metrics are missing (null), not observed zeros."
)

_CHANNEL_LABELS = {
    "wars": "regular war",
    "cwl": "CWL",
    "clan-games": "Clan Games",
    "capital": "capital",
    "donations": "donation",
}


def MISSING_CHANNEL_NOTE(channel: str) -> str:
    """Data note when a fetch file was not in the input directory."""
    label = _CHANNEL_LABELS.get(channel, channel)
    return f"{channel}.json is missing; {label} metrics are unknown (null), not observed zeros."


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


def event_in_window(event: DomainEvent, window: ReportingWindow) -> bool:
    """Whether an event belongs to this report.

    Wars and CWL use ``reporting_month`` (UTC month of war end) when the parser
    set it. Clan Games uses ``occurred_at``, which the parser sets to the
    leaderboard edit time (when the snapshot was finalized), not
    ``occurrence_key`` (the season id) and not message creation. An August
    season edited on 1 September belongs to September. Every other family
    uses the event timestamp against the reporting window.
    """
    reporting_month = getattr(event, "reporting_month", None)
    if isinstance(reporting_month, str) and reporting_month:
        return reporting_month == window.month_key
    return window.contains(event.occurred_at)


def build_monthly_dataset(
    events: Sequence[DomainEvent],
    window: ReportingWindow,
    *,
    diagnostics: Sequence[IgnoredMessage] = (),
    missing_channels: Sequence[str] = (),
    coverage: ActivityCoverage | None = None,
    extra_notes: Sequence[str] = (),
    clan_name: str = "Clan",
) -> MonthlyDataset:
    """Players keyed by tag. Activity is filled when ``coverage`` says it was parsed."""
    in_window = [event for event in events if event_in_window(event, window)]
    attributed = attribute_activity(in_window) if coverage is not None else None
    activity_events = attributed.events if attributed is not None else in_window
    member_events = _member_events(activity_events)
    roster = reconstruct_membership(member_events, window)
    events_by_tag = _events_by_tag(activity_events)
    war_miss_keys, cwl_miss_keys = miss_log_keys(activity_events)
    players = [
        _player_summary(
            membership,
            events_by_tag.get(tag, ()),
            coverage,
            war_miss_keys=war_miss_keys,
            cwl_miss_keys=cwl_miss_keys,
        )
        for tag, membership in roster.players.items()
    ]
    regular_wars, cwl_rounds, games_done, raid_weekends = (0, 0, False, 0)
    if coverage is not None:
        regular_wars, cwl_rounds, games_done, raid_weekends = clan_totals(activity_events)
        if not coverage.wars:
            regular_wars = 0
        if not coverage.cwl:
            cwl_rounds = 0
        if not coverage.clan_games:
            games_done = False
        if not coverage.capital:
            raid_weekends = 0
    notes = _data_notes(
        diagnostics,
        missing_channels,
        coverage,
        roster,
        events_by_tag,
        () if attributed is None else attributed.unmatched_names,
        () if attributed is None else attributed.ambiguous_names,
    )
    notes.extend(extra_notes)
    return MonthlyDataset(
        month_label=window.month_label,
        clan_name=clan_name,
        regular_wars=regular_wars,
        cwl_rounds=cwl_rounds,
        clan_games_completed=games_done,
        raid_weekends=raid_weekends,
        players=players,
        data_notes=notes,
    )


def _member_events(events: Sequence[DomainEvent]) -> list[MemberEvent]:
    """Membership rows only; name-only war/CWL/games/capital/donation events stay out."""
    members: list[MemberEvent] = []
    for event in events:
        if isinstance(event, MemberJoined | MemberLeft | PlayerNameChanged | PlayerRoleChanged):
            members.append(event)
    return members


def _events_by_tag(events: Sequence[DomainEvent]) -> dict[str, list[DomainEvent]]:
    grouped: dict[str, list[DomainEvent]] = {}
    for event in events:
        tag = event.player_tag
        if tag is None:
            continue
        grouped.setdefault(tag, []).append(event)
    return grouped


def _player_summary(
    membership: PlayerMembership,
    events: Sequence[DomainEvent],
    coverage: ActivityCoverage | None,
    *,
    war_miss_keys: set[str] | None = None,
    cwl_miss_keys: set[str] | None = None,
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
    if coverage is None:
        war, cwl, games, capital, donations = player_activity((), coverage=ActivityCoverage())
    else:
        war, cwl, games, capital, donations = player_activity(
            events,
            coverage=coverage,
            war_miss_keys=war_miss_keys,
            cwl_miss_keys=cwl_miss_keys,
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
        regular_war=war,
        cwl=cwl,
        clan_games=games,
        capital=capital,
        donations=donations,
        warnings=warnings,
    )


def _data_notes(
    diagnostics: Sequence[IgnoredMessage],
    missing_channels: Sequence[str],
    coverage: ActivityCoverage | None,
    roster: MembershipRoster,
    events_by_tag: dict[str, list[DomainEvent]],
    unmatched_names: Sequence[str],
    ambiguous_names: Sequence[str],
) -> list[str]:
    notes: list[str] = []
    if coverage is None:
        notes.append(MEMBERS_ONLY_NOTE)
    else:
        for name in missing_channels:
            notes.append(MISSING_CHANNEL_NOTE(name))
    if diagnostics:
        notes.append(_summarize_diagnostics(diagnostics, members_only=coverage is None))
    if unmatched_names:
        names = ", ".join(unmatched_names)
        notes.append(
            f"Unmatched display names (no unique member tag): {names}. "
            "Their activity was not assigned to a player."
        )
    if ambiguous_names:
        names = ", ".join(ambiguous_names)
        notes.append(
            f"Ambiguous display names (more than one member tag): {names}. "
            "Their activity was not assigned to a player."
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


def _summarize_diagnostics(diagnostics: Sequence[IgnoredMessage], *, members_only: bool) -> str:
    counts: dict[str, int] = {}
    for item in diagnostics:
        counts[item.reason_code] = counts.get(item.reason_code, 0) + 1
    parts = [f"{count} {code}" for code, count in sorted(counts.items())]
    prefix = "Ignored #members messages" if members_only else "Parser diagnostics"
    return prefix + ": " + ", ".join(parts) + "."
