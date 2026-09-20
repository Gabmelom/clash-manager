"""Transparent metric and ranking calculation over normalized monthly summaries.

Scoring operates only on :mod:`clash_reporter.models` aggregates. It never parses
Discord payloads and never treats missing data as zero.
"""

from clash_reporter.scoring.rankings import RankedReport, rank_players

__all__ = ["RankedReport", "rank_players"]
