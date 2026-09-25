from __future__ import annotations

import csv
import io

from clash_reporter.config import ScoringConfig
from clash_reporter.models import MonthlyDataset
from clash_reporter.reporting import render_csv
from clash_reporter.reporting.csv_export import CSV_COLUMNS
from clash_reporter.scoring import rank_players

SPEC_COLUMNS = [
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
]


def test_csv_columns_match_the_report_spec_in_order(sample_dataset: MonthlyDataset) -> None:
    assert list(CSV_COLUMNS) == SPEC_COLUMNS
    table = _rows(sample_dataset)
    assert list(table[0].keys()) == SPEC_COLUMNS


def test_csv_includes_only_ranking_eligible_members(sample_dataset: MonthlyDataset) -> None:
    table = _rows(sample_dataset)
    tags = [row["Player Tag"] for row in table]
    assert tags == ["#AAA111", "#BBB222", "#CCC333"]
    assert table[0]["Player Name"] == "Aurora"
    assert table[0]["Eligible Days"] == "31"
    assert table[0]["Regular Wars"] == "8"
    assert table[0]["Regular Attack Usage %"] == "100"
    assert table[0]["Donated"] == ""
    assert table[0]["Received"] == ""
    assert table[2]["Flags"]
    assert table[0]["Flags"] == ""


def test_missing_metrics_are_blank_not_zero() -> None:
    dataset = MonthlyDataset.model_validate(
        {
            "month_label": "August 2026",
            "players": [
                {
                    "player_tag": "#ZZZ999",
                    "current_display_name": "Zed",
                    "membership": {"eligible_days": 20},
                }
            ],
        }
    )
    row = _rows(dataset)[0]
    assert row["Regular Attacks Used"] == ""
    assert row["Regular Attacks Missed"] == ""
    assert row["Regular Attack Usage %"] == ""
    assert row["Clan Games Points"] == ""
    assert row["Capital Contribution"] == ""
    assert row["Raid Attacks"] == ""
    assert row["Regular Wars"] == "0"


def _rows(dataset: MonthlyDataset) -> list[dict[str, str]]:
    text = render_csv(rank_players(dataset, ScoringConfig()))
    return list(csv.DictReader(io.StringIO(text)))
