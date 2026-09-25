"""Clan-roster snapshot used only as a name→tag index.

The Clash of Clans API contributes current member tag and name. It is not a
source of wars, Clan Games, capital, or any other metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "ClanRoster",
    "RosterMember",
]


@dataclass(frozen=True)
class RosterMember:
    """One current clan member: canonical tag and display name."""

    tag: str
    name: str


@dataclass(frozen=True)
class ClanRoster:
    """Outcome of one roster lookup, including a fail-closed skip or error.

    ``note`` is set when the roster was not applied. Discord-only attribution
    still runs in that case. ``members`` is empty unless the fetch succeeded.
    """

    clan_tag: str | None
    members: tuple[RosterMember, ...]
    note: str | None
    fetched_at: datetime

    @property
    def applied(self) -> bool:
        return self.note is None

    def data_note(self) -> str:
        if self.note:
            return self.note
        return (
            f"CoC clan roster ({len(self.members)} members) supplemented name→tag "
            "attribution. Metrics still come only from ClashPerk logs."
        )

    def snapshot(self) -> dict[str, Any]:
        """Audit payload. Never includes the API token."""
        return {
            "clan_tag": self.clan_tag,
            "fetched_at": self.fetched_at.isoformat(),
            "ok": self.applied,
            "note": self.note,
            "members": [
                {"name": member.name, "tag": member.tag}
                for member in sorted(self.members, key=lambda item: (item.tag, item.name))
            ],
        }
