"""Configurable position-relative scoring for Recommendation Engine V1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


SMALL_SAMPLE_METRICS = {
    "attacking_output",
    "bonus",
    "form",
    "ict",
    "ppm",
    "saves",
    "value",
    "xg",
    "xgi",
    "xgc_per_90",
    "saves_per_90",
    "clean_sheet_rate",
    "defensive_contribution_per_90",
    "xg_per_90",
    "xgi_per_90",
    "goals_per_90",
    "assists_per_90",
    "conversion_rate",
    "discipline_risk_per_90",
    "bonus_points",
    "ict_per_90",
}

PRE_NORMALIZED_METRICS = {"history"}
LOWER_IS_BETTER_METRICS = {
    "ownership",
    "xgc_per_90",
    "discipline_risk_per_90",
    "penalties_missed",
}

METRIC_LABELS = {
    "attacking_output": "xGI / 90",
    "bonus": "Bonus",
    "fixture": "Fixtures",
    "form": "Form",
    "history": "Historical stability",
    "ict": "ICT",
    "minutes": "Minutes security",
    "ppm": "Points per match",
    "saves": "Saves",
    "value": "Value",
    "xg": "xG / 90",
    "xgi": "xGI / 90",
}


@dataclass(frozen=True)
class RecommendationCandidate:
    player_id: int
    position: str
    metrics: Mapping[str, float]
    confidence: float
    availability_penalty: float


@dataclass(frozen=True)
class ScoredRecommendation:
    player_id: int
    position: str
    metric_scores: Mapping[str, float]
    form_score: float
    fixture_score: float
    expected_score: float
    minutes_score: float
    history_score: float
    value_score: float
    bonus_score: float
    ownership_score: float
    final_score: float
    category: str
    reason: str


def percentile_ranks(values: Sequence[float], higher_is_better: bool = True) -> list[float]:
    """Return tie-aware percentile ranks from 0 to 100."""
    if not values:
        return []
    if len(values) == 1:
        return [50.0]
    ranks = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    start = 0
    while start < len(ordered):
        end = start + 1
        value = ordered[start][1]
        while end < len(ordered) and ordered[end][1] == value:
            end += 1
        percentile = (start + (end - start - 1) / 2) / (len(values) - 1) * 100
        normalized = round(percentile if higher_is_better else 100 - percentile, 2)
        for index, _ in ordered[start:end]:
            ranks[index] = normalized
        start = end
    return ranks


def recommendation_category(score: float) -> str:
    if score >= 80:
        return "Elite Target"
    if score >= 72:
        return "Strong Buy"
    if score >= 64:
        return "Good Option"
    if score >= 56:
        return "Watchlist"
    if score >= 45:
        return "Neutral"
    return "Avoid"


def _group_score(
    metric_scores: Mapping[str, float],
    weights: Mapping[str, float],
    names: Sequence[str],
) -> float:
    included = [(name, weights[name]) for name in names if name in weights]
    total_weight = sum(weight for _, weight in included)
    if not included or total_weight == 0:
        return 50.0
    return round(
        sum(metric_scores.get(name, 50.0) * weight for name, weight in included)
        / total_weight,
        2,
    )


def score_recommendations(
    candidates: Sequence[RecommendationCandidate],
    position_weights: Mapping[str, Mapping[str, float]],
) -> list[ScoredRecommendation]:
    """Normalize per position, apply confidence, then calculate configured scores."""
    scored: list[ScoredRecommendation] = []
    for position, weights in position_weights.items():
        group = [candidate for candidate in candidates if candidate.position == position]
        if not group:
            continue
        metric_names = set(weights) | {"bonus", "form", "history", "ownership", "value"}
        normalized: dict[str, list[float]] = {}
        for metric in metric_names:
            raw_values = [float(candidate.metrics.get(metric, 0.0)) for candidate in group]
            normalized[metric] = (
                [max(0.0, min(100.0, value)) for value in raw_values]
                if metric in PRE_NORMALIZED_METRICS
                else percentile_ranks(
                    raw_values,
                    higher_is_better=metric not in LOWER_IS_BETTER_METRICS,
                )
            )

        for index, candidate in enumerate(group):
            metric_scores = {}
            for metric in metric_names:
                percentile = normalized[metric][index]
                if metric in SMALL_SAMPLE_METRICS:
                    percentile = 50 + candidate.confidence * (percentile - 50)
                metric_scores[metric] = round(max(0.0, min(100.0, percentile)), 2)

            weighted_score = sum(
                metric_scores.get(metric, 50.0) * weight
                for metric, weight in weights.items()
            )
            final_score = round(
                max(0.0, min(100.0, weighted_score * candidate.availability_penalty)),
                2,
            )
            contributions = sorted(
                (
                    (metric, metric_scores.get(metric, 50.0) * weight)
                    for metric, weight in weights.items()
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            reasons = [
                f"{METRIC_LABELS.get(metric, metric.title())} {metric_scores[metric]:.0f}"
                for metric, _ in contributions[:2]
            ]
            scored.append(
                ScoredRecommendation(
                    player_id=candidate.player_id,
                    position=position,
                    metric_scores=metric_scores,
                    form_score=metric_scores.get("form", 50.0),
                    fixture_score=metric_scores.get("fixture", 50.0),
                    expected_score=_group_score(
                        metric_scores,
                        weights,
                        ("attacking_output", "saves", "xg", "xgi"),
                    ),
                    minutes_score=metric_scores.get("minutes", 50.0),
                    history_score=_group_score(metric_scores, weights, ("history", "ppm")),
                    value_score=metric_scores.get("value", 50.0),
                    bonus_score=metric_scores.get("bonus", 50.0),
                    ownership_score=metric_scores.get("ownership", 50.0),
                    final_score=final_score,
                    category=recommendation_category(final_score),
                    reason=" · ".join(reasons),
                )
            )
    return scored
