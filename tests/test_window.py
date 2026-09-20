from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from clash_reporter.window import (
    InvalidMonthError,
    ReportingWindow,
    instant_for,
    month_window,
    parse_iso_timestamp,
    resolve_month,
    snowflake_for,
)

TORONTO = "America/Toronto"


def test_explicit_month_is_half_open_in_report_timezone() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    assert window.month_key == "2026-08"
    assert window.month_label == "August 2026"
    assert window.start.isoformat() == "2026-08-01T00:00:00-04:00"
    assert window.end.isoformat() == "2026-09-01T00:00:00-04:00"
    assert window.start_utc == datetime(2026, 8, 1, 4, tzinfo=UTC)
    assert window.end_utc == datetime(2026, 9, 1, 4, tzinfo=UTC)


def test_previous_uses_report_timezone_not_utc() -> None:
    # 2026-09-01T02:00Z is still 2026-08-31 22:00 in Toronto, so the previous
    # month is July, not August.
    now = datetime(2026, 9, 1, 2, tzinfo=UTC)
    window = resolve_month("previous", timezone=TORONTO, now=now)
    assert window.month_key == "2026-07"
    assert resolve_month("previous", timezone="UTC", now=now).month_key == "2026-08"


def test_current_resolves_the_in_progress_month() -> None:
    now = datetime(2026, 9, 14, 17, 30, tzinfo=UTC)
    window = resolve_month("current", timezone=TORONTO, now=now)
    assert window.month_key == "2026-09"
    assert window.month_label == "September 2026"
    assert not window.is_complete(now)
    assert window.contains(now)


def test_current_month_capture_window_stays_usable_before_the_month_ends() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    window = resolve_month("current", timezone=TORONTO, now=now)
    # Three days into the month the window is still the full month: it covers
    # what exists so far and its end cursor is simply ahead of the newest message.
    assert window.contains(datetime(2026, 9, 1, 10, tzinfo=UTC))
    assert window.contains(now)
    assert window.end_snowflake > snowflake_for(now)
    assert not window.is_complete(now)


def test_previous_wraps_across_the_year_boundary() -> None:
    window = resolve_month("previous", timezone=TORONTO, now=datetime(2026, 1, 12, tzinfo=UTC))
    assert window.month_key == "2025-12"


def test_march_and_november_windows_have_correct_dst_offsets() -> None:
    march = resolve_month("2026-03", timezone=TORONTO)
    assert march.start.utcoffset() == timedelta(hours=-5)  # EST
    assert march.end.utcoffset() == timedelta(hours=-4)  # EDT
    assert march.start_utc == datetime(2026, 3, 1, 5, tzinfo=UTC)
    assert march.end_utc == datetime(2026, 4, 1, 4, tzinfo=UTC)

    november = resolve_month("2026-11", timezone=TORONTO)
    assert november.start.utcoffset() == timedelta(hours=-4)  # EDT
    assert november.end.utcoffset() == timedelta(hours=-5)  # EST
    assert november.start_utc == datetime(2026, 11, 1, 4, tzinfo=UTC)
    assert november.end_utc == datetime(2026, 12, 1, 5, tzinfo=UTC)


def test_interval_is_half_open() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    assert window.contains(window.start_utc)
    assert window.contains(window.end_utc - timedelta(microseconds=1))
    assert not window.contains(window.end_utc)
    assert not window.contains(window.start_utc - timedelta(microseconds=1))


def test_contains_accepts_any_aware_timezone_and_rejects_naive() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    assert window.contains(datetime(2026, 8, 15, tzinfo=ZoneInfo("Europe/Berlin")))
    with pytest.raises(ValueError, match="naive timestamp"):
        window.contains(datetime(2026, 8, 15))


@pytest.mark.parametrize("value", ["2026-13", "2026-00", "august", "", "2026", "26-08", "2026/08"])
def test_invalid_month_values_raise(value: str) -> None:
    with pytest.raises(InvalidMonthError):
        resolve_month(value, timezone=TORONTO)


def test_invalid_month_error_names_the_accepted_forms() -> None:
    with pytest.raises(InvalidMonthError) as excinfo:
        resolve_month("august", timezone=TORONTO)
    message = str(excinfo.value)
    assert "YYYY-MM" in message
    assert "previous" in message
    assert "current" in message


def test_month_window_rejects_out_of_range_month() -> None:
    with pytest.raises(InvalidMonthError):
        month_window(2026, 13, timezone=TORONTO)


def test_snowflake_round_trips_against_a_known_discord_pair() -> None:
    # Reference pair from the Discord snowflake documentation.
    known_id = 175928847299117063
    assert instant_for(known_id) == datetime(2016, 4, 30, 11, 18, 25, 796000, tzinfo=UTC)
    assert instant_for(str(known_id)) == instant_for(known_id)
    assert snowflake_for(instant_for(known_id)) <= known_id
    assert instant_for(snowflake_for(instant_for(known_id))) == instant_for(known_id)


def test_window_snowflakes_bracket_the_window() -> None:
    window = resolve_month("2026-08", timezone=TORONTO)
    assert instant_for(window.start_snowflake) == window.start_utc
    assert instant_for(window.end_snowflake) == window.end_utc


def test_snowflake_requires_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="naive"):
        snowflake_for(datetime(2026, 8, 1))


def test_snowflake_floors_at_the_discord_epoch() -> None:
    assert snowflake_for(datetime(2000, 1, 1, tzinfo=UTC)) == 0


def test_describe_is_serializable_and_flags_completeness() -> None:
    described = resolve_month("2026-08", timezone=TORONTO).describe()
    assert described["month_key"] == "2026-08"
    assert described["timezone"] == TORONTO
    assert described["start_utc"] == "2026-08-01T04:00:00+00:00"
    assert described["complete"] is True


def test_parse_iso_timestamp_normalizes_to_utc() -> None:
    parsed = parse_iso_timestamp("2026-08-15T12:30:00.250000-04:00")
    assert parsed == datetime(2026, 8, 15, 16, 30, 0, 250000, tzinfo=UTC)
    with pytest.raises(ValueError, match="UTC offset"):
        parse_iso_timestamp("2026-08-15T12:30:00")


def test_window_rejects_inverted_or_naive_boundaries() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ReportingWindow(
            start=datetime(2026, 8, 1),
            end=datetime(2026, 9, 1, tzinfo=UTC),
            timezone="UTC",
        )
    with pytest.raises(ValueError, match="after start"):
        ReportingWindow(
            start=datetime(2026, 9, 1, tzinfo=UTC),
            end=datetime(2026, 8, 1, tzinfo=UTC),
            timezone="UTC",
        )
