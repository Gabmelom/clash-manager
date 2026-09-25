"""Decide whether a capture is complete enough to post.

An inaccessible required channel is missing critical data. A required channel
that was read and happened to be empty is not: a month with no Clan Games
event still has a successful ``#clan-games`` capture.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from clash_reporter.config import REQUIRED_DATA_CHANNELS

__all__ = ["posting_blockers"]


def posting_blockers(
    captured: Collection[str],
    failures: Mapping[str, str],
) -> list[str]:
    """Reasons to refuse a post, in channel order.

    ``captured`` is the set of channel names that were read successfully,
    including channels whose history was empty. ``failures`` maps a channel
    name to why it could not be read.
    """
    seen = set(captured)
    blockers: list[str] = []
    for name in REQUIRED_DATA_CHANNELS:
        if name in failures:
            blockers.append(f"#{name} inaccessible: {failures[name]}")
        elif name not in seen:
            blockers.append(f"#{name} was not captured")
    return blockers
