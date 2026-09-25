"""Clash of Clans roster client. Transport is stubbed; nothing calls the live API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from clash_reporter.coc_client import CocClient, CocError, load_clan_roster
from clash_reporter.config import Settings
from clash_reporter.roster import ClanRoster, RosterMember

WHEN = datetime(2026, 9, 1, 12, tzinfo=UTC)
CLAN = "#2Y0LRPV8Q"
QUARRY = "#QY0QRRRY"
TOKEN = "coc-test-token"


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def _handler(pages: dict[str | None, dict[str, object]]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(request.url)
        after = request.url.params.get("after")
        payload = pages.get(after)
        assert payload is not None, f"unexpected cursor {after!r} for {request.url}"
        assert "%23" in str(request.url)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle)


def test_fetch_members_normalizes_tags_and_follows_the_cursor() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {
            "items": [{"tag": "qy0qrrry", "name": " Quarry ", "role": "member", "trophies": 1}],
            "paging": {"cursors": {"after": "next"}},
        },
        "next": {
            "items": [{"tag": "#2Y0LRPV8Q", "name": "Aurora"}],
            "paging": {"cursors": {}},
        },
    }
    with CocClient(TOKEN, transport=_handler(pages)) as client:
        members = client.fetch_members(CLAN)
    assert members == (
        RosterMember(tag="#2Y0LRPV8Q", name="Aurora"),
        RosterMember(tag=QUARRY, name="Quarry"),
    )


def test_api_error_does_not_leak_the_token() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"reason": f"accessDenied {TOKEN}"})

    with CocClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(CocError, match="accessDenied") as caught:
            client.fetch_members(CLAN)
    assert TOKEN not in str(caught.value)
    assert "***" in str(caught.value)


def test_invalid_clan_tag_fails_before_a_request() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("live or stub request was not expected")

    with CocClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(CocError, match="COC_CLAN_TAG"):
            client.fetch_members("not a tag")


def test_missing_credentials_skip_the_roster() -> None:
    roster = load_clan_roster(_settings(), fetched_at=WHEN)
    assert roster.applied is False
    assert roster.members == ()
    assert "COC_API_TOKEN" in (roster.note or "")
    assert "Discord logs only" in (roster.note or "")


def test_transport_error_is_a_note() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    roster = load_clan_roster(
        _settings(coc_api_token=TOKEN, coc_clan_tag=CLAN),
        transport=httpx.MockTransport(handle),
        fetched_at=WHEN,
    )
    assert roster.applied is False
    assert "connection refused" in (roster.note or "")
    assert TOKEN not in (roster.note or "")


def test_invalid_member_rows_are_skipped() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    "nope",
                    {"tag": "bad", "name": "Skip"},
                    {"tag": QUARRY, "name": "   "},
                    {"tag": QUARRY, "name": "Quarry"},
                ]
            },
        )

    with CocClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        assert client.fetch_members(CLAN) == (RosterMember(tag=QUARRY, name="Quarry"),)


def test_http_failure_is_a_note_and_not_an_exception() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"reason": "notFound"})

    roster = load_clan_roster(
        _settings(coc_api_token=TOKEN, coc_clan_tag=CLAN),
        transport=httpx.MockTransport(handle),
        fetched_at=WHEN,
    )
    assert roster.applied is False
    assert roster.members == ()
    assert roster.clan_tag == CLAN
    assert "notFound" in (roster.note or "")
    assert TOKEN not in (roster.note or "")


def test_snapshot_has_no_token() -> None:
    roster = ClanRoster(
        clan_tag=CLAN,
        members=(RosterMember(tag=QUARRY, name="Quarry"),),
        note=None,
        fetched_at=WHEN,
    )
    payload = json.dumps(roster.snapshot())
    assert TOKEN not in payload
    assert QUARRY in payload
