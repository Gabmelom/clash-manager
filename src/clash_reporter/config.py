"""Centralized configuration.

Discord/runtime settings are loaded from environment variables (see ``.env.example``).
All Discord fields are optional so that offline report rendering from normalized
fixtures does not require any secrets. Scoring weights and eligibility thresholds
live here so they can be tuned without touching business logic.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScoringConfig(BaseSettings):
    """Weights and thresholds for the transparent monthly score.

    Weights are placeholders that mirror ``docs/REPORT_SPEC.md`` and should sum to 1.0.
    """

    model_config = SettingsConfigDict(env_prefix="SCORING_")

    min_eligible_days: int = 14
    clan_games_cap: int = 4000

    weight_reliability: float = 0.40
    weight_war_performance: float = 0.30
    weight_clan_games: float = 0.15
    weight_capital: float = 0.15

    def total_weight(self) -> float:
        return (
            self.weight_reliability
            + self.weight_war_performance
            + self.weight_clan_games
            + self.weight_capital
        )


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_bot_token: str | None = Field(default=None)
    discord_guild_id: str | None = Field(default=None)
    discord_cp_members_channel_id: str | None = Field(default=None)
    discord_cp_wars_channel_id: str | None = Field(default=None)
    discord_cp_cwl_channel_id: str | None = Field(default=None)
    discord_cp_capital_channel_id: str | None = Field(default=None)
    discord_cp_games_channel_id: str | None = Field(default=None)
    discord_cp_donations_channel_id: str | None = Field(default=None)
    discord_report_channel_id: str | None = Field(default=None)
    report_timezone: str = "America/Toronto"

    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    def require_discord(self) -> None:
        """Fail closed when Discord access is needed but not configured."""
        missing = [
            name
            for name, value in {
                "DISCORD_BOT_TOKEN": self.discord_bot_token,
                "DISCORD_REPORT_CHANNEL_ID": self.discord_report_channel_id,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError("Missing required Discord configuration: " + ", ".join(missing))
