"""Normalized aggregate models.

These mirror ``docs/DATA_CONTRACT.md``. Player tag is the canonical identity and
missing data is represented as ``None`` (not ``0``). Only the aggregate models
needed to render a monthly report from normalized fixtures are implemented here;
per-event parser models are added as real ClashPerk fixtures are captured.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Membership(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible_days: int = 0
    joined_this_month: bool = False
    departed_this_month: bool = False
    left_on: str | None = None
    joined_on: str | None = None


class RegularWar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wars_participated: int = 0
    attacks_available: int | None = None
    attacks_used: int | None = None
    attacks_missed: int | None = None
    total_stars: int | None = None
    average_stars: float | None = None
    average_destruction_percent: float | None = None

    @property
    def attack_usage_percent(self) -> float | None:
        if not self.attacks_available:
            return None
        used = self.attacks_used or 0
        return round(100.0 * used / self.attacks_available, 1)


class Cwl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rounds_in_lineup: int = 0
    attacks_available: int | None = None
    attacks_used: int | None = None
    attacks_missed: int | None = None
    total_stars: int | None = None
    average_stars: float | None = None

    @property
    def attack_usage_percent(self) -> float | None:
        if not self.attacks_available:
            return None
        used = self.attacks_used or 0
        return round(100.0 * used / self.attacks_available, 1)


class ClanGames(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: int | None = None


class Capital(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contribution: int | None = None
    raid_attacks: int | None = None


class MonthlyPlayerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_tag: str
    current_display_name: str
    membership: Membership = Membership()
    regular_war: RegularWar = RegularWar()
    cwl: Cwl = Cwl()
    clan_games: ClanGames = ClanGames()
    capital: Capital = Capital()
    warnings: list[str] = []


class MonthlyDataset(BaseModel):
    """A full normalized month, the input to scoring and reporting."""

    model_config = ConfigDict(extra="forbid")

    month_label: str
    clan_name: str = "Clan"
    regular_wars: int = 0
    cwl_rounds: int = 0
    clan_games_completed: bool = False
    raid_weekends: int = 0
    players: list[MonthlyPlayerSummary] = []
    data_notes: list[str] = []
