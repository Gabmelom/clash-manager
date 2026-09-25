"""Read fetch artifacts, run the members parser, write a MonthlyDataset.

Input layout matches ``clash-reporter fetch``:

```text
<input>/
  cp-members.json    # list of Discord message objects
  cp-wars.json       # optional, ignored until that parser lands
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

from clash_reporter.aggregation.monthly_summary import MEMBERS_ONLY_NOTE, build_monthly_dataset
from clash_reporter.collection.capture import MANIFEST_FILENAME, dump_json
from clash_reporter.config import DATA_CHANNELS
from clash_reporter.models import MonthlyDataset
from clash_reporter.parsers.base import DomainEvent, IgnoredMessage, parse_all
from clash_reporter.parsers.members import MembersParser
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
MEMBERS_CHANNEL_NAME = "cp-members"


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
) -> NormalizeResult:
    """Parse ``#cp-members`` from a fetch directory and write normalize artifacts."""
    members_path = input_dir / f"{MEMBERS_CHANNEL_NAME}.json"
    if not members_path.is_file():
        raise NormalizeError(
            f"Missing {members_path.name} under {input_dir}. "
            "Run `clash-reporter fetch` first, or point --input at a fetch output directory."
        )

    messages = load_raw_messages(members_path)
    outcome = parse_all(MembersParser(), messages)
    in_window = [event for event in outcome.events if window.contains(event.occurred_at)]
    unused = _unused_channel_files(input_dir)
    extra_notes = [note for note in (_timezone_mismatch_note(input_dir, window),) if note]
    dataset = build_monthly_dataset(
        in_window,
        window,
        diagnostics=outcome.diagnostics,
        unused_channels=unused,
        extra_notes=extra_notes,
    )
    events_payload = _events_payload(in_window, window)
    diagnostics_payload = _diagnostics_payload(outcome.diagnostics, unused)

    events_path = output_dir / "events.json"
    dataset_path = output_dir / "monthly_players.json"
    diagnostics_path = output_dir / "diagnostics" / "parser_warnings.json"
    _write_json(events_path, events_payload)
    _write_json(dataset_path, dataset.model_dump(mode="json"))
    _write_json(diagnostics_path, diagnostics_payload)

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


def _unused_channel_files(input_dir: Path) -> list[str]:
    unused: list[str] = []
    for name in DATA_CHANNELS:
        if name == MEMBERS_CHANNEL_NAME:
            continue
        if (input_dir / f"{name}.json").is_file():
            unused.append(name)
    return unused


def _events_payload(events: Sequence[DomainEvent], window: ReportingWindow) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_key))
    return {
        "month_key": window.month_key,
        "month_label": window.month_label,
        "timezone": window.timezone,
        "parser": {"name": MembersParser.name, "version": MembersParser.version},
        "events": [event.model_dump(mode="json") for event in ordered],
    }


def _diagnostics_payload(
    diagnostics: Sequence[IgnoredMessage], unused_channels: Sequence[str]
) -> dict[str, Any]:
    ignored = [asdict(item) for item in diagnostics]
    ignored.sort(
        key=lambda item: (
            str(item.get("message_id") or ""),
            str(item.get("reason_code") or ""),
            str(item.get("detail") or ""),
        )
    )
    return {
        "members_only": True,
        "note": MEMBERS_ONLY_NOTE,
        "unused_channels": list(unused_channels),
        "ignored_messages": ignored,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(dump_json(payload), encoding="utf-8")
    os.replace(temporary, path)
