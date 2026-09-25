"""Split a rendered report into Discord-sized messages.

Splits happen on section boundaries. A section that is still too long is split
between entries, and each piece repeats the section header so a header is never
posted without the entry it introduces. An entry that cannot fit with its
header is refused rather than cut in half.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from clash_reporter.discord_client import DISCORD_MESSAGE_CONTENT_LIMIT
from clash_reporter.reporting.discord_report import (
    SECTION_HEADERS,
    SECTION_REVIEW,
    SECTION_TOP,
)

__all__ = ["ReportSplitError", "split_report"]

_NUMBERED_ENTRY = re.compile(r"^\d+\. ")


class ReportSplitError(ValueError):
    """The report cannot be posted without cutting an entry or dropping a header."""


def split_report(report: str, *, limit: int = DISCORD_MESSAGE_CONTENT_LIMIT) -> list[str]:
    """Return ordered message bodies, each at most ``limit`` characters."""
    if limit < 1:
        raise ValueError("limit must be positive")
    pieces = _pieces(report, limit)
    if not pieces:
        raise ReportSplitError("Report is empty")
    return _pack(pieces, limit)


def _pieces(report: str, limit: int) -> list[str]:
    preamble, sections = _parse_sections(report)
    pieces: list[str] = []
    if preamble:
        if len(preamble) > limit:
            raise ReportSplitError(
                f"Report header is {len(preamble)} characters, over the {limit} limit"
            )
        pieces.append(preamble)
    for header, body in sections:
        pieces.extend(_section_pieces(header, body, limit))
    return pieces


def _parse_sections(report: str) -> tuple[str, list[tuple[str, list[str]]]]:
    preamble_lines: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_header: str | None = None
    current_body: list[str] = []
    for line in report.split("\n"):
        if line in SECTION_HEADERS:
            if current_header is None:
                preamble_lines = _trim_edges(preamble_lines)
            else:
                sections.append((current_header, _trim_edges(current_body)))
            current_header = line
            current_body = []
            continue
        if current_header is None:
            preamble_lines.append(line)
        else:
            current_body.append(line)
    if current_header is not None:
        sections.append((current_header, _trim_edges(current_body)))
    return "\n".join(_trim_edges(preamble_lines)), sections


def _trim_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return lines[start:end]


def _section_pieces(header: str, body: list[str], limit: int) -> list[str]:
    entries = _entries(header, body)
    if not entries:
        if len(header) > limit:
            raise ReportSplitError(f"Section header {header!r} exceeds the {limit} limit")
        return [header]
    whole = _render(header, entries)
    if len(whole) <= limit:
        return [whole]

    pieces: list[str] = []
    batch: list[str] = []
    for entry in entries:
        candidate = _render(header, [*batch, entry])
        if len(candidate) <= limit:
            batch.append(entry)
            continue
        if not batch:
            raise ReportSplitError(
                f"Section {header!r} has an entry of {len(candidate)} characters, "
                f"over the {limit} limit. Refusing to split mid-entry."
            )
        pieces.append(_render(header, batch))
        alone = _render(header, [entry])
        if len(alone) > limit:
            raise ReportSplitError(
                f"Section {header!r} has an entry of {len(alone)} characters, "
                f"over the {limit} limit. Refusing to split mid-entry."
            )
        batch = [entry]
    if batch:
        pieces.append(_render(header, batch))
    return pieces


def _render(header: str, entries: list[str]) -> str:
    return header + "\n" + "\n".join(entries)


def _entries(header: str, body: list[str]) -> list[str]:
    lines = [line for line in body if line != ""]
    if not lines:
        return []
    if header == SECTION_TOP:
        return _group(lines, lambda line: _NUMBERED_ENTRY.match(line) is not None)
    if header == SECTION_REVIEW:
        return _group(lines, lambda line: not line.startswith("- "))
    return _group(lines, lambda _line: True)


def _group(lines: list[str], starts_entry: Callable[[str], bool]) -> list[str]:
    groups: list[list[str]] = []
    for line in lines:
        if not groups or starts_entry(line):
            groups.append([line])
        else:
            groups[-1].append(line)
    return ["\n".join(group) for group in groups]


def _pack(pieces: list[str], limit: int) -> list[str]:
    messages: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            messages.append("\n\n".join(buffer))
            buffer.clear()

    for piece in pieces:
        if len(piece) > limit:
            raise ReportSplitError(
                f"A report section is {len(piece)} characters, over the {limit} limit"
            )
        trial = piece if not buffer else "\n\n".join([*buffer, piece])
        if len(trial) <= limit:
            buffer.append(piece)
            continue
        flush()
        buffer.append(piece)
    flush()
    for message in messages:
        if message.split("\n")[-1] in SECTION_HEADERS:
            raise ReportSplitError("Refusing to post a section header with no content")
    return messages
