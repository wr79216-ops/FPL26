"""Official FPL refresh orchestration with atomic database loading."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import DATABASE_PATH, RAW_DATA_DIR, load_app_settings, load_scoring_config
from src.api.fpl_client import FPLClient
from src.data.raw_store import RawDataStore
from src.data.refresh_status import RefreshStatus, RefreshStatusStore
from src.database.connection import Database
from src.database.models import (
    CurrentPlayerStatsModel,
    FixtureModel,
    GameweekSnapshotModel,
    GameweekHistoryModel,
    HistoricalPlayerSeasonModel,
    PlayerModel,
    PlayerHistoricalScoreModel,
    PlayerHistorySyncModel,
    TeamModel,
)
from src.database.repository import FPLRepository
from src.etl.transform import (
    current_gameweek,
    transform_current_player_stats,
    transform_fixtures,
    transform_gameweek_snapshots,
    transform_players,
    transform_teams,
)
from src.services.application import get_database


class FPLIngestionError(RuntimeError):
    """Raised when an official refresh fails while preserving last known good data."""


@dataclass(frozen=True)
class RefreshResult:
    completed_at: datetime
    current_gameweek: int
    teams: int
    players: int
    fixtures: int
    current_stats: int
    gameweek_snapshots: int


@dataclass(frozen=True)
class IngestionStatus:
    refresh: RefreshStatus
    teams_in_database: int
    players_in_database: int
    fixtures_in_database: int
    current_stats_in_database: int
    gameweek_snapshots_in_database: int
    gameweek_history_in_database: int
    history_synced_players_in_database: int
    recommendation_scores_in_database: int
    historical_seasons_in_database: int
    historical_rows_in_database: int
    historical_matched_in_database: int
    historical_review_in_database: int
    historical_unmatched_in_database: int
    historical_scores_in_database: int


class FPLIngestionService:
    """Fetch, transform, and load official FPL data as one refresh action."""

    def __init__(
        self,
        database: Database,
        client: FPLClient,
        status_store: RefreshStatusStore,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.database = database
        self.client = client
        self.status_store = status_store
        self.logger = logger or logging.getLogger(__name__)

    def refresh(self) -> RefreshResult:
        """Run a manual refresh; errors leave the previous database state intact."""
        started_at = datetime.now(timezone.utc)
        try:
            self.client.clear_cache()
            bootstrap = self.client.get_bootstrap()
            fixtures_payload = self.client.get_fixtures()
            completed_at = datetime.now(timezone.utc)
            gameweek = current_gameweek(bootstrap["events"])
            teams = transform_teams(bootstrap["teams"])
            players = transform_players(bootstrap["elements"], bootstrap["element_types"])
            fixtures = transform_fixtures(fixtures_payload)
            current_stats = transform_current_player_stats(
                bootstrap["elements"], gameweek=gameweek, snapshot_at=completed_at
            )
            gameweek_snapshots = transform_gameweek_snapshots(current_stats, completed_at)

            with self.database.session() as session:
                repository = FPLRepository(session)
                for team in teams:
                    repository.upsert_team(team)
                for player in players:
                    repository.upsert_player(player)
                for fixture in fixtures:
                    repository.upsert_fixture(fixture)
                for stats in current_stats:
                    repository.upsert_current_stats(stats)
                for snapshot in gameweek_snapshots:
                    repository.upsert_gameweek_snapshot(snapshot)

            result = RefreshResult(
                completed_at=completed_at,
                current_gameweek=gameweek,
                teams=len(teams),
                players=len(players),
                fixtures=len(fixtures),
                current_stats=len(current_stats),
                gameweek_snapshots=len(gameweek_snapshots),
            )
            self.status_store.record_success(
                gameweek=result.current_gameweek,
                teams=result.teams,
                players=result.players,
                fixtures=result.fixtures,
                current_stats=result.current_stats,
                gameweek_snapshots=result.gameweek_snapshots,
                completed_at=result.completed_at,
            )
            self.logger.info(
                "FPL_REFRESH_COMPLETE gameweek=%s teams=%s players=%s fixtures=%s stats=%s snapshots=%s",
                result.current_gameweek,
                result.teams,
                result.players,
                result.fixtures,
                result.current_stats,
                result.gameweek_snapshots,
            )
            return result
        except Exception as exc:
            self.status_store.record_failure(str(exc), attempted_at=started_at)
            self.logger.exception("FPL_REFRESH_ERROR error=%s", type(exc).__name__)
            raise FPLIngestionError("Official FPL refresh failed; last successful data is unchanged") from exc

    def get_status(self) -> IngestionStatus:
        with self.database.session() as session:
            repository = FPLRepository(session)
            historical_mappings = repository.historical_mapping_counts()
            return IngestionStatus(
                refresh=self.status_store.load(),
                teams_in_database=repository.count(TeamModel),
                players_in_database=repository.count(PlayerModel),
                fixtures_in_database=repository.count(FixtureModel),
                current_stats_in_database=repository.count(CurrentPlayerStatsModel),
                gameweek_snapshots_in_database=repository.count(GameweekSnapshotModel),
                gameweek_history_in_database=repository.count(GameweekHistoryModel),
                history_synced_players_in_database=repository.count(PlayerHistorySyncModel),
                recommendation_scores_in_database=repository.recommendation_score_count(
                    load_scoring_config().model_version
                ),
                historical_seasons_in_database=repository.historical_season_count(),
                historical_rows_in_database=repository.count(HistoricalPlayerSeasonModel),
                historical_matched_in_database=historical_mappings.get("MATCHED", 0),
                historical_review_in_database=historical_mappings.get("REVIEW", 0),
                historical_unmatched_in_database=historical_mappings.get("UNMATCHED", 0),
                historical_scores_in_database=repository.count(PlayerHistoricalScoreModel),
            )

    def get_local_gameweek_live(self, gameweek: int) -> dict[str, Any]:
        """Build an event-live-shaped payload from the latest official local snapshot."""
        if gameweek <= 0:
            raise ValueError("gameweek must be positive")
        with self.database.session() as session:
            snapshots = session.query(GameweekSnapshotModel).filter(
                GameweekSnapshotModel.gameweek == gameweek
            ).all()
            histories = session.query(GameweekHistoryModel).filter(
                GameweekHistoryModel.gameweek == gameweek
            ).all()
        history_by_player = {}
        for history in histories:
            history_by_player.setdefault(history.player_id, history)
        return {
            "elements": [
                {
                    "id": snapshot.player_id,
                    "stats": {
                        "minutes": snapshot.minutes,
                        "total_points": snapshot.total_points,
                        "expected_goals": (
                            history_by_player[snapshot.player_id].xg
                            if snapshot.player_id in history_by_player
                            else snapshot.expected_goals
                        ),
                        "expected_assists": (
                            history_by_player[snapshot.player_id].xa
                            if snapshot.player_id in history_by_player
                            else snapshot.expected_assists
                        ),
                        "expected_goals_conceded": (
                            history_by_player[snapshot.player_id].xgc
                            if snapshot.player_id in history_by_player
                            else 0.0
                        ),
                        "goals_scored": (
                            history_by_player[snapshot.player_id].goals
                            if snapshot.player_id in history_by_player
                            else 0
                        ),
                    },
                }
                for snapshot in snapshots
            ]
        }


@lru_cache(maxsize=4)
def get_fpl_ingestion_service(
    database_path: str = str(DATABASE_PATH),
) -> FPLIngestionService:
    """Return a process-local service with reusable HTTP cache and session."""
    settings = load_app_settings()
    database = get_database(database_path)
    raw_store = RawDataStore(RAW_DATA_DIR)
    status_store = RefreshStatusStore(Path(database_path).parent / "fpl_refresh_status.json")
    client = FPLClient(
        base_url=settings.fpl_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        raw_store=raw_store,
    )
    return FPLIngestionService(database, client, status_store)
