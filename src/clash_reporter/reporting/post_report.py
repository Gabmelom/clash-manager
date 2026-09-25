"""Post a rendered report and its CSV attachment."""

from __future__ import annotations

from typing import Any

from clash_reporter.discord_client import DiscordClient, DiscordError
from clash_reporter.reporting.split import split_report

__all__ = ["CSV_ATTACHMENT_NAME", "ReportPostError", "post_monthly_report"]

CSV_ATTACHMENT_NAME = "clan-report.csv"
_CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


class ReportPostError(DiscordError):
    """A later chunk failed after earlier chunks were already accepted.

    The cause is chained. Callers must surface this; it is not a successful post.
    """

    def __init__(self, message: str, *, posted: int, total: int) -> None:
        super().__init__(message)
        self.posted = posted
        self.total = total


def post_monthly_report(
    client: DiscordClient,
    channel_id: str | int,
    report: str,
    csv_text: str,
) -> list[dict[str, Any]]:
    """Post ``report`` in order. The CSV is attached to the first message.

    A failure on the first message propagates as the original Discord error,
    because nothing was accepted. A failure after that raises
    :class:`ReportPostError` naming how many messages Discord already accepted.
    """
    chunks = split_report(report)
    posted_messages: list[dict[str, Any]] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks):
        attachment = None
        if index == 0:
            attachment = (
                CSV_ATTACHMENT_NAME,
                csv_text.encode("utf-8"),
                _CSV_CONTENT_TYPE,
            )
        try:
            message = client.post_message(channel_id, chunk, attachment=attachment)
        except DiscordError as exc:
            posted = len(posted_messages)
            if posted == 0:
                raise
            raise ReportPostError(
                f"Discord accepted {posted} of {total} report messages, then failed: {exc}. "
                "Earlier messages were already posted.",
                posted=posted,
                total=total,
            ) from exc
        posted_messages.append(message)
    return posted_messages
