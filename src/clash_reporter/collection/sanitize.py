"""Pseudonymization of Discord identifiers in captured payloads.

Fixtures are committed to the repository, so a capture can be stripped of the
identifiers that tie it to a specific server and its people. Everything a parser
needs is preserved: message IDs, timestamps, content text, embed structure, and
player tags.

Only Discord snowflakes are rewritten, and a single :class:`IdSanitizer` maps
each source ID to the same replacement for the whole run, so relationships
between messages survive the capture.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

__all__ = ["IdSanitizer"]

_GUILD_KEYS = frozenset({"guild_id"})
_USER_KEYS = frozenset({"user_id", "author_id"})
_APPLICATION_KEYS = frozenset({"webhook_id", "application_id"})
_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

# Pseudonyms stay snowflake-shaped so consumers keep seeing plausible IDs.
_KIND_BASES = {
    "guild": 100_000_000_000_000_000,
    "user": 200_000_000_000_000_000,
    "application": 300_000_000_000_000_000,
}


class IdSanitizer:
    """Stable, in-memory pseudonym mapping for one capture run."""

    def __init__(self) -> None:
        self._pseudonyms: dict[str, str] = {}
        self._counters: dict[str, int] = dict.fromkeys(_KIND_BASES, 0)
        self._pattern: re.Pattern[str] | None = None

    def sanitize_all(self, messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        collected = list(messages)
        for message in collected:
            self._collect(message)
        return [self._transform_message(message) for message in collected]

    def sanitize(self, message: dict[str, Any]) -> dict[str, Any]:
        self._collect(message)
        return self._transform_message(message)

    def _transform_message(self, message: dict[str, Any]) -> dict[str, Any]:
        transformed: dict[str, Any] = self._transform(message)
        return transformed

    def pseudonym(self, kind: str, value: str) -> str:
        """Replacement for one source ID, created on first use."""
        existing = self._pseudonyms.get(value)
        if existing is not None:
            return existing
        self._counters[kind] += 1
        replacement = str(_KIND_BASES[kind] + self._counters[kind])
        self._pseudonyms[value] = replacement
        self._pattern = None
        return replacement

    def _collect(self, value: Any, *, in_user: bool = False) -> None:
        if isinstance(value, dict):
            is_user = "username" in value
            for key, item in value.items():
                if key in _GUILD_KEYS and isinstance(item, str):
                    self.pseudonym("guild", item)
                elif key == "id" and is_user and isinstance(item, str):
                    self.pseudonym("user", item)
                elif key in _USER_KEYS and isinstance(item, str):
                    self.pseudonym("user", item)
                elif key in _APPLICATION_KEYS and isinstance(item, str):
                    self.pseudonym("application", item)
                else:
                    self._collect(item, in_user=is_user)
            return
        if isinstance(value, list):
            for item in value:
                self._collect(item, in_user=in_user)
            return
        if isinstance(value, str):
            for mentioned in _MENTION_PATTERN.findall(value):
                self.pseudonym("user", mentioned)

    def _transform(self, value: Any) -> Any:
        if isinstance(value, dict):
            is_user = "username" in value
            result: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(item, str) and (
                    key in _GUILD_KEYS
                    or key in _USER_KEYS
                    or key in _APPLICATION_KEYS
                    or (key == "id" and is_user)
                ):
                    result[key] = self._pseudonyms.get(item, item)
                else:
                    result[key] = self._transform(item)
            return result
        if isinstance(value, list):
            return [self._transform(item) for item in value]
        if isinstance(value, str):
            return self._replace_in_text(value)
        return value

    def _replace_in_text(self, text: str) -> str:
        """Rewrite known IDs embedded in text, such as mentions and Discord URLs.

        Digits are matched whole so a longer unrelated snowflake is never partly
        rewritten, and non-numeric text such as a player tag is untouched.
        """
        if not self._pseudonyms:
            return text
        if self._pattern is None:
            alternatives = sorted(self._pseudonyms, key=len, reverse=True)
            self._pattern = re.compile(
                r"(?<!\d)(" + "|".join(re.escape(value) for value in alternatives) + r")(?!\d)"
            )
        return self._pattern.sub(lambda match: self._pseudonyms[match.group(1)], text)
