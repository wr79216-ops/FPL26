"""SQLite engine, transactional sessions, and schema-version checks."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Optional

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import DATABASE_PATH
from src.database.models import (
    BacktestFixtureModel,
    BacktestPlayerGameweekModel,
    BacktestPredictionModel,
    BacktestRunModel,
    Base,
    CurrentPlayerStatsModel,
    GameweekSnapshotModel,
    HistoricalIdentityMappingModel,
    HistoricalPlayerSeasonModel,
    PlayerHistoricalScoreModel,
    PlayerHistorySyncModel,
    SchemaMetadataModel,
)
from src.domain.contracts import GameweekSnapshotRecord
from src.utils.season import season_label


SCHEMA_VERSION = 10


class SchemaVersionError(RuntimeError):
    """Raised when a database needs an unsupported schema migration."""


@dataclass(frozen=True)
class DatabaseStatus:
    path: str
    schema_version: int
    tables: List[str]


class Database:
    """Own the SQLAlchemy engine and provide transaction-scoped sessions."""

    def __init__(
        self,
        path: Path = DATABASE_PATH,
        database_url: Optional[str] = None,
    ) -> None:
        self.path = Path(path)
        if database_url is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite+pysqlite:///{self.path}"
        self.engine = create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
        self._enable_sqlite_foreign_keys(self.engine)
        self._session_factory = sessionmaker(
            bind=self.engine, class_=Session, expire_on_commit=False, future=True
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    def initialize(self) -> DatabaseStatus:
        Base.metadata.create_all(self.engine)
        with self.session() as session:
            metadata = session.get(SchemaMetadataModel, 1)
            if metadata is None:
                session.add(SchemaMetadataModel(metadata_id=1, version=SCHEMA_VERSION))
            elif metadata.version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"Database schema is v{metadata.version}; application supports up to v{SCHEMA_VERSION}."
                )
            else:
                while metadata.version < SCHEMA_VERSION:
                    self._migrate(session, metadata.version)
                    metadata.version += 1
        return self.status()

    @staticmethod
    def _migrate(session: Session, from_version: int) -> None:
        if from_version == 1:
            GameweekSnapshotModel.__table__.create(bind=session.connection(), checkfirst=True)
            existing = session.query(GameweekSnapshotModel.snapshot_id).first()
            if existing is None:
                for stats in session.query(
                    CurrentPlayerStatsModel.player_id,
                    CurrentPlayerStatsModel.gameweek,
                    CurrentPlayerStatsModel.minutes,
                    CurrentPlayerStatsModel.ict_index,
                    CurrentPlayerStatsModel.expected_goals,
                    CurrentPlayerStatsModel.expected_assists,
                    CurrentPlayerStatsModel.expected_goal_involvements,
                    CurrentPlayerStatsModel.total_points,
                    CurrentPlayerStatsModel.form,
                    CurrentPlayerStatsModel.selected_by_percent,
                    CurrentPlayerStatsModel.price,
                    CurrentPlayerStatsModel.snapshot_at,
                ).all():
                    session.add(
                        GameweekSnapshotModel(
                            **asdict(
                                GameweekSnapshotRecord(
                                    season=season_label(stats.snapshot_at),
                                    gameweek=stats.gameweek,
                                    player_id=stats.player_id,
                                    price=stats.price,
                                    ownership=stats.selected_by_percent,
                                    form=stats.form,
                                    total_points=stats.total_points,
                                    minutes=stats.minutes,
                                    expected_goals=stats.expected_goals,
                                    expected_assists=stats.expected_assists,
                                    expected_goal_involvements=stats.expected_goal_involvements,
                                    ict_index=stats.ict_index,
                                    captured_at=stats.snapshot_at,
                                )
                            )
                        )
                    )
            return
        if from_version == 2:
            PlayerHistorySyncModel.__table__.create(
                bind=session.connection(), checkfirst=True
            )
            return
        if from_version == 3:
            columns = {
                column["name"]
                for column in inspect(session.connection()).get_columns(
                    CurrentPlayerStatsModel.__tablename__
                )
            }
            if "saves" not in columns:
                session.execute(
                    text(
                        "ALTER TABLE player_current_stats "
                        "ADD COLUMN saves INTEGER NOT NULL DEFAULT 0"
                    )
                )
            return
        if from_version == 4:
            HistoricalPlayerSeasonModel.__table__.create(
                bind=session.connection(), checkfirst=True
            )
            HistoricalIdentityMappingModel.__table__.create(
                bind=session.connection(), checkfirst=True
            )
            PlayerHistoricalScoreModel.__table__.create(
                bind=session.connection(), checkfirst=True
            )
            return
        if from_version == 5:
            for model in (
                BacktestPlayerGameweekModel,
                BacktestFixtureModel,
                BacktestPredictionModel,
                BacktestRunModel,
            ):
                model.__table__.create(bind=session.connection(), checkfirst=True)
            return
        if from_version == 6:
            columns = {
                column["name"]
                for column in inspect(session.connection()).get_columns(
                    CurrentPlayerStatsModel.__tablename__
                )
            }
            if "transfers_in_event" not in columns:
                session.execute(
                    text(
                        "ALTER TABLE player_current_stats "
                        "ADD COLUMN transfers_in_event INTEGER NOT NULL DEFAULT 0"
                    )
                )
            return
        if from_version == 7:
            migrations = {
                CurrentPlayerStatsModel.__tablename__: (
                    "goals_conceded",
                    "penalties_saved",
                    "penalties_missed",
                    "yellow_cards",
                    "red_cards",
                    "defensive_contribution",
                ),
                "player_gameweek_history": (
                    "goals_conceded",
                    "penalties_saved",
                    "penalties_missed",
                    "yellow_cards",
                    "red_cards",
                    "defensive_contribution",
                ),
            }
            for table_name, column_names in migrations.items():
                existing_columns = {
                    column["name"]
                    for column in inspect(session.connection()).get_columns(table_name)
                }
                for column_name in column_names:
                    if column_name not in existing_columns:
                        session.execute(
                            text(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {column_name} INTEGER NULL"
                            )
                        )
            return
        if from_version == 8:
            columns = {
                column["name"]
                for column in inspect(session.connection()).get_columns(
                    CurrentPlayerStatsModel.__tablename__
                )
            }
            if "expected_goals_conceded" not in columns:
                session.execute(
                    text(
                        "ALTER TABLE player_current_stats "
                        "ADD COLUMN expected_goals_conceded FLOAT NULL"
                    )
                )
            return
        if from_version == 9:
            field_types = {
                "clean_sheets": "INTEGER",
                "goals_conceded": "INTEGER",
                "penalties_saved": "INTEGER",
                "penalties_missed": "INTEGER",
                "yellow_cards": "INTEGER",
                "red_cards": "INTEGER",
                "defensive_contribution": "INTEGER",
                "expected_goals_conceded": "FLOAT",
                "starts": "INTEGER",
                "bps": "INTEGER",
                "influence": "FLOAT",
                "creativity": "FLOAT",
                "threat": "FLOAT",
            }
            existing_columns = {
                column["name"]
                for column in inspect(session.connection()).get_columns(
                    BacktestPlayerGameweekModel.__tablename__
                )
            }
            for column_name, column_type in field_types.items():
                if column_name not in existing_columns:
                    session.execute(
                        text(
                            "ALTER TABLE backtest_player_gameweeks "
                            f"ADD COLUMN {column_name} {column_type} NULL"
                        )
                    )
            return
        raise SchemaVersionError(
            f"Database schema is v{from_version}; no migration to v{from_version + 1} exists."
        )

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def status(self) -> DatabaseStatus:
        inspector = inspect(self.engine)
        with self.session() as session:
            metadata = session.get(SchemaMetadataModel, 1)
            version = metadata.version if metadata is not None else 0
        return DatabaseStatus(
            path=str(self.path),
            schema_version=version,
            tables=sorted(inspector.get_table_names()),
        )

    def dispose(self) -> None:
        self.engine.dispose()
