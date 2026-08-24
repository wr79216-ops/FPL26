"""Small helpers for deriving an FPL season label from a timestamp."""

from __future__ import annotations

from datetime import datetime


def season_label(captured_at: datetime) -> str:
    """Return the football season containing ``captured_at`` (e.g. ``2026-27``)."""
    start_year = captured_at.year if captured_at.month >= 7 else captured_at.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"
