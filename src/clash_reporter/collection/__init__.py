"""Collectors: turn Discord channel history into window-bounded raw payloads.

Collectors preserve original Discord message objects. They know about reporting
windows and channels, never about ClashPerk message semantics.
"""

from clash_reporter.collection.fetch_messages import collect_channel

__all__ = ["collect_channel"]
