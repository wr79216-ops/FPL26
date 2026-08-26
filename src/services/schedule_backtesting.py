"""Leakage-safe validation gate for schedule-aware transfer adjustments.

Final historical fixture allocation is used only as the realised outcome. A
forecast is eligible for scoring only when a timestamped snapshot existed
before its target gameweek. With no eligible forecast archive, the production
gate fails closed and transfer priorities remain unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse

import yaml

from config.settings import SCHEDULE_BACKTEST_CONFIG_PATH
from src.domain.schedule_risk import ScheduleRiskStatus
from src.services.schedule_congestion import PhaseCScheduleSnapshot


@dataclass(frozen=True)
class HistoricalScheduleForecast:
    season: str
    as_of_gameweek: int
    target_gameweek: int
    team: str
    blank_probability: float
    double_probability: float
    congestion_score: float
    source_url: str
    as_of: datetime
    expires_at: datetime
    confidence: str

    def __post_init__(self) -> None:
        if not self.season.strip() or not self.team.strip():
            raise ValueError("forecast season and team are required")
        if not 1 <= self.as_of_gameweek < self.target_gameweek <= 38:
            raise ValueError("forecast target GW must be after its as-of GW")
        if not 0 <= self.blank_probability <= 1 or not 0 <= self.double_probability <= 1:
            raise ValueError("forecast probabilities must be between 0 and 1")
        if not 0 <= self.congestion_score <= 100:
            raise ValueError("forecast congestion_score must be between 0 and 100")
        if self.as_of.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("forecast timestamps must include a timezone")
        if self.expires_at <= self.as_of:
            raise ValueError("forecast expiry must be after as-of")
        parsed = urlparse(self.source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("forecast source_url must be absolute HTTP(S)")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError("forecast confidence must be low, medium, or high")


@dataclass(frozen=True)
class HistoricalScheduleOutcome:
    season: str
    team: str
    gameweek: int
    fixture_count: int
    blank: int
    double: int


@dataclass(frozen=True)
class ReliabilityBucket:
    lower: float
    upper: float
    observations: int
    mean_probability: float
    observed_rate: float


@dataclass(frozen=True)
class ScheduleAdjustmentPolicy:
    model_version: str
    double_gain_weight: float
    blank_risk_weight: float
    congestion_weight: float
    minimum_observations: int
    maximum_blank_brier: float
    maximum_double_brier: float
    maximum_calibration_error: float
    minimum_top_10_points_lift: float
    minimum_spearman_lift: float
    production_activation_approved: bool


@dataclass(frozen=True)
class ScheduleAdjustmentComparison:
    evaluated_cutoffs: int
    baseline_top_10_points: float
    adjusted_top_10_points: float
    top_10_points_lift: float
    baseline_spearman: float
    adjusted_spearman: float
    spearman_lift: float


@dataclass(frozen=True)
class ScheduleValidationReport:
    model_version: str
    realised_outcomes: int
    eligible_observations: int
    rejected_observations: int
    blank_brier: float | None
    double_brier: float | None
    calibration_error: float | None
    reliability_buckets: tuple[ReliabilityBucket, ...]
    comparison: ScheduleAdjustmentComparison | None
    quantitative_gates_passed: bool
    production_active: bool
    reasons: tuple[str, ...]
    policy: ScheduleAdjustmentPolicy


def _rank_correlation(scores: Sequence[float], outcomes: Sequence[float]) -> float:
    if len(scores) != len(outcomes) or len(scores) < 2:
        return 0.0
    score_order = sorted(range(len(scores)), key=lambda index: (scores[index], index))
    outcome_order = sorted(range(len(outcomes)), key=lambda index: (outcomes[index], index))
    score_ranks = [0.0] * len(scores)
    outcome_ranks = [0.0] * len(outcomes)
    for rank, index in enumerate(score_order, start=1):
        score_ranks[index] = float(rank)
    for rank, index in enumerate(outcome_order, start=1):
        outcome_ranks[index] = float(rank)
    left_mean = mean(score_ranks)
    right_mean = mean(outcome_ranks)
    numerator = sum(
        (left - left_mean) * (right - right_mean)
        for left, right in zip(score_ranks, outcome_ranks)
    )
    left_scale = sum((value - left_mean) ** 2 for value in score_ranks) ** 0.5
    right_scale = sum((value - right_mean) ** 2 for value in outcome_ranks) ** 0.5
    return numerator / (left_scale * right_scale) if left_scale and right_scale else 0.0


def _timestamp(value: object, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return result


def load_schedule_backtest_config(
    path: Path = SCHEDULE_BACKTEST_CONFIG_PATH,
) -> tuple[ScheduleAdjustmentPolicy, tuple[HistoricalScheduleForecast, ...]]:
    with path.open("r", encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file) or {}
    weights = payload.get("weights")
    gates = payload.get("validation_gates")
    observations = payload.get("observations", [])
    if not isinstance(weights, Mapping) or not isinstance(gates, Mapping):
        raise ValueError("schedule_backtest.yaml requires weights and validation_gates")
    if not isinstance(observations, list):
        raise ValueError("schedule_backtest observations must be a list")
    policy = ScheduleAdjustmentPolicy(
        model_version=str(payload.get("model_version", "")).strip(),
        double_gain_weight=float(weights["double_gain"]),
        blank_risk_weight=float(weights["blank_risk"]),
        congestion_weight=float(weights["congestion"]),
        minimum_observations=int(gates["minimum_observations"]),
        maximum_blank_brier=float(gates["maximum_blank_brier"]),
        maximum_double_brier=float(gates["maximum_double_brier"]),
        maximum_calibration_error=float(gates["maximum_calibration_error"]),
        minimum_top_10_points_lift=float(gates["minimum_top_10_points_lift"]),
        minimum_spearman_lift=float(gates["minimum_spearman_lift"]),
        production_activation_approved=bool(payload.get("production_activation_approved", False)),
    )
    if not policy.model_version:
        raise ValueError("schedule backtest model_version is required")
    if policy.minimum_observations <= 0:
        raise ValueError("minimum_observations must be positive")
    forecasts: list[HistoricalScheduleForecast] = []
    for index, raw in enumerate(observations):
        if not isinstance(raw, Mapping):
            raise ValueError(f"observations[{index}] must be a mapping")
        forecasts.append(
            HistoricalScheduleForecast(
                season=str(raw["season"]),
                as_of_gameweek=int(raw["as_of_gameweek"]),
                target_gameweek=int(raw["target_gameweek"]),
                team=str(raw["team"]),
                blank_probability=float(raw["blank_probability"]),
                double_probability=float(raw["double_probability"]),
                congestion_score=float(raw.get("congestion_score", 0)),
                source_url=str(raw["source_url"]),
                as_of=_timestamp(raw["as_of"], f"observations[{index}].as_of"),
                expires_at=_timestamp(raw["expires_at"], f"observations[{index}].expires_at"),
                confidence=str(raw["confidence"]),
            )
        )
    identities = {
        (item.season, item.as_of_gameweek, item.target_gameweek, item.team.casefold())
        for item in forecasts
    }
    if len(identities) != len(forecasts):
        raise ValueError("schedule backtest observations contain duplicate targets")
    return policy, tuple(forecasts)


def reconstruct_historical_schedule_outcomes(
    fixtures: Iterable[object],
) -> tuple[HistoricalScheduleOutcome, ...]:
    """Reconstruct realised blank/double labels from final official allocation."""
    records = tuple(fixtures)
    seasons = sorted({str(item.season) for item in records})
    outcomes: list[HistoricalScheduleOutcome] = []
    for season in seasons:
        season_fixtures = [item for item in records if str(item.season) == season]
        teams = sorted(
            {str(team) for item in season_fixtures for team in (item.home_team, item.away_team)}
        )
        counts: dict[tuple[str, int], int] = defaultdict(int)
        for item in season_fixtures:
            counts[(str(item.home_team), int(item.gameweek))] += 1
            counts[(str(item.away_team), int(item.gameweek))] += 1
        for team in teams:
            for gameweek in range(1, 39):
                fixture_count = counts.get((team, gameweek), 0)
                outcomes.append(
                    HistoricalScheduleOutcome(
                        season=season,
                        team=team,
                        gameweek=gameweek,
                        fixture_count=fixture_count,
                        blank=int(fixture_count == 0),
                        double=int(fixture_count >= 2),
                    )
                )
    return tuple(outcomes)


def _earliest_kickoff_by_gameweek(fixtures: Iterable[object]) -> dict[tuple[str, int], datetime]:
    result: dict[tuple[str, int], datetime] = {}
    for fixture in fixtures:
        kickoff = fixture.kickoff_time
        if kickoff is None:
            continue
        key = (str(fixture.season), int(fixture.gameweek))
        if key not in result or kickoff < result[key]:
            result[key] = kickoff
    return result


def eligible_historical_forecasts(
    forecasts: Iterable[HistoricalScheduleForecast],
    fixtures: Iterable[object],
    outcomes: Iterable[HistoricalScheduleOutcome],
) -> tuple[tuple[HistoricalScheduleForecast, HistoricalScheduleOutcome], ...]:
    """Keep only forecasts demonstrably created before the target GW began."""
    outcome_map = {
        (item.season, item.team.casefold(), item.gameweek): item for item in outcomes
    }
    first_kickoff = _earliest_kickoff_by_gameweek(fixtures)
    eligible: list[tuple[HistoricalScheduleForecast, HistoricalScheduleOutcome]] = []
    for forecast in forecasts:
        outcome = outcome_map.get(
            (forecast.season, forecast.team.casefold(), forecast.target_gameweek)
        )
        target_kickoff = first_kickoff.get((forecast.season, forecast.target_gameweek))
        if outcome is None or target_kickoff is None:
            continue
        comparable_kickoff = target_kickoff
        if comparable_kickoff.tzinfo is None:
            comparable_kickoff = comparable_kickoff.replace(tzinfo=forecast.as_of.tzinfo)
        if forecast.as_of >= comparable_kickoff or forecast.expires_at <= forecast.as_of:
            continue
        eligible.append((forecast, outcome))
    return tuple(eligible)


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("Brier score requires equal non-empty probability/outcome lists")
    return mean((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes))


def reliability_buckets(
    probabilities: Sequence[float], outcomes: Sequence[int], bucket_count: int = 5
) -> tuple[ReliabilityBucket, ...]:
    if len(probabilities) != len(outcomes) or not probabilities:
        return ()
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    buckets: list[ReliabilityBucket] = []
    for index in range(bucket_count):
        lower = index / bucket_count
        upper = (index + 1) / bucket_count
        indices = [
            item_index
            for item_index, probability in enumerate(probabilities)
            if (
                lower <= probability <= upper
                if index == bucket_count - 1
                else lower <= probability < upper
            )
        ]
        if not indices:
            continue
        buckets.append(
            ReliabilityBucket(
                lower=lower,
                upper=upper,
                observations=len(indices),
                mean_probability=mean(probabilities[item] for item in indices),
                observed_rate=mean(outcomes[item] for item in indices),
            )
        )
    return tuple(buckets)


def expected_calibration_error(buckets: Iterable[ReliabilityBucket]) -> float | None:
    records = tuple(buckets)
    total = sum(item.observations for item in records)
    if not total:
        return None
    return sum(
        item.observations / total * abs(item.mean_probability - item.observed_rate)
        for item in records
    )


def compare_schedule_adjusted_rankings(
    predictions: Iterable[object],
    player_gameweeks: Iterable[object],
    eligible_forecasts: Iterable[HistoricalScheduleForecast],
    policy: ScheduleAdjustmentPolicy,
) -> ScheduleAdjustmentComparison | None:
    """Compare the same stored player rankings with and without schedule signals."""
    forecast_map = {
        (
            item.season,
            item.as_of_gameweek,
            item.target_gameweek,
            item.team.casefold(),
        ): item
        for item in eligible_forecasts
    }
    rows_by_season_player: dict[tuple[str, int], list[object]] = defaultdict(list)
    for row in player_gameweeks:
        rows_by_season_player[(str(row.season), int(row.player_id))].append(row)
    groups: dict[tuple[str, int, int, str], list[object]] = defaultdict(list)
    for prediction in predictions:
        groups[
            (
                str(prediction.season),
                int(prediction.as_of_gameweek),
                int(prediction.horizon),
                str(prediction.model_version),
            )
        ].append(prediction)

    baseline_points: list[float] = []
    adjusted_points: list[float] = []
    baseline_spearman: list[float] = []
    adjusted_spearman: list[float] = []
    for (season, cutoff, horizon, _), group in groups.items():
        player_teams: dict[int, str] = {}
        for prediction in group:
            past = [
                row
                for row in rows_by_season_player.get((season, int(prediction.player_id)), ())
                if int(row.gameweek) <= cutoff
            ]
            if past:
                latest = max(past, key=lambda row: (int(row.gameweek), int(row.fixture_id)))
                player_teams[int(prediction.player_id)] = str(latest.team)
        if len(player_teams) != len(group):
            continue
        target_gameweeks = range(cutoff + 1, cutoff + horizon + 1)
        teams = set(player_teams.values())
        if any(
            (season, cutoff, target, team.casefold()) not in forecast_map
            for target in target_gameweeks
            for team in teams
        ):
            continue
        adjusted: list[tuple[object, float]] = []
        for prediction in group:
            team = player_teams[int(prediction.player_id)]
            schedule_delta = 0.0
            for target in target_gameweeks:
                forecast = forecast_map[(season, cutoff, target, team.casefold())]
                schedule_delta += (
                    policy.double_gain_weight * forecast.double_probability
                    - policy.blank_risk_weight * forecast.blank_probability
                    - policy.congestion_weight * forecast.congestion_score / 100
                )
            adjusted.append((prediction, float(prediction.recommendation_score) + schedule_delta))
        baseline_order = sorted(group, key=lambda item: (-float(item.recommendation_score), int(item.player_id)))
        adjusted_order = [item[0] for item in sorted(adjusted, key=lambda item: (-item[1], int(item[0].player_id)))]
        baseline_points.append(mean(float(item.actual_points) for item in baseline_order[:10]))
        adjusted_points.append(mean(float(item.actual_points) for item in adjusted_order[:10]))
        actual = [float(item.actual_points) for item in group]
        baseline_spearman.append(
            _rank_correlation([float(item.recommendation_score) for item in group], actual)
        )
        adjusted_score_map = {int(item.player_id): score for item, score in adjusted}
        adjusted_spearman.append(
            _rank_correlation(
                [adjusted_score_map[int(item.player_id)] for item in group], actual
            )
        )
    if not baseline_points:
        return None
    baseline_top = mean(baseline_points)
    adjusted_top = mean(adjusted_points)
    baseline_corr = mean(baseline_spearman)
    adjusted_corr = mean(adjusted_spearman)
    return ScheduleAdjustmentComparison(
        evaluated_cutoffs=len(baseline_points),
        baseline_top_10_points=round(baseline_top, 4),
        adjusted_top_10_points=round(adjusted_top, 4),
        top_10_points_lift=round(adjusted_top - baseline_top, 4),
        baseline_spearman=round(baseline_corr, 4),
        adjusted_spearman=round(adjusted_corr, 4),
        spearman_lift=round(adjusted_corr - baseline_corr, 4),
    )


def validate_schedule_adjustment(
    policy: ScheduleAdjustmentPolicy,
    outcomes: Sequence[HistoricalScheduleOutcome],
    forecasts: Sequence[HistoricalScheduleForecast],
    fixtures: Sequence[object],
    comparison: ScheduleAdjustmentComparison | None = None,
) -> ScheduleValidationReport:
    eligible = eligible_historical_forecasts(forecasts, fixtures, outcomes)
    blank_probabilities = [item[0].blank_probability for item in eligible]
    double_probabilities = [item[0].double_probability for item in eligible]
    blank_outcomes = [item[1].blank for item in eligible]
    double_outcomes = [item[1].double for item in eligible]
    blank_brier = brier_score(blank_probabilities, blank_outcomes) if eligible else None
    double_brier = brier_score(double_probabilities, double_outcomes) if eligible else None
    combined_probabilities = blank_probabilities + double_probabilities
    combined_outcomes = blank_outcomes + double_outcomes
    buckets = reliability_buckets(combined_probabilities, combined_outcomes)
    calibration_error = expected_calibration_error(buckets)
    reasons: list[str] = []
    if len(eligible) < policy.minimum_observations:
        reasons.append(
            f"Only {len(eligible)} eligible forecast snapshots; minimum is {policy.minimum_observations}."
        )
    if blank_brier is None or blank_brier > policy.maximum_blank_brier:
        reasons.append("Blank Brier gate is not met.")
    if double_brier is None or double_brier > policy.maximum_double_brier:
        reasons.append("Double Brier gate is not met.")
    if calibration_error is None or calibration_error > policy.maximum_calibration_error:
        reasons.append("Reliability calibration gate is not met.")
    if comparison is None or comparison.evaluated_cutoffs <= 0:
        reasons.append("No leakage-safe baseline vs adjusted ranking comparison is available.")
    else:
        if comparison.top_10_points_lift < policy.minimum_top_10_points_lift:
            reasons.append("Adjusted top-10 points lift is below the activation threshold.")
        if comparison.spearman_lift < policy.minimum_spearman_lift:
            reasons.append("Adjusted Spearman lift is below the activation threshold.")
    quantitative_passed = not reasons
    production_active = quantitative_passed and policy.production_activation_approved
    if quantitative_passed and not policy.production_activation_approved:
        reasons.append("Quantitative gates passed, but explicit production approval is still false.")
    return ScheduleValidationReport(
        model_version=policy.model_version,
        realised_outcomes=len(outcomes),
        eligible_observations=len(eligible),
        rejected_observations=len(forecasts) - len(eligible),
        blank_brier=blank_brier,
        double_brier=double_brier,
        calibration_error=calibration_error,
        reliability_buckets=buckets,
        comparison=comparison,
        quantitative_gates_passed=quantitative_passed,
        production_active=production_active,
        reasons=tuple(reasons),
        policy=policy,
    )


def current_team_priority_adjustments(
    snapshot: PhaseCScheduleSnapshot,
    current_gameweek: int,
    horizon: int,
    report: ScheduleValidationReport,
) -> dict[str, float]:
    """Build current team adjustment points only after the production gate passes."""
    if not report.production_active:
        return {}
    gameweeks = set(range(current_gameweek, min(38, current_gameweek + horizon - 1) + 1))
    team_names = {team_id: name for team_id, name, _ in snapshot.phase_b.team_names}
    blank_by_team: dict[int, float] = defaultdict(float)
    double_by_team: dict[int, float] = defaultdict(float)
    for summary in snapshot.phase_b.gameweek_risks:
        if summary.gameweek not in gameweeks:
            continue
        if summary.status is ScheduleRiskStatus.CONFIRMED_BLANK:
            blank_by_team[summary.team_id] += 1
        elif summary.status is ScheduleRiskStatus.CONFIRMED_DOUBLE:
            double_by_team[summary.team_id] += max(0, len(summary.fixture_ids) - 1)
    clashes = {item.fixture_id: item for item in snapshot.phase_b.structural_clashes}
    for projection in snapshot.fixture_projections:
        clash = clashes.get(projection.fixture_id)
        if clash is None or projection.source_gameweek not in gameweeks:
            continue
        for team_id in (clash.home_team_id, clash.away_team_id):
            blank_by_team[team_id] += projection.blank_probability
    for projection in snapshot.double_gameweek_projections:
        clash = clashes.get(projection.fixture_id)
        if clash is None or projection.target_gameweek not in gameweeks:
            continue
        for team_id in (clash.home_team_id, clash.away_team_id):
            double_by_team[team_id] += projection.double_probability
    congestion = {
        item.team_id: item.congestion_score / 100
        for item in snapshot.phase_b.congestion_leaders
    }
    return {
        team_name: round(
            report.policy.double_gain_weight * double_by_team.get(team_id, 0)
            - report.policy.blank_risk_weight * blank_by_team.get(team_id, 0)
            - report.policy.congestion_weight * congestion.get(team_id, 0),
            3,
        )
        for team_id, team_name in team_names.items()
    }
