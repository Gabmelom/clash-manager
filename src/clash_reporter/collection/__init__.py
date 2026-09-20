"""Collectors: turn Discord channel history into window-bounded raw payloads.

Collectors preserve original Discord message objects. They know about reporting
windows and channels, never about ClashPerk message semantics.
"""

from clash_reporter.collection.capture import (
    CaptureRun,
    ChannelCapture,
    ChannelCaptureError,
    capture_channels,
)
from clash_reporter.collection.fetch_messages import collect_channel
from clash_reporter.collection.sanitize import IdSanitizer

__all__ = [
    "CaptureRun",
    "ChannelCapture",
    "ChannelCaptureError",
    "IdSanitizer",
    "capture_channels",
    "collect_channel",
]
