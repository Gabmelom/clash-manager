"""Turn normalized events into a monthly dataset.

This package is the missing middle of the pipeline: parsers emit events,
scoring consumes a ``MonthlyDataset``. Aggregation reconstructs membership
and fills per-player summaries.

The current implementation is a **members-only** slice of issue #11. War,
CWL, Clan Games, capital, and donation parsers are not wired; those metrics
stay ``None`` (missing), never invented zeros. See ``docs/DEVELOPMENT.md``.
"""

from clash_reporter.aggregation.membership import (
    MembershipRoster,
    PlayerMembership,
    reconstruct_membership,
)
from clash_reporter.aggregation.monthly_summary import build_monthly_dataset
from clash_reporter.aggregation.normalize import (
    NormalizeError,
    NormalizeResult,
    normalize_capture,
)

__all__ = [
    "MembershipRoster",
    "NormalizeError",
    "NormalizeResult",
    "PlayerMembership",
    "build_monthly_dataset",
    "normalize_capture",
    "reconstruct_membership",
]
