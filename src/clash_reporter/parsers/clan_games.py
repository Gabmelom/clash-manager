"""#cp-games parser: Clan Games leaderboard snapshot.

ClashPerk edits one leaderboard message in place (``src/core/clan-games-log.ts``
and ``src/helper/clan-games.helper.ts``). The payload is a final state, not a
stream: ``timestamp`` is when the message was created (games start), so month
attribution uses ``edited_timestamp``. Rows are name-only; player tags stay
``None`` rather than invented (see ``AGENTS.md``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from clash_reporter.events import ClanGamesResult
from clash_reporter.parsers.base import (
    IGNORED_MISSING_PLAYER_TAG,
    IGNORED_MISSING_ROWS,
    IGNORED_UNKNOWN_LAYOUT,
    DomainEvent,
    IgnoredMessage,
    ParseOutcome,
)
from clash_reporter.parsers.message import (
    as_str,
    code_fence,
    first_embed,
    footer_text,
    malformed,
    parse_timestamp,
    source_metadata,
)

__all__ = [
    "CLAN_GAMES_PARSER_NAME",
    "CLAN_GAMES_PARSER_VERSION",
    "CLASHPERK_LEADERBOARD_ROW_CAP",
    "ClanGamesParser",
]

CLAN_GAMES_PARSER_NAME = "clan_games"
CLAN_GAMES_PARSER_VERSION = "1"
# clan-games.helper.ts ``members.slice(0, 55)``.
CLASHPERK_LEADERBOARD_ROW_CAP = 55

_SCOREBOARD = re.compile(r"Clan Games Scoreboard \((\d{4}-\d{2})\)")
_SEASON = re.compile(r"^\d{4}-\d{2}$")
_FOOTER_TOTALS = re.compile(r"Points:\s*(\d+)\s*\[\s*Avg:\s*([0-9.]+)\s*\]")
_ROW = re.compile(
    r"^\u200e?[\u2002 ]*(?P<rank>\d+)[\u2002 ]+(?P<points>\d+)[\u2002 ]+(?P<name>.+?)\s*$"
)
_HEADER = re.compile(r"^\u200e?[\u2002 ]*#\b", re.IGNORECASE)


class ClanGamesParser:
    """Pure parser for the ClashPerk Clan Games leaderboard embed."""

    name = CLAN_GAMES_PARSER_NAME
    version = CLAN_GAMES_PARSER_VERSION

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
        if _SCOREBOARD.search(description) is None:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNKNOWN_LAYOUT,
                        detail="unrecognized clan games embed layout",
                        message_id=message_id,
                        channel_id=channel_id,
                    )
                ]
            )

        fence_body, fence_closed = code_fence(description)
        rows = _parse_rows(fence_body)
        if not rows and fence_closed:
            return malformed(
                "leaderboard_has_no_rows",
                message_id=message_id,
                channel_id=channel_id,
            )

        edited_at = parse_timestamp(message.get("edited_timestamp"))
        embed_timestamp = parse_timestamp(embed.get("timestamp"))
        occurred_at = edited_at or embed_timestamp or message_timestamp
        occurrence_key = (
            _season_from_components(message)
            or _season_from_description(description)
            or occurred_at.strftime("%Y-%m")
        )

        source = source_metadata(
            message,
            parser_name=self.name,
            parser_version=self.version,
            message_id=message_id,
            channel_id=channel_id or "",
            message_timestamp=message_timestamp,
        )

        events: list[DomainEvent] = [
            ClanGamesResult(
                player_tag=None,
                player_name=name,
                points=points,
                occurrence_key=occurrence_key,
                message_edited_at=edited_at,
                occurred_at=occurred_at,
                source=source,
                row_index=index,
            )
            for index, (_rank, name, points) in enumerate(rows)
        ]

        diagnostics: list[IgnoredMessage] = []
        if events:
            diagnostics.append(
                IgnoredMessage(
                    reason_code=IGNORED_MISSING_PLAYER_TAG,
                    detail=(
                        f"{len(events)} name-only Clan Games row(s); "
                        "player tag attribution deferred"
                    ),
                    message_id=message_id,
                    channel_id=channel_id,
                )
            )

        missing_detail = _missing_rows_detail(
            rows=rows,
            fence_closed=fence_closed,
            footer=footer_text(embed),
        )
        if missing_detail:
            diagnostics.append(
                IgnoredMessage(
                    reason_code=IGNORED_MISSING_ROWS,
                    detail=missing_detail,
                    message_id=message_id,
                    channel_id=channel_id,
                )
            )

        if not events and not diagnostics:
            return malformed(
                "leaderboard_has_no_rows",
                message_id=message_id,
                channel_id=channel_id,
            )
        return ParseOutcome(events=events, diagnostics=diagnostics)


def _parse_rows(fence_body: str) -> list[tuple[int, str, int]]:
    rows: list[tuple[int, str, int]] = []
    for raw_line in fence_body.splitlines():
        line = raw_line.strip()
        if not line or _HEADER.match(line):
            continue
        match = _ROW.match(line)
        if match is None:
            continue
        name = match.group("name").lstrip("\u200e").strip()
        if not name:
            continue
        rows.append((int(match.group("rank")), name, int(match.group("points"))))
    return rows


def _season_from_description(description: str) -> str | None:
    match = _SCOREBOARD.search(description)
    if match is None:
        return None
    return match.group(1)


def _season_from_components(message: Mapping[str, Any]) -> str | None:
    components = message.get("components")
    if not isinstance(components, list):
        return None
    for row in components:
        if not isinstance(row, Mapping):
            continue
        inner = row.get("components")
        if not isinstance(inner, list):
            continue
        for component in inner:
            if not isinstance(component, Mapping):
                continue
            raw = as_str(component.get("custom_id"))
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("cmd") != "clan-games":
                continue
            season = payload.get("season")
            if isinstance(season, str) and _SEASON.fullmatch(season):
                return season
    return None


def _missing_rows_detail(
    *,
    rows: list[tuple[int, str, int]],
    fence_closed: bool,
    footer: str,
) -> str | None:
    parsed = len(rows)
    expected = _expected_member_count(footer)
    ranks = [rank for rank, _name, _points in rows]
    gaps = bool(ranks) and ranks != list(range(1, ranks[-1] + 1))

    if not fence_closed:
        return (
            f"Clan Games leaderboard code fence is unclosed; parsed {parsed} row(s) "
            "and further rows may be missing"
        )
    if expected is not None and parsed < expected:
        return (
            f"Clan Games leaderboard is truncated: parsed {parsed} row(s), "
            f"footer implies {expected}"
        )
    if parsed >= CLASHPERK_LEADERBOARD_ROW_CAP and (expected is None or parsed < expected):
        return (
            f"Clan Games leaderboard hit ClashPerk's {CLASHPERK_LEADERBOARD_ROW_CAP}-row cap; "
            "further rows may be missing"
        )
    if gaps:
        return f"Clan Games leaderboard rank sequence has gaps; parsed {parsed} row(s)"
    return None


def _expected_member_count(footer: str) -> int | None:
    match = _FOOTER_TOTALS.search(footer)
    if match is None:
        return None
    total = int(match.group(1))
    avg = float(match.group(2))
    if avg <= 0:
        return None
    expected = round(total / avg)
    return expected if expected > 0 else None
