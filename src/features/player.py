"""Transparent player-level feature engineering from official gameweek history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


STATUS_TO_AVAILABILITY = {
    "a": "available",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "unavailable",
}


@dataclass(frozen=True)
class PlayerFeatureSet:
    sample_fixtures: int
    sample_appearances: int
    sample_minutes: int
    period_start_gameweek: int | None
    period_end_gameweek: int | None
    form_3: float
    form_5: float
    form_10: float
    points_per_match: float
    xg_per_90: float
    xa_per_90: float
    xgi_per_90: float
    bonus_per_match: float
    value: float
    minutes_security: float
    availability_penalty: float
    confidence: float
    confidence_adjusted_form: float
    confidence_adjusted_xgi_per_90: float
    confidence_adjusted_value: float
    enough_minutes: bool


def _round_metric(value: float) -> float:
    return round(value, 2)


def _rolling_form(history: Sequence[Any], window: int) -> float:
    points_by_gameweek: dict[int, int] = {}
    for row in history:
        points_by_gameweek[row.gameweek] = points_by_gameweek.get(row.gameweek, 0) + int(
            row.total_points
        )
    values = [points_by_gameweek[gameweek] for gameweek in sorted(points_by_gameweek)]
    if not values:
        return 0.0
    return _round_metric(sum(values[-window:]) / len(values[-window:]))


def calculate_player_features(
    history: Sequence[Any],
    price: float,
    status: str,
    availability_penalties: Mapping[str, float],
    minimum_minutes: int = 270,
    minutes_security_window: int = 5,
) -> PlayerFeatureSet:
    """Calculate explainable metrics and conservative small-sample adjustments."""
    if price <= 0:
        raise ValueError("price must be positive")
    if minimum_minutes <= 0 or minutes_security_window <= 0:
        raise ValueError("feature-engineering windows must be positive")

    ordered = sorted(history, key=lambda row: (row.gameweek, row.fixture_id))
    appearances = [row for row in ordered if row.minutes > 0]
    total_minutes = sum(int(row.minutes) for row in appearances)
    total_points = sum(int(row.total_points) for row in appearances)
    appearance_count = len(appearances)

    points_per_match = total_points / appearance_count if appearance_count else 0.0
    xg_per_90 = sum(float(row.xg) for row in appearances) * 90 / total_minutes if total_minutes else 0.0
    xa_per_90 = sum(float(row.xa) for row in appearances) * 90 / total_minutes if total_minutes else 0.0
    xgi_per_90 = sum(float(row.xgi) for row in appearances) * 90 / total_minutes if total_minutes else 0.0
    bonus_per_match = (
        sum(int(row.bonus) for row in appearances) / appearance_count
        if appearance_count
        else 0.0
    )
    value = points_per_match / price

    recent = ordered[-minutes_security_window:]
    minutes_security = (
        min(100.0, sum(min(90, int(row.minutes)) for row in recent) / (90 * len(recent)) * 100)
        if recent
        else 0.0
    )
    availability_key = STATUS_TO_AVAILABILITY.get(status, "unavailable")
    availability_penalty = float(availability_penalties.get(availability_key, 0.0))
    confidence = min(1.0, total_minutes / minimum_minutes)
    adjustment = confidence * availability_penalty
    form_5 = _rolling_form(ordered, 5)

    return PlayerFeatureSet(
        sample_fixtures=len(ordered),
        sample_appearances=appearance_count,
        sample_minutes=total_minutes,
        period_start_gameweek=ordered[0].gameweek if ordered else None,
        period_end_gameweek=ordered[-1].gameweek if ordered else None,
        form_3=_rolling_form(ordered, 3),
        form_5=form_5,
        form_10=_rolling_form(ordered, 10),
        points_per_match=_round_metric(points_per_match),
        xg_per_90=_round_metric(xg_per_90),
        xa_per_90=_round_metric(xa_per_90),
        xgi_per_90=_round_metric(xgi_per_90),
        bonus_per_match=_round_metric(bonus_per_match),
        value=_round_metric(value),
        minutes_security=_round_metric(minutes_security * availability_penalty),
        availability_penalty=_round_metric(availability_penalty),
        confidence=_round_metric(confidence),
        confidence_adjusted_form=_round_metric(form_5 * adjustment),
        confidence_adjusted_xgi_per_90=_round_metric(xgi_per_90 * adjustment),
        confidence_adjusted_value=_round_metric(value * adjustment),
        enough_minutes=total_minutes >= minimum_minutes,
    )
