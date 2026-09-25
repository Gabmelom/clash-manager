"""#cp-members parser: join, leave, role change, and name change.

ClashPerk's ``getPlayerLogEmbed`` (``src/core/clan-log.ts``) is the payload
contract. Join and leave are identified from the embed footer; role and name
changes from the description. The player tag always comes from the embed title
``\\u200e{name} ({tag})``. Town-hall, war-preference, and capital logs that
land in this channel are classified as ``unsupported_log``, never as a join.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clash_reporter.events import (
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
    SourceMetadata,
)
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_UNKNOWN_LAYOUT,
    IGNORED_UNSUPPORTED_LOG,
    IgnoredMessage,
    ParseOutcome,
    parse_player_title,
)
from clash_reporter.window import parse_iso_timestamp

__all__ = ["MEMBERS_PARSER_NAME", "MEMBERS_PARSER_VERSION", "MembersParser"]

MEMBERS_PARSER_NAME = "members"
MEMBERS_PARSER_VERSION = "1"

_JOINED_FOOTER = re.compile(r"^Joined .+ \[\d+/\d+\]")
_LEFT_FOOTER = re.compile(r"^Left .+ \[\d+/\d+\]")
_NAME_CHANGED = re.compile(r"^Name changed from \*\*(.+)\*\*\s*$")
_PROMOTED = re.compile(r"^Was Promoted to \*\*(.+)\*\*\s*$")
_DEMOTED = re.compile(r"^Was Demoted to \*\*(.+)\*\*\s*$")
_TOWN_HALL = re.compile(r"Town Hall was upgraded", re.IGNORECASE)
_WAR_PREF = re.compile(r"\*\*Opted (?:in|out)\*\*", re.IGNORECASE)
_CAPITAL_GOLD = re.compile(r"Capital Gold", re.IGNORECASE)

_UNSUPPORTED: tuple[tuple[re.Pattern[str], str], ...] = (
    (_TOWN_HALL, "town_hall_upgrade"),
    (_WAR_PREF, "war_preference"),
    (_CAPITAL_GOLD, "capital"),
)


class MembersParser:
    """Pure parser for ClashPerk member join/leave/role/name logs."""

    name = MEMBERS_PARSER_NAME
    version = MEMBERS_PARSER_VERSION

    def parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        try:
            return self._parse(message)
        except Exception as exc:  # noqa: BLE001 - never raise on a bad payload
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_MALFORMED,
                        detail=f"parser_error: {exc}",
                        message_id=_as_str(message.get("id"))
                        if isinstance(message, Mapping)
                        else None,
                        channel_id=_as_str(message.get("channel_id"))
                        if isinstance(message, Mapping)
                        else None,
                    )
                ]
            )

    def _parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        if not isinstance(message, Mapping):
            return _malformed("message is not a mapping")

        message_id = _as_str(message.get("id"))
        channel_id = _as_str(message.get("channel_id"))
        if not message_id:
            return _malformed("missing_message_id", channel_id=channel_id)

        message_timestamp = _parse_timestamp(message.get("timestamp"))
        if message_timestamp is None:
            return _malformed(
                "missing_or_invalid_timestamp",
                message_id=message_id,
                channel_id=channel_id,
            )

        embed = _first_embed(message)
        if embed is None:
            return _malformed(
                "missing_embed",
                message_id=message_id,
                channel_id=channel_id,
            )

        title = _as_str(embed.get("title")) or ""
        description = _as_str(embed.get("description")) or ""
        footer_text = _footer_text(embed)
        player_name, player_tag = parse_player_title(title) if title else (None, None)

        kind = _classify(footer_text, description)
        if kind is None:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNKNOWN_LAYOUT,
                        detail="unrecognized members embed layout",
                        message_id=message_id,
                        channel_id=channel_id,
                        player_name=player_name,
                        player_tag=player_tag,
                    )
                ]
            )
        if kind.name == "unsupported":
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNSUPPORTED_LOG,
                        detail=kind.payload or "unsupported_log",
                        message_id=message_id,
                        channel_id=channel_id,
                        player_name=player_name,
                        player_tag=player_tag,
                    )
                ]
            )

        if player_tag is None:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_MISSING_PLAYER_TAG,
                        detail="display name present but no recoverable player tag in embed title",
                        message_id=message_id,
                        channel_id=channel_id,
                        player_name=player_name,
                    )
                ]
            )

        occurred_at = _parse_timestamp(embed.get("timestamp")) or message_timestamp
        source = SourceMetadata(
            channel_id=channel_id or "",
            message_id=message_id,
            message_timestamp=message_timestamp,
            message_edited_timestamp=_parse_timestamp(message.get("edited_timestamp")),
            parser_name=self.name,
            parser_version=self.version,
        )

        if kind.name == "joined":
            return ParseOutcome(
                events=[
                    MemberJoined(
                        player_tag=player_tag,
                        player_name=player_name or "",
                        occurred_at=occurred_at,
                        source=source,
                    )
                ]
            )
        if kind.name == "left":
            return ParseOutcome(
                events=[
                    MemberLeft(
                        player_tag=player_tag,
                        player_name=player_name or "",
                        occurred_at=occurred_at,
                        source=source,
                    )
                ]
            )
        if kind.name == "name_changed":
            return ParseOutcome(
                events=[
                    PlayerNameChanged(
                        player_tag=player_tag,
                        old_name=kind.payload or "",
                        new_name=player_name or "",
                        occurred_at=occurred_at,
                        source=source,
                    )
                ]
            )
        if kind.name == "role_changed":
            return ParseOutcome(
                events=[
                    PlayerRoleChanged(
                        player_tag=player_tag,
                        player_name=player_name or "",
                        old_role=None,
                        new_role=kind.payload or "",
                        occurred_at=occurred_at,
                        source=source,
                    )
                ]
            )
        return ParseOutcome(
            diagnostics=[
                IgnoredMessage(
                    reason_code=IGNORED_UNKNOWN_LAYOUT,
                    detail="unrecognized members embed layout",
                    message_id=message_id,
                    channel_id=channel_id,
                    player_name=player_name,
                    player_tag=player_tag,
                )
            ]
        )


@dataclass(frozen=True)
class _Kind:
    name: str
    payload: str | None = None


def _classify(footer_text: str, description: str) -> _Kind | None:
    """Identify join/leave from the footer, role/name from the description."""
    first_line = footer_text.split("\n", 1)[0].strip()
    if _JOINED_FOOTER.match(first_line):
        return _Kind("joined")
    if _LEFT_FOOTER.match(first_line):
        return _Kind("left")

    stripped = description.strip()
    name_match = _NAME_CHANGED.match(stripped)
    if name_match:
        return _Kind("name_changed", name_match.group(1))
    promoted = _PROMOTED.match(stripped)
    if promoted:
        return _Kind("role_changed", promoted.group(1))
    demoted = _DEMOTED.match(stripped)
    if demoted:
        return _Kind("role_changed", demoted.group(1))

    for pattern, log_kind in _UNSUPPORTED:
        if pattern.search(description):
            return _Kind("unsupported", log_kind)
    return None


def _first_embed(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
    embeds = message.get("embeds")
    if not isinstance(embeds, list) or not embeds:
        return None
    embed = embeds[0]
    if not isinstance(embed, Mapping):
        return None
    return embed


def _footer_text(embed: Mapping[str, Any]) -> str:
    footer = embed.get("footer")
    if not isinstance(footer, Mapping):
        return ""
    return _as_str(footer.get("text")) or ""


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_iso_timestamp(value)
    except ValueError:
        return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _malformed(
    detail: str,
    *,
    message_id: str | None = None,
    channel_id: str | None = None,
) -> ParseOutcome:
    return ParseOutcome(
        diagnostics=[
            IgnoredMessage(
                reason_code=IGNORED_MALFORMED,
                detail=detail,
                message_id=message_id,
                channel_id=channel_id,
            )
        ]
    )
