"""Turn normalized events into a monthly dataset.

This package is the missing middle of the pipeline: parsers emit events,
scoring consumes a ``MonthlyDataset``. Aggregation reconstructs membership
and fills per-player summaries.

``normalize`` parses every channel file present in a fetch directory. A missing
file leaves that family's metrics unknown. See ``docs/DEVELOPMENT.md``.
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
