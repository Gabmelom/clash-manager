from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from clash_reporter.discord_client import (
    DiscordClient,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    DiscordRateLimitError,
    DiscordServerError,
    DiscordUnauthorizedError,
    message_timestamp,
)

TOKEN = "not-a-real-token-abc123"  # noqa: S105 - dummy value for mocked transports

Page = Callable[..., list[dict[str, Any]]]


@pytest.fixture
def page(history_page: Page) -> Page:
    """Newest-first pages of real ClashPerk war-attack messages at given timestamps."""

    def build(*timestamps: datetime) -> list[dict[str, Any]]:
        return history_page("wars/attack.json", *timestamps)

    return build


def build_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleeps: list[float] | None = None,
    **kwargs: Any,
) -> DiscordClient:
    def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return DiscordClient(
        TOKEN,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        backoff_base_seconds=0.0,
        **kwargs,
    )


def test_requests_are_authenticated_and_versioned() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    with build_client(handler) as client:
        assert client.get_channel_messages("555", limit=50) == []

    request = seen[0]
    assert request.url.path == "/api/v10/channels/555/messages"
    assert request.url.params["limit"] == "50"
    assert request.headers["Authorization"] == f"Bot {TOKEN}"
    assert "clash-reporter" in request.headers["User-Agent"]


def test_before_and_after_cursors_are_forwarded() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    with build_client(handler) as client:
        client.get_channel_messages("555", before=99, after="7", limit=2)

    assert seen[0].url.params["before"] == "99"
    assert seen[0].url.params["after"] == "7"


def test_messages_are_returned_unmodified(clashperk_message: Callable[[str], Any]) -> None:
    attack = clashperk_message("wars/attack.json")

    with build_client(lambda request: httpx.Response(200, json=[attack])) as client:
        assert client.get_channel_messages("555") == [attack]


def test_history_walks_three_pages_and_stops_at_the_boundary(page: Page) -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    newest = datetime(2026, 8, 20, tzinfo=UTC)
    pages = [
        page(newest, newest - timedelta(days=1)),
        page(newest - timedelta(days=2), newest - timedelta(days=3)),
        # The second message crosses the window start; older history must not be drained.
        page(datetime(2026, 8, 2, tzinfo=UTC), datetime(2026, 7, 31, tzinfo=UTC)),
        page(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC)),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    with build_client(handler) as client:
        collected = list(client.iter_channel_history("555", until=start, page_size=2))

    expected = [*pages[0], *pages[1], pages[2][0]]
    assert [message["id"] for message in collected] == [m["id"] for m in expected]
    assert len(requests) == 3, "pagination must stop instead of draining the channel"
    assert requests[1].url.params["before"] == pages[0][-1]["id"]
    assert requests[2].url.params["before"] == pages[1][-1]["id"]


def test_history_can_be_seeded_with_a_before_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with build_client(handler) as client:
        list(client.iter_channel_history("555", until=datetime(2026, 8, 1, tzinfo=UTC), before=42))

    assert requests[0].url.params["before"] == "42"


def test_history_stops_on_a_short_page(page: Page) -> None:
    only = page(datetime(2026, 8, 20, tzinfo=UTC))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=only if calls == 1 else [])

    with build_client(handler) as client:
        collected = list(client.iter_channel_history("555", until=datetime(2026, 8, 1, tzinfo=UTC)))

    assert len(collected) == 1
    assert calls == 1


def test_rate_limit_is_retried_once_using_the_retry_after_header(page: Page) -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.75", "X-RateLimit-Reset-After": "0.9"},
                json={"message": "You are being rate limited.", "retry_after": 0.75},
            )
        return httpx.Response(200, json=page(datetime(2026, 8, 5, tzinfo=UTC)))

    with build_client(handler, sleeps=sleeps) as client:
        messages = client.get_channel_messages("555")

    assert calls == 2
    assert sleeps == [0.75]
    assert len(messages) == 1


def test_rate_limit_falls_back_to_reset_after_header() -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset-After": "1.5"}, json={})
        return httpx.Response(200, json=[])

    with build_client(handler, sleeps=sleeps) as client:
        client.get_channel_messages("555")

    assert sleeps == [1.5]


def test_persistent_rate_limiting_raises_after_bounded_retries() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.1"}, json={})

    with build_client(handler, sleeps=sleeps, max_retries=2) as client:
        with pytest.raises(DiscordRateLimitError):
            client.get_channel_messages("555")

    assert sleeps == [0.1, 0.1]


