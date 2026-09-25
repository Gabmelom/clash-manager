"""Normalized per-message event models from ``docs/DATA_CONTRACT.md``.

Player tag is the canonical identity when ClashPerk exposes one. Membership
logs carry a tag in the embed title; war and CWL logs are name-only, so those
events keep ``player_tag=None`` rather than inventing one. Each event carries
the source metadata block so a ranking can be traced back to the Discord
message that produced it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CwlAttack",
    "CwlLineupChange",
    "CwlMissedAttack",
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
        # logs are one event per message, so the index is always 0. Parsers that
        # emit several rows from one Discord message (missed attacks, Clan Games
        # leaderboard) must call ``make_event_key(..., index=)`` instead of
        # relying on this property.
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

    ``player_tag`` stays ``None`` until a later attribution step (issue #12).
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
