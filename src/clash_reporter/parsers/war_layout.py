"""ClashPerk war / CWL Discord layouts.

Transcribed from clashperk ``src/core/clan-war-log.ts`` (commit ``c78b459``).
Regular war and CWL share builders; the parsers keep the resulting event types
distinct. This module has no HTTP, clock, or filesystem access.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from clash_reporter.parsers.base import is_valid_player_tag, normalize_player_tag
from clash_reporter.window import parse_iso_timestamp

__all__ = [
    "AttackLine",
    "LineupChange",
    "LineupEmbed",
    "MissedAttacksEmbed",
    "MissedPlayer",
    "WarEmbedContext",
    "WarWindow",
    "as_str",
    "cwl_season_key",
    "extract_war_id",
    "fallback_war_key",
    "first_embed",
    "footer_text",
    "parse_attack_lines",
    "parse_cwl_embed",
    "parse_lineup_embed",
    "parse_missed_embed",
    "parse_regular_war_embed",
    "parse_timestamp",
    "war_reporting_month",
    "window_for_cwl_embed",
    "window_for_missed",
    "window_for_regular_embed",
    "windows_matching_attack",
]

_CUSTOM_EMOJI = re.compile(r"<a?:([^:>]+):(\d+)>")
_DESTRUCTION = re.compile(r"`\s*(\d+)\s*%\s*`")
_ARROW = re.compile(r"<a?:(ArwRight|ArwLeft):\d+>")
_CWL_ROUND = re.compile(r"CWL Round\s+(\d+)", re.IGNORECASE)
_ROUND_FOOTER = re.compile(r"Round\s+#(\d+)", re.IGNORECASE)
_MISSED_FIELD = re.compile(r"^(\d+)\s+Missed Attacks$", re.IGNORECASE)
_OPPONENT_LINK = re.compile(r"\[([^\[\]]+?) \((#[A-Za-z0-9]+)\)\]")
_DISCORD_TIME = re.compile(r"<t:(\d+):[tTdDfFR]>")
_TOWN_HALL_NAME = re.compile(r"^TownHall(\d+)$", re.IGNORECASE)
_STAR_FILLED = frozenset({"YellowStar", "RedStar", "YellowGrey", "RedGrey"})
_STAR_EMPTY = frozenset({"Grey"})
_CONTINUATION_FIELD = "\u200b"

# Missed-attacks posts land shortly after the embed's end timestamp.
_MISS_SLACK = timedelta(hours=24)
_ATTACK_END_SLACK = timedelta(hours=1)
# Prep (~23h) + battle (~24h); used when the embed has no start bound.
_WAR_DURATION = timedelta(hours=48)


@dataclass(frozen=True)
class AttackLine:
    player_name: str
    stars: int | None
    destruction_percent: int | None
    attacker_th: int | None
    defender_th: int | None
    target_position: int | None
    is_clan_attack: bool


@dataclass(frozen=True)
class MissedPlayer:
    player_name: str
    missed_count: int
    # Map-position emoji from ClashPerk. Used to parse the line; not stored on
    # V1 event models (see DATA_CONTRACT).
    map_position: int | None


@dataclass(frozen=True)
class MissedAttacksEmbed:
    clan_name: str | None
    clan_tag: str | None
    opponent_name: str | None
    opponent_tag: str | None
    round_number: int | None
    is_cwl: bool
    players: list[MissedPlayer]


@dataclass(frozen=True)
class LineupChange:
    player_name: str
    change_type: Literal["added", "removed"]
    map_position: int | None


@dataclass(frozen=True)
class LineupEmbed:
    clan_tag: str | None
    opponent_tag: str | None
    opponent_name: str | None
    round_number: int | None
    changes: list[LineupChange]


@dataclass(frozen=True)
class WarEmbedContext:
    war_id: int | None
    clan_tag: str | None
    opponent_tag: str | None
    opponent_name: str | None
    started_at: datetime | None
    ended_at: datetime | None
    round_number: int | None
    is_cwl: bool
    is_ended: bool
    message_id: str


@dataclass(frozen=True)
class WarWindow:
    """A time range used to join attacks and misses onto one war / round."""

    key: str
    clan_tag: str | None
    opponent_tag: str | None
    started_at: datetime | None
    ended_at: datetime
    round_number: int | None = None
    season_key: str | None = None


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


def war_reporting_month(ended_at: datetime) -> str:
    """UTC calendar month a war belongs to: the month in which it ended."""
    instant = ended_at.astimezone(UTC)
    return f"{instant.year:04d}-{instant.month:02d}"


def fallback_war_key(clan_tag: str, opponent_tag: str, ended_at: datetime) -> str:
    """Join key when the War Embed Log (and its ``war_id``) is missing.

    Shape: ``fallback:{home_tag}:{opponent_tag}:{YYYY-MM-DD}`` using the UTC
    date of the missed-attacks message, which ClashPerk posts at ``warEnded``.
    """
    day = ended_at.astimezone(UTC).date().isoformat()
    return f"fallback:{_canonical_tag(clan_tag)}:{_canonical_tag(opponent_tag)}:{day}"


def cwl_season_key(clan_tag: str, ended_at: datetime) -> str:
    """Group CWL rounds into one season: ``cwl:{home_tag}:{YYYY-MM}``."""
    return f"cwl:{_canonical_tag(clan_tag)}:{war_reporting_month(ended_at)}"


def extract_war_id(message: Mapping[str, Any]) -> int | None:
    """ClashPerk ``war_id`` from Attack/Defense button ``custom_id`` JSON."""
    components = message.get("components")
    if not isinstance(components, list):
        return None
    for row in components:
        if not isinstance(row, Mapping):
            continue
        children = row.get("components")
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, Mapping):
                continue
            raw = child.get("custom_id")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("cmd") != "war":
                continue
            war_id = payload.get("war_id")
            if isinstance(war_id, int):
                return war_id
            if isinstance(war_id, str) and war_id.isdigit():
                return int(war_id)
    return None


def parse_attack_lines(content: str) -> list[AttackLine]:
    """Parse ClashPerk ``getAttackLogMessage`` content (one attack per line)."""
    lines: list[AttackLine] = []
    for raw in content.splitlines():
        parsed = _parse_attack_line(raw)
        if parsed is not None:
            lines.append(parsed)
    return lines


def parse_missed_embed(embed: Mapping[str, Any]) -> MissedAttacksEmbed | None:
    """Parse ClashPerk ``getRemaining`` (War / CWL Missed Attacks Log)."""
    description = as_str(embed.get("description")) or ""
    title = as_str(embed.get("title")) or ""
    # Regular war embeds also say "War Against"; they have a War State section.
    if "**War State**" in description:
        return None
    if "**Members Added**" in description or "**Members Removed**" in description:
        return None
    has_no_missed = "No Missed Attacks" in description
    if not _has_missed_fields(embed) and not has_no_missed:
        return None
    if "**War Against" not in description:
        return None
    clan_name, clan_tag = _title_identity(title)
    opponent_name, opponent_tag = _opponent_from_text(description)
    round_number = _cwl_round(description)
    players = _missed_players(embed)
    # ClashPerk's CWL missed-attacks description is ``War Against (CWL Round N)``.
    # That round string is the only payload discriminator; parsers do not read
    # Discord channel names. Operationally ``#cp-wars`` vs ``#cp-cwl`` is the
    # routing guarantee if the round text is ever absent.
    return MissedAttacksEmbed(
        clan_name=clan_name,
        clan_tag=clan_tag,
        opponent_name=opponent_name,
        opponent_tag=opponent_tag,
        round_number=round_number,
        is_cwl=round_number is not None,
        players=players,
    )


def parse_lineup_embed(embed: Mapping[str, Any]) -> LineupEmbed | None:
    """Parse ClashPerk ``getLineupChangeEmbed``."""
    description = as_str(embed.get("description")) or ""
    if "**Members Added**" not in description and "**Members Removed**" not in description:
        return None
    title = as_str(embed.get("title")) or ""
    _, clan_tag = _title_identity(title)
    opponent_name, opponent_tag = _opponent_from_text(description)
    round_number = _cwl_round(description)
    added = _player_lines(_section(description, "**Members Added**", ("**Members Removed**",)))
    removed = _player_lines(_section(description, "**Members Removed**", ()))
    changes = [
        *[LineupChange(name, "added", pos) for pos, name in added],
        *[LineupChange(name, "removed", pos) for pos, name in removed],
    ]
    return LineupEmbed(
        clan_tag=clan_tag,
        opponent_tag=opponent_tag,
        opponent_name=opponent_name,
        round_number=round_number,
        changes=changes,
    )


def parse_regular_war_embed(
    message: Mapping[str, Any], embed: Mapping[str, Any]
) -> WarEmbedContext | None:
    """Parse ClashPerk ``getRegularWarEmbed`` (description-based, not CWL)."""
    description = as_str(embed.get("description")) or ""
    if "**War Against**" not in description or "**War State**" not in description:
        return None
    if _cwl_round(description) is not None:
        return None
    return _war_embed_context(message, embed, description=description, is_cwl=False)


def parse_cwl_embed(message: Mapping[str, Any], embed: Mapping[str, Any]) -> WarEmbedContext | None:
    """Parse ClashPerk ``getLeagueWarEmbed`` (field-based, footer ``Round #N``)."""
    fields = _embed_fields(embed)
    if "War Against" not in fields:
        return None
    if "War State" not in fields and "Team Size" not in fields:
        return None
    footer = footer_text(embed)
    round_number = _cwl_round(footer) or _round_footer(footer)
    if round_number is None:
        # CWL embeds always set the footer; without it this is not a CWL embed.
        return None
    against = fields.get("War Against") or ""
    state = fields.get("War State") or ""
    return _war_embed_context(
        message,
        embed,
        description=f"{against}\n{state}",
        is_cwl=True,
        round_number=round_number,
        state_text=state,
    )


def window_for_regular_embed(ctx: WarEmbedContext) -> WarWindow | None:
    if ctx.is_cwl:
        return None
    ended_at = ctx.ended_at
    if ended_at is None:
        return None
    key = _embed_war_key(ctx, ended_at)
    if key is None:
        return None
    return WarWindow(
        key=key,
        clan_tag=ctx.clan_tag,
        opponent_tag=ctx.opponent_tag,
        started_at=ctx.started_at,
        ended_at=ended_at,
    )


def window_for_cwl_embed(ctx: WarEmbedContext) -> WarWindow | None:
    if not ctx.is_cwl:
        return None
    ended_at = ctx.ended_at
    if ended_at is None:
        return None
    key = _embed_war_key(ctx, ended_at)
    season = cwl_season_key(ctx.clan_tag, ended_at) if ctx.clan_tag else None
    if key is None and season is None:
        return None
    return WarWindow(
        key=key or (season or ""),
        clan_tag=ctx.clan_tag,
        opponent_tag=ctx.opponent_tag,
        started_at=ctx.started_at,
        ended_at=ended_at,
        round_number=ctx.round_number,
        season_key=season,
    )


def window_for_missed(
    missed: MissedAttacksEmbed,
    ended_at: datetime,
    *,
    for_cwl: bool,
) -> WarWindow | None:
    if missed.is_cwl != for_cwl:
        return None
    if not missed.clan_tag or not missed.opponent_tag:
        return None
    key = fallback_war_key(missed.clan_tag, missed.opponent_tag, ended_at)
    season = cwl_season_key(missed.clan_tag, ended_at) if for_cwl else None
    started_at = ended_at - _WAR_DURATION
    return WarWindow(
        key=key if not for_cwl else (season or key),
        clan_tag=missed.clan_tag,
        opponent_tag=missed.opponent_tag,
        started_at=started_at,
        ended_at=ended_at,
        round_number=missed.round_number,
        season_key=season,
    )


def windows_matching_attack(
    occurred_at: datetime, windows: Sequence[WarWindow]
) -> WarWindow | None:
    """Pick the war / round window an attack belongs to.

    Prefer a window whose ``[started_at, ended_at]`` contains the attack.
    Otherwise take the earliest window that ends after the attack (fallback
    missed-attacks path).
    """
    containing: list[WarWindow] = []
    later: list[WarWindow] = []
    for window in windows:
        start = window.started_at or (window.ended_at - _WAR_DURATION)
        end = window.ended_at + _ATTACK_END_SLACK
        if start <= occurred_at <= end:
            containing.append(window)
        elif occurred_at <= window.ended_at + _MISS_SLACK:
            later.append(window)
    if containing:
        return min(containing, key=lambda item: item.ended_at)
    if later:
        return min(later, key=lambda item: item.ended_at)
    return None


def window_matching_miss(
    occurred_at: datetime,
    opponent_tag: str | None,
    windows: Sequence[WarWindow],
    *,
    round_number: int | None = None,
) -> WarWindow | None:
    """Match a missed-attacks / lineup row to an embed-derived window."""
    candidates: list[WarWindow] = []
    for window in windows:
        if opponent_tag and window.opponent_tag and window.opponent_tag != opponent_tag:
            continue
        if (
            round_number is not None
            and window.round_number is not None
            and window.round_number != round_number
        ):
            continue
        start = window.started_at or (window.ended_at - _WAR_DURATION)
        if start <= occurred_at <= window.ended_at + _MISS_SLACK:
            candidates.append(window)
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs((item.ended_at - occurred_at).total_seconds()))


