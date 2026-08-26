from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.services.schedule_backtesting import (
    HistoricalScheduleForecast,
    ScheduleAdjustmentComparison,
    ScheduleAdjustmentPolicy,
    brier_score,
    compare_schedule_adjusted_rankings,
    eligible_historical_forecasts,
    reconstruct_historical_schedule_outcomes,
    reliability_buckets,
    validate_schedule_adjustment,
)


@dataclass(frozen=True)
class _Fixture:
    season: str
    fixture_id: int
    gameweek: int
    home_team: str
    away_team: str
    kickoff_time: datetime


@dataclass(frozen=True)
class _Prediction:
    season: str
    as_of_gameweek: int
    horizon: int
    model_version: str
    player_id: int
    recommendation_score: float
    actual_points: int


@dataclass(frozen=True)
class _PlayerGameweek:
    season: str
    player_id: int
    fixture_id: int
    gameweek: int
    team: str


def _fixture(fixture_id: int, gameweek: int, home: str, away: str, day: int) -> _Fixture:
    return _Fixture(
        "2025-26", fixture_id, gameweek, home, away,
        datetime(2025, 8, day, 12, tzinfo=timezone.utc),
    )


def _forecast(
    team: str,
    target: int,
    blank: float,
    double: float,
    as_of: datetime = datetime(2025, 8, 10, tzinfo=timezone.utc),
) -> HistoricalScheduleForecast:
    return HistoricalScheduleForecast(
        "2025-26", 1, target, team, blank, double, 50.0,
        "https://example.test/snapshot", as_of,
        as_of + timedelta(days=7), "medium",
    )


def _policy() -> ScheduleAdjustmentPolicy:
    return ScheduleAdjustmentPolicy(
        "schedule-test", 8.0, 8.0, 3.0, 2, 0.05, 0.05, 0.15,
        0.0, 0.0, True,
    )


def test_historical_outcome_reconstruction_detects_final_blank_and_double() -> None:
    fixtures = (
        _fixture(1, 1, "A", "B", 9),
        _fixture(2, 2, "C", "D", 20),
        _fixture(3, 3, "A", "C", 25),
        _fixture(4, 3, "D", "A", 27),
    )
    outcomes = reconstruct_historical_schedule_outcomes(fixtures)
    by_team_gw = {(item.team, item.gameweek): item for item in outcomes}

    assert by_team_gw[("A", 2)].blank == 1
    assert by_team_gw[("A", 2)].fixture_count == 0
    assert by_team_gw[("A", 3)].double == 1
    assert by_team_gw[("A", 3)].fixture_count == 2


def test_forecast_after_target_kickoff_is_rejected_as_leakage() -> None:
    fixtures = (_fixture(1, 1, "A", "B", 9), _fixture(2, 2, "C", "D", 20))
    outcomes = reconstruct_historical_schedule_outcomes(fixtures)
    leaked = _forecast(
        "A", 2, 0.9, 0.1,
        as_of=datetime(2025, 8, 21, tzinfo=timezone.utc),
    )
    assert eligible_historical_forecasts((leaked,), fixtures, outcomes) == ()


def test_brier_reliability_and_validation_gate_are_deterministic() -> None:
    fixtures = (
        _fixture(1, 1, "A", "B", 9),
        _fixture(2, 2, "C", "D", 20),
        _fixture(3, 3, "A", "C", 25),
        _fixture(4, 3, "D", "A", 27),
    )
    outcomes = reconstruct_historical_schedule_outcomes(fixtures)
    forecasts = (_forecast("A", 2, 0.9, 0.1), _forecast("A", 3, 0.1, 0.9))
    comparison = ScheduleAdjustmentComparison(3, 5.0, 5.2, 0.2, 0.3, 0.31, 0.01)

    assert brier_score([0.9, 0.1], [1, 0]) == pytest.approx(0.01)
    assert sum(item.observations for item in reliability_buckets([0.9, 0.1], [1, 0])) == 2
    report = validate_schedule_adjustment(
        _policy(), outcomes, forecasts, fixtures, comparison
    )

    assert report.blank_brier == pytest.approx(0.01)
    assert report.double_brier == pytest.approx(0.01)
    assert report.quantitative_gates_passed is True
    assert report.production_active is True
    assert report.reasons == ()


def test_validation_fails_closed_without_archived_forecasts() -> None:
    fixtures = (_fixture(1, 1, "A", "B", 9),)
    report = validate_schedule_adjustment(
        _policy(), reconstruct_historical_schedule_outcomes(fixtures), (), fixtures
    )

    assert report.production_active is False
    assert report.eligible_observations == 0
    assert any("eligible forecast" in reason for reason in report.reasons)


def test_ranking_comparison_uses_same_players_and_future_outcomes() -> None:
    predictions = tuple(
        _Prediction(
            "2025-26", 1, 1, "production-v1", player_id,
            101.0 - player_id, 10 if player_id == 11 else 0,
        )
        for player_id in range(1, 12)
    )
    player_rows = tuple(
        _PlayerGameweek("2025-26", player_id, player_id, 1, f"Team {player_id}")
        for player_id in range(1, 12)
    )
    forecasts = tuple(
        _forecast(
            f"Team {player_id}", 2, 0.0, 1.0 if player_id == 11 else 0.0
        )
        for player_id in range(1, 12)
    )

    comparison = compare_schedule_adjusted_rankings(
        predictions, player_rows, forecasts, _policy()
    )

    assert comparison is not None
    assert comparison.evaluated_cutoffs == 1
    assert comparison.top_10_points_lift == pytest.approx(1.0)
