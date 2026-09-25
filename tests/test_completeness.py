from __future__ import annotations

from clash_reporter.completeness import posting_blockers
from clash_reporter.config import REQUIRED_DATA_CHANNELS


def test_empty_clan_games_capture_is_not_a_blocker() -> None:
    captured = set(REQUIRED_DATA_CHANNELS)
    assert posting_blockers(captured, {}) == []


def test_inaccessible_wars_blocks_posting() -> None:
    captured = set(REQUIRED_DATA_CHANNELS) - {"cp-wars"}
    blockers = posting_blockers(captured, {"cp-wars": "403"})
    assert len(blockers) == 1
    assert blockers[0].startswith("#cp-wars inaccessible")


def test_missing_required_channel_blocks_posting() -> None:
    captured = set(REQUIRED_DATA_CHANNELS) - {"cp-members"}
    blockers = posting_blockers(captured, {})
    assert blockers == ["#cp-members was not captured"]


def test_optional_donations_channel_is_not_required() -> None:
    assert posting_blockers(set(REQUIRED_DATA_CHANNELS), {}) == []
    assert "cp-donations" not in REQUIRED_DATA_CHANNELS
