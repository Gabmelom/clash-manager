"""#donations parser: daily (also weekly/monthly) donation leaderboard.

ClashPerk's ``rangeDonation`` (``src/core/donation-log.ts``) posts a name-only
embed. V1 treats donations as display-only: this parser must not feed scoring.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

from clash_reporter.events import DonationSummary
from clash_reporter.parsers.base import (
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_UNKNOWN_LAYOUT,
    DomainEvent,
    IgnoredMessage,
    ParseOutcome,
)
from clash_reporter.parsers.message import (
    as_str,
    first_embed,
    malformed,
    parse_timestamp,
    source_metadata,
)

__all__ = ["DONATIONS_PARSER_NAME", "DONATIONS_PARSER_VERSION", "DonationsParser"]

DONATIONS_PARSER_NAME = "donations"
DONATIONS_PARSER_VERSION = "1"

_TITLE = re.compile(r"\*\*(Daily|Weekly|Monthly) Donations\*\*", re.IGNORECASE)
_DISCORD_TIME = re.compile(r"<t:(\d+)(?::[tTdDfFR])?>")
_ROW = re.compile(r"`\s*(?P<donated>\d+)\s+(?P<received>\d+)\s*`\s*\u200e?(?P<name>.+?)\s*$")
_INTERVALS: dict[str, Literal["daily", "weekly", "monthly"]] = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}


class DonationsParser:
    """Pure parser for ClashPerk donation-range embeds. Display-only."""

    name = DONATIONS_PARSER_NAME
    version = DONATIONS_PARSER_VERSION

    def parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        try:
            return self._parse(message)
        except Exception as exc:  # noqa: BLE001 - never raise on a bad payload
            return malformed(
                f"parser_error: {exc}",
                message_id=as_str(message.get("id")) if isinstance(message, Mapping) else None,
                channel_id=as_str(message.get("channel_id"))
                if isinstance(message, Mapping)
                else None,
            )

    def _parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        if not isinstance(message, Mapping):
            return malformed("message is not a mapping")

        message_id = as_str(message.get("id"))
        channel_id = as_str(message.get("channel_id"))
        if not message_id:
            return malformed("missing_message_id", channel_id=channel_id)

        message_timestamp = parse_timestamp(message.get("timestamp"))
        if message_timestamp is None:
            return malformed(
                "missing_or_invalid_timestamp",
                message_id=message_id,
                channel_id=channel_id,
            )

        embed = first_embed(message)
        if embed is None:
            return malformed(
                "missing_embed",
                message_id=message_id,
                channel_id=channel_id,
            )

        description = as_str(embed.get("description")) or ""
        title_match = _TITLE.search(description)
        if title_match is None:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNKNOWN_LAYOUT,
                        detail="unrecognized donation embed layout",
                        message_id=message_id,
                        channel_id=channel_id,
                    )
                ]
            )

        interval = _INTERVALS.get(title_match.group(1).lower())
        if interval is None:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNKNOWN_LAYOUT,
                        detail="unrecognized donation interval",
                        message_id=message_id,
                        channel_id=channel_id,
                    )
                ]
            )

        summary_date = _summary_date(description, message_timestamp)
        occurred_at = parse_timestamp(embed.get("timestamp")) or message_timestamp
        source = source_metadata(
            message,
            parser_name=self.name,
            parser_version=self.version,
            message_id=message_id,
            channel_id=channel_id or "",
            message_timestamp=message_timestamp,
        )

        events: list[DomainEvent] = [
            DonationSummary(
                player_tag=None,
                player_name=name,
                donated=donated,
                received=received,
                summary_date=summary_date,
                interval=interval,
                occurred_at=occurred_at,
                source=source,
                row_index=index,
            )
            for index, (name, donated, received) in enumerate(_parse_rows(description))
        ]
        if not events:
            return malformed(
                "donation_log_has_no_rows",
                message_id=message_id,
                channel_id=channel_id,
            )
        return ParseOutcome(
            events=events,
            diagnostics=[
                IgnoredMessage(
                    reason_code=IGNORED_MISSING_PLAYER_TAG,
                    detail=(
                        f"{len(events)} name-only donation row(s); player tag attribution deferred"
                    ),
                    message_id=message_id,
                    channel_id=channel_id,
                )
            ],
        )


def _parse_rows(description: str) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for raw_line in description.splitlines():
        match = _ROW.match(raw_line.strip())
        if match is None:
            continue
        name = match.group("name").lstrip("\u200e").strip()
        if not name:
            continue
        rows.append((name, int(match.group("donated")), int(match.group("received"))))
    return rows


def _summary_date(description: str, message_timestamp: datetime) -> date:
    stamps = [int(value) for value in _DISCORD_TIME.findall(description)]
    if stamps:
        start = datetime.fromtimestamp(stamps[0], tz=UTC)
        return start.date()
    return message_timestamp.astimezone(UTC).date()
