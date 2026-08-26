from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, text

from src.database.connection import SCHEMA_VERSION, Database
from src.database.models import (
    BacktestPlayerGameweekModel,
    CurrentPlayerStatsModel,
    GameweekSnapshotModel,
    HistoricalIdentityMappingModel,
    HistoricalPlayerSeasonModel,
    PlayerModel,
    PlayerHistoricalScoreModel,
    RecommendationScoreModel,
    SchemaMetadataModel,
    TeamModel,
)
from src.database.repository import FPLRepository
from src.domain.contracts import (
    FixtureRecord,
    PlayerRecord,
    Position,
    RecommendationScoreRecord,
    TeamRecord,
)


def team(team_id: int, name: str, short_name: str) -> TeamRecord:
    return TeamRecord(
        team_id=team_id,
        name=name,
        short_name=short_name,
        strength=4,
        strength_overall_home=4,
        strength_overall_away=4,
        strength_attack_home=4,
        strength_attack_away=4,
        strength_defence_home=4,
        strength_defence_away=4,
    )


def player(price: float = 7.0) -> PlayerRecord:
    return PlayerRecord(
        player_id=10,
        first_name="Test",
        second_name="Player",
        web_name="Test Player",
        team_id=1,
        position_id=3,
        position=Position.MID,
        status="a",
        news="",
        price=price,
        ownership=8.5,
    )


def recommendation(final_score: float) -> RecommendationScoreRecord:
    return RecommendationScoreRecord(
        player_id=10,
        gameweek=8,
        horizon=5,
        form_score=80,
        fixture_score=85,
        expected_score=88,
        minutes_score=92,
        history_score=70,
        value_score=89,
        bonus_score=65,
        ownership_score=75,
        final_score=final_score,
        model_version="v1.0",
        calculated_at=datetime.now(timezone.utc),
    )


def test_database_initializes_expected_baseline_schema(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    status = database.initialize()

    assert status.schema_version == SCHEMA_VERSION
    assert set(status.tables) == {
        "fixtures",
        "backtest_fixtures",
        "backtest_player_gameweeks",
        "backtest_predictions",
        "backtest_runs",
        "gameweek_snapshots",
        "historical_identity_mappings",
        "historical_player_seasons",
        "player_current_stats",
        "player_gameweek_history",
        "player_historical_scores",
        "player_history_sync",
        "players",
        "recommendation_scores",
        "schema_metadata",
        "teams",
    }


def test_v1_database_migrates_and_backfills_current_stats_snapshot(tmp_path) -> None:
    database = Database(tmp_path / "v1.db")
    for table in (
        SchemaMetadataModel.__table__,
        TeamModel.__table__,
        PlayerModel.__table__,
        CurrentPlayerStatsModel.__table__,
    ):
        table.create(database.engine)

    captured_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    with database.session() as session:
        session.add(SchemaMetadataModel(metadata_id=1, version=1))
        session.add(
            TeamModel(
                team_id=1,
                name="Alpha FC",
                short_name="ALP",
                strength=4,
                strength_overall_home=4,
                strength_overall_away=4,
                strength_attack_home=4,
                strength_attack_away=4,
                strength_defence_home=4,
                strength_defence_away=4,
            )
        )
        session.flush()
        session.add(
            PlayerModel(
                player_id=10,
                first_name="Test",
                second_name="Player",
                web_name="Test Player",
                team_id=1,
                position_id=3,
                position="MID",
                status="a",
                news="",
                price=7.0,
                ownership=8.5,
            )
        )
        session.flush()
        session.add(
            CurrentPlayerStatsModel(
                player_id=10,
                gameweek=1,
                minutes=90,
                starts=1,
                goals=1,
                assists=0,
                clean_sheets=0,
                bonus=0,
                bps=20,
                influence=12.0,
                creativity=6.0,
                threat=9.0,
                ict_index=2.7,
                expected_goals=0.4,
                expected_assists=0.1,
                expected_goal_involvements=0.5,
                total_points=8,
                points_per_game=8.0,
                form=8.0,
                selected_by_percent=8.5,
                price=7.0,
                snapshot_at=captured_at,
            )
        )

    assert database.initialize().schema_version == SCHEMA_VERSION
    with database.session() as session:
        snapshots = session.query(GameweekSnapshotModel).all()
        assert len(snapshots) == 1
        assert snapshots[0].season == "2026-27"
        assert snapshots[0].player_id == 10


def test_v7_database_migrates_optional_signal_columns(tmp_path) -> None:
    database = Database(tmp_path / "v7.db")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_metadata ("
                "metadata_id INTEGER PRIMARY KEY, version INTEGER NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE player_current_stats ("
                "player_id INTEGER NOT NULL, gameweek INTEGER NOT NULL, "
                "PRIMARY KEY (player_id, gameweek))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE player_gameweek_history ("
                "player_id INTEGER NOT NULL, season VARCHAR(9) NOT NULL, "
                "gameweek INTEGER NOT NULL, fixture_id INTEGER NOT NULL, "
                "PRIMARY KEY (player_id, season, gameweek, fixture_id))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_metadata(metadata_id, version, updated_at) "
                "VALUES (1, 7, '2026-08-26T00:00:00')"
            )
        )

    assert database.initialize().schema_version == SCHEMA_VERSION
    current_columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("player_current_stats")
    }
    history_columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("player_gameweek_history")
    }
    expected = {
        "goals_conceded",
        "penalties_saved",
        "penalties_missed",
        "yellow_cards",
        "red_cards",
        "defensive_contribution",
    }
    assert expected <= current_columns
    assert expected <= history_columns


