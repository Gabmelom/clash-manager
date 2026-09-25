"""Normalized per-message event models from ``docs/DATA_CONTRACT.md``.

Player tag is the canonical identity when ClashPerk exposes one. Membership
and per-player capital logs carry a tag in the embed title. War, CWL, Clan
Games, capital weekly summaries, and donations are name-only, so those events
keep ``player_tag=None`` rather than inventing one. Each event carries the
source metadata block so a ranking can be traced back to the Discord message
that produced it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CapitalContribution",
    "CapitalRaidAttack",
    "CapitalWeeklySummaryRow",
    "ClanGamesResult",
    "CwlAttack",
    "CwlLineupChange",
    "CwlMissedAttack",
    "DonationSummary",
    "MemberEvent",
    "MemberJoined",
    "MemberLeft",
    "PlayerNameChanged",
    "PlayerRoleChanged",
    "SourceMetadata",
    "WarAttack",
    "WarMissedAttacks",
]


class SourceMetadata(BaseModel):
    """Provenance for a normalized event, retained for debugging."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel_id: str
    message_id: str
    message_timestamp: datetime
    message_edited_timestamp: datetime | None
    parser_name: str
    parser_version: str


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str
    player_tag: str
    occurred_at: datetime
    source: SourceMetadata

    @property
    def event_key(self) -> str:
        # Same shape as ``clash_reporter.parsers.base.make_event_key``. Members
        # logs are one event per message, so the index is always 0. Name-only
        # snapshot rows (Clan Games, weekly capital, donations) use
        # ``_IndexedEvent.row_index``; war/CWL use ``_IndexedNameEvent.event_index``.
        return f"{self.source.message_id}:{self.event_type}:{self.player_tag}:0"


class MemberJoined(_EventBase):
    event_type: Literal["MemberJoined"] = "MemberJoined"
    player_name: str


class MemberLeft(_EventBase):
    event_type: Literal["MemberLeft"] = "MemberLeft"
    player_name: str


class PlayerNameChanged(_EventBase):
    event_type: Literal["PlayerNameChanged"] = "PlayerNameChanged"
    old_name: str
    new_name: str


class PlayerRoleChanged(_EventBase):
    event_type: Literal["PlayerRoleChanged"] = "PlayerRoleChanged"
    player_name: str
    new_role: str
    # ClashPerk's role-change log only emits the new role.
    old_role: str | None = None


class _IndexedNameEvent(BaseModel):
    """Player event from a name-only ClashPerk log.

    ``player_tag`` stays ``None`` until aggregation attributes the display name.
    ``event_index`` distinguishes several rows from one Discord message.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str
    player_tag: str | None = None
    player_name: str
    occurred_at: datetime
    source: SourceMetadata
    event_index: int = 0

    @property
    def event_key(self) -> str:
        identity = self.player_tag or self.player_name
        return f"{self.source.message_id}:{self.event_type}:{identity}:{self.event_index}"


class WarAttack(_IndexedNameEvent):
    event_type: Literal["WarAttack"] = "WarAttack"
    war_id_or_key: str | None = None
    stars: int | None = None
    destruction_percent: int | None = None
    attacker_th: int | None = None
    defender_th: int | None = None
    target_position: int | None = None
    ended_at: datetime | None = None
    reporting_month: str | None = None


class WarMissedAttacks(_IndexedNameEvent):
    event_type: Literal["WarMissedAttacks"] = "WarMissedAttacks"
    war_id_or_key: str | None = None
    missed_count: int
    clan_tag: str | None = None
    opponent_tag: str | None = None
    ended_at: datetime | None = None
    reporting_month: str | None = None


class CwlAttack(_IndexedNameEvent):
    event_type: Literal["CwlAttack"] = "CwlAttack"
    cwl_season_or_key: str | None = None
    round_number: int | None = None
    stars: int | None = None
    destruction_percent: int | None = None
    attacker_th: int | None = None
    defender_th: int | None = None
    target_position: int | None = None
    ended_at: datetime | None = None
    reporting_month: str | None = None


class CwlMissedAttack(_IndexedNameEvent):
    event_type: Literal["CwlMissedAttack"] = "CwlMissedAttack"
    cwl_season_or_key: str | None = None
    round_number: int | None = None
    missed_count: int
    clan_tag: str | None = None
    opponent_tag: str | None = None
    ended_at: datetime | None = None
    reporting_month: str | None = None


class CwlLineupChange(_IndexedNameEvent):
    event_type: Literal["CwlLineupChange"] = "CwlLineupChange"
    cwl_season_or_key: str | None = None
    round_number: int | None = None
    change_type: Literal["added", "removed"]
    clan_tag: str | None = None
    opponent_tag: str | None = None
    ended_at: datetime | None = None
    reporting_month: str | None = None


class _IndexedEvent(BaseModel):
    """Several name-only rows from one snapshot-style Discord message.

    ``player_tag`` stays ``None`` until aggregation attributes the display name.
    ``row_index``
    distinguishes leaderboard / summary rows. War/CWL use ``event_index``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str
    player_tag: str | None = None
    player_name: str
    occurred_at: datetime
    source: SourceMetadata
    row_index: int = 0

    @property
    def event_key(self) -> str:
        identity = self.player_tag or ""
        return f"{self.source.message_id}:{self.event_type}:{identity}:{self.row_index}"


class ClanGamesResult(_IndexedEvent):
    """One Clan Games leaderboard row. A final snapshot, not a scoring stream."""

    event_type: Literal["ClanGamesResult"] = "ClanGamesResult"
    points: int
    occurrence_key: str
    message_edited_at: datetime | None = None


class CapitalContribution(_EventBase):
    """Per-player Capital Gold Contribution Log. ``amount`` is the raw gold."""

    event_type: Literal["CapitalContribution"] = "CapitalContribution"
    player_name: str
    amount: int


class CapitalRaidAttack(_EventBase):
    """Per-player Capital Gold Raid Log. Loot is raw; scoring does not live here."""

    event_type: Literal["CapitalRaidAttack"] = "CapitalRaidAttack"
    player_name: str
    raid_weekend_key: str
    looted: int | None = None
    attacks_used: int | None = None
    attacks_available: int | None = None


class CapitalWeeklySummaryRow(_IndexedEvent):
    """One row from a capital weekly summary. Validation context, not a source."""

    event_type: Literal["CapitalWeeklySummaryRow"] = "CapitalWeeklySummaryRow"
    raid_weekend_key: str
    kind: Literal["raid", "contribution"]
    amount: int
    attacks_used: int | None = None
    attacks_available: int | None = None


class DonationSummary(_IndexedEvent):
    """One row from ClashPerk's daily/weekly/monthly donation log. Display-only."""

    event_type: Literal["DonationSummary"] = "DonationSummary"
    donated: int
    received: int
    summary_date: date
    interval: Literal["daily", "weekly", "monthly"]


# Membership logs always carry a player tag. Name-only log families are separate
# union arms on ``DomainEvent`` because those payloads set ``player_tag=None``.
type MemberEvent = MemberJoined | MemberLeft | PlayerNameChanged | PlayerRoleChanged
