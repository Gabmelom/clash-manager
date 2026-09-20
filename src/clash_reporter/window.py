"""Timezone-aware reporting windows.

Every downstream step has to agree on which messages belong to a reporting month.
The application owns that calculation rather than the scheduler, because GitHub
Actions cron runs in UTC while the clan lives in ``Settings.report_timezone``.

A window is the half-open interval ``[start_of_month, start_of_next_month)``
expressed in the report timezone, with UTC equivalents for comparing Discord
timestamps and Discord snowflakes for seeding pagination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

__all__ = [
    "DISCORD_EPOCH_MS",
    "InvalidMonthError",
    "ReportingWindow",
    "instant_for",
    "month_window",
    "parse_iso_timestamp",
    "resolve_month",
    "snowflake_for",
]

# Discord snowflakes count milliseconds since 2015-01-01T00:00:00Z in their high bits.
# https://docs.discord.com/developers/reference#snowflakes
DISCORD_EPOCH_MS = 1_420_070_400_000
_SNOWFLAKE_TIMESTAMP_SHIFT = 22

_MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class InvalidMonthError(ValueError):
    """Raised when a ``--month`` value cannot be resolved to a calendar month."""


@dataclass(frozen=True)
class ReportingWindow:
    """A half-open calendar month in a specific timezone.

    ``start`` and ``end`` are timezone-aware instants at local midnight on the
    first day of the month and of the following month. ``end`` is exclusive: a
    message posted at exactly ``end`` belongs to the next report.
    """

    start: datetime
    end: datetime
    timezone: str

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("ReportingWindow boundaries must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("ReportingWindow end must be after start")

    @property
    def start_utc(self) -> datetime:
        return self.start.astimezone(UTC)

    @property
    def end_utc(self) -> datetime:
        return self.end.astimezone(UTC)

    @property
    def month_key(self) -> str:
        """Sortable machine key, for example ``"2026-08"``."""
        return f"{self.start.year:04d}-{self.start.month:02d}"

    @property
    def month_label(self) -> str:
        """Human label, for example ``"August 2026"``."""
        return f"{_MONTH_NAMES[self.start.month - 1]} {self.start.year}"

    @property
    def start_snowflake(self) -> int:
        """Snowflake usable as an ``after`` pagination cursor."""
        return snowflake_for(self.start_utc)

    @property
    def end_snowflake(self) -> int:
        """Snowflake usable as a ``before`` pagination cursor."""
        return snowflake_for(self.end_utc)

    def contains(self, timestamp: datetime) -> bool:
        """Whether a timezone-aware instant falls inside the half-open interval."""
        if timestamp.tzinfo is None:
            raise ValueError("Cannot compare a naive timestamp against a reporting window")
        instant = timestamp.astimezone(UTC)
        return self.start_utc <= instant < self.end_utc

    def is_complete(self, now: datetime | None = None) -> bool:
        """Whether the month has already ended.

        A current-month window is intentionally usable before it is complete;
        callers record this flag so a partial capture is recognizable later.
        """
        moment = (now or datetime.now(tz=UTC)).astimezone(UTC)
        return self.end_utc <= moment

    def describe(self) -> dict[str, str | bool]:
        """Serializable summary for run manifests and diagnostics."""
        return {
            "month_key": self.month_key,
            "month_label": self.month_label,
            "timezone": self.timezone,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "complete": self.is_complete(),
        }


def month_window(year: int, month: int, *, timezone: str) -> ReportingWindow:
    """Build the window for one calendar month in ``timezone``."""
    if not 1 <= month <= 12:
        raise InvalidMonthError(f"Month must be between 01 and 12, got {month:02d}")
    zone = ZoneInfo(timezone)
    start = datetime(year, month, 1, tzinfo=zone)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(next_year, next_month, 1, tzinfo=zone)
    return ReportingWindow(start=start, end=end, timezone=timezone)


def resolve_month(
    value: str,
    *,
    timezone: str,
    now: datetime | None = None,
) -> ReportingWindow:
    """Resolve ``YYYY-MM``, ``previous``, or ``current`` into a reporting window.

    ``previous`` and ``current`` are evaluated in ``timezone``, not in UTC, so a
    run at ``2026-09-01T02:00:00Z`` (still August 31 in America/Toronto) resolves
    ``previous`` to July 2026.
    """
    raw = value.strip()
    if not raw:
        raise InvalidMonthError("Month is required. Use 'YYYY-MM', 'previous', or 'current'.")

    keyword = raw.lower()
    if keyword in {"previous", "current"}:
        moment = (now or datetime.now(tz=UTC)).astimezone(ZoneInfo(timezone))
        year, month = moment.year, moment.month
        if keyword == "previous":
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        return month_window(year, month, timezone=timezone)

    match = _MONTH_PATTERN.match(raw)
    if match is None:
        raise InvalidMonthError(
            f"Invalid month {value!r}. Expected 'YYYY-MM' (for example '2026-08'), "
            "'previous', or 'current'."
        )
    month = int(match.group("month"))
    if not 1 <= month <= 12:
        raise InvalidMonthError(f"Invalid month {value!r}. Month part must be between 01 and 12.")
    return month_window(int(match.group("year")), month, timezone=timezone)


def snowflake_for(instant: datetime) -> int:
    """Smallest Discord snowflake created at or after ``instant``."""
    if instant.tzinfo is None:
        raise ValueError("Cannot build a snowflake from a naive datetime")
    milliseconds = int(instant.astimezone(UTC).timestamp() * 1000)
    offset = max(milliseconds - DISCORD_EPOCH_MS, 0)
    return offset << _SNOWFLAKE_TIMESTAMP_SHIFT


def instant_for(snowflake: int | str) -> datetime:
    """UTC creation instant encoded in a Discord snowflake."""
    milliseconds = (int(snowflake) >> _SNOWFLAKE_TIMESTAMP_SHIFT) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def parse_iso_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 Discord timestamp into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp {value!r} is missing a UTC offset")
    return parsed.astimezone(UTC)
