from __future__ import annotations

import pytest

from clash_reporter.config import REQUIRED_DATA_CHANNELS, ScoringConfig, Settings, channel_env_var


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


def test_run_requires_every_critical_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(channel_env_var("cp-members"), "1")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="DISCORD_CP_WARS_CHANNEL_ID"):
        settings.channels_for_run(allow_partial=False)
    partial = settings.channels_for_run(allow_partial=True)
    assert partial == {"cp-members": "1"}


def test_run_includes_optional_donations_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for index, name in enumerate(REQUIRED_DATA_CHANNELS, start=1):
        monkeypatch.setenv(channel_env_var(name), str(index))
    monkeypatch.setenv(channel_env_var("cp-donations"), "9")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    resolved = settings.channels_for_run(allow_partial=False)
    assert set(resolved) == set(REQUIRED_DATA_CHANNELS) | {"cp-donations"}