def test_server_errors_are_retried_with_backoff_then_raise() -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"message": "service unavailable"})
        return httpx.Response(200, json=[])

    with build_client(handler, sleeps=sleeps) as client:
        assert client.get_channel_messages("555") == []
    assert len(sleeps) == 1

    with build_client(lambda request: httpx.Response(500, json={}), max_retries=1) as client:
        with pytest.raises(DiscordServerError):
            client.get_channel_messages("555")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, DiscordUnauthorizedError),
        (403, DiscordForbiddenError),
        (404, DiscordNotFoundError),
    ],
)
def test_permission_failures_raise_distinct_typed_errors(
    status: int, expected: type[DiscordError]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "Missing Access"})

    with build_client(handler) as client:
        with pytest.raises(expected) as excinfo:
            client.get_channel_messages("555")

    error = excinfo.value
    assert "channel 555" in str(error)
    assert isinstance(error, DiscordError)


def test_token_never_appears_in_errors_logs_or_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A hostile or buggy upstream echoing the credential must not leak either.
        return httpx.Response(403, json={"message": f"Missing Access for Bot {TOKEN}"})

    with caplog.at_level("DEBUG"):
        with build_client(handler) as client:
            assert TOKEN not in repr(client)
            with pytest.raises(DiscordForbiddenError) as excinfo:
                client.get_channel_messages("555")

    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)
    assert TOKEN not in caplog.text


def test_rate_limit_logging_does_not_leak_the_token(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json=[])

    with caplog.at_level("DEBUG"):
        with build_client(handler) as client:
            client.get_channel_messages("555")

    assert TOKEN not in caplog.text


def test_client_rejects_an_empty_token() -> None:
    with pytest.raises(ValueError, match="token is required"):
        DiscordClient("")


def test_limit_is_validated() -> None:
    with build_client(lambda request: httpx.Response(200, json=[])) as client:
        with pytest.raises(ValueError, match="limit must be between"):
            client.get_channel_messages("555", limit=101)


def test_unexpected_payload_shape_is_reported() -> None:
    with build_client(lambda request: httpx.Response(200, json={"message": "nope"})) as client:
        with pytest.raises(DiscordError, match="Unexpected message history payload"):
            client.get_channel_messages("555")


def test_message_timestamp_reads_the_discord_timestamp(
    clashperk_message: Callable[[str], Any],
) -> None:
    joined = clashperk_message("members/join.json")
    assert message_timestamp(joined) == datetime(2026, 8, 3, 18, 12, 44, 281000, tzinfo=UTC)
    with pytest.raises(DiscordError, match="no timestamp"):
        message_timestamp({"id": "1"})


def test_post_message_sends_json_content() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "99", "content": "hello"})

    with build_client(handler) as client:
        posted = client.post_message("555", "hello")

    assert posted["id"] == "99"
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v10/channels/555/messages"
    assert request.headers["Authorization"] == f"Bot {TOKEN}"
    assert request.read() == b'{"content":"hello"}'


def test_post_message_uploads_a_multipart_attachment() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "100"})

    payload = b"Player Tag,Player Name\n#AAA,Aurora\n"
    with build_client(handler) as client:
        client.post_message(
            "555",
            "report",
            attachment=("clan-report.csv", payload, "text/csv; charset=utf-8"),
        )

    request = seen[0]
    body = request.read()
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data")
    assert b"payload_json" in body
    assert b"clan-report.csv" in body
    assert b'"content": "report"' in body or b'"content":"report"' in body
    assert payload in body
    assert TOKEN not in body.decode()


def test_post_message_counts_emoji_in_utf16_code_units() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("over-long content must not be sent")

    # 1001 trophies: Python len is 1001, Discord counts 2002 UTF-16 code units.
    with build_client(handler) as client:
        with pytest.raises(ValueError, match="UTF-16"):
            client.post_message("555", "🏆" * 1001)


def test_post_message_rejects_content_over_the_discord_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("over-long content must not be sent")

    with build_client(handler) as client:
        with pytest.raises(ValueError, match="2000"):
            client.post_message("555", "x" * 2001)


def test_post_message_retries_rate_limits() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"id": "1"})

    with build_client(handler) as client:
        assert client.post_message("555", "ok")["id"] == "1"
    assert calls == 2


def test_post_forbidden_names_send_permission() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Missing Access"})

    with build_client(handler) as client:
        with pytest.raises(DiscordForbiddenError, match="Send Messages"):
            client.post_message("555", "hello")


def test_history_requires_an_aware_boundary() -> None:
    with build_client(lambda request: httpx.Response(200, json=[])) as client:
        with pytest.raises(ValueError, match="timezone-aware"):
            list(client.iter_channel_history("555", until=datetime(2026, 8, 1)))