def _embed_war_key(ctx: WarEmbedContext, ended_at: datetime) -> str | None:
    if ctx.war_id is not None:
        return f"war:{ctx.war_id}"
    if ctx.clan_tag and ctx.opponent_tag:
        return fallback_war_key(ctx.clan_tag, ctx.opponent_tag, ended_at)
    return None


def _war_embed_context(
    message: Mapping[str, Any],
    embed: Mapping[str, Any],
    *,
    description: str,
    is_cwl: bool,
    round_number: int | None = None,
    state_text: str | None = None,
) -> WarEmbedContext:
    title = as_str(embed.get("title")) or ""
    _, clan_tag = _title_identity(title)
    opponent_name, opponent_tag = _opponent_from_text(description)
    footer = footer_text(embed)
    state = state_text if state_text is not None else description
    is_ended = "War Ended" in state or footer.strip().lower() == "ended"
    message_timestamp = parse_timestamp(message.get("timestamp"))
    embed_timestamp = parse_timestamp(embed.get("timestamp"))
    edited = parse_timestamp(message.get("edited_timestamp"))
    discord_times = [datetime.fromtimestamp(int(ts), tz=UTC) for ts in _DISCORD_TIME.findall(state)]
    ended_at: datetime | None = None
    if is_ended:
        ended_at = embed_timestamp or edited or message_timestamp
    elif discord_times:
        # In-war embeds include ``End Time: <t:unix:R>``.
        ended_at = discord_times[-1]
    # ClashPerk creates the war embed at prep start and edits it through
    # warEnded, so ``message.timestamp`` is the start bound. A capture whose
    # first post is already the final edit has no prep timestamp; matching then
    # uses the 48h window behind ``ended_at``.
    started_at = message_timestamp
    return WarEmbedContext(
        war_id=extract_war_id(message),
        clan_tag=clan_tag,
        opponent_tag=opponent_tag,
        opponent_name=opponent_name,
        started_at=started_at,
        ended_at=ended_at,
        round_number=round_number or _cwl_round(description) or _round_footer(footer),
        is_cwl=is_cwl,
        is_ended=is_ended,
        message_id=as_str(message.get("id")) or "",
    )


