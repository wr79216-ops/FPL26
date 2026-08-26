"""Recommendation Engine V1 orchestration and persisted ranking results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from config.settings import (
    DATABASE_PATH,
    SCORING_CONFIG_PATH,
    ScoringConfig,
    load_scoring_config,
)
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import RecommendationScoreRecord
from src.features.player import STATUS_TO_AVAILABILITY
from src.features.recommendation import RecommendationCandidate, score_recommendations
from src.services.application import get_database
from src.services.fixture_analytics import FixtureAnalyticsService, get_fixture_analytics_service
from src.services.fpl_ingestion import FPLIngestionService, get_fpl_ingestion_service
from src.utils.text import normalize_display_name


@dataclass(frozen=True)
class RecommendationRow:
    player_id: int
    name: str
    team: str
    position: str
    status: str
    news: str
    price: float
    ownership: float
    minutes: int
    form: float
    points_per_game: float
    xg_per_90: float
    xa_per_90: float
    xgi_per_90: float
    confidence: float
    next_fixture: str
    form_score: float
    fixture_score: float
    expected_score: float
    minutes_score: float
    history_score: float
    value_score: float
    bonus_score: float
    ownership_score: float
    final_score: float
    category: str
    reason: str
    transfers_in_event: int = 0


class RecommendationEngineService:
    """Calculate and cache official rankings for all positions and horizons."""

    def __init__(
        self,
        database: Database,
        ingestion: FPLIngestionService,
        fixture_analytics: FixtureAnalyticsService,
        scoring: ScoringConfig,
    ) -> None:
        self.database = database
        self.ingestion = ingestion
        self.fixture_analytics = fixture_analytics
        self.scoring = scoring
        self._cache: dict[tuple[str, int, str], tuple[RecommendationRow, ...]] = {}

    def clear_cache(self) -> None:
        """Force score recalculation after persisted feature data changes."""
        self._cache.clear()

    def get_rankings(
        self,
        position: Optional[str] = None,
        horizon: int = 5,
        limit: Optional[int] = None,
    ) -> tuple[RecommendationRow, ...]:
        if horizon not in (1, 3, 5, 8):
            raise ValueError("horizon must be one of 1, 3, 5, or 8")
        refresh = self.ingestion.status_store.load()
        cache_key = (
            refresh.last_successful_at or "never",
            horizon,
            self.scoring.model_version,
        )
        if cache_key not in self._cache:
            self._cache = {cache_key: self._calculate(horizon)}
        rows = self._cache[cache_key]
        if position is not None:
            rows = tuple(row for row in rows if row.position == position)
        return rows[:limit] if limit is not None else rows

    def _calculate(self, horizon: int) -> tuple[RecommendationRow, ...]:
        refresh = self.ingestion.status_store.load()
        current_gameweek = refresh.current_gameweek or 0
        fixture_matrix = self.fixture_analytics.get_matrix(horizon)
        fixture_by_team = {summary.team_name: summary for summary in fixture_matrix.teams}
        with self.database.session() as session:
            repository = FPLRepository(session)
            source_rows = repository.list_players_with_latest_stats()
            historical_scores = repository.get_player_historical_scores()

        candidates = []
        metadata = {}
        possible_minutes = max(1, current_gameweek) * 90
        for player, stats, team in source_rows:
            played_minutes = max(0, stats.minutes)
            xg_per_90 = stats.expected_goals * 90 / played_minutes if played_minutes else 0.0
            xa_per_90 = stats.expected_assists * 90 / played_minutes if played_minutes else 0.0
            xgi_per_90 = (
                stats.expected_goal_involvements * 90 / played_minutes
                if played_minutes
                else 0.0
            )
            ict_per_90 = stats.ict_index * 90 / played_minutes if played_minutes else 0.0
            minutes_security = min(100.0, played_minutes / possible_minutes * 100)
            fixture_summary = fixture_by_team.get(team.name)
            fixture_ease = (
                fixture_summary.fixture_score
                if fixture_summary is not None and fixture_summary.fixture_score is not None
                else 50.0
            )
            availability_key = STATUS_TO_AVAILABILITY.get(player.status, "unavailable")
            availability_penalty = self.scoring.availability_penalty.get(
                availability_key, 0.0
            )
            confidence = min(1.0, played_minutes / self.scoring.minimum_minutes)
            metrics = {
                "attacking_output": xgi_per_90,
                "bonus": float(stats.bonus),
                "fixture": float(fixture_ease),
                "form": stats.form,
                "history": float(
                    historical_scores[player.player_id].score
                    if player.player_id in historical_scores
                    else 50.0
                ),
                "ict": ict_per_90,
                "minutes": minutes_security,
                "ownership": stats.selected_by_percent,
                "ppm": stats.points_per_game,
                "saves": float(stats.saves),
                "value": stats.points_per_game / stats.price if stats.price else 0.0,
                "xg": xg_per_90,
                "xgi": xgi_per_90,
            }
            candidates.append(
                RecommendationCandidate(
                    player_id=player.player_id,
                    position=player.position,
                    metrics=metrics,
                    confidence=confidence,
                    availability_penalty=availability_penalty,
                )
            )
            first_fixture = fixture_summary.fixtures[0] if fixture_summary and fixture_summary.fixtures else None
            metadata[player.player_id] = {
                "player": player,
                "stats": stats,
                "team": team,
                "xg_per_90": xg_per_90,
                "xa_per_90": xa_per_90,
                "xgi_per_90": xgi_per_90,
                "confidence": confidence,
                "next_fixture": first_fixture.fixture if first_fixture else "TBC",
            }

        calculated_at = datetime.now(timezone.utc)
        scored = score_recommendations(candidates, self.scoring.position_weights)
        rows = []
        with self.database.session() as session:
            repository = FPLRepository(session)
            for score in scored:
                item = metadata[score.player_id]
                player = item["player"]
                stats = item["stats"]
                team = item["team"]
                repository.upsert_recommendation(
                    RecommendationScoreRecord(
                        player_id=score.player_id,
                        gameweek=current_gameweek,
                        horizon=horizon,
                        form_score=score.form_score,
                        fixture_score=score.fixture_score,
                        expected_score=score.expected_score,
                        minutes_score=score.minutes_score,
                        history_score=score.history_score,
                        value_score=score.value_score,
                        bonus_score=score.bonus_score,
                        ownership_score=score.ownership_score,
                        final_score=score.final_score,
                        model_version=self.scoring.model_version,
                        calculated_at=calculated_at,
                    )
                )
                rows.append(
                    RecommendationRow(
                        player_id=score.player_id,
                        name=normalize_display_name(player.web_name),
                        team=team.name,
                        position=player.position,
                        status=player.status,
                        news=player.news,
                        price=stats.price,
                        ownership=stats.selected_by_percent,
                        minutes=stats.minutes,
                        form=stats.form,
                        points_per_game=stats.points_per_game,
                        xg_per_90=round(float(item["xg_per_90"]), 2),
                        xa_per_90=round(float(item["xa_per_90"]), 2),
                        xgi_per_90=round(float(item["xgi_per_90"]), 2),
                        confidence=round(float(item["confidence"]), 2),
                        next_fixture=str(item["next_fixture"]),
                        form_score=score.form_score,
                        fixture_score=score.fixture_score,
                        expected_score=score.expected_score,
                        minutes_score=score.minutes_score,
                        history_score=score.history_score,
                        value_score=score.value_score,
                        bonus_score=score.bonus_score,
                        ownership_score=score.ownership_score,
                        final_score=score.final_score,
                        category=score.category,
                        reason=score.reason,
                        transfers_in_event=stats.transfers_in_event,
                    )
                )
        return tuple(sorted(rows, key=lambda row: row.final_score, reverse=True))


def get_recommendation_engine_service(
    database_path: str = str(DATABASE_PATH),
) -> RecommendationEngineService:
    """Reload the engine automatically when scoring.yaml changes."""
    return _get_cached_recommendation_engine_service(
        database_path, SCORING_CONFIG_PATH.stat().st_mtime_ns
    )


@lru_cache(maxsize=8)
def _get_cached_recommendation_engine_service(
    database_path: str, scoring_config_mtime: int
) -> RecommendationEngineService:
    del scoring_config_mtime
    return RecommendationEngineService(
        database=get_database(database_path),
        ingestion=get_fpl_ingestion_service(database_path),
        fixture_analytics=get_fixture_analytics_service(database_path),
        scoring=load_scoring_config(),
    )
