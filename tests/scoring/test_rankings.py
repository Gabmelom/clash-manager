from __future__ import annotations

from clash_reporter.config import ScoringConfig
from clash_reporter.models import (
    Capital,
    ClanGames,
    Membership,
    MonthlyDataset,
    MonthlyPlayerSummary,
    RegularWar,
)
from clash_reporter.scoring import rank_players
from clash_reporter.scoring.metrics import clan_games_score, composite_score


def test_new_member_excluded_from_rankings(sample_dataset: MonthlyDataset) -> None:
    ranked = rank_players(sample_dataset, ScoringConfig())
    tags = {p.summary.player_tag for p in ranked.ranked}
    assert "#DDD444" not in tags
    assert {p.player_tag for p in ranked.new_members} == {"#DDD444"}


def test_departed_member_excluded_but_listed(sample_dataset: MonthlyDataset) -> None:
    ranked = rank_players(sample_dataset, ScoringConfig())
    tags = {p.summary.player_tag for p in ranked.ranked}
    assert "#EEE555" not in tags
    assert {p.player_tag for p in ranked.departed_members} == {"#EEE555"}


def test_top_performer_is_deterministic(sample_dataset: MonthlyDataset) -> None:
    ranked = rank_players(sample_dataset, ScoringConfig())
    assert ranked.ranked[0].summary.player_tag == "#AAA111"
    scores = [p.score.overall for p in ranked.ranked]
    assert scores == sorted(scores, reverse=True)


def test_low_performer_flagged_for_review(sample_dataset: MonthlyDataset) -> None:
    ranked = rank_players(sample_dataset, ScoringConfig())
    review_tags = {p.summary.player_tag for p in ranked.review}
    assert "#CCC333" in review_tags


def test_missing_data_does_not_become_zero() -> None:
    config = ScoringConfig()
    player = MonthlyPlayerSummary(
        player_tag="#Z",
        current_display_name="Zed",
        membership=Membership(eligible_days=31),
        regular_war=RegularWar(attacks_available=2, attacks_used=2, average_stars=3.0),
        clan_games=ClanGames(points=None),
        capital=Capital(contribution=None),
    )
    dataset = MonthlyDataset(month_label="X", players=[player])
    ranked = rank_players(dataset, config)
    breakdown = ranked.ranked[0].score
    assert breakdown.clan_games is None
    assert breakdown.capital is None
    # Perfect on the only known components should not be dragged down by nulls.
    assert breakdown.overall == 100.0


def test_clan_games_cap() -> None:
    config = ScoringConfig()
    player = MonthlyPlayerSummary(
        player_tag="#C", current_display_name="Cap", clan_games=ClanGames(points=9000)
    )
    assert clan_games_score(player, config) == 1.0


def test_composite_renormalizes_missing_weights() -> None:
    weights = {"a": 0.5, "b": 0.5}
    assert composite_score({"a": 1.0, "b": None}, weights) == 1.0
