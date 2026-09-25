"""#cp-capital parser: contribution, raid, and weekly summary.

Per-player Capital Gold Contribution / Raid logs (``src/core/clan-log.ts``)
carry a tag in the embed title and are the primary source. Amounts stay raw:
no cap, clan-relative scaling, or min-max lives in this module. The weekly summary
(``src/core/capital-log.ts``) is parsed as validation context.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from clash_reporter.events import (
    CapitalContribution,
    CapitalRaidAttack,
    CapitalWeeklySummaryRow,
    SourceMetadata,
)
from clash_reporter.parsers.base import (
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_MISSING_ROWS,
    IGNORED_UNKNOWN_LAYOUT,
    DomainEvent,
    IgnoredMessage,
    ParseOutcome,
    parse_player_title,
)
from clash_reporter.parsers.message import (
    as_str,
    code_fence,
    first_embed,
    footer_text,
    malformed,
    parse_grouped_int,
    parse_timestamp,
    source_metadata,
)

__all__ = [
    "CAPITAL_PARSER_NAME",
    "CAPITAL_PARSER_VERSION",
    "CapitalParser",
    "raid_weekend_key",
]

CAPITAL_PARSER_NAME = "capital"
CAPITAL_PARSER_VERSION = "1"

# ClashPerk ``Util.geRaidWeekend`` / ``getRaidWeekEndTimestamp``: Friday 07:00 UTC
# through Monday 07:00 UTC. ``weekId`` is the Friday date.
_RAID_WEEK_START_WEEKDAY = 4  # Monday = 0
_RAID_WEEK_START_HOUR = 7

_CONTRIBUTED = re.compile(
    r"Contributed \*\*(?P<amount>[0-9][0-9,]*)\*\* Capital Gold",
    re.IGNORECASE,
)
_RAIDED = re.compile(
    r"Raided \*\*(?P<looted>[0-9][0-9,]*)\*\* Capital Gold "
    r"\((?P<used>\d+)/(?P<limit>\d+)\)",
    re.IGNORECASE,
)
_WEEKLY_RAIDS = re.compile(r"Clan Capital Raids", re.IGNORECASE)
_WEEKLY_CONTRIBUTIONS = re.compile(r"Clan Capital Contributions", re.IGNORECASE)
_WEEK_OF = re.compile(r"Week of\s+(.+)", re.IGNORECASE)
_RAID_ROW = re.compile(
    r"^\u200e?\s*(?P<rank>\d+)\s+(?P<looted>[0-9][0-9,]*)\s+"
    r"(?P<used>\d+)/(?P<limit>\d+)\s+(?P<name>.+?)\s*$"
)
_CONTRIBUTION_ROW = re.compile(
    r"^\u200e?\s*(?P<rank>\d+)\s+(?P<amount>[0-9][0-9,]*)\s+(?P<name>.+?)\s*$"
)
_HEADER = re.compile(r"^\u200e?\s*#\b")
_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class CapitalParser:
    """Pure parser for ClashPerk capital contribution, raid, and weekly logs."""

    name = CAPITAL_PARSER_NAME
    version = CAPITAL_PARSER_VERSION

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

        title = as_str(embed.get("title")) or ""
        description = as_str(embed.get("description")) or ""
        player_name, player_tag = parse_player_title(title) if title else (None, None)
        occurred_at = parse_timestamp(embed.get("timestamp")) or message_timestamp
        source = source_metadata(
            message,
            parser_name=self.name,
            parser_version=self.version,
            message_id=message_id,
            channel_id=channel_id or "",
            message_timestamp=message_timestamp,
        )

        contributed = _CONTRIBUTED.search(description)
        if contributed:
            return _per_player_contribution(
                message_id=message_id,
                channel_id=channel_id,
                player_name=player_name,
                player_tag=player_tag,
                amount=parse_grouped_int(contributed.group("amount")),
                occurred_at=occurred_at,
                source=source,
            )

        raided = _RAIDED.search(description)
        if raided:
            return _per_player_raid(
                message_id=message_id,
                channel_id=channel_id,
                player_name=player_name,
                player_tag=player_tag,
                looted=parse_grouped_int(raided.group("looted")),
                attacks_used=int(raided.group("used")),
                attacks_available=int(raided.group("limit")),
                occurred_at=occurred_at,
                source=source,
            )

        if _WEEKLY_RAIDS.search(description):
            return _weekly_summary(
                message_id=message_id,
                channel_id=channel_id,
                description=description,
                footer=footer_text(embed),
                occurred_at=occurred_at,
                source=source,
                kind="raid",
            )
        if _WEEKLY_CONTRIBUTIONS.search(description):
            return _weekly_summary(
                message_id=message_id,
                channel_id=channel_id,
                description=description,
                footer=footer_text(embed),
                occurred_at=occurred_at,
                source=source,
                kind="contribution",
            )

        return ParseOutcome(
            diagnostics=[
                IgnoredMessage(
                    reason_code=IGNORED_UNKNOWN_LAYOUT,
                    detail="unrecognized capital embed layout",
                    message_id=message_id,
                    channel_id=channel_id,
                    player_name=player_name,
                    player_tag=player_tag,
                )
            ]
        )


def raid_weekend_key(instant: datetime) -> str:
    """ClashPerk ``weekId``: the Friday (UTC) that opened the raid weekend.

    Raid weekends run Friday 07:00 UTC through Monday 07:00 UTC. An instant
    outside that window is attributed to the most recently completed weekend
    so a late-posted raid log still groups with that weekend.
    """
    utc = instant.astimezone(UTC)
    days_since_friday = (utc.weekday() - _RAID_WEEK_START_WEEKDAY) % 7
    friday = utc.replace(hour=_RAID_WEEK_START_HOUR, minute=0, second=0, microsecond=0) - timedelta(
        days=days_since_friday
    )
    if utc < friday:
        friday -= timedelta(days=7)
    return friday.date().isoformat()


def _per_player_contribution(
    *,
    message_id: str,
    channel_id: str | None,
    player_name: str | None,
    player_tag: str | None,
    amount: int,
    occurred_at: datetime,
    source: SourceMetadata,
) -> ParseOutcome:
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
    return ParseOutcome(
        events=[
            CapitalContribution(
                player_tag=player_tag,
                player_name=player_name or "",
                amount=amount,
                occurred_at=occurred_at,
                source=source,
            )
        ]
    )


def _per_player_raid(
    *,
    message_id: str,
    channel_id: str | None,
    player_name: str | None,
    player_tag: str | None,
    looted: int,
    attacks_used: int,
    attacks_available: int,
    occurred_at: datetime,
    source: SourceMetadata,
) -> ParseOutcome:
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
    return ParseOutcome(
        events=[
            CapitalRaidAttack(
                player_tag=player_tag,
                player_name=player_name or "",
                raid_weekend_key=raid_weekend_key(occurred_at),
                looted=looted,
                attacks_used=attacks_used,
                attacks_available=attacks_available,
                occurred_at=occurred_at,
                source=source,
            )
        ]
    )


def _weekly_summary(
    *,
    message_id: str,
    channel_id: str | None,
    description: str,
    footer: str,
    occurred_at: datetime,
    source: SourceMetadata,
    kind: Literal["raid", "contribution"],
) -> ParseOutcome:
    weekend = _raid_weekend_from_footer(footer) or raid_weekend_key(occurred_at)
    fence_body, fence_closed = code_fence(description)
    rows = _parse_weekly_rows(fence_body, kind=kind)
    events: list[DomainEvent] = [
        CapitalWeeklySummaryRow(
            player_tag=None,
            player_name=name,
            raid_weekend_key=weekend,
            kind=kind,
            amount=amount,
            attacks_used=used,
            attacks_available=limit,
            occurred_at=occurred_at,
            source=source,
            row_index=index,
        )
        for index, (name, amount, used, limit) in enumerate(rows)
    ]
    diagnostics: list[IgnoredMessage] = []
    if events:
        diagnostics.append(
            IgnoredMessage(
                reason_code=IGNORED_MISSING_PLAYER_TAG,
                detail=(
                    f"{len(events)} name-only capital weekly {kind} row(s); "
                    "player tag attribution deferred"
                ),
                message_id=message_id,
                channel_id=channel_id,
            )
        )
    if not fence_closed:
        diagnostics.append(
            IgnoredMessage(
                reason_code=IGNORED_MISSING_ROWS,
                detail=(
                    f"capital weekly {kind} summary code fence is unclosed; "
                    f"parsed {len(events)} row(s) and further rows may be missing"
                ),
                message_id=message_id,
                channel_id=channel_id,
            )
        )
    if not events and not diagnostics:
        return malformed(
            f"weekly_{kind}_summary_has_no_rows",
            message_id=message_id,
            channel_id=channel_id,
        )
    return ParseOutcome(events=events, diagnostics=diagnostics)


def _parse_weekly_rows(
    fence_body: str, *, kind: Literal["raid", "contribution"]
) -> list[tuple[str, int, int | None, int | None]]:
    pattern = _RAID_ROW if kind == "raid" else _CONTRIBUTION_ROW
    rows: list[tuple[str, int, int | None, int | None]] = []
    for raw_line in fence_body.splitlines():
        line = raw_line.strip()
        if not line or _HEADER.match(line):
            continue
        match = pattern.match(line)
        if match is None:
            continue
        name = match.group("name").lstrip("\u200e").strip()
        if not name:
            continue
        if kind == "raid":
            rows.append(
                (
                    name,
                    parse_grouped_int(match.group("looted")),
                    int(match.group("used")),
                    int(match.group("limit")),
                )
            )
        else:
            rows.append((name, parse_grouped_int(match.group("amount")), None, None))
    return rows


def _raid_weekend_from_footer(footer: str) -> str | None:
    match = _WEEK_OF.search(footer)
    if match is None:
        return None
    rest = match.group(1).strip()
    parsed = _parse_week_of_rest(rest)
    if parsed is None:
        return None
    noon = parsed.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=UTC)
    return raid_weekend_key(noon)


def _parse_week_of_rest(rest: str) -> datetime | None:
    """Parse ClashPerk ``Week of …`` footers into a start date.

    Known shapes from ``Util.raidWeekDateFormat`` plus the synthetic fixture
    ``Week of August 07, 2026``.
    """
    # "August 07, 2026"
    long = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", rest)
    if long:
        month = _month_number(long.group(1))
        if month is None:
            return None
        return datetime(int(long.group(3)), month, int(long.group(2)), tzinfo=UTC)

    # "7 - 10 Aug 2026"
    same_month = re.fullmatch(r"(\d{1,2})\s*-\s*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})", rest)
    if same_month:
        month = _month_number(same_month.group(2))
        if month is None:
            return None
        return datetime(int(same_month.group(3)), month, int(same_month.group(1)), tzinfo=UTC)

    # "07 Aug - 10 Sep 2026"
    cross_month = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s*-\s*\d{1,2}\s+[A-Za-z]+\s+(\d{4})", rest)
    if cross_month:
        month = _month_number(cross_month.group(2))
        if month is None:
            return None
        return datetime(int(cross_month.group(3)), month, int(cross_month.group(1)), tzinfo=UTC)

    # "28 Dec 2025 - 01 Jan 2026"
    cross_year = re.fullmatch(
        r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*-\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}", rest
    )
    if cross_year:
        month = _month_number(cross_year.group(2))
        if month is None:
            return None
        return datetime(int(cross_year.group(3)), month, int(cross_year.group(1)), tzinfo=UTC)
    return None


def _month_number(name: str) -> int | None:
    return _MONTH_NAMES.get(name.strip().lower())
