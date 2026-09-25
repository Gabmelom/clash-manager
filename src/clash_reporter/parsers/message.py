"""Shared accessors for Discord message mappings.

Parsers stay pure: these helpers only read dictionaries. They do not perform
HTTP, touch the clock, or import ``pathlib``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from clash_reporter.events import SourceMetadata
from clash_reporter.parsers.base import IGNORED_MALFORMED, IgnoredMessage, ParseOutcome
from clash_reporter.window import parse_iso_timestamp

__all__ = [
    "as_str",
    "code_fence",
    "first_embed",
    "footer_text",
    "malformed",
    "parse_grouped_int",
    "parse_timestamp",
    "source_metadata",
]


def as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def first_embed(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
    embeds = message.get("embeds")
    if not isinstance(embeds, list) or not embeds:
        return None
    embed = embeds[0]
    if not isinstance(embed, Mapping):
        return None
    return embed


def footer_text(embed: Mapping[str, Any]) -> str:
    footer = embed.get("footer")
    if not isinstance(footer, Mapping):
        return ""
    return as_str(footer.get("text")) or ""


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_iso_timestamp(value)
    except ValueError:
        return None


def parse_grouped_int(value: str) -> int:
    """Parse an integer that may use comma or space thousands separators."""
    return int(value.replace(",", "").replace(" ", ""))


def code_fence(text: str) -> tuple[str, bool]:
    """Return ``(body, closed)`` for the first markdown code fence.

    ``closed`` is False when the opening fence has no matching closer, which is
    how a Discord-truncated embed description typically looks.
    """
    start = text.find("```")
    if start < 0:
        return "", False
    rest = text[start + 3 :]
    if rest.startswith("\n"):
        rest = rest[1:]
    elif "\n" in rest:
        language, remainder = rest.split("\n", 1)
        rest = remainder if language.strip() else language + "\n" + remainder
    end = rest.find("```")
    if end < 0:
        return rest, False
    return rest[:end], True


def source_metadata(
    message: Mapping[str, Any],
    *,
    parser_name: str,
    parser_version: str,
    message_id: str,
    channel_id: str,
    message_timestamp: datetime,
) -> SourceMetadata:
    return SourceMetadata(
        channel_id=channel_id,
        message_id=message_id,
        message_timestamp=message_timestamp,
        message_edited_timestamp=parse_timestamp(message.get("edited_timestamp")),
        parser_name=parser_name,
        parser_version=parser_version,
    )


def malformed(
    detail: str,
    *,
    message_id: str | None = None,
    channel_id: str | None = None,
    player_name: str | None = None,
    player_tag: str | None = None,
) -> ParseOutcome:
    return ParseOutcome(
        diagnostics=[
            IgnoredMessage(
                reason_code=IGNORED_MALFORMED,
                detail=detail,
                message_id=message_id,
                channel_id=channel_id,
                player_name=player_name,
                player_tag=player_tag,
            )
        ]
    )
