"""Render a concise monthly report from a ranked dataset.

The layout follows ``docs/REPORT_SPEC.md``. Rendering is pure: given the same
dataset and configuration it always produces identical text.
"""

from __future__ import annotations

from clash_reporter.models import MonthlyDataset, MonthlyPlayerSummary
from clash_reporter.scoring.rankings import RankedPlayer, RankedReport

SECTION_TOP = "🏆 Top Performers"
SECTION_REVIEW = "⚠️ Needs Review"
SECTION_NEW = "🆕 New Members"
SECTION_DEPARTED = "👋 Departed Members"
SECTION_NOTES = "ℹ️ Data notes"

SECTION_HEADERS: tuple[str, ...] = (
    SECTION_TOP,
    SECTION_REVIEW,
    SECTION_NEW,
    SECTION_DEPARTED,
    SECTION_NOTES,
)


def _pct(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "n/a"


def _stars(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _format_top_player(index: int, player: RankedPlayer) -> list[str]:
    s = player.summary
    lines = [f"{index}. {s.current_display_name} ({s.player_tag}) - {player.score.overall}"]
    war = s.regular_war
    if war.attack_usage_percent is not None or war.average_stars is not None:
        usage = _pct(war.attack_usage_percent)
        stars = _stars(war.average_stars)
        lines.append(f"   War: {usage} attacks used | {stars} avg stars")
    cwl = s.cwl
    if cwl.attack_usage_percent is not None or cwl.average_stars is not None:
        used = cwl.attacks_used if cwl.attacks_used is not None else "?"
        avail = cwl.attacks_available if cwl.attacks_available is not None else "?"
        stars = _stars(cwl.average_stars)
        lines.append(f"   CWL: {used}/{avail} attacks | {stars} avg stars")
    extras: list[str] = []
    if s.clan_games.points is not None:
        extras.append(f"Games: {s.clan_games.points:,}")
    if s.capital.contribution is not None:
        extras.append(f"Capital: {s.capital.contribution:,}")
    if extras:
        lines.append("   " + " | ".join(extras))
    return lines


def _member_line(player: MonthlyPlayerSummary, *, departed: bool) -> str:
    name = f"{player.current_display_name} ({player.player_tag})"
    if departed:
        when = player.membership.left_on or "this month"
        return f"- {name} - left {when}"
    when = player.membership.joined_on or "this month"
    return f"- {name} - joined {when} - not ranking eligible"


def _same_window_join_and_leave(player: MonthlyPlayerSummary) -> bool:
    """True when the player both joined and left inside this reporting window.

    Identity is the player tag on the summary. Display names are not compared.
    """
    membership = player.membership
    return membership.joined_this_month and membership.departed_this_month


def listed_members(players: list[MonthlyPlayerSummary]) -> list[MonthlyPlayerSummary]:
    """Drop same-window join-and-leave players from a New or Departed list."""
    return [player for player in players if not _same_window_join_and_leave(player)]


def render_report(
    dataset: MonthlyDataset,
    ranked: RankedReport,
    *,
    top_n: int = 5,
) -> str:
    new_members = listed_members(ranked.new_members)
    departed_members = listed_members(ranked.departed_members)
    lines: list[str] = []

    lines.append(f"🏰 {dataset.clan_name} Monthly Report - {dataset.month_label}")
    lines.append("")
    lines.append(f"{len(ranked.ranked)} ranking-eligible members")
    lines.append(f"{len(new_members)} new members")
    lines.append(f"{len(departed_members)} departed members")
    lines.append(f"{dataset.regular_wars} regular wars")
    lines.append(f"{dataset.cwl_rounds} CWL rounds")
    lines.append("Clan Games completed" if dataset.clan_games_completed else "No Clan Games event")
    lines.append(f"{dataset.raid_weekends} Raid Weekends")

    lines.append("")
    lines.append(SECTION_TOP)
    if ranked.ranked:
        for index, player in enumerate(ranked.ranked[:top_n], start=1):
            lines.extend(_format_top_player(index, player))
    else:
        lines.append("No ranking-eligible members this month.")

    review = ranked.review
    if review:
        lines.append("")
        lines.append(SECTION_REVIEW)
        for player in review:
            lines.append(f"{player.summary.current_display_name} ({player.summary.player_tag})")
            for reason in player.review_reasons:
                lines.append(f"- {reason}")

    if new_members:
        lines.append("")
        lines.append(SECTION_NEW)
        for member in new_members:
            lines.append(_member_line(member, departed=False))

    if departed_members:
        lines.append("")
        lines.append(SECTION_DEPARTED)
        for member in departed_members:
            lines.append(_member_line(member, departed=True))

    if dataset.data_notes:
        lines.append("")
        lines.append(SECTION_NOTES)
        for note in dataset.data_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)
