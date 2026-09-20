from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from clash_reporter.models import MonthlyDataset
from clash_reporter.window import snowflake_for

FIXTURES = Path(__file__).parent / "fixtures"

# Low 22 bits of a snowflake (worker, process, increment). Any value works; a fixed one
# keeps re-dated fixtures deterministic.
SNOWFLAKE_SUFFIX = 0x0A1B02


@pytest.fixture
def sample_dataset() -> MonthlyDataset:
    path = FIXTURES / "normalized" / "monthly_players.sample.json"
    return MonthlyDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _load_message(relative_path: str) -> dict[str, Any]:
    return json.loads((FIXTURES / relative_path).read_text(encoding="utf-8"))


def _repost(
    message: dict[str, Any], timestamp: datetime, *, message_id: str | None = None
) -> dict[str, Any]:
    """A copy of a fixture message re-dated, with a snowflake matching its timestamp."""
    copy = deepcopy(message)
    copy["timestamp"] = timestamp.isoformat()
    copy["id"] = message_id or str(snowflake_for(timestamp) | SNOWFLAKE_SUFFIX)
    return copy


@pytest.fixture
def clashperk_message() -> Callable[[str], dict[str, Any]]:
    """Load a ClashPerk-shaped Discord message. See ``tests/fixtures/README.md``."""
    return _load_message


@pytest.fixture
def repost() -> Callable[..., dict[str, Any]]:
    """Re-date a fixture message so tests can place real payloads inside a window."""
    return _repost


@pytest.fixture
def history_page(
    clashperk_message: Callable[[str], dict[str, Any]],
    repost: Callable[..., dict[str, Any]],
) -> Callable[..., list[dict[str, Any]]]:
    """Build a newest-first page of real ClashPerk messages at the given timestamps."""

    def build(relative_path: str, *timestamps: datetime) -> list[dict[str, Any]]:
        message = clashperk_message(relative_path)
        return [repost(message, timestamp) for timestamp in timestamps]

    return build
