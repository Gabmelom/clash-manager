"""ClashPerk log-family parsers.

Each parser is a pure function over a raw Discord message: it emits normalized
events or a structured diagnostic. There is no HTTP, clock, or file access
here, and no name→tag resolver (see ``AGENTS.md``, Known deferred decisions).
"""

from clash_reporter.parsers.base import (
    DomainEvent,
    IgnoredMessage,
    ParseOutcome,
    Parser,
    make_event_key,
    normalize_player_tag,
    parse_all,
)
from clash_reporter.parsers.members import MembersParser

__all__ = [
    "DomainEvent",
    "IgnoredMessage",
    "MembersParser",
    "ParseOutcome",
    "Parser",
    "make_event_key",
    "normalize_player_tag",
    "parse_all",
]
