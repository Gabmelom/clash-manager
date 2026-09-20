"""Window-bounded message collection.

The collector sits between the Discord transport and everything that
understands ClashPerk. It decides which messages belong to a reporting window
and preserves the original payloads untouched.
"""

from __future__ import annotations

from typing import Any

from clash_reporter.discord_client import MAX_MESSAGES_PER_PAGE, DiscordClient, message_timestamp
from clash_reporter.window import ReportingWindow

__all__ = ["collect_channel"]


def collect_channel(
    client: DiscordClient,
    channel_id: str | int,
    window: ReportingWindow,
    *,
    page_size: int = MAX_MESSAGES_PER_PAGE,
) -> list[dict[str, Any]]:
    """Every message a channel holds inside ``window``, oldest first.

    Pagination is seeded with the window's end snowflake so history is not
    scanned back from the present, and stops at the window start. Messages
    repeated across page boundaries are de-duplicated by message ID.

    A window that has not ended yet is fine: the capture simply contains the
    part of the month that exists so far.
    """
    seen: set[str] = set()
    messages: list[dict[str, Any]] = []
    history = client.iter_channel_history(
        channel_id,
        until=window.start_utc,
        before=window.end_snowflake,
        page_size=page_size,
    )
    for message in history:
        message_id = str(message["id"])
        if message_id in seen:
            continue
        if not window.contains(message_timestamp(message)):
            continue
        seen.add(message_id)
        messages.append(message)
    messages.sort(key=lambda message: (message_timestamp(message), int(message["id"])))
    return messages
