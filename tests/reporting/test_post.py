from __future__ import annotations

import httpx
import pytest

from clash_reporter.discord_client import DiscordClient, DiscordServerError
from clash_reporter.reporting.post_report import ReportPostError, post_monthly_report

TOKEN = "not-a-real-token-abc123"  # noqa: S105 - dummy value for mocked transports


def _client(handler: httpx.MockTransport) -> DiscordClient:
    return DiscordClient(
        TOKEN,
        transport=handler,
        sleep=lambda _seconds: None,
        max_retries=0,
        backoff_base_seconds=0.0,
    )


def test_post_attaches_csv_to_the_first_message_and_keeps_order() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": str(len(seen))})

    report = "🏆 Top Performers\n" + "\n".join(
        f"{index}. Player {index} (#T{index}) - 10.0" for index in range(1, 6)
    )
    with _client(httpx.MockTransport(handler)) as client:
        messages = post_monthly_report(client, "42", report, "Player Tag\n#T1\n")

    assert [message["id"] for message in messages] == ["1"]
    body = seen[0].read()
    assert b"clan-report.csv" in body
    assert b"Player Tag" in body
    assert "🏆 Top Performers" in body.decode()


def test_partial_failure_mid_split_is_raised() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"id": "1"})
        return httpx.Response(500, json={"message": "upstream down"})

    report = "\n".join(
        [
            "🏰 Clan Monthly Report - August 2026",
            "",
            "m" * 1900,
            "",
            "🏆 Top Performers",
            "1. Player A (#AAA) - 91.4",
            "   War: 100% attacks used | 2.71 avg stars",
            "",
            "⚠️ Needs Review",
            "Player X (#CCC)",
            "- 3 regular war attacks missed",
        ]
    )
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(ReportPostError, match="accepted 1 of 2") as excinfo:
            post_monthly_report(client, "42", report, "col\n")

    assert excinfo.value.posted == 1
    assert excinfo.value.total == 2
    assert isinstance(excinfo.value.__cause__, DiscordServerError)
    assert calls == 2
