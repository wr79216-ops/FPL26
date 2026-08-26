from types import SimpleNamespace

import pytest

from src.features.positional_signals import (
    build_positional_signal_profile,
    normalize_positional_signal_profiles,
)


def _stats(**overrides):
    values = {
        "minutes": 180,
        "starts": 2,
        "goals": 1,
        "assists": 1,
        "clean_sheets": 1,
        "saves": 6,
        "bonus": 3,
        "bps": 50,
        "influence": 35.0,
        "creativity": 22.0,
        "threat": 28.0,
        "ict_index": 8.5,
        "expected_goals": 1.0,
        "expected_assists": 0.5,
        "expected_goal_involvements": 1.5,
        "expected_goals_conceded": 1.0,
        "goals_conceded": 1,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "defensive_contribution": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_gk_profile_calculates_position_relevant_rates_and_directions() -> None:
    profile = build_positional_signal_profile(
        player_id=1,
        position="GK",
        stats=_stats(expected_goals_conceded=0.8, saves=8, goals_conceded=1),
        minimum_minutes=180,
    )

    assert profile.confidence == 1.0
    assert profile.signal("xgc_per_90").raw_value == 0.4
    assert profile.signal("xgc_per_90").direction == "lower_is_better"
    assert profile.signal("saves_per_90").raw_value == 4.0
    assert profile.signal("saves_per_90").used_in_ranking
    assert profile.signal("clean_sheet_rate").raw_value == 0.5


def test_normalization_is_position_relative_and_inverts_lower_is_better_signals() -> None:
    stronger_xgc = build_positional_signal_profile(
        1, "GK", _stats(expected_goals_conceded=0.6, saves=8), minimum_minutes=180
    )
    weaker_xgc = build_positional_signal_profile(
        2, "GK", _stats(expected_goals_conceded=2.4, saves=2), minimum_minutes=180
    )
    forward = build_positional_signal_profile(
        3, "FWD", _stats(expected_goals_conceded=9.0), minimum_minutes=180
    )

    normalized = normalize_positional_signal_profiles((stronger_xgc, weaker_xgc, forward))

    assert normalized[0].signal("xgc_per_90").normalized_score == 100.0
    assert normalized[1].signal("xgc_per_90").normalized_score == 0.0
    assert normalized[0].signal("saves_per_90").normalized_score == 100.0
    assert normalized[1].signal("saves_per_90").normalized_score == 0.0


def test_forward_conversion_rate_is_smoothed_when_xg_is_zero() -> None:
    profile = build_positional_signal_profile(
        1,
        "FWD",
        _stats(minutes=90, starts=1, goals=1, expected_goals=0.0),
        minimum_minutes=90,
    )

    assert profile.signal("conversion_rate").raw_value == pytest.approx(1.45 / 3, abs=0.0001)
    assert profile.signal("xg_per_90").raw_value == 0.0


def test_small_samples_shrink_percentile_scores_toward_neutral() -> None:
    low_minutes = build_positional_signal_profile(
        1, "GK", _stats(minutes=90, starts=1, expected_goals_conceded=0.3), minimum_minutes=270
    )
    established = build_positional_signal_profile(
        2, "GK", _stats(minutes=270, starts=3, expected_goals_conceded=2.7), minimum_minutes=270
    )

    normalized = normalize_positional_signal_profiles((low_minutes, established))

    assert normalized[0].signal("xgc_per_90").normalized_score == 66.67
    assert normalized[1].signal("xgc_per_90").normalized_score == 0.0


def test_missing_and_zero_minute_signals_stay_unavailable_not_artificially_positive() -> None:
    profile = build_positional_signal_profile(
        1,
        "DEF",
        _stats(
            minutes=0,
            starts=0,
            expected_goals_conceded=None,
            goals_conceded=None,
            defensive_contribution=None,
        ),
    )
    normalized = normalize_positional_signal_profiles((profile,))[0]

    assert profile.signal("xgc_per_90").raw_value is None
    assert profile.signal("clean_sheet_rate").raw_value is None
    assert profile.signal("defensive_contribution_per_90").raw_value is None
    assert normalized.signal("xgc_per_90").normalized_score is None
    assert normalized.signal("defensive_contribution_per_90").normalized_score is None


def test_red_card_risk_is_weighted_more_heavily_and_never_changes_availability() -> None:
    profile = build_positional_signal_profile(
        1,
        "MID",
        _stats(minutes=90, yellow_cards=1, red_cards=1),
        minimum_minutes=90,
    )

    assert profile.signal("yellow_cards").raw_value == 1.0
    assert profile.signal("red_cards").raw_value == 1.0
    assert profile.signal("discipline_risk_per_90").raw_value == 4.0
