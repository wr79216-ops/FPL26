"""Timestamped raw JSON persistence for reproducible ingestion runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.settings import RAW_DATA_DIR


SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


class RawDataStore:
    """Write API responses into date/run folders without overwriting older data."""

    def __init__(self, root: Path = RAW_DATA_DIR) -> None:
        self.root = Path(root)

    def save(
        self,
        source: str,
        payload: Any,
        captured_at: Optional[datetime] = None,
    ) -> Path:
        timestamp = captured_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)

        safe_source = SAFE_NAME_PATTERN.sub("_", source).strip("_").lower()
        if not safe_source:
            raise ValueError("source must contain at least one safe character")

        day_directory = self.root / timestamp.strftime("%Y-%m-%d")
        run_directory = day_directory / timestamp.strftime("%H%M%S_%fZ")
        run_directory.mkdir(parents=True, exist_ok=True)
        destination = run_directory / f"{safe_source}.json"
        if destination.exists():
            suffix = 2
            while destination.exists():
                destination = run_directory / f"{safe_source}_{suffix}.json"
                suffix += 1
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return destination

    def load_latest(self, source: str) -> Optional[Any]:
        """Read the newest valid locally cached payload for a known source."""
        safe_source = SAFE_NAME_PATTERN.sub("_", source).strip("_").lower()
        if not safe_source:
            raise ValueError("source must contain at least one safe character")
        candidates = sorted(
            self.root.rglob(f"{safe_source}.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for candidate in candidates:
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        return None
