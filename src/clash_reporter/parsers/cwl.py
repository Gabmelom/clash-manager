"""#cp-cwl parser: CWL attacks, missed attacks, and lineup changes.

Regular-war payloads that land here are ``unsupported_log``, never ``Cwl*``.
Attack logs are name-only plain ``content``; round number is filled in when a
CWL embed or missed-attacks message in the same channel can join the attack.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from clash_reporter.events import (
    CwlAttack,
    CwlLineupChange,
    CwlMissedAttack,
    SourceMetadata,
)
from clash_reporter.parsers.base import (
    IGNORED_MALFORMED,
    IGNORED_UNKNOWN_LAYOUT,
    IGNORED_UNSUPPORTED_LOG,
    WARNING_MISSING_WAR_CONTEXT,
    DomainEvent,
    IgnoredMessage,
    ParseOutcome,
    parse_all,
)
from clash_reporter.parsers.war_layout import (
    as_str,
    cwl_season_key,
    first_embed,
    parse_attack_lines,
    parse_cwl_embed,
    parse_lineup_embed,
    parse_missed_embed,
    parse_regular_war_embed,
    parse_timestamp,
    war_reporting_month,
    window_for_cwl_embed,
    window_for_missed,
    window_matching_miss,
    windows_matching_attack,
)

__all__ = ["CWL_PARSER_NAME", "CWL_PARSER_VERSION", "CwlParser"]

CWL_PARSER_NAME = "cwl"
CWL_PARSER_VERSION = "1"

_LOG_ATTACK = "cwl_attack_log"
_LOG_MISSED = "cwl_missed_attacks_log"
_LOG_LINEUP = "cwl_lineup_change_log"
_LOG_EMBED = "cwl_embed_log"


class CwlParser:
    """Pure parser for ClashPerk CWL logs on ``#cp-cwl``."""

    name = CWL_PARSER_NAME
    version = CWL_PARSER_VERSION

    def parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        try:
            return self._parse(message)
        except Exception as exc:  # noqa: BLE001 - never raise on a bad payload
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_MALFORMED,
                        detail=f"parser_error: {exc}",
                        message_id=as_str(message.get("id"))
                        if isinstance(message, Mapping)
                        else None,
                        channel_id=as_str(message.get("channel_id"))
                        if isinstance(message, Mapping)
                        else None,
                    )
                ]
            )

    def parse_channel(self, messages: Iterable[Mapping[str, Any]]) -> ParseOutcome:
        """Parse a ``#cp-cwl`` history and group rounds into one season key."""
        collected = list(messages)
        outcome = parse_all(self, collected)
        return self._assign_season(outcome, collected)

    def _parse(self, message: Mapping[str, Any]) -> ParseOutcome:
        if not isinstance(message, Mapping):
            return _malformed("message is not a mapping")

        message_id = as_str(message.get("id"))
        channel_id = as_str(message.get("channel_id"))
        if not message_id:
            return _malformed("missing_message_id", channel_id=channel_id)

        message_timestamp = parse_timestamp(message.get("timestamp"))
        if message_timestamp is None:
            return _malformed(
                "missing_or_invalid_timestamp",
                message_id=message_id,
                channel_id=channel_id,
            )

        content = as_str(message.get("content")) or ""
        embed = first_embed(message)
        source = _source(self, message, message_id, channel_id, message_timestamp)

        if content.strip():
            return self._parse_attacks(
                content, source, message_id=message_id, channel_id=channel_id
            )

        if embed is None:
            return _malformed(
                "missing_embed",
                message_id=message_id,
                channel_id=channel_id,
            )

        return self._parse_embed(
            message,
            embed,
            source,
            message_id=message_id,
            channel_id=channel_id,
        )

    def _parse_attacks(
        self,
        content: str,
        source: SourceMetadata,
        *,
        message_id: str,
        channel_id: str | None,
    ) -> ParseOutcome:
        lines = parse_attack_lines(content)
        if not lines:
            return _unknown(
                _LOG_ATTACK,
                message_id=message_id,
                channel_id=channel_id,
            )
        events: list[DomainEvent] = []
        index = 0
        for line in lines:
            if not line.is_clan_attack:
                continue
            events.append(
                CwlAttack(
                    player_name=line.player_name,
                    occurred_at=source.message_timestamp,
                    source=source,
                    event_index=index,
                    stars=line.stars,
                    destruction_percent=line.destruction_percent,
                    attacker_th=line.attacker_th,
                    defender_th=line.defender_th,
                    target_position=line.target_position,
                )
            )
            index += 1
        if not events:
            return ParseOutcome(
                diagnostics=[
                    IgnoredMessage(
                        reason_code=IGNORED_UNSUPPORTED_LOG,
                        detail="cwl_defense",
                        message_id=message_id,
                        channel_id=channel_id,
                    )
                ]
            )
        return ParseOutcome(events=events)

    def _parse_embed(
        self,
        message: Mapping[str, Any],
        embed: Mapping[str, Any],
        source: SourceMetadata,
        *,
        message_id: str,
        channel_id: str | None,
    ) -> ParseOutcome:
        regular = parse_regular_war_embed(message, embed)
        if regular is not None:
            return _unsupported(
                "regular_war_embed",
                message_id=message_id,
                channel_id=channel_id,
            )
        lineup = parse_lineup_embed(embed)
        if lineup is not None:
            return self._lineup_events(lineup, source)
        missed = parse_missed_embed(embed)
        if missed is not None:
            if not missed.is_cwl:
                return _unsupported(
                    "regular_war_missed_attacks",
                    message_id=message_id,
                    channel_id=channel_id,
                )
            return self._missed_events(missed, source)
        cwl_embed = parse_cwl_embed(message, embed)
        if cwl_embed is not None:
            return ParseOutcome()
        log_type = _LOG_LINEUP if _looks_like_lineup(embed) else _LOG_EMBED
        if _looks_like_missed(embed):
            log_type = _LOG_MISSED
        return _unknown(log_type, message_id=message_id, channel_id=channel_id)

    def _missed_events(self, missed: Any, source: SourceMetadata) -> ParseOutcome:
        ended_at = source.message_timestamp
        season = cwl_season_key(missed.clan_tag, ended_at) if missed.clan_tag else None
        month = war_reporting_month(ended_at)
        events: list[DomainEvent] = [
            CwlMissedAttack(
                player_name=player.player_name,
                occurred_at=ended_at,
                source=source,
                event_index=index,
                cwl_season_or_key=season,
                round_number=missed.round_number,
                missed_count=player.missed_count,
                clan_tag=missed.clan_tag,
                opponent_tag=missed.opponent_tag,
                ended_at=ended_at,
                reporting_month=month,
            )
            for index, player in enumerate(missed.players)
        ]
        return ParseOutcome(events=events)

    def _lineup_events(self, lineup: Any, source: SourceMetadata) -> ParseOutcome:
        occurred_at = source.message_timestamp
        season = cwl_season_key(lineup.clan_tag, occurred_at) if lineup.clan_tag else None
        month = war_reporting_month(occurred_at)
        events: list[DomainEvent] = [
            CwlLineupChange(
                player_name=change.player_name,
                occurred_at=occurred_at,
                source=source,
                event_index=index,
                cwl_season_or_key=season,
                round_number=lineup.round_number,
                change_type=change.change_type,
                clan_tag=lineup.clan_tag,
                opponent_tag=lineup.opponent_tag,
                reporting_month=month,
            )
            for index, change in enumerate(lineup.changes)
        ]
        return ParseOutcome(events=events)

    def _assign_season(
        self,
        outcome: ParseOutcome,
        messages: list[Mapping[str, Any]],
    ) -> ParseOutcome:
        embed_windows = []
        fallback_windows = []
        for message in messages:
            embed = first_embed(message)
            if embed is None:
                continue
            ctx = parse_cwl_embed(message, embed)
            if ctx is not None:
                window = window_for_cwl_embed(ctx)
                if window is not None:
                    embed_windows.append(window)
                continue
            missed = parse_missed_embed(embed)
            if missed is None or not missed.is_cwl:
                continue
            ended_at = parse_timestamp(message.get("timestamp"))
            if ended_at is None:
                continue
            window = window_for_missed(missed, ended_at, for_cwl=True)
            if window is not None:
                fallback_windows.append(window)

        events: list[DomainEvent] = []
        diagnostics = list(outcome.diagnostics)
        for event in outcome.events:
            if isinstance(event, CwlAttack):
                window = windows_matching_attack(event.occurred_at, embed_windows)
                if window is None:
                    window = windows_matching_attack(event.occurred_at, fallback_windows)
                if window is None:
                    events.append(event)
                    diagnostics.append(
                        IgnoredMessage(
                            reason_code=WARNING_MISSING_WAR_CONTEXT,
                            detail="cwl_attack without matching round embed or missed-attacks",
                            message_id=event.source.message_id,
                            channel_id=event.source.channel_id or None,
                            player_name=event.player_name,
                        )
                    )
                    continue
                events.append(
                    event.model_copy(
                        update={
                            "cwl_season_or_key": window.season_key,
                            "round_number": window.round_number,
                            "ended_at": window.ended_at,
                            "reporting_month": war_reporting_month(window.ended_at),
                        }
                    )
                )
                continue
            if isinstance(event, (CwlMissedAttack, CwlLineupChange)):
                window = window_matching_miss(
                    event.occurred_at,
                    event.opponent_tag,
                    embed_windows,
                    round_number=event.round_number,
                )
                if window is None:
                    events.append(event)
                    continue
                events.append(
                    event.model_copy(
                        update={
                            "cwl_season_or_key": window.season_key or event.cwl_season_or_key,
                            "round_number": window.round_number or event.round_number,
                            "ended_at": window.ended_at,
                            "reporting_month": war_reporting_month(window.ended_at),
                        }
                    )
                )
                continue
            events.append(event)
        return ParseOutcome(events=events, diagnostics=diagnostics)


