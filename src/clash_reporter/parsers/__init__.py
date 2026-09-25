"""ClashPerk log-family parsers.

Each parser is a pure function over a raw Discord message: it emits normalized
events or a structured diagnostic. There is no HTTP, clock, or file access
here, and no name→tag resolver (see ``AGENTS.md``, Known deferred decisions).
"""

from clash_reporter.parsers.base import (
    DomainEvent,
    IgnoredMessage,
    MemberEvent,
    ParseOutcome,
    Parser,
    make_event_key,
    normalize_player_tag,
    parse_all,
)
from clash_reporter.parsers.cwl import CwlParser
from clash_reporter.parsers.members import MembersParser
from clash_reporter.parsers.war_layout import cwl_season_key, fallback_war_key, war_reporting_month
from clash_reporter.parsers.wars import WarsParser

__all__ = [
    "CwlParser",
    "DomainEvent",
    "IgnoredMessage",
    "MemberEvent",
    "MembersParser",
    "ParseOutcome",
    "Parser",
    "WarsParser",
    "cwl_season_key",
    "fallback_war_key",
    "make_event_key",
    "normalize_player_tag",
    "parse_all",
    "war_reporting_month",
]