def _parse_attack_line(line: str) -> AttackLine | None:
    stripped = line.strip()
    if not stripped:
        return None
    arrow = _ARROW.search(stripped)
    if arrow is None:
        return None
    dest_match = _DESTRUCTION.search(stripped)
    destruction = int(dest_match.group(1)) if dest_match else None
    head_end = dest_match.start() if dest_match is not None else arrow.start()
    stars = _count_stars(stripped[:head_end])
    mid = stripped[dest_match.end() if dest_match is not None else 0 : arrow.start()]
    after = stripped[arrow.end() :]
    mid_emojis = list(_CUSTOM_EMOJI.finditer(mid))
    after_emojis = list(_CUSTOM_EMOJI.finditer(after))
    attacker_th = _emoji_number(mid_emojis[1]) if len(mid_emojis) >= 2 else None
    target_position = _emoji_number(after_emojis[0]) if after_emojis else None
    defender_th = _emoji_number(after_emojis[1]) if len(after_emojis) >= 2 else None
    if mid_emojis:
        name_raw = mid[mid_emojis[-1].end() :]
    else:
        name_raw = mid
    name = _clean_name(name_raw)
    if not name:
        return None
    return AttackLine(
        player_name=name,
        stars=stars,
        destruction_percent=destruction,
        attacker_th=attacker_th,
        defender_th=defender_th,
        target_position=target_position,
        is_clan_attack=arrow.group(1) == "ArwRight",
    )


