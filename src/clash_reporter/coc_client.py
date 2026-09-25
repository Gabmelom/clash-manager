"""Clash of Clans API client for the current clan member list.

Identity only: tag and name. Wars, Clan Games, capital, and donations stay on
ClashPerk Discord logs. A missing token, a missing clan tag, or an API error
becomes a :class:`ClanRoster` note. Callers keep going with Discord attribution.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from clash_reporter import __version__
from clash_reporter.config import Settings
from clash_reporter.parsers.base import is_valid_player_tag, normalize_player_tag
from clash_reporter.roster import ClanRoster, RosterMember

__all__ = [
    "DEFAULT_BASE_URL",
    "CocClient",
    "CocError",
    "load_clan_roster",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.clashofclans.com/v1"
_REDACTED = "***"
_MAX_PAGES = 5
_SKIP_NOTE = (
    "CoC clan roster was not used: COC_API_TOKEN or COC_CLAN_TAG is unset. "
    "Name→tag attribution used Discord logs only."
)


class CocError(RuntimeError):
    """The clan roster could not be fetched. The token is never part of the message."""


class CocClient:
    """Small authenticated client for ``GET /clans/{tag}/members``."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("A Clash of Clans API token is required")
        self._token = token.strip()
        self._max_retries = max_retries
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": (
                    f"clash-reporter/{__version__} (https://github.com/Gabmelom/clash-manager)"
                ),
            },
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"CocClient(base_url={self.base_url!r})"

    def __enter__(self) -> CocClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_members(self, clan_tag: str) -> tuple[RosterMember, ...]:
        """Current clan members. Tags are normalized; invalid rows are skipped."""
        if not is_valid_player_tag(clan_tag):
            raise CocError(f"COC_CLAN_TAG {clan_tag!r} is not a valid clan tag")
        tag = normalize_player_tag(clan_tag)
        path = f"/clans/{quote(tag, safe='')}/members"
        found: dict[str, RosterMember] = {}
        after: str | None = None
        for _page in range(_MAX_PAGES):
            params = {"limit": "50"}
            if after:
                params["after"] = after
            payload = self._get_json(path, params)
            items = payload.get("items")
            if not isinstance(items, list):
                raise CocError("CoC clan members response did not include an items list")
            for item in items:
                member = _member(item)
                if member is not None and member.tag not in found:
                    found[member.tag] = member
            after = _after_cursor(payload)
            if not after:
                break
        else:
            logger.warning("stopped reading clan members after %s pages", _MAX_PAGES)
        return tuple(sorted(found.values(), key=lambda item: (item.tag, item.name)))

    def _get_json(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise CocError(self._scrub(f"CoC API request failed: {exc}")) from exc
            status = response.status_code
            if status < 300:
                body = response.json()
                if not isinstance(body, dict):
                    raise CocError("CoC API returned a response that is not a JSON object")
                return body
            if status in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                attempt += 1
                continue
            raise CocError(
                self._scrub(f"CoC API returned {status} for clan members: {self._reason(response)}")
            )

    def _scrub(self, message: str) -> str:
        return message.replace(self._token, _REDACTED)

    def _reason(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return "unreadable response"
        if isinstance(body, dict):
            reason = body.get("reason")
            if isinstance(reason, str) and reason:
                return self._scrub(reason)
        return "request rejected"


def load_clan_roster(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    fetched_at: datetime | None = None,
) -> ClanRoster:
    """Fetch the configured clan, or a note when credentials or the API fail.

    This never raises for a missing token, a missing clan tag, or an HTTP error.
    """
    moment = (fetched_at or datetime.now(tz=UTC)).astimezone(UTC)
    token = (settings.coc_api_token or "").strip()
    clan_tag = (settings.coc_clan_tag or "").strip()
    if not token or not clan_tag:
        return ClanRoster(clan_tag=clan_tag or None, members=(), note=_SKIP_NOTE, fetched_at=moment)
    try:
        with CocClient(
            token,
            base_url=settings.coc_api_base_url,
            transport=transport,
        ) as client:
            members = client.fetch_members(clan_tag)
    except (CocError, ValueError) as exc:
        stored_tag = normalize_player_tag(clan_tag) if is_valid_player_tag(clan_tag) else clan_tag
        return ClanRoster(
            clan_tag=stored_tag,
            members=(),
            note=(
                f"CoC clan roster was not used: {exc}. Name→tag attribution used Discord logs only."
            ),
            fetched_at=moment,
        )
    return ClanRoster(
        clan_tag=normalize_player_tag(clan_tag),
        members=members,
        note=None,
        fetched_at=moment,
    )


def _member(item: object) -> RosterMember | None:
    if not isinstance(item, dict):
        return None
    raw_tag = item.get("tag")
    name = item.get("name")
    if not isinstance(raw_tag, str) or not isinstance(name, str):
        return None
    if not name.strip() or not is_valid_player_tag(raw_tag):
        return None
    return RosterMember(tag=normalize_player_tag(raw_tag), name=name.strip())


def _after_cursor(payload: Mapping[str, Any]) -> str | None:
    paging = payload.get("paging")
    if not isinstance(paging, dict):
        return None
    cursors = paging.get("cursors")
    if not isinstance(cursors, dict):
        return None
    after = cursors.get("after")
    if isinstance(after, str) and after:
        return after
    return None
