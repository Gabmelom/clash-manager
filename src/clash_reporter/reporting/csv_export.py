"""CSV attachment of every ranking-eligible member.

Column order is the list under "Full-data attachment" in ``docs/REPORT_SPEC.md``.
Missing values stay blank: ``None`` is unknown and is never written as ``0``.

Donated and Received have no field on ``MonthlyPlayerSummary`` yet (donation
logs are name-only and are not aggregated). Those columns are present and empty.
Flags are the review reasons that placed the member in Needs Review.
"""

from __future__ import annotations

import csv
import io

from clash_reporter.scoring.rankings import RankedPlayer, RankedReport

__all__ = ["CSV_COLUMNS", "render_csv"]

CSV_COLUMNS: tuple[str, ...] = (
    "Player Tag",
    "Player Name",
    "Eligible Days",
    "Overall Score",
    "Regular Wars",
    "Regular Attacks Used",
    "Regular Attacks Missed",
    "Regular Attack Usage %",
    "Regular Avg Stars",
    "CWL Rounds",
    "CWL Attacks Used",
    "CWL Attacks Missed",
    "CWL Attack Usage %",
    "CWL Avg Stars",
    "Clan Games Points",
    "Capital Contribution",
    "Raid Attacks",
    "Donated",
    "Received",
    "Flags",
)


def render_csv(ranked: RankedReport) -> str:
    """CSV text for ``ranked.ranked``, in ranking order."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for player in ranked.ranked:
        writer.writerow(_row(player))
    return buffer.getvalue()


def _row(player: RankedPlayer) -> dict[str, str]:
    summary = player.summary
    war = summary.regular_war
    cwl = summary.cwl
    return {
        "Player Tag": summary.player_tag,
        "Player Name": summary.current_display_name,
        "Eligible Days": _cell(summary.membership.eligible_days),
        "Overall Score": _cell(player.score.overall),
        "Regular Wars": _cell(war.wars_participated),
        "Regular Attacks Used": _cell(war.attacks_used),
        "Regular Attacks Missed": _cell(war.attacks_missed),
        "Regular Attack Usage %": _cell(war.attack_usage_percent),
        "Regular Avg Stars": _cell(war.average_stars),
        "CWL Rounds": _cell(cwl.rounds_in_lineup),
        "CWL Attacks Used": _cell(cwl.attacks_used),
        "CWL Attacks Missed": _cell(cwl.attacks_missed),
        "CWL Attack Usage %": _cell(cwl.attack_usage_percent),
        "CWL Avg Stars": _cell(cwl.average_stars),
        "Clan Games Points": _cell(summary.clan_games.points),
        "Capital Contribution": _cell(summary.capital.contribution),
        "Raid Attacks": _cell(summary.capital.raid_attacks),
        "Donated": "",
        "Received": "",
        "Flags": "; ".join(player.review_reasons),
    }


def _cell(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, "g")
    return str(value)