def _count_stars(text: str) -> int | None:
    filled = 0
    empty = 0
    combo: int | None = None
    for name, _emoji_id in _CUSTOM_EMOJI.findall(text):
        combo_stars = _stars_from_combo(name)
        if combo_stars is not None:
            combo = combo_stars
            continue
        if name in _STAR_FILLED:
            filled += 1
        elif name in _STAR_EMPTY:
            empty += 1
    if combo is not None:
        return combo
    if filled or empty:
        return filled
    return None


def _stars_from_combo(name: str) -> int | None:
    if len(name) == 3 and set(name) <= {"N", "O", "E"}:
        return sum(1 for char in name if char in {"N", "O"})
    return None


def _emoji_number(match: re.Match[str]) -> int | None:
    name = match.group(1)
    if name.isdigit():
        return int(name)
    town_hall = _TOWN_HALL_NAME.match(name)
    if town_hall:
        return int(town_hall.group(1))
    return None


def _has_missed_fields(embed: Mapping[str, Any]) -> bool:
    for field in _field_list(embed):
        name = as_str(field.get("name")) or ""
        if _MISSED_FIELD.match(name.strip()) or name.strip() == _CONTINUATION_FIELD:
            return True
        if "No Missed Attacks" in (as_str(field.get("value")) or ""):
            return True
    return "No Missed Attacks" in (as_str(embed.get("description")) or "")


