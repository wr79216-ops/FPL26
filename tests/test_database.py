from datetime import datetime, timezone

import pytest

from src.database.connection import Database
from src.database.models import (
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

    assert status.schema_version == 7
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

    assert database.initialize().schema_version == 7
    with database.session() as session:
        snapshots = session.query(GameweekSnapshotModel).all()
        assert len(snapshots) == 1
        assert snapshots[0].season == "2026-27"
        assert snapshots[0].player_id == 10


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
