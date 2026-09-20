from __future__ import annotations

from pathlib import Path

import pytest

from clash_reporter.models import MonthlyDataset

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_dataset() -> MonthlyDataset:
    path = FIXTURES / "normalized" / "monthly_players.sample.json"
    return MonthlyDataset.model_validate_json(path.read_text(encoding="utf-8"))
