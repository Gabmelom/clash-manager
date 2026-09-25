"""Read fetch artifacts, run channel parsers, write a MonthlyDataset.

Input layout matches ``clash-reporter fetch``:

```text
<input>/
  members.json       # required
  wars.json          # parsed when present
  cwl.json
  clan-games.json
  capital.json
  donations.json
  manifest.json      # optional; supplies month_key when --month is omitted
```

Output:

```text
<output>/
  events.json
  monthly_players.json
  diagnostics/parser_warnings.json
```
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clash_reporter.aggregation.activity import ActivityCoverage
from clash_reporter.aggregation.monthly_summary import (
    MEMBERS_ONLY_NOTE,
    build_monthly_dataset,
    event_in_window,
)
from clash_reporter.collection.capture import MANIFEST_FILENAME, dump_json
from clash_reporter.config import DATA_CHANNELS
from clash_reporter.models import MonthlyDataset
from clash_reporter.parsers.base import DomainEvent, IgnoredMessage, Parser, parse_all
from clash_reporter.parsers.capital import CapitalParser
from clash_reporter.parsers.clan_games import ClanGamesParser
from clash_reporter.parsers.cwl import CwlParser
from clash_reporter.parsers.donations import DonationsParser
from clash_reporter.parsers.members import MembersParser
from clash_reporter.parsers.wars import WarsParser
from clash_reporter.roster import ClanRoster
from clash_reporter.window import ReportingWindow, resolve_month

__all__ = [
    "DEFAULT_NORMALIZED_OUTPUT",
    "MEMBERS_CHANNEL_NAME",
    "NormalizeError",
    "NormalizeResult",
    "load_raw_messages",
    "normalize_capture",
    "window_from_manifest",
]

DEFAULT_NORMALIZED_OUTPUT = Path("./artifacts/normalized")
MEMBERS_CHANNEL_NAME = "members"


class NormalizeError(RuntimeError):
    """The capture could not be normalized. The CLI prints this and exits 2."""


@dataclass(frozen=True)
class NormalizeResult:
    window: ReportingWindow
    output_dir: Path
    dataset: MonthlyDataset
    events_path: Path
    dataset_path: Path
    diagnostics_path: Path
    event_count: int
    player_count: int
    ignored_count: int
    roster_path: Path | None = None


def window_from_manifest(path: Path, *, timezone: str) -> ReportingWindow | None:
    """Resolve a reporting window from a fetch ``manifest.json``, if present.

    Only ``month_key`` is used. Boundaries are always built in ``timezone``
    (``Settings.report_timezone``), not the manifest's captured timezone. A
    mismatch is recorded as a dataset data note by :func:`normalize_capture`.
    """
    payload = _load_manifest(path)
    if payload is None:
        return None
    window = payload.get("window")
    if not isinstance(window, Mapping):
        return None
    month_key = window.get("month_key")
    if not isinstance(month_key, str) or not month_key:
        return None
    return resolve_month(month_key, timezone=timezone)


def load_raw_messages(path: Path) -> list[dict[str, Any]]:
    """Load one fetch channel file: a JSON array of Discord message objects."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NormalizeError(f"Invalid {path.name}: {exc}") from exc
    if not isinstance(payload, list):
        raise NormalizeError(f"{path.name} must be a JSON array of Discord messages")
    messages: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise NormalizeError(f"{path.name} item {index} is not a JSON object")
        messages.append(item)
    return messages


def normalize_capture(
    input_dir: Path,
    output_dir: Path,
    *,
    window: ReportingWindow,
    roster: ClanRoster | None = None,
) -> NormalizeResult:
    """Parse a fetch directory and write normalize artifacts.

    ``roster`` is the current CoC clan member list. When it was fetched, unique
    unmatched display names are filled from it and ``coc_roster.json`` is written
    beside the dataset. When it is omitted, attribution stays Discord-only and
    no roster file is written. A roster whose ``note`` is set was not applied;
    the note is recorded and Discord attribution still runs.
    """
    members_path = input_dir / f"{MEMBERS_CHANNEL_NAME}.json"
    if not members_path.is_file():
        raise NormalizeError(
            f"Missing {members_path.name} under {input_dir}. "
            "Run `clash-reporter fetch` first, or point --input at a fetch output directory."
        )

    messages = load_raw_messages(members_path)
    outcome = parse_all(MembersParser(), messages)
    parsed_channels = [MEMBERS_CHANNEL_NAME]
    coverage = ActivityCoverage()
    for name in DATA_CHANNELS:
        if name == MEMBERS_CHANNEL_NAME:
            continue
        path = input_dir / f"{name}.json"
        if not path.is_file():
            continue
        channel_outcome = _parse_channel_file(name, load_raw_messages(path))
        outcome = outcome.extend(channel_outcome)
        parsed_channels.append(name)
        coverage = _with_channel(coverage, name)
    in_window = [event for event in outcome.events if event_in_window(event, window)]
    missing = _missing_channel_files(input_dir)
    extra_notes = [note for note in (_timezone_mismatch_note(input_dir, window),) if note]
    clan_roster = None
    roster_path: Path | None = None
    if roster is not None:
        extra_notes.append(roster.data_note())
        if roster.applied:
            clan_roster = roster.members
        roster_path = output_dir / "coc_roster.json"
    dataset = build_monthly_dataset(
        in_window,
        window,
        diagnostics=outcome.diagnostics,
        missing_channels=missing,
        coverage=coverage,
        extra_notes=extra_notes,
        clan_roster=clan_roster,
    )
    events_payload = _events_payload(in_window, window, parsed_channels)
    diagnostics_payload = _diagnostics_payload(
        outcome.diagnostics, parsed_channels, missing, coverage
    )

    events_path = output_dir / "events.json"
    dataset_path = output_dir / "monthly_players.json"
    diagnostics_path = output_dir / "diagnostics" / "parser_warnings.json"
    _write_json(events_path, events_payload)
    _write_json(dataset_path, dataset.model_dump(mode="json"))
    _write_json(diagnostics_path, diagnostics_payload)
    if roster is not None and roster_path is not None:
        _write_json(roster_path, roster.snapshot())

    return NormalizeResult(
        window=window,
        output_dir=output_dir,
        dataset=dataset,
        events_path=events_path,
        dataset_path=dataset_path,
        diagnostics_path=diagnostics_path,
        event_count=len(in_window),
        player_count=len(dataset.players),
        ignored_count=len(outcome.diagnostics),
        roster_path=roster_path,
    )