def _source(
    parser: CwlParser,
    message: Mapping[str, Any],
    message_id: str,
    channel_id: str | None,
    message_timestamp: Any,
) -> SourceMetadata:
    return SourceMetadata(
        channel_id=channel_id or "",
        message_id=message_id,
        message_timestamp=message_timestamp,
        message_edited_timestamp=parse_timestamp(message.get("edited_timestamp")),
        parser_name=parser.name,
        parser_version=parser.version,
    )


def _looks_like_lineup(embed: Mapping[str, Any]) -> bool:
    description = as_str(embed.get("description")) or ""
    return "Members Added" in description or "Members Removed" in description


def _looks_like_missed(embed: Mapping[str, Any]) -> bool:
    description = as_str(embed.get("description")) or ""
    return "Missed Attacks" in description or "War Against" in description


def _unknown(log_type: str, *, message_id: str | None, channel_id: str | None) -> ParseOutcome:
    return ParseOutcome(
        diagnostics=[
            IgnoredMessage(
                reason_code=IGNORED_UNKNOWN_LAYOUT,
                detail=f"unrecognized {log_type} layout",
                message_id=message_id,
                channel_id=channel_id,
            )
        ]
    )


def _unsupported(detail: str, *, message_id: str | None, channel_id: str | None) -> ParseOutcome:
    return ParseOutcome(
        diagnostics=[
            IgnoredMessage(
                reason_code=IGNORED_UNSUPPORTED_LOG,
                detail=detail,
                message_id=message_id,
                channel_id=channel_id,
            )
        ]
    )


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
