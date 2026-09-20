from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from clash_reporter.collection import ChannelCaptureError, capture_channels
from clash_reporter.collection.capture import MANIFEST_FILENAME
from clash_reporter.discord_client import DiscordClient
from clash_reporter.window import resolve_month

TOKEN = "not-a-real-token-abc123"  # noqa: S105 - dummy value for mocked transports
TORONTO = "America/Toronto"
CAPTURED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)

MEMBERS = [
    {
        "id": "200",
        "channel_id": "111",
        "guild_id": "900",
        "timestamp": "2026-08-20T18:00:00+00:00",
        "author": {"id": "700", "username": "ClashPerk", "bot": True},
        "content": "<@800> joined",
        "embeds": [
            {
                "title": "Member Joined",
                "description": "Aurora (#R22YRC0UY)",
                "fields": [{"name": "Tag", "value": "#R22YRC0UY"}],
            }
        ],
        "mentions": [{"id": "800", "username": "gabriel"}],
    },
    {
        "id": "100",
        "channel_id": "111",
        "guild_id": "900",
        "timestamp": "2026-08-02T18:00:00+00:00",
        "author": {"id": "700", "username": "ClashPerk", "bot": True},
        "content": "Aurora (#R22YRC0UY) left",
        "embeds": [],
        "mentions": [],
    },
]
WARS = [
    {
        "id": "300",
        "channel_id": "222",
        "guild_id": "900",
        "timestamp": "2026-08-11T09:00:00+00:00",
        "author": {"id": "700", "username": "ClashPerk", "bot": True},
        "content": "#R22YRC0UY 3 stars",
        "embeds": [],
    }
]


def transport_for(pages: Mapping[str, list[list[dict[str, Any]]]]) -> httpx.MockTransport:
    """Serve a canned sequence of history pages per channel ID."""
    calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        channel_id = request.url.path.split("/")[-2]
        channel_pages = pages[channel_id]
        index = calls.get(channel_id, 0)
        calls[channel_id] = index + 1
        if index >= len(channel_pages):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=channel_pages[index])

    return httpx.MockTransport(handler)


def client_for(transport: httpx.MockTransport) -> DiscordClient:
    return DiscordClient(TOKEN, transport=transport, sleep=lambda seconds: None)


def default_transport() -> httpx.MockTransport:
    return transport_for({"111": [MEMBERS], "222": [WARS]})


def capture(tmp_path: Path, **kwargs: Any) -> Any:
    window = kwargs.pop("window", None) or resolve_month("2026-08", timezone=TORONTO)
    transport = kwargs.pop("transport", None) or default_transport()
    channels = kwargs.pop("channels", None) or {"cp-members": "111", "cp-wars": "222"}
    kwargs.setdefault("captured_at", CAPTURED_AT)
    with client_for(transport) as client:
        return capture_channels(
            client,
            channels=channels,
            window=window,
            output_dir=tmp_path,
            **kwargs,
        )


def test_writes_one_file_per_channel_plus_a_manifest(tmp_path: Path) -> None:
    run = capture(tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "cp-members.json",
        "cp-wars.json",
        "manifest.json",
    ]
    assert [channel.name for channel in run.channels] == ["cp-members", "cp-wars"]
    assert run.message_count == 3
    assert run.manifest_path == tmp_path / MANIFEST_FILENAME


def test_messages_are_written_in_chronological_order(tmp_path: Path) -> None:
    capture(tmp_path)
    written = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    assert [message["id"] for message in written] == ["100", "200"]


def test_output_round_trips_to_the_same_message_objects(tmp_path: Path) -> None:
    capture(tmp_path)
    written = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    assert written == sorted(MEMBERS, key=lambda message: message["timestamp"])
    assert json.loads((tmp_path / "cp-wars.json").read_text(encoding="utf-8")) == WARS