def _load_manifest(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NormalizeError(f"Invalid {MANIFEST_FILENAME}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise NormalizeError(f"{MANIFEST_FILENAME} must be a JSON object")
    return payload


def _timezone_mismatch_note(input_dir: Path, window: ReportingWindow) -> str | None:
    payload = _load_manifest(input_dir / MANIFEST_FILENAME)
    if payload is None:
        return None
    captured = payload.get("window")
    if not isinstance(captured, Mapping):
        return None
    timezone = captured.get("timezone")
    if not isinstance(timezone, str) or not timezone or timezone == window.timezone:
        return None
    return f"Fetch manifest timezone is {timezone}; eligible_days used {window.timezone}."


_CHANNEL_PARSERS: dict[str, Parser] = {
    "wars": WarsParser(),
    "cwl": CwlParser(),
    "capital": CapitalParser(),
    "clan-games": ClanGamesParser(),
    "donations": DonationsParser(),
}


def _parse_channel_file(name: str, messages: Sequence[Mapping[str, Any]]) -> Any:
    parser = _CHANNEL_PARSERS[name]
    if isinstance(parser, WarsParser | CwlParser):
        return parser.parse_channel(messages)
    return parse_all(parser, messages)


def _with_channel(coverage: ActivityCoverage, name: str) -> ActivityCoverage:
    flags = {
        "wars": "wars",
        "cwl": "cwl",
        "clan-games": "clan_games",
        "capital": "capital",
        "donations": "donations",
    }
    field = flags[name]
    return ActivityCoverage(**{**asdict(coverage), field: True})


def _missing_channel_files(input_dir: Path) -> list[str]:
    missing: list[str] = []
    for name in DATA_CHANNELS:
        if name == MEMBERS_CHANNEL_NAME:
            continue
        if not (input_dir / f"{name}.json").is_file():
            missing.append(name)
    return missing


def _events_payload(
    events: Sequence[DomainEvent],
    window: ReportingWindow,
    parsed_channels: Sequence[str],
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_key))
    parsers = [_parser_meta(name) for name in parsed_channels]
    return {
        "month_key": window.month_key,
        "month_label": window.month_label,
        "timezone": window.timezone,
        "parser": parsers[0],
        "parsers": parsers,
        "events": [event.model_dump(mode="json") for event in ordered],
    }


def _parser_meta(channel: str) -> dict[str, str]:
    if channel == MEMBERS_CHANNEL_NAME:
        return {"name": MembersParser.name, "version": MembersParser.version}
    parser = _CHANNEL_PARSERS[channel]
    return {"name": parser.name, "version": parser.version}


def _diagnostics_payload(
    diagnostics: Sequence[IgnoredMessage],
    parsed_channels: Sequence[str],
    missing_channels: Sequence[str],
    coverage: ActivityCoverage,
) -> dict[str, Any]:
    ignored = [asdict(item) for item in diagnostics]
    ignored.sort(
        key=lambda item: (
            str(item.get("message_id") or ""),
            str(item.get("reason_code") or ""),
            str(item.get("detail") or ""),
        )
    )
    members_only = not coverage.any_parsed
    return {
        "members_only": members_only,
        "note": (
            MEMBERS_ONLY_NOTE
            if members_only
            else "Parsed every channel file present in the capture."
        ),
        "parsed_channels": list(parsed_channels),
        "missing_channels": list(missing_channels),
        "unused_channels": [],
        "ignored_messages": ignored,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(dump_json(payload), encoding="utf-8")
    os.replace(temporary, path)
