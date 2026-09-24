"""Normalized per-message event models from ``docs/DATA_CONTRACT.md``.

Player tag is the canonical identity. Each event carries the source metadata
block so a ranking can be traced back to the Discord message that produced it.
Membership events are the first log family; later parsers add their own types
alongside these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
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
    new_role: str
    # ClashPerk's role-change log only emits the new role.
    old_role: str | None = None
