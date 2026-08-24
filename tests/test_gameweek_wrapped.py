from src.services.gameweek_wrapped import build_gameweek_wrapped, previous_completed_gameweek


def _bootstrap():
    return {
        "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Brentford"}],
        "elements": [
            {"id": 1, "web_name": "Raya", "team": 1},
            {"id": 2, "web_name": "Saka", "team": 1},
            {"id": 3, "web_name": "Mbeumo", "team": 2},
        ],
    }


def _live():
    return {
        "elements": [
            {"id": 1, "stats": {"minutes": 90, "total_points": 6, "expected_goals": "0.00", "expected_assists": "0.00", "expected_goals_conceded": "0.40", "goals_scored": 0}},
            {"id": 2, "stats": {"minutes": 90, "total_points": 12, "expected_goals": "0.70", "expected_assists": "0.35", "expected_goals_conceded": "0.40", "goals_scored": 1}},
            {"id": 3, "stats": {"minutes": 90, "total_points": 2, "expected_goals": "1.10", "expected_assists": "0.10", "expected_goals_conceded": "1.20", "goals_scored": 0}},
        ]
    }


def test_previous_completed_gameweek_prefers_official_previous_flag() -> None:
    event = previous_completed_gameweek(
        [{"id": 1, "finished": True}, {"id": 2, "is_previous": True, "finished": True}]
    )

    assert event is not None
    assert event["id"] == 2


def test_gameweek_wrapped_uses_official_player_event_and_chip_data() -> None:
    recap = build_gameweek_wrapped(
        {
            "id": 1,
            "average_entry_score": 49,
            "most_selected": 2,
            "most_transferred_in": 3,
            "chip_plays": [{"chip_name": "bboost", "num_played": 1234}],
        },
        _bootstrap(),
        _live(),
    )

    assert recap is not None
    assert recap.gameweek == 1
    assert recap.average_score == 49
    assert recap.metrics[0].label == "Most selected"
    assert recap.metrics[0].value == "Saka"
    assert recap.metrics[2].value == "Saka"
    assert recap.metrics[4].value == "Brentford"
    assert recap.metrics[8].value == "Mbeumo"
    assert recap.chips[0].name == "Bench Boost"
    assert recap.chips[0].uses == 1234
