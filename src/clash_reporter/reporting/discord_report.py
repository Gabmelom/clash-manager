"""Render a concise monthly report from a ranked dataset.

The layout follows ``docs/REPORT_SPEC.md``. Rendering is pure: given the same
dataset and configuration it always produces identical text.
"""

from __future__ import annotations

from clash_reporter.models import MonthlyDataset, MonthlyPlayerSummary
from clash_reporter.scoring.rankings import RankedPlayer, RankedReport


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


def render_report(
    dataset: MonthlyDataset,
    ranked: RankedReport,
    *,
    top_n: int = 5,
) -> str:
    lines: list[str] = []

    lines.append(f"🏰 {dataset.clan_name} Monthly Report - {dataset.month_label}")
    lines.append("")
    lines.append(f"{len(ranked.ranked)} ranking-eligible members")
    lines.append(f"{len(ranked.new_members)} new members")
    lines.append(f"{len(ranked.departed_members)} departed members")
    lines.append(f"{dataset.regular_wars} regular wars")
    lines.append(f"{dataset.cwl_rounds} CWL rounds")
    lines.append("Clan Games completed" if dataset.clan_games_completed else "No Clan Games event")
    lines.append(f"{dataset.raid_weekends} Raid Weekends")

    lines.append("")
    lines.append("🏆 Top Performers")
    if ranked.ranked:
        for index, player in enumerate(ranked.ranked[:top_n], start=1):
            lines.extend(_format_top_player(index, player))
    else:
        lines.append("No ranking-eligible members this month.")

    review = ranked.review
    if review:
        lines.append("")
        lines.append("⚠️ Needs Review")
        for player in review:
            lines.append(f"{player.summary.current_display_name} ({player.summary.player_tag})")
            for reason in player.review_reasons:
                lines.append(f"- {reason}")

    if ranked.new_members:
        lines.append("")
        lines.append("🆕 New Members")
        for member in ranked.new_members:
            lines.append(_member_line(member, departed=False))

    if ranked.departed_members:
        lines.append("")
        lines.append("👋 Departed Members")
        for member in ranked.departed_members:
            lines.append(_member_line(member, departed=True))

    if dataset.data_notes:
        lines.append("")
        lines.append("ℹ️ Data notes")
        for note in dataset.data_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)