def _missed_players(embed: Mapping[str, Any]) -> list[MissedPlayer]:
    players: list[MissedPlayer] = []
    current_count: int | None = None
    for field in _field_list(embed):
        name = (as_str(field.get("name")) or "").strip()
        count_match = _MISSED_FIELD.match(name)
        if count_match:
            current_count = int(count_match.group(1))
        elif name != _CONTINUATION_FIELD:
            continue
        if current_count is None:
            continue
        for map_position, player_name in _player_lines(as_str(field.get("value")) or ""):
            players.append(
                MissedPlayer(
                    player_name=player_name,
                    missed_count=current_count,
                    map_position=map_position,
                )
            )
    return players


def _player_lines(text: str) -> list[tuple[int | None, str]]:
    rows: list[tuple[int | None, str]] = []
    for raw in text.splitlines():
        line = raw.replace("\u200e", "").replace("\u200f", "").strip()
        if not line or line.startswith("**"):
            continue
        emojis = list(_CUSTOM_EMOJI.finditer(line))
        map_position = _emoji_number(emojis[0]) if emojis else None
        name = _clean_name(line[emojis[-1].end() :] if emojis else line)
        if name:
            rows.append((map_position, name))
    return rows


def _section(description: str, header: str, next_headers: tuple[str, ...]) -> str:
    start = description.find(header)
    if start < 0:
        return ""
    body = description[start + len(header) :]
    cuts = [body.find(item) for item in next_headers]
    cuts = [cut for cut in cuts if cut >= 0]
    if cuts:
        body = body[: min(cuts)]
    return body


def _title_identity(title: str) -> tuple[str | None, str | None]:
    text = title.lstrip("\u200e").strip()
    if not text:
        return None, None
    match = re.search(r"^(.*) \((#[A-Za-z0-9]+)\)$", text)
    if not match:
        return text or None, None
    name = match.group(1).strip() or None
    raw_tag = match.group(2)
    tag = _canonical_tag(raw_tag) if is_valid_player_tag(raw_tag) else None
    return name, tag


def _opponent_from_text(text: str) -> tuple[str | None, str | None]:
    match = _OPPONENT_LINK.search(text)
    if match is None:
        return None, None
    name = _clean_name(match.group(1))
    raw_tag = match.group(2)
    tag = _canonical_tag(raw_tag) if is_valid_player_tag(raw_tag) else None
    return name or None, tag


def _cwl_round(text: str) -> int | None:
    match = _CWL_ROUND.search(text)
    if match:
        return int(match.group(1))
    return _round_footer(text)


def _round_footer(text: str) -> int | None:
    match = _ROUND_FOOTER.search(text)
    return int(match.group(1)) if match else None


def _embed_fields(embed: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in _field_list(embed):
        name = as_str(field.get("name"))
        value = as_str(field.get("value"))
        if name:
            result[name] = value or ""
    return result


def _field_list(embed: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    fields = embed.get("fields")
    if not isinstance(fields, list):
        return []
    return [field for field in fields if isinstance(field, Mapping)]


def _canonical_tag(tag: str) -> str:
    return normalize_player_tag(tag) if is_valid_player_tag(tag) else tag


def _clean_name(value: str) -> str:
    return value.replace("\u200e", "").replace("\u200f", "").strip().strip("*").strip()
