"""Reconstruct membership intervals and eligible days from member events.

Join/leave events are the source of truth for being in or out of the clan.
A player who appears in the window with no join event is treated as already
present at window start (they joined before the capture). Eligible days are
calendar dates in the reporting timezone, not UTC dates, clipped to the
half-open reporting window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from clash_reporter.events import (
    MemberEvent,
    MemberJoined,
    MemberLeft,
)
from clash_reporter.window import ReportingWindow

__all__ = [
    "MembershipInterval",
    "MembershipRoster",
    "MembershipWarning",
    "PlayerMembership",
    "count_eligible_days",
    "format_month_day",
    "reconstruct_membership",
]

_MONTH_ABBREV = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True)
class MembershipInterval:
    """Half-open membership span ``[start, end)`` in UTC."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class MembershipWarning:
    player_tag: str
    code: str
    detail: str


@dataclass(frozen=True)
class PlayerMembership:
    player_tag: str
    intervals: tuple[MembershipInterval, ...]
    eligible_days: int
    joined_this_month: bool
    departed_this_month: bool
    joined_on: str | None
    left_on: str | None


@dataclass(frozen=True)
class MembershipRoster:
    players: dict[str, PlayerMembership]
    warnings: tuple[MembershipWarning, ...]


def format_month_day(instant: datetime, timezone: str) -> str:
    """Format an instant as ``Aug 3`` in ``timezone`` without a locale."""
    local = instant.astimezone(ZoneInfo(timezone))
    return f"{_MONTH_ABBREV[local.month - 1]} {local.day}"


def count_eligible_days(
    intervals: Sequence[MembershipInterval],
    *,
    timezone: str,
) -> int:
    """Unique calendar dates in ``timezone`` covered by the half-open intervals."""
    zone = ZoneInfo(timezone)
    dates: set[date] = set()
    for interval in intervals:
        if interval.end <= interval.start:
            continue
        local_start = interval.start.astimezone(zone)
        last_instant = interval.end.astimezone(zone) - timedelta(microseconds=1)
        current = local_start.date()
        last = last_instant.date()
        while current <= last:
            dates.add(current)
            current += timedelta(days=1)
    return len(dates)


def reconstruct_membership(
    events: Sequence[MemberEvent],
    window: ReportingWindow,
) -> MembershipRoster:
    """Build per-tag membership for events that fall inside ``window``.

    Rules:

    - First observed event is a join: the player is out until that join.
    - First observed event is a leave: present from window start until that leave.
    - Name/role events with no join/leave: present for the whole window.
    - Leave then rejoin produces two (or more) intervals; eligible days are the union.
      ``joined_this_month`` / ``departed_this_month`` still mean presence at the
      window start / end, so a gap in the middle does not mark the player new or
      departed. Ranking depends on those flags.
    """
    grouped = _group_by_tag(events, window)
    players: dict[str, PlayerMembership] = {}
    warnings: list[MembershipWarning] = []

    for tag in sorted(grouped):
        membership, player_warnings = _reconstruct_player(tag, grouped[tag], window)
        if membership is None:
            continue
        players[tag] = membership
        warnings.extend(player_warnings)

    warnings.sort(key=lambda item: (item.player_tag, item.code, item.detail))
    return MembershipRoster(players=players, warnings=tuple(warnings))


def _group_by_tag(
    events: Sequence[MemberEvent], window: ReportingWindow
) -> dict[str, list[MemberEvent]]:
    grouped: dict[str, list[MemberEvent]] = {}
    for event in events:
        if not window.contains(event.occurred_at):
            continue
        grouped.setdefault(event.player_tag, []).append(event)
    for tag in grouped:
        grouped[tag].sort(key=lambda event: (event.occurred_at, event.event_key))
    return grouped


def _reconstruct_player(
    tag: str,
    events: Sequence[MemberEvent],
    window: ReportingWindow,
) -> tuple[PlayerMembership | None, list[MembershipWarning]]:
    join_leave = [event for event in events if isinstance(event, MemberJoined | MemberLeft)]
    warnings: list[MembershipWarning] = []

    if not join_leave:
        intervals = (MembershipInterval(start=window.start_utc, end=window.end_utc),)
        return _finalize(tag, intervals, window), warnings

    in_clan = not isinstance(join_leave[0], MemberJoined)
    current_start = window.start_utc if in_clan else None
    raw_intervals: list[MembershipInterval] = []

    for event in join_leave:
        instant = event.occurred_at.astimezone(UTC)
        if isinstance(event, MemberJoined):
            if in_clan:
                warnings.append(
                    MembershipWarning(
                        player_tag=tag,
                        code="duplicate_join",
                        detail="join event while already a member",
                    )
                )
                continue
            current_start = instant
            in_clan = True
            continue
        # MemberLeft
        if not in_clan or current_start is None:
            warnings.append(
                MembershipWarning(
                    player_tag=tag,
                    code="leave_without_open_interval",
                    detail="leave event while not a member",
                )
            )
            continue
        raw_intervals.append(MembershipInterval(start=current_start, end=instant))
        in_clan = False
        current_start = None

    if in_clan and current_start is not None:
        raw_intervals.append(MembershipInterval(start=current_start, end=window.end_utc))

    clipped = tuple(
        interval
        for interval in (_clip(item, window) for item in raw_intervals)
        if interval is not None
    )
    if not clipped:
        return None, warnings
    return _finalize(tag, clipped, window), warnings


def _clip(interval: MembershipInterval, window: ReportingWindow) -> MembershipInterval | None:
    start = max(interval.start.astimezone(UTC), window.start_utc)
    end = min(interval.end.astimezone(UTC), window.end_utc)
    if end <= start:
        return None
    return MembershipInterval(start=start, end=end)


def _finalize(
    tag: str,
    intervals: tuple[MembershipInterval, ...],
    window: ReportingWindow,
) -> PlayerMembership:
    # Flags describe window-boundary presence, not mid-month churn. A
    # leave-then-rejoin stays ranking-eligible when present at both ends.
    present_at_start = any(interval.start <= window.start_utc for interval in intervals)
    present_at_end = any(interval.end >= window.end_utc for interval in intervals)
    first = intervals[0]
    last = intervals[-1]
    joined_on = None if present_at_start else format_month_day(first.start, window.timezone)
    left_on = None if present_at_end else format_month_day(last.end, window.timezone)
    return PlayerMembership(
        player_tag=tag,
        intervals=intervals,
        eligible_days=count_eligible_days(intervals, timezone=window.timezone),
        joined_this_month=not present_at_start,
        departed_this_month=not present_at_end,
        joined_on=joined_on,
        left_on=left_on,
    )
