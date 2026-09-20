"""Raw payload capture.

Writes one JSON file per channel plus a run manifest so real ClashPerk payloads
can be promoted into ``tests/fixtures/`` and every later parser can be built
offline. This module downloads and writes; it never parses.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clash_reporter.collection.fetch_messages import collect_channel
from clash_reporter.collection.sanitize import IdSanitizer
from clash_reporter.discord_client import DiscordClient, DiscordError
from clash_reporter.window import ReportingWindow

__all__ = [
    "MANIFEST_FILENAME",
    "CaptureRun",
    "ChannelCapture",
    "ChannelCaptureError",
    "capture_channels",
    "dump_json",
]

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"


class ChannelCaptureError(RuntimeError):
    """One channel could not be captured. The run fails rather than writing nothing."""

    def __init__(self, channel_name: str, channel_id: str, reason: str) -> None:
        super().__init__(f"Failed to capture #{channel_name} (channel {channel_id}): {reason}")
        self.channel_name = channel_name
        self.channel_id = channel_id
        self.reason = reason


@dataclass(frozen=True)
class ChannelCapture:
    name: str
    channel_id: str
    path: Path
    message_count: int


@dataclass(frozen=True)
class CaptureRun:
    window: ReportingWindow
    output_dir: Path
    manifest_path: Path
    channels: tuple[ChannelCapture, ...]
    sanitized: bool
    captured_at: datetime

    @property
    def message_count(self) -> int:
        return sum(channel.message_count for channel in self.channels)


def dump_json(payload: Any) -> str:
    """Deterministic JSON text: sorted keys, fixed indentation, trailing newline."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def capture_channels(
    client: DiscordClient,
    *,
    channels: Mapping[str, str],
    window: ReportingWindow,
    output_dir: Path,
    sanitize: bool = False,
    captured_at: datetime | None = None,
) -> CaptureRun:
    """Capture every configured channel for ``window`` into ``output_dir``.

    A window that is still open (``--month current``) is captured as far as it
    exists; the manifest records whether the month was complete.

    Raises :class:`ChannelCaptureError` naming the channel as soon as one
    channel cannot be read, and leaves no file behind for that channel.
    """
    if not channels:
        raise ValueError("No channels to capture")

    output_dir.mkdir(parents=True, exist_ok=True)
    moment = (captured_at or datetime.now(tz=UTC)).astimezone(UTC)
    sanitizer = IdSanitizer() if sanitize else None
    captures: list[ChannelCapture] = []

    for name, channel_id in channels.items():
        try:
            messages = collect_channel(client, channel_id, window)
        except DiscordError as exc:
            raise ChannelCaptureError(name, str(channel_id), str(exc)) from exc
        if sanitizer is not None:
            messages = sanitizer.sanitize_all(messages)
        path = output_dir / f"{name}.json"
        _write_atomic(path, dump_json(messages))
        logger.info(
            "captured %s: %d messages",
            name,
            len(messages),
            extra={
                "operation": "fetch",
                "channel": name,
                "channel_id": str(channel_id),
                "message_count": len(messages),
            },
        )
        captures.append(
            ChannelCapture(
                name=name,
                channel_id=str(channel_id),
                path=path,
                message_count=len(messages),
            )
        )

    manifest_path = output_dir / MANIFEST_FILENAME
    _write_atomic(
        manifest_path,
        dump_json(
            {
                "captured_at": moment.isoformat(),
                "api_version": client.api_version,
                "sanitized": sanitize,
                "window": window.describe(),
                "channels": [
                    {
                        "name": capture.name,
                        "channel_id": capture.channel_id,
                        "file": capture.path.name,
                        "message_count": capture.message_count,
                    }
                    for capture in captures
                ],
            }
        ),
    )
    return CaptureRun(
        window=window,
        output_dir=output_dir,
        manifest_path=manifest_path,
        channels=tuple(captures),
        sanitized=sanitize,
        captured_at=moment,
    )


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file so a crash cannot leave a half-written capture."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
