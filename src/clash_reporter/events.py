"""Normalized per-message event models from ``docs/DATA_CONTRACT.md``.

Player tag is the canonical identity. Each event carries the source metadata
block so a ranking can be traced back to the Discord message that produced it.
Name-only ClashPerk logs set ``player_tag`` to ``None`` rather than inventing a
tag; see ``AGENTS.md``, Known deferred decisions.
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
    "DonationSummary",
    "MemberJoined",
    "MemberLeft",
    "PlayerNameChanged",
    "PlayerRoleChanged",
    "SourceMetadata",
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
    player_tag: str | None = None
    occurred_at: datetime
    source: SourceMetadata

    @property
    def event_key(self) -> str:
        # Same shape as ``clash_reporter.parsers.base.make_event_key``. Members
        # logs are one event per message, so the index is always 0. Parsers that
        # emit several rows from one Discord message (missed attacks, Clan Games
        # leaderboard) override this to pass ``row_index``.
        identity = self.player_tag or ""
        return f"{self.source.message_id}:{self.event_type}:{identity}:0"


class _IndexedEvent(_EventBase):
    """Several normalized rows from one Discord message."""

    row_index: int = 0

    @property
    def event_key(self) -> str:
        identity = self.player_tag or ""
        return f"{self.source.message_id}:{self.event_type}:{identity}:{self.row_index}"


class MemberJoined(_EventBase):
    event_type: Literal["MemberJoined"] = "MemberJoined"
    player_tag: str
    player_name: str


class MemberLeft(_EventBase):
    event_type: Literal["MemberLeft"] = "MemberLeft"
    player_tag: str
    player_name: str


class PlayerNameChanged(_EventBase):
    event_type: Literal["PlayerNameChanged"] = "PlayerNameChanged"
    player_tag: str
    old_name: str
    new_name: str


class PlayerRoleChanged(_EventBase):
    event_type: Literal["PlayerRoleChanged"] = "PlayerRoleChanged"
    player_tag: str
    player_name: str
    new_role: str
    # ClashPerk's role-change log only emits the new role.
    old_role: str | None = None


class ClanGamesResult(_IndexedEvent):
    """One Clan Games leaderboard row. A final snapshot, not a scoring stream."""

    event_type: Literal["ClanGamesResult"] = "ClanGamesResult"
    player_name: str
    points: int
    occurrence_key: str
    message_edited_at: datetime | None = None


class CapitalContribution(_EventBase):
    """Per-player Capital Gold Contribution Log. ``amount`` is the raw gold."""

    event_type: Literal["CapitalContribution"] = "CapitalContribution"
    player_tag: str
    player_name: str
    amount: int


class CapitalRaidAttack(_EventBase):
    """Per-player Capital Gold Raid Log. Loot is raw; scoring does not live here."""

    event_type: Literal["CapitalRaidAttack"] = "CapitalRaidAttack"
    player_tag: str
    player_name: str
    raid_weekend_key: str
    looted: int | None = None
    attacks_used: int | None = None
    attacks_available: int | None = None


class CapitalWeeklySummaryRow(_IndexedEvent):
    """One row from a capital weekly summary. Validation context, not a source."""

    event_type: Literal["CapitalWeeklySummaryRow"] = "CapitalWeeklySummaryRow"
    player_name: str
    raid_weekend_key: str
    kind: Literal["raid", "contribution"]
    amount: int
    attacks_used: int | None = None
    attacks_available: int | None = None


class DonationSummary(_IndexedEvent):
    """One row from ClashPerk's daily/weekly/monthly donation log. Display-only."""

    event_type: Literal["DonationSummary"] = "DonationSummary"
    player_name: str
    donated: int
    received: int
    summary_date: date
    interval: Literal["daily", "weekly", "monthly"]
