from src.services.backtesting import (
    BacktestingService,
    load_positional_candidate_model,
    parse_backtest_fixtures,
    parse_backtest_gameweeks,
    spearman_rank_correlation,
)
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import BacktestFixtureRecord, BacktestPlayerGameweekRecord, Position
from config.settings import load_scoring_config


GAMEWEEK_HEADER = (
    "name,position,team,element,fixture,round,minutes,total_points,goals_scored,"
    "assists,bonus,saves,ict_index,expected_goals,expected_assists,"
    "expected_goal_involvements,selected,value,kickoff_time\n"
)


def test_backtest_gameweek_parser_preserves_prediction_cutoff_fields() -> None:
    source_row = "Martin Ødegaard,MID,Arsenal,10,100,5,90,8,1,0,2,0,8.4,0.5,0.2,0.7,1000000,85,2025-09-01T12:00:00Z\n"
    rows = parse_backtest_gameweeks(
        GAMEWEEK_HEADER + source_row + source_row,
        "2025-26",
    )

    assert len(rows) == 1
    assert rows[0].normalized_name == "martin odegaard"
    assert rows[0].gameweek == 5
    assert rows[0].price == 8.5


def test_backtest_fixture_parser_maps_teams_and_scores() -> None:
    teams = "id,name\n1,Arsenal\n2,Chelsea\n"
    fixtures = (
        "event,id,team_h,team_a,team_h_difficulty,team_a_difficulty,"
        "team_h_score,team_a_score,kickoff_time\n"
        "5,100,1,2,3,4,2,1,2025-09-01T12:00:00Z\n"
    )

    rows = parse_backtest_fixtures(fixtures, teams, "2025-26")

    assert len(rows) == 1
    assert rows[0].home_team == "Arsenal"
    assert rows[0].away_team == "Chelsea"
    assert rows[0].home_score == 2


def test_spearman_rank_correlation_handles_direction_and_ties() -> None:
    assert spearman_rank_correlation([1, 2, 3], [10, 20, 30]) == 1.0
    assert spearman_rank_correlation([1, 2, 3], [30, 20, 10]) == -1.0
    assert spearman_rank_correlation([1, 1, 1], [10, 20, 30]) == 0.0


def test_backtest_parser_preserves_optional_positional_candidate_fields() -> None:
    header = GAMEWEEK_HEADER.strip() + (
        ",clean_sheets,goals_conceded,penalties_saved,penalties_missed,"
        "yellow_cards,red_cards,defensive_contribution,expected_goals_conceded,"
        "starts,bps,influence,creativity,threat\n"
    )
    row = (
        "Goalkeeper,GK,Arsenal,1,10,4,90,6,0,0,1,3,4,0.2,0.1,0.3,100,50,"
        "2025-09-01T12:00:00Z,1,1,0,0,1,0,9,0.8,1,22,13.4,4.1,0.2\n"
    )

    parsed = parse_backtest_gameweeks(header + row, "2025-26")[0]

    assert parsed.clean_sheets == 1
    assert parsed.expected_goals_conceded == 0.8
    assert parsed.defensive_contribution == 9
    assert parsed.starts == 1
    assert parsed.threat == 0.2


def test_positional_candidate_config_and_missing_feature_coverage_fail_closed() -> None:
    version, production, weights, policy = load_positional_candidate_model()

    assert version == "candidate-v1.3-positional"
    assert production == "v1.1"
    assert weights["DEF"]["defensive_contribution_per_90"] == 0.08
    assert policy.minimum_feature_coverage == 0.98

    row = type(
        "BacktestRow",
        (),
        {
            "position": "DEF",
            "minutes": 90,
            "expected_goals_conceded": 0.5,
            "clean_sheets": 1,
            "starts": 1,
            "expected_goal_involvements": 0.1,
            "defensive_contribution": None,
            "bonus": 1,
            "yellow_cards": 0,
            "red_cards": 0,
        },
    )()
    coverage = BacktestingService._candidate_feature_coverage((row,))

    assert coverage["DEF"][0] == 0.0
    assert coverage["DEF"][1] == ("defensive_contribution",)


def test_positional_candidate_runs_from_historical_cutoff_data(tmp_path) -> None:
    database = Database(tmp_path / "backtest.db")
    database.initialize()
    gameweeks = []
    fixtures = []
    for gameweek in range(1, 6):
        fixtures.append(
            BacktestFixtureRecord(
                season="2025-26", fixture_id=gameweek, gameweek=gameweek,
                home_team="Alpha", away_team="Beta", home_difficulty=3,
                away_difficulty=3, home_score=1, away_score=0, kickoff_time=None,
            )
        )
        for player_id, team, points, xg in (
            (1, "Alpha", gameweek + 1, 0.4),
            (2, "Beta", gameweek, 0.2),
        ):
            gameweeks.append(
                BacktestPlayerGameweekRecord(
                    season="2025-26", player_id=player_id, fixture_id=gameweek,
                    gameweek=gameweek, player_name=f"Player {player_id}",
                    normalized_name=f"player {player_id}", position=Position.MID,
                    team=team, minutes=90, total_points=points, goals=1, assists=0,
                    bonus=1, saves=0, ict_index=4.0, expected_goals=xg,
                    expected_assists=0.1, expected_goal_involvements=xg + 0.1,
                    selected=100, price=7.0, kickoff_time=None, clean_sheets=1,
                    goals_conceded=0, penalties_saved=0, penalties_missed=0,
                    yellow_cards=0, red_cards=0, defensive_contribution=4,
                    expected_goals_conceded=0.5, starts=1, bps=20,
                    influence=10.0, creativity=5.0, threat=8.0,
                )
            )
    with database.session() as session:
        repository = FPLRepository(session)
        repository.bulk_upsert_backtest_player_gameweeks(gameweeks)
        repository.bulk_upsert_backtest_fixtures(fixtures)

    service = BacktestingService(database=database, client=None)
    candidate_version, _, candidate_weights, _ = load_positional_candidate_model()
    service.run_model("2025-26", 1, "production-v1.1", load_scoring_config().position_weights)
    service.run_model("2025-26", 1, candidate_version, candidate_weights)
    report = service.get_positional_candidate_validation_report(horizon=1)
    mid = next(item for item in report.evaluations if item.position == "MID")

    assert mid.baseline is not None
    assert mid.candidate is not None
    assert mid.feature_coverage == 1.0
    assert report.production_active is False
