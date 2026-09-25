from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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

MEMBERS_CHANNEL = "400000000000000001"
WARS_CHANNEL = "400000000000000002"


@pytest.fixture
def clashperk_history(
    clashperk_message: Callable[[str], dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """One page of real ClashPerk history per channel, newest first."""
    return {
        MEMBERS_CHANNEL: [
            clashperk_message("members/name-change.json"),  # 2026-08-22
            clashperk_message("members/leave.json"),  # 2026-08-19
            clashperk_message("members/join.json"),  # 2026-08-03
        ],
        WARS_CHANNEL: [clashperk_message("wars/attack.json")],
    }


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


@pytest.fixture
def capture(
    clashperk_history: dict[str, list[dict[str, Any]]],
) -> Callable[..., Any]:
    """Run a capture of the ClashPerk fixture channels into a directory."""

    def run(output_dir: Path, **kwargs: Any) -> Any:
        window = kwargs.pop("window", None) or resolve_month("2026-08", timezone=TORONTO)
        transport = kwargs.pop("transport", None) or transport_for(
            {channel: [messages] for channel, messages in clashperk_history.items()}
        )
        channels = kwargs.pop("channels", None) or {
            "members": MEMBERS_CHANNEL,
            "wars": WARS_CHANNEL,
        }
        kwargs.setdefault("captured_at", CAPTURED_AT)
        with client_for(transport) as client:
            return capture_channels(
                client,
                channels=channels,
                window=window,
                output_dir=output_dir,
                **kwargs,
            )

    return run


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_writes_one_file_per_channel_plus_a_manifest(
    capture: Callable[..., Any], tmp_path: Path
) -> None:
    run = capture(tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "manifest.json",
        "members.json",
        "wars.json",
    ]
    assert [channel.name for channel in run.channels] == ["members", "wars"]
    assert run.message_count == 4
    assert run.manifest_path == tmp_path / MANIFEST_FILENAME


def test_messages_are_written_in_chronological_order(
    capture: Callable[..., Any], tmp_path: Path
) -> None:
    capture(tmp_path)
    written = read(tmp_path / "members.json")
    assert [message["timestamp"] for message in written] == [
        "2026-08-03T18:12:44.281000+00:00",
        "2026-08-19T02:41:09.553000+00:00",
        "2026-08-22T09:33:51.902000+00:00",
    ]


def test_output_round_trips_to_the_same_message_objects(
    capture: Callable[..., Any],
    clashperk_history: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    capture(tmp_path)
    written = read(tmp_path / "members.json")
    assert written == list(reversed(clashperk_history[MEMBERS_CHANNEL]))
    assert read(tmp_path / "wars.json") == clashperk_history[WARS_CHANNEL]


def test_clashperk_payload_details_survive_the_capture(
    capture: Callable[..., Any], tmp_path: Path
) -> None:
    capture(tmp_path)
    join = read(tmp_path / "members.json")[0]
    attack = read(tmp_path / "wars.json")[0]

    assert join["embeds"][0]["title"] == "\u200eAurora (#2Y0LRPV8Q)"
    assert join["embeds"][0]["footer"]["text"] == "Joined Maple Legends [43/50]"
    assert join["components"][0]["components"][0]["label"] == "View Profile"
    # War attacks are plain content, not embeds, and name-only.
    assert attack["embeds"] == []
    assert "Aurora" in attack["content"]


def test_output_is_byte_identical_for_the_same_input(
    capture: Callable[..., Any], tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    capture(first)
    capture(second)
    assert (first / "members.json").read_bytes() == (second / "members.json").read_bytes()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()


def test_manifest_records_window_counts_and_api_version(
    capture: Callable[..., Any], tmp_path: Path
) -> None:
    run = capture(tmp_path)
    manifest = read(run.manifest_path)

    assert manifest["captured_at"] == "2026-09-01T12:00:00+00:00"
    assert manifest["api_version"] == 10
    assert manifest["sanitized"] is False
    assert manifest["window"]["month_key"] == "2026-08"
    assert manifest["window"]["timezone"] == TORONTO
    assert manifest["window"]["start_utc"] == "2026-08-01T04:00:00+00:00"
    assert manifest["window"]["complete"] is True
    assert manifest["channels"] == [
        {
            "channel_id": MEMBERS_CHANNEL,
            "file": "members.json",
            "message_count": 3,
            "name": "members",
        },
        {
            "channel_id": WARS_CHANNEL,
            "file": "wars.json",
            "message_count": 1,
            "name": "wars",
        },
    ]


def test_partial_current_month_capture_is_recorded_as_incomplete(
    capture: Callable[..., Any],
    clashperk_message: Callable[[str], dict[str, Any]],
    repost: Callable[..., dict[str, Any]],
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    window = resolve_month("current", timezone=TORONTO, now=now)
    partial = [repost(clashperk_message("members/join.json"), datetime(2026, 9, 2, 10, tzinfo=UTC))]
    run = capture(
        tmp_path,
        window=window,
        channels={"members": MEMBERS_CHANNEL},
        transport=transport_for({MEMBERS_CHANNEL: [partial]}),
        captured_at=now,
    )

    manifest = read(run.manifest_path)
    assert manifest["window"]["month_key"] == "2026-09"
    assert manifest["window"]["complete"] is False
    assert run.message_count == 1


def test_a_forbidden_channel_fails_the_run_and_leaves_no_file(
    clashperk_history: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if f"/channels/{WARS_CHANNEL}/" in request.url.path:
            return httpx.Response(403, json={"message": "Missing Access"})
        return httpx.Response(200, json=clashperk_history[MEMBERS_CHANNEL])

    with client_for(httpx.MockTransport(handler)) as client:
        with pytest.raises(ChannelCaptureError) as excinfo:
            capture_channels(
                client,
                channels={"members": MEMBERS_CHANNEL, "wars": WARS_CHANNEL},
                window=resolve_month("2026-08", timezone=TORONTO),
                output_dir=tmp_path,
                captured_at=CAPTURED_AT,
            )

    error = excinfo.value
    assert error.channel_name == "wars"
    assert "wars" in str(error)
    assert WARS_CHANNEL in str(error)
    assert TOKEN not in str(error)
    assert not (tmp_path / "wars.json").exists()
    assert not (tmp_path / MANIFEST_FILENAME).exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_allow_partial_records_an_inaccessible_channel_and_continues(
    clashperk_history: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if f"/channels/{WARS_CHANNEL}/" in request.url.path:
            return httpx.Response(403, json={"message": "Missing Access"})
        return httpx.Response(200, json=clashperk_history[MEMBERS_CHANNEL])

    with client_for(httpx.MockTransport(handler)) as client:
        run = capture_channels(
            client,
            channels={"members": MEMBERS_CHANNEL, "wars": WARS_CHANNEL},
            window=resolve_month("2026-08", timezone=TORONTO),
            output_dir=tmp_path,
            captured_at=CAPTURED_AT,
            allow_partial=True,
        )

    assert [channel.name for channel in run.channels] == ["members"]
    assert [failure.name for failure in run.failures] == ["wars"]
    assert not (tmp_path / "wars.json").exists()
    assert (tmp_path / "members.json").is_file()
    manifest = read(run.manifest_path)
    assert manifest["failures"][0]["name"] == "wars"
    assert TOKEN not in json.dumps(manifest)


def test_capture_requires_at_least_one_channel(
    clashperk_history: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    transport = transport_for({channel: [page] for channel, page in clashperk_history.items()})
    with client_for(transport) as client:
        with pytest.raises(ValueError, match="No channels"):
            capture_channels(
                client,
                channels={},
                window=resolve_month("2026-08", timezone=TORONTO),
                output_dir=tmp_path,
            )


def test_sanitize_pseudonymizes_ids_consistently_and_keeps_payload_structure(
    capture: Callable[..., Any],
    clashperk_history: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    run = capture(tmp_path, sanitize=True)

    members = read(tmp_path / "members.json")
    join, leave = members[0], members[1]
    original_join = clashperk_history[MEMBERS_CHANNEL][-1]

    # Message IDs, timestamps, embeds, components, and player tags survive untouched.
    assert join["id"] == original_join["id"]
    assert join["timestamp"] == original_join["timestamp"]
    assert join["embeds"] == original_join["embeds"]
    assert join["components"] == original_join["components"]
    assert "#2Y0LRPV8Q" in json.dumps(members)

    # The webhook identity is replaced, and ClashPerk posts through a webhook, so the
    # author ID and the webhook ID are the same snowflake and must stay equal.
    assert join["webhook_id"] != original_join["webhook_id"]
    assert join["author"]["id"] == join["webhook_id"]
    assert leave["author"]["id"] == join["author"]["id"]
    assert join["author"]["username"] == "ClashPerk"

    assert read(run.manifest_path)["sanitized"] is True


def test_sanitize_is_deterministic_across_runs(capture: Callable[..., Any], tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    capture(first, sanitize=True)
    capture(second, sanitize=True)
    assert (first / "members.json").read_bytes() == (second / "members.json").read_bytes()


def test_unsanitized_capture_preserves_original_ids(
    capture: Callable[..., Any],
    clashperk_history: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    capture(tmp_path)
    join = read(tmp_path / "members.json")[0]
    assert join["webhook_id"] == clashperk_history[MEMBERS_CHANNEL][-1]["webhook_id"]
    assert join["author"]["id"] == clashperk_history[MEMBERS_CHANNEL][-1]["author"]["id"]
