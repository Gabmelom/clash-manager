"""Fold parsed war, CWL, Clan Games, capital, and donation events into metrics.

Name-only rows are attached to a player tag only when that display name maps to
exactly one tag from in-window member or per-player capital logs. A duplicate
or unknown name stays unattributed. Weekly capital rows are raid-weekend
context and are not added to per-player contribution or raid totals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from clash_reporter.events import (
    CapitalContribution,
    CapitalRaidAttack,
    CapitalWeeklySummaryRow,
    ClanGamesResult,
    CwlAttack,
    CwlLineupChange,
    CwlMissedAttack,
    DonationSummary,
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
    WarAttack,
    WarMissedAttacks,
)
from clash_reporter.models import Capital, ClanGames, Cwl, Donations, RegularWar
from clash_reporter.parsers.base import DomainEvent

__all__ = [
    "ActivityCoverage",
    "AttributedActivity",
    "attribute_activity",
    "clan_totals",
    "miss_log_keys",
    "player_activity",
]

_INTERVAL_RANK = {"monthly": 0, "weekly": 1, "daily": 2}


@dataclass(frozen=True)
class ActivityCoverage:
    """Which channel files were present and parsed for this normalize run."""

    wars: bool = False
    cwl: bool = False
    clan_games: bool = False
    capital: bool = False
    donations: bool = False

    @property
    def any_parsed(self) -> bool:
        return self.wars or self.cwl or self.clan_games or self.capital or self.donations


@dataclass(frozen=True)
class AttributedActivity:
    events: list[DomainEvent]
    unmatched_names: tuple[str, ...]
    ambiguous_names: tuple[str, ...]


@dataclass
class _WarBucket:
    used: int = 0
    missed: int = 0
    saw_miss_log: bool = False
    stars: list[int] = field(default_factory=list)
    stars_incomplete: bool = False
    destruction: list[int] = field(default_factory=list)
    destruction_incomplete: bool = False


def attribute_activity(events: Sequence[DomainEvent]) -> AttributedActivity:
    """Copy name-only events onto a tag when the display name is unique."""
    index, ambiguous = _name_index(events)
    attributed: list[DomainEvent] = []
    unmatched: set[str] = set()
    for event in events:
        if event.player_tag or not _needs_name(event):
            attributed.append(event)
            continue
        name = getattr(event, "player_name", None)
        if not isinstance(name, str):
            attributed.append(event)
            continue
        if name in ambiguous:
            attributed.append(event)
            continue
        tag = index.get(name)
        if tag is None:
            unmatched.add(name)
            attributed.append(event)
            continue
        attributed.append(event.model_copy(update={"player_tag": tag}))
    return AttributedActivity(
        events=attributed,
        unmatched_names=tuple(sorted(unmatched)),
        ambiguous_names=tuple(sorted(ambiguous)),
    )


def clan_totals(events: Sequence[DomainEvent]) -> tuple[int, int, bool, int]:
    """``regular_wars``, ``cwl_rounds``, ``clan_games_completed``, ``raid_weekends``."""
    wars = {_war_key(event) for event in events if isinstance(event, WarAttack | WarMissedAttacks)}
    rounds = {
        _cwl_round_key(event)
        for event in events
        if isinstance(event, CwlAttack | CwlMissedAttack | CwlLineupChange)
    }
    games = any(isinstance(event, ClanGamesResult) for event in events)
    weekends = {
        event.raid_weekend_key
        for event in events
        if isinstance(event, CapitalRaidAttack | CapitalWeeklySummaryRow) and event.raid_weekend_key
    }
    return len(wars), len(rounds), games, len(weekends)


def player_activity(
    events: Sequence[DomainEvent],
    *,
    coverage: ActivityCoverage,
    war_miss_keys: set[str] | None = None,
    cwl_miss_keys: set[str] | None = None,
) -> tuple[RegularWar, Cwl, ClanGames, Capital, Donations]:
    """Per-player metrics. Unparsed families stay at model defaults (missing)."""
    war = (
        _regular_war(events, war_miss_keys or set())
        if _covered(coverage.wars, events, (WarAttack, WarMissedAttacks))
        else RegularWar()
    )
    cwl = (
        _cwl(events, cwl_miss_keys or set())
        if _covered(coverage.cwl, events, (CwlAttack, CwlMissedAttack, CwlLineupChange))
        else Cwl()
    )
    games = (
        _clan_games(events)
        if _covered(coverage.clan_games, events, (ClanGamesResult,))
        else ClanGames(points=None)
    )
    capital = (
        _capital(events)
        if _covered(coverage.capital, events, (CapitalContribution, CapitalRaidAttack))
        else Capital(contribution=None, raid_attacks=None)
    )
    donations = Donations()
    if _covered(coverage.donations, events, (DonationSummary,)):
        donations = _donations(events)
    if coverage.wars and not _has(events, (WarAttack, WarMissedAttacks)):
        war = RegularWar(wars_participated=0)
    if coverage.cwl and not _has(events, (CwlAttack, CwlMissedAttack, CwlLineupChange)):
        cwl = Cwl(rounds_in_lineup=0)
    return war, cwl, games, capital, donations


def miss_log_keys(events: Sequence[DomainEvent]) -> tuple[set[str], set[str]]:
    """War and CWL keys that have a missed-attack log in this window."""
    wars = {_war_key(event) for event in events if isinstance(event, WarMissedAttacks)}
    rounds = {_cwl_round_key(event) for event in events if isinstance(event, CwlMissedAttack)}
    return wars, rounds


def _regular_war(events: Sequence[DomainEvent], miss_keys: set[str]) -> RegularWar:
    buckets: dict[str, _WarBucket] = {}
    for event in events:
        if isinstance(event, WarAttack):
            bucket = buckets.setdefault(_war_key(event), _WarBucket())
            bucket.used += 1
            if event.stars is None:
                bucket.stars_incomplete = True
            else:
                bucket.stars.append(event.stars)
            if event.destruction_percent is None:
                bucket.destruction_incomplete = True
            else:
                bucket.destruction.append(event.destruction_percent)
        elif isinstance(event, WarMissedAttacks):
            bucket = buckets.setdefault(_war_key(event), _WarBucket())
            bucket.missed += event.missed_count
            bucket.saw_miss_log = True
    for key, bucket in buckets.items():
        if key in miss_keys:
            bucket.saw_miss_log = True
    if not buckets:
        return RegularWar()
    return _war_model(buckets)


def _cwl(events: Sequence[DomainEvent], miss_keys: set[str]) -> Cwl:
    buckets: dict[str, _WarBucket] = {}
    lineup_rounds: set[str] = set()
    for event in events:
        if isinstance(event, CwlAttack):
            bucket = buckets.setdefault(_cwl_round_key(event), _WarBucket())
            bucket.used += 1
            if event.stars is None:
                bucket.stars_incomplete = True
            else:
                bucket.stars.append(event.stars)
        elif isinstance(event, CwlMissedAttack):
            bucket = buckets.setdefault(_cwl_round_key(event), _WarBucket())
            bucket.missed += event.missed_count
            bucket.saw_miss_log = True
        elif isinstance(event, CwlLineupChange):
            lineup_rounds.add(_cwl_round_key(event))
    for key, bucket in buckets.items():
        if key in miss_keys:
            bucket.saw_miss_log = True
    if not buckets and not lineup_rounds:
        return Cwl()
    rounds = set(buckets) | lineup_rounds
    used = sum(bucket.used for bucket in buckets.values())
    missed = _sum_missed(buckets)
    stars, average = _stars(buckets)
    available = (used + missed) if missed is not None and (used or missed) else None
    if not buckets:
        used_value: int | None = None
    else:
        used_value = used
    return Cwl(
        rounds_in_lineup=len(rounds),
        attacks_available=available,
        attacks_used=used_value,
        attacks_missed=missed if buckets else None,
        total_stars=stars,
        average_stars=average,
    )


def _clan_games(events: Sequence[DomainEvent]) -> ClanGames:
    rows = [event for event in events if isinstance(event, ClanGamesResult)]
    if not rows:
        return ClanGames(points=None)
    latest = max(
        rows,
        key=lambda event: (event.occurred_at, event.source.message_id, event.row_index),
    )
    return ClanGames(points=latest.points)


def _capital(events: Sequence[DomainEvent]) -> Capital:
    contributions = [event.amount for event in events if isinstance(event, CapitalContribution)]
    raids = [event for event in events if isinstance(event, CapitalRaidAttack)]
    contribution = sum(contributions) if contributions else None
    used = [event.attacks_used for event in raids]
    if raids and all(count is not None for count in used):
        raid_attacks = sum(count for count in used if count is not None)
    else:
        raid_attacks = None
    return Capital(contribution=contribution, raid_attacks=raid_attacks)


def _donations(events: Sequence[DomainEvent]) -> Donations:
    rows = [event for event in events if isinstance(event, DonationSummary)]
    if not rows:
        return Donations()
    best_rank = min(_INTERVAL_RANK[event.interval] for event in rows)
    chosen = [event for event in rows if _INTERVAL_RANK[event.interval] == best_rank]
    latest = max(
        chosen,
        key=lambda event: (event.summary_date, event.source.message_id, event.row_index),
    )
    return Donations(donated=latest.donated, received=latest.received)


def _war_model(buckets: dict[str, _WarBucket]) -> RegularWar:
    used = sum(bucket.used for bucket in buckets.values())
    missed = _sum_missed(buckets)
    stars, average = _stars(buckets)
    destruction = _destruction(buckets)
    available = (used + missed) if missed is not None and (used or missed) else None
    return RegularWar(
        wars_participated=len(buckets),
        attacks_available=available,
        attacks_used=used,
        attacks_missed=missed,
        total_stars=stars,
        average_stars=average,
        average_destruction_percent=destruction,
    )


def _sum_missed(buckets: dict[str, _WarBucket]) -> int | None:
    if any(bucket.used and not bucket.saw_miss_log for bucket in buckets.values()):
        return None
    return sum(bucket.missed for bucket in buckets.values())


def _stars(buckets: dict[str, _WarBucket]) -> tuple[int | None, float | None]:
    if any(bucket.stars_incomplete for bucket in buckets.values()):
        return None, None
    stars = [star for bucket in buckets.values() for star in bucket.stars]
    if not stars:
        return None, None
    total = sum(stars)
    return total, round(total / len(stars), 2)


def _destruction(buckets: dict[str, _WarBucket]) -> float | None:
    if any(bucket.destruction_incomplete for bucket in buckets.values()):
        return None
    values = [value for bucket in buckets.values() for value in bucket.destruction]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _name_index(events: Sequence[DomainEvent]) -> tuple[dict[str, str], set[str]]:
    owners: dict[str, set[str]] = {}

    def add(name: str | None, tag: str | None) -> None:
        if name and tag:
            owners.setdefault(name, set()).add(tag)

    for event in events:
        if isinstance(event, MemberJoined | MemberLeft | PlayerRoleChanged):
            add(event.player_name, event.player_tag)
        elif isinstance(event, PlayerNameChanged):
            add(event.old_name, event.player_tag)
            add(event.new_name, event.player_tag)
        elif isinstance(event, CapitalContribution | CapitalRaidAttack):
            add(event.player_name, event.player_tag)
    ambiguous = {name for name, tags in owners.items() if len(tags) > 1}
    index = {name: next(iter(tags)) for name, tags in owners.items() if name not in ambiguous}
    return index, ambiguous


def _needs_name(event: DomainEvent) -> bool:
    return isinstance(
        event,
        WarAttack
        | WarMissedAttacks
        | CwlAttack
        | CwlMissedAttack
        | CwlLineupChange
        | ClanGamesResult
        | DonationSummary,
    )


def _war_key(event: WarAttack | WarMissedAttacks) -> str:
    if event.war_id_or_key:
        return event.war_id_or_key
    return f"unscoped:{event.source.message_id}"


def _cwl_round_key(event: CwlAttack | CwlMissedAttack | CwlLineupChange) -> str:
    season = event.cwl_season_or_key or f"unscoped:{event.source.message_id}"
    if event.round_number is None:
        return f"{season}:message:{event.source.message_id}"
    return f"{season}:{event.round_number}"


def _covered(
    parsed: bool,
    events: Sequence[DomainEvent],
    kinds: tuple[type[DomainEvent], ...],
) -> bool:
    return parsed or _has(events, kinds)


def _has(events: Sequence[DomainEvent], kinds: tuple[type[DomainEvent], ...]) -> bool:
    return any(isinstance(event, kinds) for event in events)
