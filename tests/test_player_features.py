from types import SimpleNamespace

from src.features.player import calculate_player_features


PENALTIES = {
    "available": 1.0,
    "doubtful": 0.8,
    "injured": 0.2,
    "suspended": 0.1,
    "unavailable": 0.0,
}


def _history(gameweek, fixture_id, minutes, points, xg, xa, xgi, bonus=0):
    return SimpleNamespace(
        gameweek=gameweek,
        fixture_id=fixture_id,
        minutes=minutes,
        total_points=points,
        xg=xg,
        xa=xa,
        xgi=xgi,
        bonus=bonus,
    )


def test_player_features_calculate_rolling_per90_value_and_confidence() -> None:
    history = [
        _history(1, 101, 90, 6, 0.5, 0.1, 0.6, 2),
        _history(2, 102, 30, 2, 0.2, 0.3, 0.5),
        _history(3, 103, 0, 0, 0.0, 0.0, 0.0),
    ]

    features = calculate_player_features(history, 8.0, "a", PENALTIES)

    assert features.form_3 == 2.67
    assert features.points_per_match == 4.0
    assert features.xg_per_90 == 0.52
    assert features.xa_per_90 == 0.3
    assert features.xgi_per_90 == 0.83
    assert features.value == 0.5
    assert features.minutes_security == 44.44
    assert features.confidence == 0.44
    assert features.confidence_adjusted_xgi_per_90 == 0.37
    assert not features.enough_minutes


def test_availability_penalty_reduces_minutes_and_adjusted_output() -> None:
    history = [_history(1, 101, 90, 6, 0.5, 0.1, 0.6)] * 3

    available = calculate_player_features(history, 8.0, "a", PENALTIES)
    injured = calculate_player_features(history, 8.0, "i", PENALTIES)

    assert available.enough_minutes
    assert available.minutes_security == 100.0
    assert injured.availability_penalty == 0.2
    assert injured.minutes_security == 20.0
    assert injured.confidence_adjusted_xgi_per_90 < available.confidence_adjusted_xgi_per_90
