"""Ranking, eligibility, and review classification.

Ordering is deterministic for a given dataset and configuration. Tie-breakers
follow ``docs/REPORT_SPEC.md``: overall score descending, reliability descending,
player tag ascending.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clash_reporter.config import ScoringConfig
from clash_reporter.models import MonthlyDataset, MonthlyPlayerSummary
from clash_reporter.scoring.metrics import ScoreBreakdown, score_player


@dataclass(frozen=True)
class RankedPlayer:
    summary: MonthlyPlayerSummary
    score: ScoreBreakdown
    review_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RankedReport:
    ranked: list[RankedPlayer]
    new_members: list[MonthlyPlayerSummary]
    departed_members: list[MonthlyPlayerSummary]

    @property
    def review(self) -> list[RankedPlayer]:
        flagged = [p for p in self.ranked if p.review_reasons]
        return sorted(flagged, key=lambda p: p.score.overall)


def is_ranking_eligible(player: MonthlyPlayerSummary, config: ScoringConfig) -> bool:
    if player.membership.departed_this_month:
        return False
    return player.membership.eligible_days >= config.min_eligible_days


def _review_reasons(player: MonthlyPlayerSummary, config: ScoringConfig) -> list[str]:
    reasons: list[str] = []
    usage = player.regular_war.attack_usage_percent
    if usage is not None and usage < 80:
        reasons.append(f"{usage:.0f}% regular war attack usage")
    missed = player.regular_war.attacks_missed
    if missed:
        reasons.append(f"{missed} regular war attacks missed")
    cwl_missed = player.cwl.attacks_missed
    if cwl_missed:
        reasons.append(f"{cwl_missed} CWL attacks missed")
    points = player.clan_games.points
    if points is not None and points < config.clan_games_cap // 4:
        reasons.append(f"{points} Clan Games points")
    if player.capital.contribution == 0:
        reasons.append("no capital contribution recorded")
    return reasons


def rank_players(dataset: MonthlyDataset, config: ScoringConfig) -> RankedReport:
    new_members = [
        p
        for p in dataset.players
        if p.membership.joined_this_month and not is_ranking_eligible(p, config)
    ]
    departed_members = [p for p in dataset.players if p.membership.departed_this_month]

    eligible = [p for p in dataset.players if is_ranking_eligible(p, config)]

    contributions = [p.capital.contribution for p in eligible if p.capital.contribution is not None]
    min_contribution = min(contributions) if contributions else 0
    max_contribution = max(contributions) if contributions else 0

    ranked: list[RankedPlayer] = []
    for player in eligible:
        breakdown = score_player(
            player,
            config,
            min_contribution=min_contribution,
            max_contribution=max_contribution,
        )
        reasons = _review_reasons(player, config)
        # Only surface for review when at least two negative signals are present.
        review = reasons if len(reasons) >= 2 else []
        ranked.append(RankedPlayer(summary=player, score=breakdown, review_reasons=review))

    ranked.sort(
        key=lambda p: (
            -p.score.overall,
            -(p.score.reliability if p.score.reliability is not None else -1.0),
            p.summary.player_tag,
        )
    )
    return RankedReport(
        ranked=ranked,
        new_members=new_members,
        departed_members=departed_members,
    )
