"""Persistent last-known-good status for official FPL refreshes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR


STATUS_PATH = DATA_DIR / "fpl_refresh_status.json"


@dataclass(frozen=True)
class RefreshStatus:
    last_attempt_at: Optional[str] = None
    last_successful_at: Optional[str] = None
    current_gameweek: Optional[int] = None
    teams: int = 0
    players: int = 0
    fixtures: int = 0
    current_stats: int = 0
    gameweek_snapshots: int = 0
    last_error: Optional[str] = None


class RefreshStatusStore:
    """Store refresh results separately from raw payloads and SQLite schema."""

    def __init__(self, path: Path = STATUS_PATH) -> None:
        self.path = Path(path)

    def load(self) -> RefreshStatus:
        if not self.path.exists():
            return RefreshStatus()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RefreshStatus(last_error="Refresh status file could not be read")
        allowed = {field_name: data.get(field_name) for field_name in RefreshStatus.__dataclass_fields__}
        return RefreshStatus(**allowed)

    def record_success(
        self,
        gameweek: int,
        teams: int,
        players: int,
        fixtures: int,
        current_stats: int,
        gameweek_snapshots: int = 0,
        completed_at: Optional[datetime] = None,
    ) -> RefreshStatus:
        timestamp = (completed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        status = RefreshStatus(
            last_attempt_at=timestamp,
            last_successful_at=timestamp,
            current_gameweek=gameweek,
            teams=teams,
            players=players,
            fixtures=fixtures,
            current_stats=current_stats,
            gameweek_snapshots=gameweek_snapshots,
            last_error=None,
        )
        self._write(status)
        return status

    def record_failure(
        self, error: str, attempted_at: Optional[datetime] = None
    ) -> RefreshStatus:
        previous = self.load()
        timestamp = (attempted_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        status = RefreshStatus(
            last_attempt_at=timestamp,
            last_successful_at=previous.last_successful_at,
            current_gameweek=previous.current_gameweek,
            teams=previous.teams,
            players=previous.players,
            fixtures=previous.fixtures,
            current_stats=previous.current_stats,
            gameweek_snapshots=previous.gameweek_snapshots,
            last_error=error,
        )
        self._write(status)
        return status

    def _write(self, status: RefreshStatus) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(asdict(status), indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary_path.replace(self.path)
