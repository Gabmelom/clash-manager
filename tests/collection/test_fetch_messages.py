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

Page = Callable[..., list[dict[str, Any]]]


@pytest.fixture
def page(history_page: Page) -> Page:
    """Newest-first pages of real ClashPerk member-log messages."""

    def build(*timestamps: datetime) -> list[dict[str, Any]]:
        return history_page("members/join.json", *timestamps)

    return build


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> DiscordClient:
    return DiscordClient(
        TOKEN,
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )


def test_collects_only_messages_inside_the_window_in_chronological_order(page: Page) -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    after_close = datetime(2026, 9, 1, 5, tzinfo=UTC)  # Sept 1 01:00 in Toronto
    late = datetime(2026, 8, 30, 12, tzinfo=UTC)
    early = datetime(2026, 8, 2, 8, tzinfo=UTC)
    before_open = datetime(2026, 7, 31, 23, tzinfo=UTC)
    pages = [page(after_close, late), page(early, before_open)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [message["timestamp"] for message in collected] == [
        early.isoformat(),
        late.isoformat(),
    ]
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


def test_messages_repeated_across_pages_are_deduplicated(page: Page) -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    newest, overlap, oldest = (
        datetime(2026, 8, 12, 10, tzinfo=UTC),
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        datetime(2026, 8, 5, 10, tzinfo=UTC),
    )
    first_page = page(newest, overlap)
    pages = [
        first_page,
        [dict(first_page[1]), *page(oldest)],
        page(datetime(2026, 7, 20, 10, tzinfo=UTC)),
    ]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=pages[calls - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [message["timestamp"] for message in collected] == [
        oldest.isoformat(),
        overlap.isoformat(),
        newest.isoformat(),
    ]


def test_partial_current_month_capture_returns_what_exists_so_far(page: Page) -> None:
    now = datetime(2026, 9, 4, 15, tzinfo=UTC)
    window = resolve_month("current", timezone=TORONTO, now=now)
    inside = [datetime(2026, 9, 4, 11, tzinfo=UTC), datetime(2026, 9, 1, 9, tzinfo=UTC)]
    pages = [page(*inside), page(datetime(2026, 8, 30, 9, tzinfo=UTC))]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    with client_for(handler) as client:
        collected = collect_channel(client, "555", window, page_size=2)

    assert [message["timestamp"] for message in collected] == [
        inside[1].isoformat(),
        inside[0].isoformat(),
    ]
    assert int(requests[0].url.params["before"]) > snowflake_for(now)


def test_payloads_are_returned_unmodified(clashperk_message: Callable[[str], Any]) -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    war_embed = clashperk_message("wars/embed-final.json")

    with client_for(lambda request: httpx.Response(200, json=[war_embed])) as client:
        collected = collect_channel(client, "555", window)

    assert collected == [war_embed]
    assert collected[0]["embeds"][0]["footer"]["text"] == "Ended"


def test_a_forbidden_channel_propagates_a_typed_error() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)

    with client_for(lambda request: httpx.Response(403, json={"message": "Missing Access"})) as (
        client
    ):
        with pytest.raises(DiscordForbiddenError):
            collect_channel(client, "555", window)
