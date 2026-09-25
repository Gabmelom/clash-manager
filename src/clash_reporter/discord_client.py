"""Discord REST transport.

A deliberately small HTTP client for reading channel history. It knows nothing
about channel names or ClashPerk message shapes: it authenticates, paginates,
respects rate limits, and returns raw message dictionaries.

V1 never opens a Gateway/websocket connection.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

from clash_reporter import __version__
from clash_reporter.window import parse_iso_timestamp

__all__ = [
    "DEFAULT_API_VERSION",
    "DEFAULT_BASE_URL",
    "DISCORD_MESSAGE_CONTENT_LIMIT",
    "Attachment",
    "DiscordClient",
    "DiscordError",
    "DiscordForbiddenError",
    "DiscordNotFoundError",
    "DiscordRateLimitError",
    "DiscordRequestError",
    "DiscordServerError",
    "DiscordUnauthorizedError",
    "message_timestamp",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://discord.com/api"
DEFAULT_API_VERSION = 10
#: Discord message ``content`` limit. Reporting splits on this before posting.
DISCORD_MESSAGE_CONTENT_LIMIT = 2000

Attachment = tuple[str, bytes, str]
DEFAULT_USER_AGENT = (
    f"DiscordBot (https://github.com/Gabmelom/clash-manager, {__version__}) clash-reporter"
)
MAX_MESSAGES_PER_PAGE = 100

_REDACTED = "***"


class DiscordError(RuntimeError):
    """Base class for every Discord transport failure."""


class DiscordRequestError(DiscordError):
    """A Discord response that the client refuses to retry or interpret."""

    def __init__(self, message: str, *, status_code: int, context: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.context = context


class DiscordUnauthorizedError(DiscordRequestError):
    """401: the bot token was rejected."""


class DiscordForbiddenError(DiscordRequestError):
    """403: the bot lacks permission on the requested resource."""


class DiscordNotFoundError(DiscordRequestError):
    """404: the requested resource does not exist."""


class DiscordRateLimitError(DiscordRequestError):
    """429 that survived the configured number of retries."""


class DiscordServerError(DiscordRequestError):
    """5xx that survived the configured number of retries."""


def message_timestamp(message: dict[str, Any]) -> datetime:
    """Creation instant of a raw Discord message, in UTC."""
    raw = message.get("timestamp")
    if not isinstance(raw, str):
        raise DiscordError(f"Discord message {message.get('id', '<unknown>')} has no timestamp")
    return parse_iso_timestamp(raw)


class DiscordClient:
    """Authenticated Discord REST client with bounded retries.

    The bot token is held privately and never rendered: it is excluded from the
    repr, from log records, and scrubbed out of any response text surfaced in an
    exception.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_version: int = DEFAULT_API_VERSION,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("A Discord bot token is required")
        self._token = token
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self._client = httpx.Client(
            base_url=f"{self.base_url}/v{api_version}",
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": user_agent,
            },
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"DiscordClient(base_url={self.base_url!r}, api_version={self.api_version})"

    def __enter__(self) -> DiscordClient:
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

    def get_channel_messages(
        self,
        channel_id: str | int,
        *,
        before: str | int | None = None,
        after: str | int | None = None,
        limit: int = MAX_MESSAGES_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """One page of channel history, newest first, exactly as Discord returned it."""
        if not 1 <= limit <= MAX_MESSAGES_PER_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_MESSAGES_PER_PAGE}, got {limit}")
        params: dict[str, str] = {"limit": str(limit)}
        if before is not None:
            params["before"] = str(before)
        if after is not None:
            params["after"] = str(after)
        response = self._request(
            "GET",
            f"/channels/{channel_id}/messages",
            params=params,
            context=f"channel {channel_id}",
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise DiscordError(f"Unexpected message history payload for channel {channel_id}")
        return [dict(message) for message in payload]

    def iter_channel_history(
        self,
        channel_id: str | int,
        *,
        until: datetime,
        before: str | int | None = None,
        page_size: int = MAX_MESSAGES_PER_PAGE,
    ) -> Iterator[dict[str, Any]]:
        """Yield messages newest-first, stopping once history crosses ``until``.

        Pagination is seeded with ``before`` so a caller can start at a window
        boundary instead of scanning back from the present.
        """
        if until.tzinfo is None:
            raise ValueError("until must be timezone-aware")
        cursor: str | int | None = before
        while True:
            page = self.get_channel_messages(channel_id, before=cursor, limit=page_size)
            if not page:
                return
            for message in page:
                if message_timestamp(message) < until:
                    return
                yield message
            if len(page) < page_size:
                return
            cursor = page[-1]["id"]

    def post_message(
        self,
        channel_id: str | int,
        content: str,
        *,
        attachment: Attachment | None = None,
    ) -> dict[str, Any]:
        """Post ``content`` to a channel.

        ``attachment`` is ``(filename, data, content_type)``. When present the
        request is ``multipart/form-data`` with a ``payload_json`` part, which
        is how Discord accepts a message and a file together.
        """
        if content == "":
            raise ValueError("content must be a non-empty string")
        if len(content) > DISCORD_MESSAGE_CONTENT_LIMIT:
            raise ValueError(
                f"content is {len(content)} characters; Discord allows "
                f"{DISCORD_MESSAGE_CONTENT_LIMIT}"
            )
        path = f"/channels/{channel_id}/messages"
        context = f"channel {channel_id}"
        if attachment is None:
            response = self._request(
                "POST",
                path,
                json_body={"content": content},
                context=context,
            )
        else:
            filename, data, content_type = attachment
            if not filename:
                raise ValueError("attachment requires a filename")
            payload = {
                "content": content,
                "attachments": [{"id": 0, "filename": filename}],
            }
            response = self._request(
                "POST",
                path,
                form={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files={"files[0]": (filename, data, content_type)},
                context=context,
            )
        body = response.json()
        if not isinstance(body, dict):
            raise DiscordError(f"Unexpected message payload when posting to {context}")
        return dict(body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        form: Mapping[str, str] | None = None,
        files: Mapping[str, Attachment] | None = None,
        context: str,
    ) -> httpx.Response:
        attempt = 0
        while True:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                data=form,
                files=files,
            )
            status = response.status_code
            if status < 300:
                return response

            if status == 429:
                attempt += 1
                delay = self._retry_after(response)
                if attempt > self._max_retries:
                    raise DiscordRateLimitError(
                        f"Discord kept rate limiting {context} after {self._max_retries} retries.",
                        status_code=status,
                        context=context,
                    )
                logger.warning(
                    "rate limited on %s, retrying in %.2fs",
                    context,
                    delay,
                    extra={"operation": path, "context": context, "retry_after": delay},
                )
                self._sleep(delay)
                continue

            if status >= 500:
                attempt += 1
                if attempt > self._max_retries:
                    raise DiscordServerError(
                        f"Discord returned {status} for {context} after "
                        f"{self._max_retries} retries: {self._detail(response)}",
                        status_code=status,
                        context=context,
                    )
                delay = min(
                    self._backoff_base_seconds * (2 ** (attempt - 1)),
                    self._max_backoff_seconds,
                )
                logger.warning(
                    "discord returned %s for %s, retrying in %.2fs",
                    status,
                    context,
                    delay,
                    extra={"operation": path, "context": context, "status": status},
                )
                self._sleep(delay)
                continue

            raise self._client_error(status, context, response, method=method)

    def _client_error(
        self, status: int, context: str, response: httpx.Response, *, method: str
    ) -> DiscordRequestError:
        detail = self._detail(response)
        if status == 401:
            action = "posting to" if method == "POST" else "reading"
            return DiscordUnauthorizedError(
                f"Discord rejected the bot token while {action} {context} (401). "
                f"Check DISCORD_BOT_TOKEN. {detail}",
                status_code=status,
                context=context,
            )
        if status == 403:
            if method == "POST":
                message = (
                    f"The bot is not allowed to post to {context} (403). Grant View Channel, "
                    f"Send Messages, and Attach Files. {detail}"
                )
            else:
                message = (
                    f"The bot is not allowed to read {context} (403). Grant View Channel and "
                    f"Read Message History. {detail}"
                )
            return DiscordForbiddenError(message, status_code=status, context=context)
        if status == 404:
            return DiscordNotFoundError(
                f"Discord could not find {context} (404). Check the configured ID. {detail}",
                status_code=status,
                context=context,
            )
        return DiscordRequestError(
            f"Discord returned {status} for {context}. {detail}",
            status_code=status,
            context=context,
        )

    def _detail(self, response: httpx.Response) -> str:
        """Short, token-free description of an error response."""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        message = payload.get("message") if isinstance(payload, dict) else None
        text = str(message) if message else response.reason_phrase or ""
        return self._scrub(text).strip()

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, _REDACTED) if self._token else text

    def _retry_after(self, response: httpx.Response) -> float:
        for header in ("Retry-After", "X-RateLimit-Reset-After"):
            raw = response.headers.get(header)
            if raw is None:
                continue
            try:
                return max(float(raw), 0.0)
            except ValueError:
                continue
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and "retry_after" in payload:
            try:
                return max(float(payload["retry_after"]), 0.0)
            except (TypeError, ValueError):
                pass
        return self._backoff_base_seconds
