from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from clash_reporter import main as cli
from clash_reporter.aggregation.normalize import normalize_capture
from clash_reporter.collection.capture import dump_json
from clash_reporter.config import ScoringConfig
from clash_reporter.models import MonthlyDataset
from clash_reporter.parsers.base import parse_all, parse_player_title
from clash_reporter.parsers.members import MembersParser
from clash_reporter.scoring import rank_players
from clash_reporter.window import month_window, snowflake_for

TORONTO = "America/Toronto"
AUGUST = month_window(2026, 8, timezone=TORONTO)
SNOWFLAKE_SUFFIX = 0x0A1B02

AURORA = "#2Y0LRPV8Q"
BOREALIS = "#8QCU29VJ0"
CASCADE = "#9YLG2PJRQ"
DUNE = "#2P0CQ9LUR"

Message = Callable[[str], dict[str, Any]]


@pytest.fixture(autouse=True)
def _clear_report_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPORT_TIMEZONE", raising=False)


def utc(year: int, month: int, day: int, hour: int = 16, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def members_message(
    fixture: dict[str, Any],
    *,
    at: datetime | None = None,
    tag: str | None = None,
    name: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    message = deepcopy(fixture)
    if at is not None:
        iso = at.isoformat()
        message["timestamp"] = iso
        message["embeds"][0]["timestamp"] = iso
        message["id"] = message_id or str(snowflake_for(at) | SNOWFLAKE_SUFFIX)
    elif message_id is not None:
        message["id"] = message_id
    if tag is not None or name is not None:
        current_name, current_tag = parse_player_title(message["embeds"][0]["title"])
        title_name = name if name is not None else current_name
        title_tag = tag if tag is not None else current_tag
        message["embeds"][0]["title"] = f"\u200e{title_name} ({title_tag})"
    return message


def write_raw_capture(
    directory: Path,
    messages: list[dict[str, Any]],
    *,
    month_key: str = "2026-08",
    extra_channels: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "members.json").write_text(dump_json(messages), encoding="utf-8")
    channels = [
        {
            "name": "members",
            "channel_id": "400000000000000001",
            "file": "members.json",
            "message_count": len(messages),
        }
    ]
    if extra_channels:
        for name, payload in extra_channels.items():
            (directory / f"{name}.json").write_text(dump_json(payload), encoding="utf-8")
            channels.append(
                {
                    "name": name,
                    "channel_id": "400000000000000000",
                    "file": f"{name}.json",
                    "message_count": len(payload),
                }
            )
    manifest = {
        "captured_at": "2026-09-01T12:00:00+00:00",
        "api_version": "v10",
        "sanitized": True,
        "window": {"month_key": month_key, "timezone": TORONTO},
        "channels": channels,
    }
    (directory / "manifest.json").write_text(dump_json(manifest), encoding="utf-8")
    return directory


def _sample_messages(clashperk_message: Message) -> list[dict[str, Any]]:
    join = clashperk_message("members/join.json")
    leave = clashperk_message("members/leave.json")
    name_change = clashperk_message("members/name-change.json")
    role_change = clashperk_message("members/role-change.json")
    dune_leave = members_message(
        leave, at=utc(2026, 8, 8), tag=DUNE, name="Dune", message_id="1001"
    )
    dune_join = members_message(join, at=utc(2026, 8, 15), tag=DUNE, name="Dune", message_id="1002")
    return [join, leave, name_change, role_change, dune_leave, dune_join]


def test_duplicate_messages_are_deduped(clashperk_message: Message) -> None:
    join = clashperk_message("members/join.json")
    outcome = parse_all(MembersParser(), [join, join])
    assert len(outcome.events) == 1
    assert outcome.events[0].player_tag == AURORA


def test_normalize_writes_dataset_events_and_diagnostics(
    clashperk_message: Message, tmp_path: Path
) -> None:
    raw = write_raw_capture(
        tmp_path / "raw",
        _sample_messages(clashperk_message),
        extra_channels={"wars": [clashperk_message("wars/attack.json")]},
    )
    out = tmp_path / "normalized"
    result = normalize_capture(raw, out, window=AUGUST)

    dataset = MonthlyDataset.model_validate_json(result.dataset_path.read_text(encoding="utf-8"))
    assert dataset.month_label == "August 2026"
    tags = {player.player_tag for player in dataset.players}
    assert tags == {AURORA, BOREALIS, CASCADE, DUNE}

    aurora = next(player for player in dataset.players if player.player_tag == AURORA)
    assert aurora.current_display_name == "Aurora"
    assert aurora.membership.joined_this_month is True
    assert aurora.membership.eligible_days == 29
    assert aurora.regular_war.attacks_missed is None
    assert aurora.clan_games.points is None
    assert aurora.capital.contribution is None

    cascade = next(player for player in dataset.players if player.player_tag == CASCADE)
    assert cascade.current_display_name == "Cascade"
    assert cascade.membership.eligible_days == 31

    events = json.loads(result.events_path.read_text(encoding="utf-8"))
    assert events["month_key"] == "2026-08"
    assert {item["event_type"] for item in events["events"]} >= {
        "MemberJoined",
        "MemberLeft",
        "PlayerNameChanged",
        "PlayerRoleChanged",
    }

    diagnostics = json.loads(result.diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["members_only"] is False
    assert diagnostics["unused_channels"] == []
    assert "wars" in diagnostics["parsed_channels"]
    assert aurora.regular_war.attacks_used == 1
    assert not any("not wired" in note for note in dataset.data_notes)
    assert any("clan-games.json is missing" in note for note in dataset.data_notes)


def test_normalize_output_is_deterministic(clashperk_message: Message, tmp_path: Path) -> None:
    messages = _sample_messages(clashperk_message)
    first_dir = write_raw_capture(tmp_path / "raw-a", messages)
    second_dir = write_raw_capture(tmp_path / "raw-b", list(reversed(messages)))
    first = tmp_path / "out-a"
    second = tmp_path / "out-b"
    normalize_capture(first_dir, first, window=AUGUST)
    normalize_capture(second_dir, second, window=AUGUST)
    for name in ("events.json", "monthly_players.json", "diagnostics/parser_warnings.json"):
        assert (first / name).read_text(encoding="utf-8") == (second / name).read_text(
            encoding="utf-8"
        )


def test_normalize_output_validates_and_feeds_report_dry_run(
    clashperk_message: Message, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = write_raw_capture(tmp_path / "raw", _sample_messages(clashperk_message))
    out = tmp_path / "normalized"
    assert cli.main(["normalize", "--input", str(raw), "--output", str(out)]) == 0
    dataset_path = out / "monthly_players.json"
    dataset = MonthlyDataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    ranked = rank_players(dataset, ScoringConfig())
    assert ranked.review == []

    capsys.readouterr()
    assert cli.main(["report", "--input", str(dataset_path), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "August 2026" in printed
    assert "Data notes" in printed
    assert "Cascade" in printed
    assert "Needs Review" not in printed


def test_normalize_requires_month_without_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "members.json").write_text("[]", encoding="utf-8")
    exit_code = cli.main(["normalize", "--input", str(raw), "--output", str(tmp_path / "out")])
    assert exit_code == 2
    assert "Month is required" in capsys.readouterr().err


def test_normalize_missing_members_file_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    exit_code = cli.main(
        [
            "normalize",
            "--input",
            str(raw),
            "--output",
            str(tmp_path / "out"),
            "--month",
            "2026-08",
        ]
    )
    assert exit_code == 2
    assert "members.json" in capsys.readouterr().err


def test_members_only_capture_leaves_activity_unknown(
    clashperk_message: Message, tmp_path: Path
) -> None:
    raw = write_raw_capture(tmp_path / "raw", _sample_messages(clashperk_message))
    result = normalize_capture(raw, tmp_path / "out", window=AUGUST)
    assert result.dataset.regular_wars == 0
    assert result.dataset.cwl_rounds == 0
    assert result.dataset.clan_games_completed is False
    assert result.dataset.raid_weekends == 0
    for player in result.dataset.players:
        assert player.regular_war.attacks_used is None
        assert player.cwl.attacks_used is None
        assert player.clan_games.points is None
        assert player.capital.contribution is None
        assert player.donations.donated is None
    notes = " ".join(result.dataset.data_notes)
    assert "not wired" not in notes
    assert "wars.json is missing" in notes
    diagnostics = json.loads(result.diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["members_only"] is True
    assert "wars" in diagnostics["missing_channels"]


def test_multi_channel_normalize_fills_activity_metrics(
    clashperk_message: Message, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = write_raw_capture(
        tmp_path / "raw",
        _sample_messages(clashperk_message),
        extra_channels={
            "wars": [
                clashperk_message("wars/embed-final.json"),
                clashperk_message("wars/attack.json"),
                clashperk_message("wars/missed-attacks.json"),
                clashperk_message("wars/unknown-layout.json"),
            ],
            "cwl": [
                clashperk_message("cwl/embed-round.json"),
                clashperk_message("cwl/attack.json"),
                clashperk_message("cwl/missed-attacks.json"),
                clashperk_message("cwl/lineup-change.json"),
            ],
            "clan-games": [clashperk_message("clan-games/final-leaderboard.json")],
            "capital": [
                clashperk_message("capital/contribution.json"),
                clashperk_message("capital/raid-attack.json"),
                clashperk_message("capital/weekly-summary.json"),
            ],
            "donations": [clashperk_message("donations/daily.json")],
        },
    )
    out = tmp_path / "normalized"
    result = normalize_capture(raw, out, window=AUGUST)
    dataset = result.dataset
    assert dataset.regular_wars == 1
    assert dataset.cwl_rounds == 2
    assert dataset.clan_games_completed is True
    assert dataset.raid_weekends == 1
    by_tag = {player.player_tag: player for player in dataset.players}

    aurora = by_tag[AURORA]
    assert aurora.regular_war.wars_participated == 1
    assert aurora.regular_war.attacks_used == 1
    assert aurora.regular_war.attacks_missed == 0
    assert aurora.regular_war.total_stars == 3
    assert aurora.regular_war.average_destruction_percent == 100.0
    assert aurora.clan_games.points == 4000
    assert aurora.capital.contribution == 1200
    assert aurora.capital.raid_attacks is None
    assert aurora.donations.donated == 8420
    assert aurora.donations.received == 5210

    cascade = by_tag[CASCADE]
    assert cascade.regular_war.attacks_used == 1
    assert cascade.regular_war.attacks_missed == 1
    assert cascade.regular_war.total_stars == 2
    assert cascade.clan_games.points == 4000
    assert cascade.capital.contribution is None
    assert cascade.capital.raid_attacks == 6
    assert cascade.donations.donated == 6100

    dune = by_tag[DUNE]
    assert dune.regular_war.attacks_used == 0
    assert dune.regular_war.attacks_missed == 2
    assert dune.clan_games.points == 0
    assert dune.cwl.attacks_missed == 1
    assert dune.cwl.rounds_in_lineup == 2
    assert dune.donations.donated == 0

    borealis = by_tag[BOREALIS]
    assert borealis.regular_war.wars_participated == 0
    assert borealis.regular_war.attacks_used is None
    assert borealis.clan_games.points is None
    assert borealis.cwl.rounds_in_lineup == 1
    assert borealis.capital.contribution is None

    notes = " ".join(dataset.data_notes)
    assert "not wired" not in notes
    assert "Everest" in notes
    assert any("unknown_layout" in note for note in dataset.data_notes)
    MonthlyDataset.model_validate_json(result.dataset_path.read_text(encoding="utf-8"))

    capsys.readouterr()
    assert cli.main(["report", "--input", str(result.dataset_path), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "1 regular wars" in printed
    assert "Clan Games completed" in printed
    assert "1 Raid Weekends" in printed


def test_cross_month_clan_games_follows_edit_time_not_season(
    clashperk_message: Message, tmp_path: Path
) -> None:
    """August season edited on 1 September belongs to September, not August."""
    board = clashperk_message("clan-games/cross-month-leaderboard.json")
    august = write_raw_capture(
        tmp_path / "august",
        _sample_messages(clashperk_message),
        extra_channels={"clan-games": [board]},
    )
    september_member = members_message(
        clashperk_message("members/role-change.json"),
        at=utc(2026, 9, 2),
        tag=AURORA,
        name="Aurora",
        message_id="sept-aurora",
    )
    september = write_raw_capture(
        tmp_path / "september",
        [september_member],
        month_key="2026-09",
        extra_channels={"clan-games": [board]},
    )
    august_result = normalize_capture(august, tmp_path / "out-august", window=AUGUST)
    september_window = month_window(2026, 9, timezone=TORONTO)
    september_result = normalize_capture(
        september, tmp_path / "out-september", window=september_window
    )
    august_aurora = next(
        player for player in august_result.dataset.players if player.player_tag == AURORA
    )
    september_aurora = next(
        player for player in september_result.dataset.players if player.player_tag == AURORA
    )
    assert august_result.dataset.clan_games_completed is False
    assert august_aurora.clan_games.points is None
    assert september_result.dataset.clan_games_completed is True
    assert september_aurora.clan_games.points == 4000


def test_empty_wars_file_is_observed_empty_participation(
    clashperk_message: Message, tmp_path: Path
) -> None:
    raw = write_raw_capture(
        tmp_path / "raw",
        _sample_messages(clashperk_message),
        extra_channels={"wars": []},
    )
    result = normalize_capture(raw, tmp_path / "out", window=AUGUST)
    assert result.dataset.regular_wars == 0
    notes = " ".join(result.dataset.data_notes)
    assert "wars.json is missing" not in notes
    assert "not wired" not in notes
    for player in result.dataset.players:
        assert player.regular_war.wars_participated == 0
        assert player.regular_war.attacks_used is None
        assert player.regular_war.attacks_missed is None


def test_coarsest_donation_interval_wins(clashperk_message: Message, tmp_path: Path) -> None:
    daily = clashperk_message("donations/daily.json")
    weekly = deepcopy(daily)
    weekly["id"] = "1538000000000000002"
    weekly["embeds"][0]["description"] = weekly["embeds"][0]["description"].replace(
        "Daily Donations", "Weekly Donations"
    )
    weekly["embeds"][0]["description"] = weekly["embeds"][0]["description"].replace(
        "`  8420  5210 `", "`  1111  2222 `"
    )
    monthly = deepcopy(clashperk_message("donations/monthly-summary.json"))
    monthly["id"] = "1538000000000000003"
    monthly["embeds"][0]["description"] = monthly["embeds"][0]["description"].replace(
        "`  8420  5210 `", "`  9999  8888 `"
    )
    raw = write_raw_capture(
        tmp_path / "raw",
        _sample_messages(clashperk_message),
        extra_channels={"donations": [daily, weekly, monthly]},
    )
    result = normalize_capture(raw, tmp_path / "out", window=AUGUST)
    aurora = next(player for player in result.dataset.players if player.player_tag == AURORA)
    assert aurora.donations.donated == 9999
    assert aurora.donations.received == 8888


def test_manifest_timezone_mismatch_is_a_data_note(
    clashperk_message: Message, tmp_path: Path
) -> None:
    raw = write_raw_capture(tmp_path / "raw", _sample_messages(clashperk_message))
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    manifest["window"]["timezone"] = "UTC"
    (raw / "manifest.json").write_text(dump_json(manifest), encoding="utf-8")
    result = normalize_capture(raw, tmp_path / "out", window=AUGUST)
    assert any(
        "Fetch manifest timezone is UTC" in note and "America/Toronto" in note
        for note in result.dataset.data_notes
    )
