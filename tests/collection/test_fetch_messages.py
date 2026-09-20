from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from clash_reporter.collection import collect_channel
from clash_reporter.discord_client import DiscordClient, DiscordForbiddenError
from clash_reporter.window import resolve_month, snowflake_for

TOKEN = "not-a-real-token-abc123"  # noqa: S105 - dummy value for mocked transports
TORONTO = "America/Toronto"


def message(message_id: str, timestamp: str) -> dict[str, Any]:
    return {"id": message_id, "channel_id": "555", "timestamp": timestamp, "content": "x"}


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> DiscordClient:
    return DiscordClient(
        TOKEN,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )


def test_collects_only_messages_inside_the_window_in_chronological_order() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    pages = [
        [
            # Posted after the window closed (Sept 1 local), must be excluded.
            message("40", "2026-09-01T05:00:00+00:00"),
            message("30", "2026-08-30T12:00:00+00:00"),
        ],
        [
            message("20", "2026-08-02T08:00:00+00:00"),
            # Before the window opened (Aug 1 04:00 UTC), stops pagination.
            message("10", "2026-07-31T23:00:00+00:00"),
        ],
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [item["id"] for item in collected] == ["20", "30"]
    assert len(requests) == 2


def test_pagination_is_seeded_with_the_window_end_snowflake() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with client_for(handler) as client:
        collect_channel(client, "555", window)

    assert requests[0].url.params["before"] == str(window.end_snowflake)


def test_messages_repeated_across_pages_are_deduplicated() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    overlap = message("20", "2026-08-10T10:00:00+00:00")
    pages = [
        [message("30", "2026-08-12T10:00:00+00:00"), overlap],
        [dict(overlap), message("10", "2026-08-05T10:00:00+00:00")],
        [message("05", "2026-07-20T10:00:00+00:00")],
    ]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=pages[calls - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [item["id"] for item in collected] == ["10", "20", "30"]


def test_partial_current_month_capture_returns_what_exists_so_far() -> None:
    now = datetime(2026, 9, 4, 15, tzinfo=UTC)
    window = resolve_month("current", timezone=TORONTO, now=now)
    pages = [
        [
            message("20", "2026-09-04T11:00:00+00:00"),
            message("10", "2026-09-01T09:00:00+00:00"),
        ],
        [message("05", "2026-08-30T09:00:00+00:00")],
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [item["id"] for item in collected] == ["10", "20"]
    assert int(requests[0].url.params["before"]) > snowflake_for(now)


def test_payloads_are_returned_unmodified() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    raw = {
        "id": "20",
        "channel_id": "555",
        "timestamp": "2026-08-10T10:00:00+00:00",
        "embeds": [{"title": "War ended", "fields": [{"name": "#R22YRC0UY", "value": "3 stars"}]}],
    }

    with client_for(lambda request: httpx.Response(200, json=[raw])) as client:
        collected = collect_channel(client, "555", window)

    assert collected == [raw]


def test_a_forbidden_channel_propagates_a_typed_error() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)

    with client_for(lambda request: httpx.Response(403, json={"message": "Missing Access"})) as (
        client
    ):
        with pytest.raises(DiscordForbiddenError):
            collect_channel(client, "555", window)