def test_output_is_byte_identical_for_the_same_input(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    capture(first)
    capture(second)
    assert (first / "cp-members.json").read_bytes() == (second / "cp-members.json").read_bytes()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()


def test_manifest_records_window_counts_and_api_version(tmp_path: Path) -> None:
    run = capture(tmp_path)
    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))

    assert manifest["captured_at"] == "2026-09-01T12:00:00+00:00"
    assert manifest["api_version"] == 10
    assert manifest["sanitized"] is False
    assert manifest["window"]["month_key"] == "2026-08"
    assert manifest["window"]["timezone"] == TORONTO
    assert manifest["window"]["start_utc"] == "2026-08-01T04:00:00+00:00"
    assert manifest["window"]["complete"] is True
    assert manifest["channels"] == [
        {"channel_id": "111", "file": "cp-members.json", "message_count": 2, "name": "cp-members"},
        {"channel_id": "222", "file": "cp-wars.json", "message_count": 1, "name": "cp-wars"},
    ]


def test_partial_current_month_capture_is_recorded_as_incomplete(tmp_path: Path) -> None:
    window = resolve_month("current", timezone=TORONTO, now=datetime(2026, 9, 4, tzinfo=UTC))
    partial = [
        {
            "id": "400",
            "channel_id": "111",
            "timestamp": "2026-09-02T10:00:00+00:00",
            "content": "#R22YRC0UY joined",
        }
    ]
    run = capture(
        tmp_path,
        window=window,
        channels={"cp-members": "111"},
        transport=transport_for({"111": [partial]}),
        captured_at=datetime(2026, 9, 4, tzinfo=UTC),
    )

    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["window"]["month_key"] == "2026-09"
    assert manifest["window"]["complete"] is False
    assert run.message_count == 1


def test_a_forbidden_channel_fails_the_run_and_leaves_no_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/channels/222/" in request.url.path:
            return httpx.Response(403, json={"message": "Missing Access"})
        return httpx.Response(200, json=MEMBERS)

    with client_for(httpx.MockTransport(handler)) as client:
        with pytest.raises(ChannelCaptureError) as excinfo:
            capture_channels(
                client,
                channels={"cp-members": "111", "cp-wars": "222"},
                window=resolve_month("2026-08", timezone=TORONTO),
                output_dir=tmp_path,
                captured_at=CAPTURED_AT,
            )

    error = excinfo.value
    assert error.channel_name == "cp-wars"
    assert "cp-wars" in str(error)
    assert "222" in str(error)
    assert TOKEN not in str(error)
    assert not (tmp_path / "cp-wars.json").exists()
    assert not (tmp_path / MANIFEST_FILENAME).exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_capture_requires_at_least_one_channel(tmp_path: Path) -> None:
    with client_for(default_transport()) as client:
        with pytest.raises(ValueError, match="No channels"):
            capture_channels(
                client,
                channels={},
                window=resolve_month("2026-08", timezone=TORONTO),
                output_dir=tmp_path,
            )


def test_sanitize_pseudonymizes_ids_consistently_and_keeps_payload_structure(
    tmp_path: Path,
) -> None:
    run = capture(tmp_path, sanitize=True)

    members = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    wars = json.loads((tmp_path / "cp-wars.json").read_text(encoding="utf-8"))
    join = members[1]

    # Message IDs, timestamps, embeds, and player tags survive untouched.
    assert [message["id"] for message in members] == ["100", "200"]
    assert join["timestamp"] == "2026-08-20T18:00:00+00:00"
    assert join["embeds"] == MEMBERS[0]["embeds"]
    assert "#R22YRC0UY" in json.dumps(members)

    # Guild and user IDs are replaced, and the same source ID maps to the same
    # replacement everywhere, including across channels and inside content.
    assert join["guild_id"] != "900"
    assert join["author"]["id"] != "700"
    assert join["author"]["username"] == "ClashPerk"
    assert members[0]["author"]["id"] == join["author"]["id"]
    assert wars[0]["author"]["id"] == join["author"]["id"]
    assert wars[0]["guild_id"] == join["guild_id"]
    assert join["content"] == f"<@{join['mentions'][0]['id']}> joined"
    assert "800" not in join["content"]

    assert json.loads(run.manifest_path.read_text(encoding="utf-8"))["sanitized"] is True


def test_sanitize_is_deterministic_across_runs(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    capture(first, sanitize=True)
    capture(second, sanitize=True)
    assert (first / "cp-members.json").read_bytes() == (second / "cp-members.json").read_bytes()


def test_unsanitized_capture_preserves_original_ids(tmp_path: Path) -> None:
    capture(tmp_path)
    members = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    assert members[1]["guild_id"] == "900"
    assert members[1]["author"]["id"] == "700"
