from datetime import datetime, timezone

import pytest

from src.domain.contracts import Position
from src.etl.transform import (
    DataTransformError,
    current_gameweek,
    transform_current_player_stats,
    transform_fixtures,
    transform_gameweek_history,
    transform_players,
    transform_teams,
)


ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]

TEAMS = [
    {
        "id": 1,
        "name": "Alpha FC",
        "short_name": "ALP",
        "strength": 4,
        "strength_overall_home": 4,
        "strength_overall_away": 4,
        "strength_attack_home": 4,
        "strength_attack_away": 4,
        "strength_defence_home": 4,
        "strength_defence_away": 4,
    },
    {
        "id": 2,
        "name": "Beta FC",
        "short_name": "BET",
        "strength": 3,
        "strength_overall_home": 3,
        "strength_overall_away": 3,
        "strength_attack_home": 3,
        "strength_attack_away": 3,
        "strength_defence_home": 3,
        "strength_defence_away": 3,
    },
]

ELEMENTS = [
    {
        "id": 10,
        "first_name": "Test",
        "second_name": "Midfielder",
        "web_name": "Test Mid",
        "team": 1,
        "element_type": 3,
        "status": "a",
        "news": "",
        "now_cost": 70,
        "selected_by_percent": "8.5",
        "minutes": 640,
        "starts": 7,
        "goals_scored": 4,
        "assists": 3,
        "clean_sheets": 2,
        "saves": 4,
        "bonus": 9,
        "bps": 160,
        "influence": "221.4",
        "creativity": "190.2",
        "threat": "198.9",
        "ict_index": "61.0",
        "expected_goals": "4.10",
        "expected_assists": "3.40",
        "expected_goal_involvements": "7.50",
        "total_points": 66,
        "points_per_game": "7.3",
        "form": "8.2",
        "transfers_in_event": "12345",
        "goals_conceded": 2,
        "penalties_saved": 1,
        "penalties_missed": 0,
        "yellow_cards": 2,
        "red_cards": 0,
        "defensive_contribution": 37,
    }
]

FIXTURES = [
    {
        "id": 100,
        "event": 8,
        "team_h": 1,
        "team_a": 2,
        "kickoff_time": "2026-08-24T12:30:00Z",
        "team_h_difficulty": 2,
        "team_a_difficulty": 4,
        "team_h_score": None,
        "team_a_score": None,
        "finished": False,
        "started": False,
    }
]


def test_official_shape_transforms_to_contracts() -> None:
    teams = transform_teams(TEAMS)
    players = transform_players(ELEMENTS, ELEMENT_TYPES)
    stats = transform_current_player_stats(
        ELEMENTS,
        gameweek=8,
        snapshot_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    fixtures = transform_fixtures(FIXTURES)

    assert len(teams) == 2
    assert players[0].position is Position.MID
    assert players[0].price == 7.0
    assert players[0].ownership == 8.5
    assert stats[0].expected_goal_involvements == 7.5
    assert stats[0].saves == 4
    assert stats[0].transfers_in_event == 12345
    assert stats[0].goals_conceded == 2
    assert stats[0].penalties_saved == 1
    assert stats[0].defensive_contribution == 37
    assert fixtures[0].kickoff_time == datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)


def test_current_gameweek_prefers_current_then_next_then_latest() -> None:
    assert current_gameweek([{"id": 7}, {"id": 8, "is_next": True}]) == 8
    assert current_gameweek([{"id": 7}, {"id": 8, "is_current": True}]) == 8
    assert current_gameweek([{"id": 7}, {"id": 8}]) == 8


def test_transform_fails_when_position_reference_is_unknown() -> None:
    invalid = [dict(ELEMENTS[0], element_type=99)]

    with pytest.raises(DataTransformError, match="unknown position"):
        transform_players(invalid, ELEMENT_TYPES)


def test_player_summary_history_transforms_official_per_match_fields() -> None:
    history = transform_gameweek_history(
        [
            {
                "round": 8,
                "fixture": 100,
                "opponent_team": 2,
                "was_home": True,
                "minutes": 90,
                "goals_scored": 1,
                "assists": 1,
                "clean_sheets": 0,
                "bonus": 3,
                "bps": 38,
                "expected_goals": "0.61",
                "expected_assists": "0.28",
                "expected_goal_involvements": "0.89",
                "expected_goals_conceded": "1.20",
                "goals_conceded": 2,
                "penalties_saved": 0,
                "penalties_missed": 1,
                "yellow_cards": 1,
                "red_cards": 0,
                "defensive_contribution": 18,
                "total_points": 12,
                "value": 70,
            }
        ],
        player_id=10,
        season="2026-27",
    )

    assert history[0].gameweek == 8
    assert history[0].xgi == 0.89
    assert history[0].value == 7.0
    assert history[0].goals_conceded == 2
    assert history[0].penalties_missed == 1
    assert history[0].defensive_contribution == 18


def test_optional_signal_fields_preserve_unavailable_as_none() -> None:
    missing = dict(ELEMENTS[0])
    for field in (
        "goals_conceded",
        "penalties_saved",
        "penalties_missed",
        "yellow_cards",
        "red_cards",
        "defensive_contribution",
    ):
        missing.pop(field)

    stats = transform_current_player_stats([missing], gameweek=8)[0]
    assert stats.goals_conceded is None
    assert stats.penalties_saved is None
    assert stats.defensive_contribution is None

    history = transform_gameweek_history(
        [
            {
                "round": 8,
                "fixture": 100,
                "opponent_team": 2,
                "was_home": True,
                "minutes": 0,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
                "bonus": 0,
                "bps": 0,
                "expected_goals": "0.00",
                "expected_assists": "0.00",
                "expected_goal_involvements": "0.00",
                "expected_goals_conceded": "0.00",
                "total_points": 0,
                "value": 70,
            }
        ],
        player_id=10,
        season="2026-27",
    )[0]
    assert history.goals_conceded is None
    assert history.red_cards is None
