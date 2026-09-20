from __future__ import annotations

import pytest

from clash_reporter.config import ScoringConfig, Settings


def test_settings_load_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(Settings.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.discord_bot_token is None
    assert settings.report_timezone == "America/Toronto"


def test_require_discord_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_REPORT_CHANNEL_ID", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="Missing required Discord configuration"):
        settings.require_discord()


def test_default_weights_sum_to_one() -> None:
    assert ScoringConfig().total_weight() == pytest.approx(1.0)
