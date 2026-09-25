"""Shared parser protocol, diagnostics, and identity helpers.

Parsers are pure: they take a raw Discord message mapping and return events or
an explicit diagnostic. They do not perform HTTP, read the clock, or touch the
filesystem. Unrecognized input is never a silent drop.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from clash_reporter.events import (
    MemberJoined,
    MemberLeft,
    PlayerNameChanged,
    PlayerRoleChanged,
)

__all__ = [
    "DomainEvent",
    "IGNORED_MALFORMED",
    "IGNORED_MISSING_PLAYER_TAG",
    "IGNORED_UNKNOWN_LAYOUT",
    "IGNORED_UNSUPPORTED_LOG",
    "IgnoredMessage",
    "ParseOutcome",
    "Parser",
    "DomainEvent",
    "deduplicate_events",
    "extract_player_tag",
    "is_valid_player_tag",
    "make_event_key",
    "normalize_player_tag",
    "parse_all",
    "parse_player_title",
]

# Clash of Clans player-tag alphabet (letter O is not in it; it normalizes to 0).
_TAG_BODY = frozenset("0289PYLQGRJCUV")
_TAG_MIN_LENGTH = 3

IGNORED_MALFORMED = "malformed"
IGNORED_UNKNOWN_LAYOUT = "unknown_layout"
IGNORED_MISSING_PLAYER_TAG = "missing_player_tag"
IGNORED_UNSUPPORTED_LOG = "unsupported_log"

# Closed to membership events in this PR. Widen the union (and ``__all__``)
# when war, CWL, games, or capital parsers start emitting their own types.
type DomainEvent = MemberJoined | MemberLeft | PlayerNameChanged | PlayerRoleChanged


@dataclass(frozen=True)
class IgnoredMessage:
    """A structured reason a message produced no event."""

    reason_code: str
    detail: str
    message_id: str | None = None
    channel_id: str | None = None
    player_name: str | None = None
    player_tag: str | None = None


@dataclass
class ParseOutcome:
    """Events and diagnostics from one or more parse calls."""

    events: list[DomainEvent] = field(default_factory=list)
    diagnostics: list[IgnoredMessage] = field(default_factory=list)

    @property
    def classified(self) -> bool:
        """Whether the input was either parsed or explicitly ignored."""
        return bool(self.events or self.diagnostics)

    def extend(self, other: ParseOutcome) -> ParseOutcome:
        """Append another outcome, de-duplicating events by ``event_key``."""
        return ParseOutcome(
            events=deduplicate_events([*self.events, *other.events]),
            diagnostics=[*self.diagnostics, *other.diagnostics],
        )


class Parser(Protocol):
    """A ClashPerk log-family parser.

    ``parse`` never raises on a well-typed message dict: malformed or unknown
    layouts become :class:`IgnoredMessage` diagnostics.
    """

    name: str
    version: str

    def parse(self, message: Mapping[str, Any]) -> ParseOutcome: ...


def make_event_key(
    message_id: str,
    event_type: str,
    player_tag: str,
    index: int = 0,
) -> str:
    """Deterministic de-duplication key for one normalized row.

    Shape: ``<message_id>:<event_type>:<player_tag>:<index>``.
    """
    return f"{message_id}:{event_type}:{player_tag}:{index}"


def normalize_player_tag(tag: str) -> str:
    """Canonical player tag matching clashofclans.js ``Util.formatTag``.

    Uppercase, replace letter ``O`` with ``0``, strip a leading ``#`` and
    spaces, then prefix ``#``.
    """
    formatted = tag.upper().replace("O", "0")
    if formatted.startswith("#"):
        formatted = formatted[1:]
    formatted = formatted.replace(" ", "")
    return f"#{formatted}"


def is_valid_player_tag(tag: str) -> bool:
    """Whether ``tag`` is a well-formed Clash of Clans tag after normalization."""
    normalized = normalize_player_tag(tag)
    body = normalized[1:]
    return len(body) >= _TAG_MIN_LENGTH and all(char in _TAG_BODY for char in body)


def parse_player_title(title: str) -> tuple[str | None, str | None]:
    """Split a ClashPerk embed title ``\\u200e{name} ({tag})``.

    Returns ``(display_name, normalized_tag)``. A name with no recoverable tag
    yields ``(name, None)``; an empty title yields ``(None, None)``. The tag is
    taken from the rightmost parenthesized group so a name that itself contains
    parentheses still parses.
    """
    text = title.lstrip("\u200e").strip()
    if not text:
        return None, None
    if not text.endswith(")"):
        return text, None
    open_paren = text.rfind(" (")
    if open_paren < 0:
        return text, None
    name = text[:open_paren].strip() or None
    raw_tag = text[open_paren + 2 : -1].strip()
    if not raw_tag:
        return name, None
    if is_valid_player_tag(raw_tag):
        return name, normalize_player_tag(raw_tag)
    return name, None


def extract_player_tag(title: str) -> str | None:
    """Normalized player tag from a ClashPerk embed title, or ``None``."""
    _, tag = parse_player_title(title)
    return tag


def deduplicate_events(events: Iterable[DomainEvent]) -> list[DomainEvent]:
    """Keep the first event for each ``event_key``, in input order."""
    unique: list[DomainEvent] = []
    seen: set[str] = set()
    for event in events:
        if event.event_key in seen:
            continue
        seen.add(event.event_key)
        unique.append(event)
    return unique


def parse_all(parser: Parser, messages: Iterable[Mapping[str, Any]]) -> ParseOutcome:
    """Parse many messages, skipping duplicate Discord message IDs.

    Event keys still de-duplicate inside a single message that yields several
    rows. Message-ID de-duplication is the first key, matching
    ``docs/DATA_CONTRACT.md``.
    """
    events: list[DomainEvent] = []
    diagnostics: list[IgnoredMessage] = []
    seen_message_ids: set[str] = set()
    for message in messages:
        message_id = message.get("id")
        if isinstance(message_id, str) and message_id in seen_message_ids:
            continue
        if isinstance(message_id, str):
            seen_message_ids.add(message_id)
        outcome = parser.parse(message)
        events.extend(outcome.events)
        diagnostics.extend(outcome.diagnostics)
    return ParseOutcome(events=deduplicate_events(events), diagnostics=diagnostics)
