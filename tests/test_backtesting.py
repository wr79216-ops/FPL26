from src.services.backtesting import (
    parse_backtest_fixtures,
    parse_backtest_gameweeks,
    spearman_rank_correlation,
)


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
