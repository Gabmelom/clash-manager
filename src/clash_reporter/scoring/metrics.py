"""Per-player component metrics.

Each component returns a normalized value in ``[0, 1]`` or ``None`` when the
underlying source data is not available. ``None`` is deliberately distinct from a
score of ``0`` so missing data never masquerades as poor performance.
"""

from __future__ import annotations

from dataclasses import dataclass

from clash_reporter.config import ScoringConfig
from clash_reporter.models import MonthlyPlayerSummary


@dataclass(frozen=True)
class ScoreBreakdown:
    reliability: float | None
    war_performance: float | None
    clan_games: float | None
    capital: float | None
    overall: float


def _mean(values: list[float]) -> float | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known) / len(known)


def reliability_score(player: MonthlyPlayerSummary) -> float | None:
    """Attack usage across regular war and CWL, as a fraction in ``[0, 1]``."""
    usages: list[float] = []
    for usage in (player.regular_war.attack_usage_percent, player.cwl.attack_usage_percent):
        if usage is not None:
            usages.append(usage / 100.0)
    return _mean(usages)


def war_performance_score(player: MonthlyPlayerSummary) -> float | None:
    """Average stars normalized against the 3-star maximum."""
    stars: list[float] = []
    for avg in (player.regular_war.average_stars, player.cwl.average_stars):
        if avg is not None:
            stars.append(min(avg / 3.0, 1.0))
    return _mean(stars)


def clan_games_score(player: MonthlyPlayerSummary, config: ScoringConfig) -> float | None:
    points = player.clan_games.points
    if points is None:
        return None
    return min(points / config.clan_games_cap, 1.0)


def capital_score(
    player: MonthlyPlayerSummary,
    *,
    min_contribution: int,
    max_contribution: int,
) -> float | None:
    """Clan-relative min-max normalization of capital contribution."""
    contribution = player.capital.contribution
    if contribution is None:
        return None
    if max_contribution <= min_contribution:
        return 1.0
    span = max_contribution - min_contribution
    return max(0.0, min((contribution - min_contribution) / span, 1.0))


def composite_score(
    breakdown_inputs: dict[str, float | None],
    weights: dict[str, float],
) -> float:
    """Weighted mean over available components, renormalizing to present weights."""
    numerator = 0.0
    denominator = 0.0
    for key, value in breakdown_inputs.items():
        if value is None:
            continue
        weight = weights[key]
        numerator += weight * value
        denominator += weight
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def score_player(
    player: MonthlyPlayerSummary,
    config: ScoringConfig,
    *,
    min_contribution: int,
    max_contribution: int,
) -> ScoreBreakdown:
    reliability = reliability_score(player)
    war = war_performance_score(player)
    games = clan_games_score(player, config)
    capital = capital_score(
        player,
        min_contribution=min_contribution,
        max_contribution=max_contribution,
    )
    weights = {
        "reliability": config.weight_reliability,
        "war_performance": config.weight_war_performance,
        "clan_games": config.weight_clan_games,
        "capital": config.weight_capital,
    }
    overall = composite_score(
        {
            "reliability": reliability,
            "war_performance": war,
            "clan_games": games,
            "capital": capital,
        },
        weights,
    )
    return ScoreBreakdown(
        reliability=reliability,
        war_performance=war,
        clan_games=games,
        capital=capital,
        overall=round(overall * 100, 1),
    )
