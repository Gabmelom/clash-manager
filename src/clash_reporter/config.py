"""Centralized configuration.

Discord/runtime settings are loaded from environment variables (see ``.env.example``).
All Discord fields are optional so that offline report rendering from normalized
fixtures does not require any secrets. Scoring weights and eligibility thresholds
live here so they can be tuned without touching business logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from clash_reporter.discord_client import DEFAULT_BASE_URL

#: ClashPerk data channels, in capture order. Names are configuration, not
#: business logic: everything downstream addresses a channel by this name and
#: resolves the ID through :class:`Settings`.
DATA_CHANNELS: Final[tuple[str, ...]] = (
    "cp-members",
    "cp-wars",
    "cp-cwl",
    "cp-capital",
    "cp-games",
    "cp-donations",
)

#: Channels the monthly report cannot omit. ``#cp-donations`` stays optional.
#: An empty ``#cp-games`` capture is still a successful read: no Clan Games
#: event that month is valid. Inaccessible is not the same thing.
REQUIRED_DATA_CHANNELS: Final[tuple[str, ...]] = (
    "cp-members",
    "cp-wars",
    "cp-cwl",
    "cp-capital",
    "cp-games",
)


def channel_env_var(name: str) -> str:
    """Environment variable holding the ID of a data channel."""
    return f"DISCORD_{name.replace('-', '_').upper()}_CHANNEL_ID"


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

    #: Override only to point the client at a local stub instead of Discord.
    discord_api_base_url: str = DEFAULT_BASE_URL

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

    def require_bot_token(self) -> str:
        """The bot token, or a failure that never echoes its value."""
        if not self.discord_bot_token:
            raise RuntimeError("Missing required Discord configuration: DISCORD_BOT_TOKEN")
        return self.discord_bot_token

    def channel_id(self, name: str) -> str | None:
        """ID configured for a data channel name such as ``cp-wars``."""
        if name not in DATA_CHANNELS:
            raise KeyError(f"Unknown data channel {name!r}. Known channels: {known_channels()}")
        value = getattr(self, f"discord_{name.replace('-', '_')}_channel_id")
        return str(value) if value else None

    def data_channel_ids(self, names: Sequence[str] | None = None) -> dict[str, str]:
        """Configured data channels, in capture order, skipping unset ones."""
        selected = tuple(names) if names else DATA_CHANNELS
        resolved: dict[str, str] = {}
        for name in selected:
            channel_id = self.channel_id(name)
            if channel_id:
                resolved[name] = channel_id
        return resolved

    def require_data_channels(self, names: Sequence[str] | None = None) -> dict[str, str]:
        """Fail closed when a requested data channel has no configured ID."""
        if names:
            unknown = [name for name in names if name not in DATA_CHANNELS]
            if unknown:
                raise RuntimeError(
                    f"Unknown data channel(s): {', '.join(unknown)}. "
                    f"Known channels: {known_channels()}"
                )
        resolved = self.data_channel_ids(names)
        if names:
            missing = [channel_env_var(name) for name in names if name not in resolved]
            if missing:
                raise RuntimeError("Missing required Discord configuration: " + ", ".join(missing))
        elif not resolved:
            raise RuntimeError(
                "No ClashPerk data channels configured. Set at least one of: "
                + ", ".join(channel_env_var(name) for name in DATA_CHANNELS)
            )
        return resolved

    def channels_for_run(self, *, allow_partial: bool) -> dict[str, str]:
        """Channels for ``run``.

        By default every required data channel must be configured, and
        ``#cp-donations`` is included only when its ID is set. ``allow_partial``
        keeps whatever is configured so a known-incomplete month can still post.
        """
        if allow_partial:
            return self.require_data_channels()
        resolved = self.require_data_channels(REQUIRED_DATA_CHANNELS)
        donations = self.channel_id("cp-donations")
        if donations:
            resolved["cp-donations"] = donations
        return resolved


def known_channels() -> str:
    return ", ".join(DATA_CHANNELS)
