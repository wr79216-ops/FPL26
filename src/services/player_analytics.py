"""On-demand official player history and explainable feature orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from config.settings import DATABASE_PATH, ScoringConfig, load_scoring_config
from src.api.fpl_client import FPLClient
from src.data.refresh_status import RefreshStatusStore
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import PlayerHistorySyncRecord
from src.etl.transform import transform_gameweek_history
from src.features.player import PlayerFeatureSet, calculate_player_features
from src.services.application import get_database
from src.services.fpl_ingestion import get_fpl_ingestion_service
from src.utils.season import season_label
from src.utils.text import normalize_display_name


@dataclass(frozen=True)
class PlayerOption:
    player_id: int
    label: str


@dataclass(frozen=True)
class PlayerHistoryRow:
    gameweek: int
    opponent: str
    venue: str
    minutes: int
    points: int
    xg: float
    xa: float
    xgi: float
    bonus: int
    price: float


@dataclass(frozen=True)
class PlayerDetail:
    player_id: int
    name: str
    team_id: int
    team: str
    position: str
    status: str
    news: str
    price: float
    ownership: float
    total_points: int
    current_form: float
    current_minutes: int
    current_xg: float
    current_xa: float
    current_xgi: float
    points_per_game: float
    features: PlayerFeatureSet
    history: tuple[PlayerHistoryRow, ...]
    history_checked_at: datetime | None
    history_checked_gameweek: int | None


@dataclass(frozen=True)
class HistorySyncResult:
    player_id: int
    row_count: int
    checked_at: datetime
    from_cache: bool


class PlayerAnalyticsService:
    """Serve local player detail and sync element-summary only when requested."""

    def __init__(
        self,
        database: Database,
        client: FPLClient,
        status_store: RefreshStatusStore,
        scoring: ScoringConfig,
    ) -> None:
        self.database = database
        self.client = client
        self.status_store = status_store
        self.scoring = scoring

    def list_player_options(self) -> tuple[PlayerOption, ...]:
        with self.database.session() as session:
            repository = FPLRepository(session)
            teams = {team.team_id: team.name for team in repository.list_teams()}
            return tuple(
                PlayerOption(
                    player.player_id,
                    f"{normalize_display_name(player.web_name)} · "
                    f"{teams.get(player.team_id, 'Unknown')} · {player.position}",
                )
                for player in repository.list_players()
            )

    def sync_history(self, player_id: int) -> HistorySyncResult:
        now = datetime.now(timezone.utc)
        season = season_label(now)
        current_gameweek = self.status_store.load().current_gameweek or 0
        with self.database.session() as session:
            repository = FPLRepository(session)
            if repository.get_player(player_id) is None:
                raise ValueError(f"Unknown player_id: {player_id}")
            previous = repository.get_player_history_sync(player_id)
            if (
                previous is not None
                and previous.season == season
                and previous.gameweek == current_gameweek
            ):
                return HistorySyncResult(
                    player_id, previous.row_count, previous.checked_at, True
                )

        payload = self.client.get_player_summary(player_id)
        records = transform_gameweek_history(payload["history"], player_id, season)
        with self.database.session() as session:
            repository = FPLRepository(session)
            for record in records:
                repository.upsert_gameweek_history(record)
            repository.upsert_player_history_sync(
                PlayerHistorySyncRecord(
                    player_id=player_id,
                    season=season,
                    gameweek=current_gameweek,
                    row_count=len(records),
                    checked_at=now,
                )
            )
        return HistorySyncResult(player_id, len(records), now, False)

    def get_detail(self, player_id: int) -> PlayerDetail:
        with self.database.session() as session:
            repository = FPLRepository(session)
            player = repository.get_player(player_id)
            if player is None:
                raise ValueError(f"Unknown player_id: {player_id}")
            team = repository.get_team(player.team_id)
            current = repository.get_latest_current_stats(player_id)
            history_models = repository.list_gameweek_history(player_id)
            sync = repository.get_player_history_sync(player_id)
            opponent_names = {}
            for row in history_models:
                opponent = repository.get_team(row.opponent_team_id)
                opponent_names[row.opponent_team_id] = (
                    opponent.name if opponent is not None else "Unknown"
                )
            history = tuple(
                PlayerHistoryRow(
                    gameweek=row.gameweek,
                    opponent=opponent_names[row.opponent_team_id],
                    venue="Home" if row.was_home else "Away",
                    minutes=row.minutes,
                    points=row.total_points,
                    xg=row.xg,
                    xa=row.xa,
                    xgi=row.xgi,
                    bonus=row.bonus,
                    price=row.value,
                )
                for row in history_models
            )
            features = calculate_player_features(
                history_models,
                price=player.price,
                status=player.status,
                availability_penalties=self.scoring.availability_penalty,
                minimum_minutes=self.scoring.minimum_minutes,
                minutes_security_window=self.scoring.minutes_security_window,
            )
            return PlayerDetail(
                player_id=player.player_id,
                name=normalize_display_name(f"{player.first_name} {player.second_name}".strip()),
                team_id=player.team_id,
                team=team.name if team is not None else "Unknown",
                position=player.position,
                status=player.status,
                news=player.news,
                price=player.price,
                ownership=player.ownership,
                total_points=current.total_points if current is not None else 0,
                current_form=current.form if current is not None else 0.0,
                current_minutes=current.minutes if current is not None else 0,
                current_xg=current.expected_goals if current is not None else 0.0,
                current_xa=current.expected_assists if current is not None else 0.0,
                current_xgi=(
                    current.expected_goal_involvements if current is not None else 0.0
                ),
                points_per_game=current.points_per_game if current is not None else 0.0,
                features=features,
                history=history,
                history_checked_at=sync.checked_at if sync is not None else None,
                history_checked_gameweek=sync.gameweek if sync is not None else None,
            )


@lru_cache(maxsize=4)
def get_player_analytics_service(
    database_path: str = str(DATABASE_PATH),
) -> PlayerAnalyticsService:
    ingestion = get_fpl_ingestion_service(database_path)
    return PlayerAnalyticsService(
        database=get_database(database_path),
        client=ingestion.client,
        status_store=ingestion.status_store,
        scoring=load_scoring_config(),
    )