def test_v8_database_migrates_current_xgc_column(tmp_path) -> None:
    database = Database(tmp_path / "v8.db")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_metadata ("
                "metadata_id INTEGER PRIMARY KEY, version INTEGER NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE player_current_stats ("
                "player_id INTEGER NOT NULL, gameweek INTEGER NOT NULL, "
                "PRIMARY KEY (player_id, gameweek))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_metadata(metadata_id, version, updated_at) "
                "VALUES (1, 8, '2026-08-26T00:00:00')"
            )
        )

    assert database.initialize().schema_version == SCHEMA_VERSION
    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("player_current_stats")
    }
    assert "expected_goals_conceded" in columns


def test_v9_database_migrates_historical_positional_candidate_columns(tmp_path) -> None:
    database = Database(tmp_path / "v9.db")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_metadata ("
                "metadata_id INTEGER PRIMARY KEY, version INTEGER NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE backtest_player_gameweeks ("
                "season VARCHAR(9) NOT NULL, player_id INTEGER NOT NULL, "
                "fixture_id INTEGER NOT NULL, PRIMARY KEY (season, player_id, fixture_id))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_metadata(metadata_id, version, updated_at) "
                "VALUES (1, 9, '2026-08-26T00:00:00')"
            )
        )

    assert database.initialize().schema_version == SCHEMA_VERSION
    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns(
            BacktestPlayerGameweekModel.__tablename__
        )
    }
    assert {
        "clean_sheets",
        "expected_goals_conceded",
        "defensive_contribution",
        "penalties_missed",
        "starts",
        "bps",
        "influence",
        "creativity",
        "threat",
    } <= columns


def test_repository_upserts_are_idempotent(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    with database.session() as session:
        repository = FPLRepository(session)
        repository.upsert_team(team(1, "Alpha FC", "ALP"))
        repository.upsert_team(team(2, "Beta FC", "BET"))
        repository.upsert_player(player(price=7.0))
        repository.upsert_player(player(price=7.2))
        repository.upsert_fixture(
            FixtureRecord(
                fixture_id=100,
                gameweek=8,
                home_team_id=1,
                away_team_id=2,
                kickoff_time=None,
                home_difficulty=2,
                away_difficulty=4,
                home_score=None,
                away_score=None,
                finished=False,
                started=False,
            )
        )
        repository.upsert_recommendation(recommendation(86))
        repository.upsert_recommendation(recommendation(91))

    with database.session() as session:
        repository = FPLRepository(session)
        stored_player = repository.get_player(10)
        assert stored_player is not None
        assert stored_player.price == 7.2
        assert repository.count(PlayerModel) == 1
        assert repository.count(RecommendationScoreModel) == 1
        stored_score = session.get(RecommendationScoreModel, (10, 8, 5, "v1.0"))
        assert stored_score is not None
        assert stored_score.final_score == 91


def test_database_session_rolls_back_on_error(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    with pytest.raises(RuntimeError):
        with database.session() as session:
            FPLRepository(session).upsert_team(team(1, "Alpha FC", "ALP"))
            raise RuntimeError("force rollback")

    with database.session() as session:
        assert FPLRepository(session).count(TeamModel) == 0


def test_domain_contracts_reject_invalid_fixture() -> None:
    with pytest.raises(ValueError, match="must be different"):
        FixtureRecord(
            fixture_id=1,
            gameweek=1,
            home_team_id=2,
            away_team_id=2,
            kickoff_time=None,
            home_difficulty=2,
            away_difficulty=2,
            home_score=None,
            away_score=None,
            finished=False,
            started=False,
        )
