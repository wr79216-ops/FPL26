"""Repository operations that isolate SQLAlchemy from services and UI."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.database.models import (
    BacktestFixtureModel,
    BacktestPlayerGameweekModel,
    BacktestPredictionModel,
    BacktestRunModel,
    CurrentPlayerStatsModel,
    FixtureModel,
    GameweekHistoryModel,
    GameweekSnapshotModel,
    HistoricalIdentityMappingModel,
    HistoricalPlayerSeasonModel,
    PlayerModel,
    PlayerHistoricalScoreModel,
    PlayerHistorySyncModel,
    RecommendationScoreModel,
    TeamModel,
)
from src.domain.contracts import (
    BacktestFixtureRecord,
    BacktestPlayerGameweekRecord,
    BacktestPredictionRecord,
    BacktestRunRecord,
    CurrentPlayerStatsRecord,
    FixtureRecord,
    GameweekHistoryRecord,
    GameweekSnapshotRecord,
    HistoricalIdentityMappingRecord,
    HistoricalPlayerSeasonRecord,
    PlayerRecord,
    PlayerHistoricalScoreRecord,
    PlayerHistorySyncRecord,
    RecommendationScoreRecord,
    TeamRecord,
)


ModelType = TypeVar("ModelType")


def _assign(entity: Any, values: Dict[str, Any]) -> None:
    for field_name, value in values.items():
        setattr(entity, field_name, value)


class FPLRepository:
    """Idempotent writes and focused reads for the baseline FPL schema."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _upsert(
        self,
        model: Type[ModelType],
        identity: Any,
        values: Dict[str, Any],
    ) -> ModelType:
        entity = self.session.get(model, identity)
        if entity is None:
            entity = model(**values)
            self.session.add(entity)
        else:
            _assign(entity, values)
        self.session.flush()
        return entity

    def upsert_team(self, record: TeamRecord) -> TeamModel:
        values = asdict(record)
        return self._upsert(TeamModel, record.team_id, values)

    def upsert_backtest_player_gameweek(
        self, record: BacktestPlayerGameweekRecord
    ) -> BacktestPlayerGameweekModel:
        values = asdict(record)
        values["position"] = record.position.value
        identity = (record.season, record.player_id, record.fixture_id)
        return self._upsert(BacktestPlayerGameweekModel, identity, values)

    def bulk_upsert_backtest_player_gameweeks(
        self, records: List[BacktestPlayerGameweekRecord]
    ) -> None:
        if not records:
            return
        values = []
        for record in records:
            row = asdict(record)
            row["position"] = record.position.value
            values.append(row)
        statement = sqlite_insert(BacktestPlayerGameweekModel)
        update_columns = {
            column.name: getattr(statement.excluded, column.name)
            for column in BacktestPlayerGameweekModel.__table__.columns
            if column.name not in {"season", "player_id", "fixture_id"}
        }
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["season", "player_id", "fixture_id"],
                set_=update_columns,
            ),
            values,
        )
        self.session.flush()

    def upsert_backtest_fixture(
        self, record: BacktestFixtureRecord
    ) -> BacktestFixtureModel:
        identity = (record.season, record.fixture_id)
        return self._upsert(BacktestFixtureModel, identity, asdict(record))

    def bulk_upsert_backtest_fixtures(
        self, records: List[BacktestFixtureRecord]
    ) -> None:
        if not records:
            return
        statement = sqlite_insert(BacktestFixtureModel)
        update_columns = {
            column.name: getattr(statement.excluded, column.name)
            for column in BacktestFixtureModel.__table__.columns
            if column.name not in {"season", "fixture_id"}
        }
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["season", "fixture_id"],
                set_=update_columns,
            ),
            [asdict(record) for record in records],
        )
        self.session.flush()

    def upsert_backtest_prediction(
        self, record: BacktestPredictionRecord
    ) -> BacktestPredictionModel:
        identity = (
            record.season,
            record.as_of_gameweek,
            record.horizon,
            record.model_version,
            record.player_id,
        )
        return self._upsert(BacktestPredictionModel, identity, asdict(record))

    def bulk_upsert_backtest_predictions(
        self, records: List[BacktestPredictionRecord]
    ) -> None:
        if not records:
            return
        statement = sqlite_insert(BacktestPredictionModel)
        primary_key_columns = [
            "season", "as_of_gameweek", "horizon", "model_version", "player_id"
        ]
        primary_keys = set(primary_key_columns)
        update_columns = {
            column.name: getattr(statement.excluded, column.name)
            for column in BacktestPredictionModel.__table__.columns
            if column.name not in primary_keys
        }
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=primary_key_columns,
                set_=update_columns,
            ),
            [asdict(record) for record in records],
        )
        self.session.flush()

    def upsert_backtest_run(self, record: BacktestRunRecord) -> BacktestRunModel:
        identity = (record.season, record.horizon, record.model_version)
        return self._upsert(BacktestRunModel, identity, asdict(record))

    def upsert_player(self, record: PlayerRecord) -> PlayerModel:
        values = asdict(record)
        values["position"] = record.position.value
        return self._upsert(PlayerModel, record.player_id, values)

    def upsert_fixture(self, record: FixtureRecord) -> FixtureModel:
        return self._upsert(FixtureModel, record.fixture_id, asdict(record))

    def upsert_current_stats(
        self, record: CurrentPlayerStatsRecord
    ) -> CurrentPlayerStatsModel:
        identity = (record.player_id, record.gameweek)
        return self._upsert(CurrentPlayerStatsModel, identity, asdict(record))

    def upsert_gameweek_snapshot(
        self, record: GameweekSnapshotRecord
    ) -> GameweekSnapshotModel:
        statement = select(GameweekSnapshotModel).where(
            GameweekSnapshotModel.season == record.season,
            GameweekSnapshotModel.gameweek == record.gameweek,
            GameweekSnapshotModel.player_id == record.player_id,
        )
        entity = self.session.scalar(statement)
        values = asdict(record)
        if entity is None:
            entity = GameweekSnapshotModel(**values)
            self.session.add(entity)
        else:
            _assign(entity, values)
        self.session.flush()
        return entity

    def upsert_gameweek_history(
        self, record: GameweekHistoryRecord
    ) -> GameweekHistoryModel:
        identity = (record.player_id, record.season, record.gameweek, record.fixture_id)
        return self._upsert(GameweekHistoryModel, identity, asdict(record))

    def upsert_player_history_sync(
        self, record: PlayerHistorySyncRecord
    ) -> PlayerHistorySyncModel:
        return self._upsert(PlayerHistorySyncModel, record.player_id, asdict(record))

    def upsert_historical_player_season(
        self, record: HistoricalPlayerSeasonRecord
    ) -> HistoricalPlayerSeasonModel:
        statement = select(HistoricalPlayerSeasonModel).where(
            HistoricalPlayerSeasonModel.source == record.source,
            HistoricalPlayerSeasonModel.season == record.season,
            HistoricalPlayerSeasonModel.source_player_key == record.source_player_key,
        )
        entity = self.session.scalar(statement)
        values = asdict(record)
        values["position"] = record.position.value
        if entity is None:
            entity = HistoricalPlayerSeasonModel(**values)
            self.session.add(entity)
        else:
            _assign(entity, values)
        self.session.flush()
        return entity

    def upsert_historical_identity_mapping(
        self, record: HistoricalIdentityMappingRecord
    ) -> HistoricalIdentityMappingModel:
        return self._upsert(
            HistoricalIdentityMappingModel,
            record.historical_player_id,
            asdict(record),
        )

    def upsert_player_historical_score(
        self, record: PlayerHistoricalScoreRecord
    ) -> PlayerHistoricalScoreModel:
        return self._upsert(PlayerHistoricalScoreModel, record.player_id, asdict(record))

    def clear_player_historical_scores(self) -> None:
        self.session.execute(delete(PlayerHistoricalScoreModel))
        self.session.flush()

    def upsert_recommendation(
        self, record: RecommendationScoreRecord
    ) -> RecommendationScoreModel:
        identity = (
            record.player_id,
            record.gameweek,
            record.horizon,
            record.model_version,
        )
        return self._upsert(RecommendationScoreModel, identity, asdict(record))

    def get_player(self, player_id: int) -> Optional[PlayerModel]:
        return self.session.get(PlayerModel, player_id)

    def get_team(self, team_id: int) -> Optional[TeamModel]:
        return self.session.get(TeamModel, team_id)

    def get_player_history_sync(self, player_id: int) -> Optional[PlayerHistorySyncModel]:
        return self.session.get(PlayerHistorySyncModel, player_id)

    def get_latest_current_stats(
        self, player_id: int
    ) -> Optional[CurrentPlayerStatsModel]:
        statement = (
            select(CurrentPlayerStatsModel)
            .where(CurrentPlayerStatsModel.player_id == player_id)
            .order_by(CurrentPlayerStatsModel.gameweek.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def list_gameweek_history(self, player_id: int) -> List[GameweekHistoryModel]:
        statement = (
            select(GameweekHistoryModel)
            .where(GameweekHistoryModel.player_id == player_id)
            .order_by(GameweekHistoryModel.gameweek, GameweekHistoryModel.fixture_id)
        )
        return list(self.session.scalars(statement))

    def list_players(self, position: Optional[str] = None) -> List[PlayerModel]:
        statement = select(PlayerModel)
        if position is not None:
            statement = statement.where(PlayerModel.position == position)
        statement = statement.order_by(PlayerModel.web_name)
        return list(self.session.scalars(statement))

    def list_historical_player_seasons(self) -> List[HistoricalPlayerSeasonModel]:
        return list(
            self.session.scalars(
                select(HistoricalPlayerSeasonModel).order_by(
                    HistoricalPlayerSeasonModel.season,
                    HistoricalPlayerSeasonModel.display_name,
                )
            )
        )

    def list_matched_historical_seasons(
        self,
    ) -> List[Tuple[HistoricalPlayerSeasonModel, HistoricalIdentityMappingModel]]:
        statement = (
            select(HistoricalPlayerSeasonModel, HistoricalIdentityMappingModel)
            .join(
                HistoricalIdentityMappingModel,
                HistoricalIdentityMappingModel.historical_player_id
                == HistoricalPlayerSeasonModel.historical_player_id,
            )
            .where(HistoricalIdentityMappingModel.status == "MATCHED")
        )
        return list(self.session.execute(statement).all())

    def list_historical_identity_mappings(
        self, status: str, limit: int = 20
    ) -> List[
        Tuple[
            HistoricalPlayerSeasonModel,
            HistoricalIdentityMappingModel,
            Optional[PlayerModel],
        ]
    ]:
        statement = (
            select(
                HistoricalPlayerSeasonModel,
                HistoricalIdentityMappingModel,
                PlayerModel,
            )
            .join(
                HistoricalIdentityMappingModel,
                HistoricalIdentityMappingModel.historical_player_id
                == HistoricalPlayerSeasonModel.historical_player_id,
            )
            .outerjoin(
                PlayerModel,
                PlayerModel.player_id == HistoricalIdentityMappingModel.current_player_id,
            )
            .where(HistoricalIdentityMappingModel.status == status)
            .order_by(
                HistoricalIdentityMappingModel.match_score.desc(),
                HistoricalPlayerSeasonModel.season.desc(),
            )
            .limit(limit)
        )
        return list(self.session.execute(statement).all())

    def get_player_historical_scores(self) -> Dict[int, PlayerHistoricalScoreModel]:
        return {
            score.player_id: score
            for score in self.session.scalars(select(PlayerHistoricalScoreModel))
        }

    def list_backtest_player_gameweeks(
        self, season: str
    ) -> List[BacktestPlayerGameweekModel]:
        statement = (
            select(BacktestPlayerGameweekModel)
            .where(BacktestPlayerGameweekModel.season == season)
            .order_by(
                BacktestPlayerGameweekModel.gameweek,
                BacktestPlayerGameweekModel.player_id,
                BacktestPlayerGameweekModel.fixture_id,
            )
        )
        return list(self.session.scalars(statement))

    def list_backtest_fixtures(self, season: str) -> List[BacktestFixtureModel]:
        statement = (
            select(BacktestFixtureModel)
            .where(BacktestFixtureModel.season == season)
            .order_by(BacktestFixtureModel.gameweek, BacktestFixtureModel.fixture_id)
        )
        return list(self.session.scalars(statement))

    def list_backtest_runs(self, season: Optional[str] = None) -> List[BacktestRunModel]:
        statement = select(BacktestRunModel)
        if season is not None:
            statement = statement.where(BacktestRunModel.season == season)
        return list(
            self.session.scalars(
                statement.order_by(
                    BacktestRunModel.season.desc(),
                    BacktestRunModel.horizon,
                    BacktestRunModel.model_version,
                )
            )
        )

    def list_backtest_predictions(
        self,
        season: str,
        horizon: int,
        model_version: str,
        as_of_gameweek: Optional[int] = None,
    ) -> List[BacktestPredictionModel]:
        statement = select(BacktestPredictionModel).where(
            BacktestPredictionModel.season == season,
            BacktestPredictionModel.horizon == horizon,
            BacktestPredictionModel.model_version == model_version,
        )
        if as_of_gameweek is not None:
            statement = statement.where(
                BacktestPredictionModel.as_of_gameweek == as_of_gameweek
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    BacktestPredictionModel.as_of_gameweek,
                    BacktestPredictionModel.predicted_rank,
                )
            )
        )

    def clear_backtest_results(
        self, season: str, horizon: int, model_version: str
    ) -> None:
        self.session.execute(
            delete(BacktestPredictionModel).where(
                BacktestPredictionModel.season == season,
                BacktestPredictionModel.horizon == horizon,
                BacktestPredictionModel.model_version == model_version,
            )
        )
        self.session.execute(
            delete(BacktestRunModel).where(
                BacktestRunModel.season == season,
                BacktestRunModel.horizon == horizon,
                BacktestRunModel.model_version == model_version,
            )
        )
        self.session.flush()

    def historical_mapping_counts(self) -> Dict[str, int]:
        rows = self.session.execute(
            select(
                HistoricalIdentityMappingModel.status,
                func.count(HistoricalIdentityMappingModel.historical_player_id),
            ).group_by(HistoricalIdentityMappingModel.status)
        ).all()
        return {status: int(count) for status, count in rows}

    def historical_season_count(self) -> int:
        return int(
            self.session.scalar(
                select(func.count(func.distinct(HistoricalPlayerSeasonModel.season)))
            )
            or 0
        )

    def recommendation_score_count(self, model_version: Optional[str] = None) -> int:
        statement = select(func.count()).select_from(RecommendationScoreModel)
        if model_version is not None:
            statement = statement.where(
                RecommendationScoreModel.model_version == model_version
            )
        return int(self.session.scalar(statement) or 0)

    def list_players_with_latest_stats(
        self,
    ) -> List[Tuple[PlayerModel, CurrentPlayerStatsModel, TeamModel]]:
        latest_gameweek = (
            select(
                CurrentPlayerStatsModel.player_id.label("player_id"),
                func.max(CurrentPlayerStatsModel.gameweek).label("gameweek"),
            )
            .group_by(CurrentPlayerStatsModel.player_id)
            .subquery()
        )
        statement = (
            select(PlayerModel, CurrentPlayerStatsModel, TeamModel)
            .join(
                latest_gameweek,
                latest_gameweek.c.player_id == PlayerModel.player_id,
            )
            .join(
                CurrentPlayerStatsModel,
                (CurrentPlayerStatsModel.player_id == latest_gameweek.c.player_id)
                & (CurrentPlayerStatsModel.gameweek == latest_gameweek.c.gameweek),
            )
            .join(TeamModel, TeamModel.team_id == PlayerModel.team_id)
            .order_by(PlayerModel.position, PlayerModel.web_name)
        )
        return list(self.session.execute(statement).all())

    def list_teams(self) -> List[TeamModel]:
        return list(self.session.scalars(select(TeamModel).order_by(TeamModel.name)))

    def list_fixtures(self) -> List[FixtureModel]:
        return list(
            self.session.scalars(
                select(FixtureModel).order_by(
                    FixtureModel.gameweek,
                    FixtureModel.kickoff_time,
                    FixtureModel.fixture_id,
                )
            )
        )

    def list_upcoming_fixtures(self, start_gameweek: Optional[int] = None) -> List[FixtureModel]:
        statement = select(FixtureModel).where(
            FixtureModel.finished.is_(False), FixtureModel.started.is_(False)
        )
        if start_gameweek is not None:
            statement = statement.where(
                (FixtureModel.gameweek.is_(None)) | (FixtureModel.gameweek >= start_gameweek)
            )
        return list(
            self.session.scalars(
                statement.order_by(FixtureModel.gameweek, FixtureModel.kickoff_time, FixtureModel.fixture_id)
            )
        )

    def count(self, model: Type[ModelType]) -> int:
        return int(self.session.scalar(select(func.count()).select_from(model)) or 0)
