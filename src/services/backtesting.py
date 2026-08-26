"""Time-safe historical backtesting and model calibration for Phase 9."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Mapping, Sequence

import yaml

from config.settings import (
    DATABASE_PATH,
    HISTORICAL_DATA_DIR,
    SCORING_CONFIG_PATH,
    load_app_settings,
    load_scoring_config,
)
from src.api.historical_client import HistoricalDataClient
from src.database.connection import Database
from src.database.models import (
    BacktestFixtureModel,
    BacktestPlayerGameweekModel,
    BacktestPredictionModel,
    BacktestRunModel,
)
from src.database.repository import FPLRepository
from src.domain.contracts import (
    BacktestFixtureRecord,
    BacktestPlayerGameweekRecord,
    BacktestPredictionRecord,
    BacktestRunRecord,
)
from src.features.fixture import HORIZON_WEIGHTS
from src.features.recommendation import (
    RecommendationCandidate,
    percentile_ranks,
    score_recommendations,
)
from src.services.application import get_database
from src.services.historical_data import (
    HISTORICAL_POSITION_MAP,
    MIN_SEASON_MINUTES,
    normalize_identity_name,
)
from src.services.schedule_backtesting import (
    ScheduleValidationReport,
    compare_schedule_adjusted_rankings,
    eligible_historical_forecasts,
    load_schedule_backtest_config,
    reconstruct_historical_schedule_outcomes,
    validate_schedule_adjustment,
)


BACKTEST_MODELS_PATH = SCORING_CONFIG_PATH.with_name("backtest_models.yaml")
POSITIONAL_CANDIDATE_CONFIG_PATH = SCORING_CONFIG_PATH.with_name(
    "positional_candidate_weights.yaml"
)
BACKTEST_SEASON = "2025-26"
BACKTEST_HORIZONS = (1, 3, 5)
MIN_AS_OF_GAMEWEEK = 3
LIMITATIONS = (
    "Time-safe outcomes: only rows through GW N form features and GW N+1..N+h form targets. "
    "Historical availability/injury status is unavailable, so availability penalty is neutral. "
    "Fixture ease is reconstructed from opponent league points earned only through GW N, "
    "not from the end-season FDR snapshot. Official form is approximated by rolling five-GW points."
)


@dataclass(frozen=True)
class BacktestStatus:
    gameweek_rows: int
    fixture_rows: int
    prediction_rows: int
    runs: int


@dataclass(frozen=True)
class BacktestExecutionResult:
    season: str
    gameweek_rows: int
    fixture_rows: int
    runs: int
    prediction_rows: int


@dataclass(frozen=True)
class BacktestRunSummary:
    season: str
    horizon: int
    model_version: str
    gameweeks: int
    predictions: int
    mae_percentile: float
    spearman: float
    top_10_hit_rate: float
    average_actual_points_top_10: float
    first_gameweek: int
    last_gameweek: int
    limitations: str


@dataclass(frozen=True)
class BacktestPredictionView:
    as_of_gameweek: int
    player: str
    position: str
    recommendation_score: float
    predicted_rank: int
    actual_points: int
    actual_percentile: float
    actual_rank: int


@dataclass(frozen=True)
class PositionalValidationPolicy:
    minimum_cutoffs: int
    minimum_predictions_per_position: int
    minimum_feature_coverage: float
    maximum_mae_increase: float
    maximum_spearman_decrease: float
    maximum_top_10_hit_rate_decrease: float
    maximum_top_10_points_decrease: float
    require_at_least_one_improvement: bool
    production_activation_approved: bool


@dataclass(frozen=True)
class PositionalMetricSummary:
    cutoffs: int
    predictions: int
    mae_percentile: float
    spearman: float
    top_10_hit_rate: float
    average_actual_points_top_10: float


@dataclass(frozen=True)
class PositionalCandidateEvaluation:
    position: str
    baseline: PositionalMetricSummary | None
    candidate: PositionalMetricSummary | None
    feature_coverage: float
    gate_passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PositionalCandidateValidationReport:
    season: str
    horizon: int
    production_version: str
    candidate_version: str
    evaluations: tuple[PositionalCandidateEvaluation, ...]
    policy: PositionalValidationPolicy
    quantitative_gates_passed: bool
    production_active: bool
    reasons: tuple[str, ...]


def _integer(value: object, default: int = 0) -> int:
    text = str(value or "").strip()
    return int(float(text)) if text else default


def _number(value: object, default: float = 0.0) -> float:
    text = str(value or "").strip()
    return float(text) if text else default


def _optional_integer(value: object) -> int | None:
    text = str(value or "").strip()
    return int(float(text)) if text else None


def _optional_number(value: object) -> float | None:
    text = str(value or "").strip()
    return float(text) if text else None


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def parse_backtest_gameweeks(
    payload: str, season: str
) -> list[BacktestPlayerGameweekRecord]:
    records: list[BacktestPlayerGameweekRecord] = []
    seen: dict[tuple[int, int], tuple[tuple[str, str], ...]] = {}
    for line_number, row in enumerate(csv.DictReader(io.StringIO(payload)), start=2):
        try:
            player_id = _integer(row["element"])
            fixture_id = _integer(row["fixture"])
            identity = (player_id, fixture_id)
            fingerprint = tuple(sorted((str(key), str(value)) for key, value in row.items()))
            if identity in seen:
                if seen[identity] == fingerprint:
                    continue
                raise ValueError("conflicting duplicate player fixture")
            seen[identity] = fingerprint
            source_position = str(row["position"]).strip().upper()
            position = HISTORICAL_POSITION_MAP[source_position]
            name = str(row["name"]).strip()
            records.append(
                BacktestPlayerGameweekRecord(
                    season=season,
                    player_id=player_id,
                    fixture_id=fixture_id,
                    gameweek=_integer(row["round"]),
                    player_name=name,
                    normalized_name=normalize_identity_name(name),
                    position=position,
                    team=str(row["team"]).strip(),
                    minutes=_integer(row["minutes"]),
                    total_points=_integer(row["total_points"]),
                    goals=_integer(row["goals_scored"]),
                    assists=_integer(row["assists"]),
                    bonus=_integer(row["bonus"]),
                    saves=_integer(row["saves"]),
                    ict_index=_number(row["ict_index"]),
                    expected_goals=_number(row["expected_goals"]),
                    expected_assists=_number(row["expected_assists"]),
                    expected_goal_involvements=_number(
                        row["expected_goal_involvements"]
                    ),
                    selected=_integer(row["selected"]),
                    price=_number(row["value"]) / 10,
                    kickoff_time=_timestamp(row["kickoff_time"]),
                    clean_sheets=_optional_integer(row.get("clean_sheets")),
                    goals_conceded=_optional_integer(row.get("goals_conceded")),
                    penalties_saved=_optional_integer(row.get("penalties_saved")),
                    penalties_missed=_optional_integer(row.get("penalties_missed")),
                    yellow_cards=_optional_integer(row.get("yellow_cards")),
                    red_cards=_optional_integer(row.get("red_cards")),
                    defensive_contribution=_optional_integer(
                        row.get("defensive_contribution")
                    ),
                    expected_goals_conceded=_optional_number(
                        row.get("expected_goals_conceded")
                    ),
                    starts=_optional_integer(row.get("starts")),
                    bps=_optional_integer(row.get("bps")),
                    influence=_optional_number(row.get("influence")),
                    creativity=_optional_number(row.get("creativity")),
                    threat=_optional_number(row.get("threat")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid backtest gameweek row {line_number} for {season}"
            ) from exc
    if not records:
        raise ValueError(f"Backtest gameweek dataset {season} is empty")
    return records


def parse_backtest_fixtures(
    fixtures_payload: str, teams_payload: str, season: str
) -> list[BacktestFixtureRecord]:
    teams = {
        _integer(row["id"]): str(row["name"]).strip()
        for row in csv.DictReader(io.StringIO(teams_payload))
    }
    records: list[BacktestFixtureRecord] = []
    for line_number, row in enumerate(
        csv.DictReader(io.StringIO(fixtures_payload)), start=2
    ):
        try:
            gameweek = _integer(row["event"])
            if gameweek <= 0:
                continue
            home_team = teams[_integer(row["team_h"])]
            away_team = teams[_integer(row["team_a"])]
            records.append(
                BacktestFixtureRecord(
                    season=season,
                    fixture_id=_integer(row["id"]),
                    gameweek=gameweek,
                    home_team=home_team,
                    away_team=away_team,
                    home_difficulty=_integer(row["team_h_difficulty"]),
                    away_difficulty=_integer(row["team_a_difficulty"]),
                    home_score=(
                        _integer(row["team_h_score"])
                        if str(row["team_h_score"] or "").strip()
                        else None
                    ),
                    away_score=(
                        _integer(row["team_a_score"])
                        if str(row["team_a_score"] or "").strip()
                        else None
                    ),
                    kickoff_time=_timestamp(row["kickoff_time"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid backtest fixture row {line_number} for {season}"
            ) from exc
    if not records:
        raise ValueError(f"Backtest fixture dataset {season} is empty")
    return records


def spearman_rank_correlation(predicted: Sequence[float], actual: Sequence[float]) -> float:
    if len(predicted) != len(actual) or len(predicted) < 2:
        return 0.0
    predicted_ranks = percentile_ranks(predicted)
    actual_ranks = percentile_ranks(actual)
    predicted_mean = mean(predicted_ranks)
    actual_mean = mean(actual_ranks)
    numerator = sum(
        (left - predicted_mean) * (right - actual_mean)
        for left, right in zip(predicted_ranks, actual_ranks)
    )
    left_scale = math.sqrt(sum((value - predicted_mean) ** 2 for value in predicted_ranks))
    right_scale = math.sqrt(sum((value - actual_mean) ** 2 for value in actual_ranks))
    return numerator / (left_scale * right_scale) if left_scale and right_scale else 0.0


def load_candidate_models(
    path: Path = BACKTEST_MODELS_PATH,
) -> dict[str, dict[str, dict[str, float]]]:
    with path.open("r", encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file) or {}
    models = payload.get("candidate_models")
    if not isinstance(models, dict) or not models:
        raise ValueError("backtest_models.yaml requires candidate_models")
    validated: dict[str, dict[str, dict[str, float]]] = {}
    for version, definition in models.items():
        weights_by_position = definition.get("position_weights", {})
        validated[str(version)] = {}
        for position in ("GK", "DEF", "MID", "FWD"):
            weights = {
                str(metric): float(weight)
                for metric, weight in weights_by_position.get(position, {}).items()
            }
            if not weights or abs(sum(weights.values()) - 1.0) > 1e-9:
                raise ValueError(
                    f"backtest candidate {version} {position} weights must sum to 1.0"
                )
            validated[str(version)][position] = weights
    return validated


def load_positional_candidate_model(
    path: Path = POSITIONAL_CANDIDATE_CONFIG_PATH,
) -> tuple[str, str, dict[str, dict[str, float]], PositionalValidationPolicy]:
    """Load the Phase D candidate separately from the live scoring config.

    Keeping this candidate out of ``scoring.yaml`` makes an accidental
    production promotion impossible: only backtesting reads these weights.
    """
    with path.open("r", encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file) or {}
    version = str(payload.get("model_version", "")).strip()
    production_version = str(payload.get("production_model", "")).strip()
    if not version or not production_version:
        raise ValueError("positional candidate requires model and production versions")
    if payload.get("status") != "experimental":
        raise ValueError("positional candidate must remain experimental during validation")
    raw_weights = payload.get("position_weights")
    if not isinstance(raw_weights, Mapping):
        raise ValueError("positional candidate requires position_weights")
    weights: dict[str, dict[str, float]] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        raw_position_weights = raw_weights.get(position)
        if not isinstance(raw_position_weights, Mapping) or not raw_position_weights:
            raise ValueError(f"positional candidate missing {position} weights")
        normalized = {
            str(metric): float(weight)
            for metric, weight in raw_position_weights.items()
        }
        if any(weight < 0 for weight in normalized.values()) or abs(
            sum(normalized.values()) - 1.0
        ) > 1e-9:
            raise ValueError(f"positional candidate {position} weights must sum to 1.0")
        weights[position] = normalized

    gates = payload.get("validation_gates")
    if not isinstance(gates, Mapping):
        raise ValueError("positional candidate requires validation_gates")
    policy = PositionalValidationPolicy(
        minimum_cutoffs=int(gates["minimum_cutoffs"]),
        minimum_predictions_per_position=int(gates["minimum_predictions_per_position"]),
        minimum_feature_coverage=float(gates["minimum_feature_coverage"]),
        maximum_mae_increase=float(gates["maximum_mae_increase"]),
        maximum_spearman_decrease=float(gates["maximum_spearman_decrease"]),
        maximum_top_10_hit_rate_decrease=float(
            gates["maximum_top_10_hit_rate_decrease"]
        ),
        maximum_top_10_points_decrease=float(
            gates["maximum_top_10_points_decrease"]
        ),
        require_at_least_one_improvement=bool(
            gates["require_at_least_one_improvement"]
        ),
        production_activation_approved=bool(
            gates["production_activation_approved"]
        ),
    )
    if (
        policy.minimum_cutoffs <= 0
        or policy.minimum_predictions_per_position <= 0
        or not 0 <= policy.minimum_feature_coverage <= 1
    ):
        raise ValueError("positional candidate validation gates are invalid")
    return version, production_version, weights, policy


class BacktestingService:
    def __init__(
        self,
        database: Database,
        client: HistoricalDataClient,
        archive_dir: Path = HISTORICAL_DATA_DIR,
    ) -> None:
        self.database = database
        self.client = client
        self.archive_dir = Path(archive_dir)

    def import_and_run(
        self,
        season: str = BACKTEST_SEASON,
        horizons: Sequence[int] = BACKTEST_HORIZONS,
    ) -> BacktestExecutionResult:
        gameweek_payload = self.client.get_merged_gameweeks(season)
        fixture_payload = self.client.get_fixtures(season)
        team_payload = self.client.get_teams(season)
        gameweeks = parse_backtest_gameweeks(gameweek_payload, season)
        fixtures = parse_backtest_fixtures(fixture_payload, team_payload, season)

        season_dir = self.archive_dir / season
        season_dir.mkdir(parents=True, exist_ok=True)
        for filename, payload in (
            ("merged_gw.csv", gameweek_payload),
            ("fixtures.csv", fixture_payload),
            ("teams.csv", team_payload),
        ):
            (season_dir / filename).write_text(payload, encoding="utf-8")

        with self.database.session() as session:
            repository = FPLRepository(session)
            repository.bulk_upsert_backtest_player_gameweeks(gameweeks)
            repository.bulk_upsert_backtest_fixtures(fixtures)

        scoring = load_scoring_config()
        positional_version, positional_production, positional_weights, _ = (
            load_positional_candidate_model()
        )
        if positional_production != scoring.model_version:
            raise ValueError(
                "positional candidate production_model must match scoring.yaml before validation"
            )
        models: dict[str, Mapping[str, Mapping[str, float]]] = {
            f"production-{scoring.model_version}": scoring.position_weights,
            **load_candidate_models(),
            positional_version: positional_weights,
        }
        for horizon in horizons:
            if horizon not in BACKTEST_HORIZONS:
                raise ValueError("backtest horizon must be 1, 3, or 5")
            for model_version, weights in models.items():
                self.run_model(season, horizon, model_version, weights)

        status = self.get_status()
        return BacktestExecutionResult(
            season=season,
            gameweek_rows=status.gameweek_rows,
            fixture_rows=status.fixture_rows,
            runs=status.runs,
            prediction_rows=status.prediction_rows,
        )

    def run_model(
        self,
        season: str,
        horizon: int,
        model_version: str,
        position_weights: Mapping[str, Mapping[str, float]],
    ) -> BacktestRunRecord:
        with self.database.session() as session:
            repository = FPLRepository(session)
            gameweeks = repository.list_backtest_player_gameweeks(season)
            fixtures = repository.list_backtest_fixtures(season)
            historical_rows = repository.list_historical_player_seasons()
        if not gameweeks or not fixtures:
            raise ValueError("Import historical gameweek and fixture data before backtesting")

        historical_scores = self._historical_scores_for_season(
            historical_rows, season
        )
        max_gameweek = max(row.gameweek for row in gameweeks)
        cutoffs = list(range(MIN_AS_OF_GAMEWEEK, max_gameweek - horizon + 1))
        calculated_at = datetime.now(timezone.utc)
        predictions: list[BacktestPredictionRecord] = []
        cutoff_spearman: list[float] = []
        cutoff_hit_rate: list[float] = []
        cutoff_top_points: list[float] = []

        rows_by_gameweek: dict[int, list[BacktestPlayerGameweekModel]] = defaultdict(list)
        for row in gameweeks:
            rows_by_gameweek[row.gameweek].append(row)

        for cutoff in cutoffs:
            candidates, metadata = self._build_candidates(
                rows_by_gameweek,
                fixtures,
                historical_scores,
                cutoff,
                horizon,
            )
            scored = score_recommendations(candidates, position_weights)
            scored_rows = sorted(scored, key=lambda row: (-row.final_score, row.player_id))
            future_points: dict[int, int] = defaultdict(int)
            for gameweek in range(cutoff + 1, cutoff + horizon + 1):
                for item in rows_by_gameweek.get(gameweek, []):
                    future_points[item.player_id] += item.total_points
            actual_points = {
                row.player_id: future_points.get(row.player_id, 0)
                for row in scored_rows
            }
            actual_percentiles: dict[int, float] = {}
            for position in position_weights:
                position_ids = [
                    row.player_id for row in scored_rows if row.position == position
                ]
                percentiles = percentile_ranks(
                    [float(actual_points[player_id]) for player_id in position_ids]
                )
                actual_percentiles.update(dict(zip(position_ids, percentiles)))

            actual_order = sorted(
                scored_rows,
                key=lambda row: (-actual_points[row.player_id], row.player_id),
            )
            actual_ranks = {
                row.player_id: rank for rank, row in enumerate(actual_order, start=1)
            }
            predicted_top = {row.player_id for row in scored_rows[:10]}
            actual_top = {row.player_id for row in actual_order[:10]}
            cutoff_hit_rate.append(len(predicted_top & actual_top) / 10 * 100)
            cutoff_top_points.append(
                mean(actual_points[row.player_id] for row in scored_rows[:10])
            )
            cutoff_spearman.append(
                spearman_rank_correlation(
                    [row.final_score for row in scored_rows],
                    [float(actual_points[row.player_id]) for row in scored_rows],
                )
            )
            for predicted_rank, row in enumerate(scored_rows, start=1):
                player = metadata[row.player_id]
                predictions.append(
                    BacktestPredictionRecord(
                        season=season,
                        as_of_gameweek=cutoff,
                        horizon=horizon,
                        model_version=model_version,
                        player_id=row.player_id,
                        player_name=player.player_name,
                        position=row.position,
                        recommendation_score=row.final_score,
                        predicted_rank=predicted_rank,
                        actual_points=actual_points[row.player_id],
                        actual_percentile=actual_percentiles[row.player_id],
                        actual_rank=actual_ranks[row.player_id],
                        calculated_at=calculated_at,
                    )
                )

        mae = mean(
            abs(row.recommendation_score - row.actual_percentile)
            for row in predictions
        )
        run = BacktestRunRecord(
            season=season,
            horizon=horizon,
            model_version=model_version,
            first_as_of_gameweek=cutoffs[0],
            last_as_of_gameweek=cutoffs[-1],
            gameweek_count=len(cutoffs),
            prediction_count=len(predictions),
            mae_percentile=round(mae, 4),
            spearman=round(mean(cutoff_spearman), 4),
            top_10_hit_rate=round(mean(cutoff_hit_rate), 2),
            average_actual_points_top_10=round(mean(cutoff_top_points), 3),
            calculated_at=calculated_at,
            limitations=LIMITATIONS,
        )
        with self.database.session() as session:
            repository = FPLRepository(session)
            repository.clear_backtest_results(season, horizon, model_version)
            repository.bulk_upsert_backtest_predictions(predictions)
            repository.upsert_backtest_run(run)
        return run

    @staticmethod
    def _historical_scores_for_season(
        historical_rows: Sequence[object], target_season: str
    ) -> dict[tuple[str, str], float]:
        histories: dict[tuple[str, str], list[object]] = defaultdict(list)
        for row in historical_rows:
            if row.season < target_season and row.minutes >= MIN_SEASON_MINUTES:
                histories[(row.normalized_name, row.position)].append(row)
        raw: dict[tuple[str, str], tuple[float, float, int, int]] = {}
        by_position: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for identity, seasons in histories.items():
            seasons.sort(key=lambda item: item.season, reverse=True)
            weights = [math.pow(0.6, index) for index in range(len(seasons))]
            weighted_output = sum(
                row.points_per_90 * weight for row, weight in zip(seasons, weights)
            ) / sum(weights)
            outputs = [row.points_per_90 for row in seasons]
            output_mean = mean(outputs)
            variation = (
                math.sqrt(mean((value - output_mean) ** 2 for value in outputs))
                / abs(output_mean)
                if len(outputs) > 1 and output_mean
                else 0.0
            )
            consistency = max(0.0, 100.0 - min(100.0, variation * 100))
            total_minutes = sum(row.minutes for row in seasons)
            raw[identity] = (
                weighted_output,
                consistency,
                len(seasons),
                total_minutes,
            )
            by_position[identity[1]].append(identity)
        scores: dict[tuple[str, str], float] = {}
        for identities in by_position.values():
            output_percentiles = percentile_ranks(
                [raw[identity][0] for identity in identities]
            )
            for identity, output_percentile in zip(identities, output_percentiles):
                _, consistency, season_count, total_minutes = raw[identity]
                base = output_percentile * 0.8 + consistency * 0.2
                evidence = min(1.0, season_count / 2) * min(1.0, total_minutes / 1800)
                scores[identity] = round(50 + evidence * (base - 50), 2)
        return scores

    @staticmethod
    def _fixture_scores_as_of(
        fixtures: Sequence[BacktestFixtureModel], cutoff: int, horizon: int
    ) -> dict[str, float]:
        teams = sorted(
            {team for fixture in fixtures for team in (fixture.home_team, fixture.away_team)}
        )
        points = defaultdict(float)
        games = defaultdict(int)
        for fixture in fixtures:
            if (
                fixture.gameweek > cutoff
                or fixture.home_score is None
                or fixture.away_score is None
            ):
                continue
            games[fixture.home_team] += 1
            games[fixture.away_team] += 1
            if fixture.home_score > fixture.away_score:
                points[fixture.home_team] += 3
            elif fixture.home_score < fixture.away_score:
                points[fixture.away_team] += 3
            else:
                points[fixture.home_team] += 1
                points[fixture.away_team] += 1
        strength = [points[team] / games[team] if games[team] else 1.0 for team in teams]
        opponent_ease = {
            team: 100 - percentile
            for team, percentile in zip(teams, percentile_ranks(strength))
        }
        future_by_team: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for fixture in fixtures:
            if not cutoff < fixture.gameweek <= cutoff + horizon:
                continue
            future_by_team[fixture.home_team].append(
                (fixture.gameweek, min(100.0, opponent_ease[fixture.away_team] + 5))
            )
            future_by_team[fixture.away_team].append(
                (fixture.gameweek, max(0.0, opponent_ease[fixture.home_team] - 5))
            )
        scores = {}
        for team in teams:
            future = sorted(future_by_team.get(team, []))
            values = [value for _, value in future]
            if not values:
                scores[team] = 50.0
                continue
            weights = HORIZON_WEIGHTS[horizon][: len(values)]
            scores[team] = sum(
                value * weight for value, weight in zip(values, weights)
            ) / sum(weights)
        return scores

    @classmethod
    def _build_candidates(
        cls,
        rows_by_gameweek: Mapping[int, Sequence[BacktestPlayerGameweekModel]],
        fixtures: Sequence[BacktestFixtureModel],
        historical_scores: Mapping[tuple[str, str], float],
        cutoff: int,
        horizon: int,
    ) -> tuple[list[RecommendationCandidate], dict[int, BacktestPlayerGameweekModel]]:
        current_rows = list(rows_by_gameweek.get(cutoff, []))
        current_player_ids = {row.player_id for row in current_rows}
        past_by_player: dict[int, list[BacktestPlayerGameweekModel]] = defaultdict(list)
        for gameweek in range(1, cutoff + 1):
            for row in rows_by_gameweek.get(gameweek, []):
                if row.player_id in current_player_ids:
                    past_by_player[row.player_id].append(row)
        fixture_scores = cls._fixture_scores_as_of(fixtures, cutoff, horizon)
        candidates: list[RecommendationCandidate] = []
        metadata: dict[int, BacktestPlayerGameweekModel] = {}
        for player_id, rows in past_by_player.items():
            latest = max(
                rows,
                key=lambda row: (
                    row.gameweek,
                    row.kickoff_time or datetime.min.replace(tzinfo=timezone.utc),
                    row.fixture_id,
                ),
            )
            metadata[player_id] = latest
            minutes = sum(row.minutes for row in rows)
            total_points = sum(row.total_points for row in rows)
            appearances = sum(row.minutes > 0 for row in rows)
            recent_points_by_gw = defaultdict(int)
            for row in rows:
                recent_points_by_gw[row.gameweek] += row.total_points
            recent_gameweeks = range(max(1, cutoff - 4), cutoff + 1)
            form = mean(recent_points_by_gw.get(gameweek, 0) for gameweek in recent_gameweeks)
            xg = sum(row.expected_goals for row in rows)
            xa = sum(row.expected_assists for row in rows)
            xgi = sum(row.expected_goal_involvements for row in rows)
            ict = sum(row.ict_index for row in rows)
            starts = sum(int(row.starts or 0) for row in rows)
            clean_sheets = sum(int(row.clean_sheets or 0) for row in rows)
            expected_goals_conceded = sum(
                float(row.expected_goals_conceded or 0.0) for row in rows
            )
            defensive_contribution = sum(
                int(row.defensive_contribution or 0) for row in rows
            )
            yellow_cards = sum(int(row.yellow_cards or 0) for row in rows)
            red_cards = sum(int(row.red_cards or 0) for row in rows)
            penalties_missed = sum(int(row.penalties_missed or 0) for row in rows)
            goals = sum(row.goals for row in rows)
            assists = sum(row.assists for row in rows)
            ppm = total_points / appearances if appearances else 0.0
            history = historical_scores.get(
                (latest.normalized_name, latest.position), 50.0
            )
            metrics = {
                "attacking_output": xgi * 90 / minutes if minutes else 0.0,
                "bonus": float(sum(row.bonus for row in rows)),
                "fixture": fixture_scores.get(latest.team, 50.0),
                "form": form,
                "history": history,
                "ict": ict * 90 / minutes if minutes else 0.0,
                "minutes": min(100.0, minutes / (cutoff * 90) * 100),
                "ownership": float(latest.selected),
                "ppm": ppm,
                "saves": float(sum(row.saves for row in rows)),
                "value": ppm / latest.price if latest.price else 0.0,
                "xg": xg * 90 / minutes if minutes else 0.0,
                "xgi": xgi * 90 / minutes if minutes else 0.0,
                # Phase E candidate signals. They are calculated strictly
                # from rows at or before this cutoff; future outcomes are
                # joined only after rankings have been frozen.
                "minutes_played": float(minutes),
                "xgc_per_90": (
                    expected_goals_conceded * 90 / minutes if minutes else 0.0
                ),
                "saves_per_90": (
                    sum(row.saves for row in rows) * 90 / minutes if minutes else 0.0
                ),
                "clean_sheet_rate": clean_sheets / starts if starts else 0.0,
                "defensive_contribution_per_90": (
                    defensive_contribution * 90 / minutes if minutes else 0.0
                ),
                "xg_per_90": xg * 90 / minutes if minutes else 0.0,
                "xgi_per_90": xgi * 90 / minutes if minutes else 0.0,
                "goals_per_90": goals * 90 / minutes if minutes else 0.0,
                "assists_per_90": assists * 90 / minutes if minutes else 0.0,
                "conversion_rate": (
                    (goals + 0.15 * 3.0) / (xg + 3.0)
                    if latest.position == "FWD"
                    else 0.0
                ),
                "bonus_points": float(sum(row.bonus for row in rows)),
                "discipline_risk_per_90": (
                    (yellow_cards + 3 * red_cards) * 90 / minutes
                    if minutes
                    else 0.0
                ),
                "ict_per_90": ict * 90 / minutes if minutes else 0.0,
                "penalties_missed": float(penalties_missed),
            }
            candidates.append(
                RecommendationCandidate(
                    player_id=player_id,
                    position=latest.position,
                    metrics=metrics,
                    confidence=min(1.0, minutes / 270),
                    availability_penalty=1.0,
                )
            )
        return candidates, metadata

    def get_status(self) -> BacktestStatus:
        with self.database.session() as session:
            repository = FPLRepository(session)
            return BacktestStatus(
                gameweek_rows=repository.count(BacktestPlayerGameweekModel),
                fixture_rows=repository.count(BacktestFixtureModel),
                prediction_rows=repository.count(BacktestPredictionModel),
                runs=repository.count(BacktestRunModel),
            )

    def list_runs(self, season: str = BACKTEST_SEASON) -> list[BacktestRunSummary]:
        with self.database.session() as session:
            rows = FPLRepository(session).list_backtest_runs(season)
            return [
                BacktestRunSummary(
                    season=row.season,
                    horizon=row.horizon,
                    model_version=row.model_version,
                    gameweeks=row.gameweek_count,
                    predictions=row.prediction_count,
                    mae_percentile=row.mae_percentile,
                    spearman=row.spearman,
                    top_10_hit_rate=row.top_10_hit_rate,
                    average_actual_points_top_10=row.average_actual_points_top_10,
                    first_gameweek=row.first_as_of_gameweek,
                    last_gameweek=row.last_as_of_gameweek,
                    limitations=row.limitations,
                )
                for row in rows
            ]

    def list_predictions(
        self,
        season: str,
        horizon: int,
        model_version: str,
        as_of_gameweek: int,
    ) -> list[BacktestPredictionView]:
        with self.database.session() as session:
            rows = FPLRepository(session).list_backtest_predictions(
                season, horizon, model_version, as_of_gameweek
            )
            return [
                BacktestPredictionView(
                    as_of_gameweek=row.as_of_gameweek,
                    player=row.player_name,
                    position=row.position,
                    recommendation_score=row.recommendation_score,
                    predicted_rank=row.predicted_rank,
                    actual_points=row.actual_points,
                    actual_percentile=row.actual_percentile,
                    actual_rank=row.actual_rank,
                )
                for row in rows
            ]

    @staticmethod
    def _summarize_position_predictions(
        predictions: Sequence[BacktestPredictionModel],
    ) -> PositionalMetricSummary | None:
        """Summarise only like-for-like cutoff rankings for one FPL position."""
        if not predictions:
            return None
        by_cutoff: dict[int, list[BacktestPredictionModel]] = defaultdict(list)
        for prediction in predictions:
            by_cutoff[int(prediction.as_of_gameweek)].append(prediction)
        mae_values: list[float] = []
        spearman_values: list[float] = []
        hit_rates: list[float] = []
        top_points: list[float] = []
        for group in by_cutoff.values():
            if len(group) < 2:
                continue
            ordered_prediction = sorted(
                group,
                key=lambda item: (int(item.predicted_rank), int(item.player_id)),
            )
            ordered_actual = sorted(
                group,
                key=lambda item: (-int(item.actual_points), int(item.player_id)),
            )
            top_count = min(10, len(group))
            predicted_top = {item.player_id for item in ordered_prediction[:top_count]}
            actual_top = {item.player_id for item in ordered_actual[:top_count]}
            mae_values.extend(
                abs(float(item.recommendation_score) - float(item.actual_percentile))
                for item in group
            )
            spearman_values.append(
                spearman_rank_correlation(
                    [float(item.recommendation_score) for item in group],
                    [float(item.actual_points) for item in group],
                )
            )
            hit_rates.append(len(predicted_top & actual_top) / top_count * 100)
            top_points.append(
                mean(float(item.actual_points) for item in ordered_prediction[:top_count])
            )
        if not spearman_values:
            return None
        return PositionalMetricSummary(
            cutoffs=len(spearman_values),
            predictions=len(predictions),
            mae_percentile=round(mean(mae_values), 4),
            spearman=round(mean(spearman_values), 4),
            top_10_hit_rate=round(mean(hit_rates), 2),
            average_actual_points_top_10=round(mean(top_points), 3),
        )

    @staticmethod
    def _candidate_feature_coverage(
        rows: Sequence[BacktestPlayerGameweekModel],
    ) -> dict[str, tuple[float, tuple[str, ...]]]:
        """Return the lowest required official-field coverage per position.

        This is deliberately conservative: a candidate cannot be promoted if a
        position relies on a mostly absent historical field, even if a neutral
        fallback would make a numerical backtest run possible.
        """
        required_fields = {
            "GK": (
                "minutes", "expected_goals_conceded", "saves", "clean_sheets",
                "starts", "bonus", "yellow_cards", "red_cards",
            ),
            "DEF": (
                "minutes", "expected_goals_conceded", "clean_sheets", "starts",
                "expected_goal_involvements", "defensive_contribution", "bonus",
                "yellow_cards", "red_cards",
            ),
            "MID": (
                "minutes", "expected_goal_involvements", "goals", "assists",
                "clean_sheets", "starts", "bonus", "yellow_cards", "red_cards",
                "ict_index",
            ),
            "FWD": (
                "minutes", "expected_goals", "expected_goal_involvements", "goals",
                "assists", "bonus", "yellow_cards", "red_cards", "penalties_missed",
            ),
        }
        by_position: dict[str, list[BacktestPlayerGameweekModel]] = defaultdict(list)
        for row in rows:
            by_position[str(row.position)].append(row)
        coverage: dict[str, tuple[float, tuple[str, ...]]] = {}
        for position, fields in required_fields.items():
            position_rows = by_position.get(position, [])
            if not position_rows:
                coverage[position] = (0.0, fields)
                continue
            missing = tuple(
                field
                for field in fields
                if any(getattr(row, field, None) is None for row in position_rows)
            )
            field_rates = [
                sum(getattr(row, field, None) is not None for row in position_rows)
                / len(position_rows)
                for field in fields
            ]
            coverage[position] = (min(field_rates), missing)
        return coverage

    def get_positional_candidate_validation_report(
        self,
        season: str = BACKTEST_SEASON,
        horizon: int = 5,
    ) -> PositionalCandidateValidationReport:
        """Compare the experimental positional candidate to production, fail closed."""
        candidate_version, production_version, _, policy = load_positional_candidate_model()
        production_model_version = f"production-{production_version}"
        with self.database.session() as session:
            repository = FPLRepository(session)
            base_predictions = repository.list_backtest_predictions(
                season, horizon, production_model_version
            )
            candidate_predictions = repository.list_backtest_predictions(
                season, horizon, candidate_version
            )
            gameweek_rows = repository.list_backtest_player_gameweeks(season)

        base_by_position: dict[str, list[BacktestPredictionModel]] = defaultdict(list)
        candidate_by_position: dict[str, list[BacktestPredictionModel]] = defaultdict(list)
        for prediction in base_predictions:
            base_by_position[str(prediction.position)].append(prediction)
        for prediction in candidate_predictions:
            candidate_by_position[str(prediction.position)].append(prediction)
        coverage = self._candidate_feature_coverage(gameweek_rows)

        evaluations: list[PositionalCandidateEvaluation] = []
        any_improvement = False
        for position in ("GK", "DEF", "MID", "FWD"):
            base = self._summarize_position_predictions(base_by_position[position])
            candidate = self._summarize_position_predictions(
                candidate_by_position[position]
            )
            coverage_rate, missing_fields = coverage[position]
            reasons: list[str] = []
            if base is None or candidate is None:
                reasons.append("Production or candidate predictions are not available for this position.")
            else:
                if min(base.cutoffs, candidate.cutoffs) < policy.minimum_cutoffs:
                    reasons.append(
                        f"Only {min(base.cutoffs, candidate.cutoffs)} comparable cutoffs; minimum is {policy.minimum_cutoffs}."
                    )
                if min(base.predictions, candidate.predictions) < policy.minimum_predictions_per_position:
                    reasons.append(
                        f"Only {min(base.predictions, candidate.predictions)} predictions; minimum is {policy.minimum_predictions_per_position}."
                    )
                if candidate.mae_percentile - base.mae_percentile > policy.maximum_mae_increase:
                    reasons.append("Candidate MAE worsens beyond the permitted tolerance.")
                if candidate.spearman - base.spearman < -policy.maximum_spearman_decrease:
                    reasons.append("Candidate Spearman declines beyond the permitted tolerance.")
                if candidate.top_10_hit_rate - base.top_10_hit_rate < -policy.maximum_top_10_hit_rate_decrease:
                    reasons.append("Candidate top-10 hit rate declines beyond the permitted tolerance.")
                if candidate.average_actual_points_top_10 - base.average_actual_points_top_10 < -policy.maximum_top_10_points_decrease:
                    reasons.append("Candidate top-10 points decline beyond the permitted tolerance.")
                any_improvement = any_improvement or any(
                    (
                        candidate.mae_percentile < base.mae_percentile,
                        candidate.spearman > base.spearman,
                        candidate.top_10_hit_rate > base.top_10_hit_rate,
                        candidate.average_actual_points_top_10 > base.average_actual_points_top_10,
                    )
                )
            if coverage_rate < policy.minimum_feature_coverage:
                reasons.append(
                    f"Official historical feature coverage is {coverage_rate:.0%}; minimum is {policy.minimum_feature_coverage:.0%}."
                )
            if missing_fields:
                reasons.append(
                    "Missing official historical fields: " + ", ".join(missing_fields) + "."
                )
            evaluations.append(
                PositionalCandidateEvaluation(
                    position=position,
                    baseline=base,
                    candidate=candidate,
                    feature_coverage=round(coverage_rate, 4),
                    gate_passed=not reasons,
                    reasons=tuple(reasons),
                )
            )

        report_reasons = [
            f"{item.position}: {reason}"
            for item in evaluations
            for reason in item.reasons
        ]
        if policy.require_at_least_one_improvement and not any_improvement:
            report_reasons.append("Candidate does not improve any tracked position-level metric.")
        quantitative_gates_passed = not report_reasons
        production_active = quantitative_gates_passed and policy.production_activation_approved
        if quantitative_gates_passed and not policy.production_activation_approved:
            report_reasons.append(
                "Quantitative gates passed, but explicit production approval remains false."
            )
        return PositionalCandidateValidationReport(
            season=season,
            horizon=horizon,
            production_version=production_model_version,
            candidate_version=candidate_version,
            evaluations=tuple(evaluations),
            policy=policy,
            quantitative_gates_passed=quantitative_gates_passed,
            production_active=production_active,
            reasons=tuple(report_reasons),
        )

    def get_schedule_validation_report(self) -> ScheduleValidationReport:
        """Evaluate Phase F inputs and fail closed when history is insufficient."""
        policy, forecasts = load_schedule_backtest_config()
        with self.database.session() as session:
            repository = FPLRepository(session)
            fixtures = repository.list_backtest_fixtures(BACKTEST_SEASON)
            player_gameweeks = repository.list_backtest_player_gameweeks(BACKTEST_SEASON)
            runs = repository.list_backtest_runs(BACKTEST_SEASON)
            production_runs = [
                run for run in runs if str(run.model_version).startswith("production-")
            ]
            predictions = [
                prediction
                for run in production_runs
                for prediction in repository.list_backtest_predictions(
                    run.season, run.horizon, run.model_version
                )
            ]
        outcomes = reconstruct_historical_schedule_outcomes(fixtures)
        eligible_pairs = eligible_historical_forecasts(forecasts, fixtures, outcomes)
        comparison = compare_schedule_adjusted_rankings(
            predictions,
            player_gameweeks,
            (forecast for forecast, _ in eligible_pairs),
            policy,
        )
        return validate_schedule_adjustment(
            policy,
            outcomes,
            forecasts,
            fixtures,
            comparison,
        )


def get_backtesting_service(
    database_path: str = str(DATABASE_PATH),
) -> BacktestingService:
    settings = load_app_settings()
    return _get_cached_backtesting_service(
        database_path,
        settings.historical_base_url,
        settings.request_timeout_seconds,
        BACKTEST_MODELS_PATH.stat().st_mtime_ns,
        POSITIONAL_CANDIDATE_CONFIG_PATH.stat().st_mtime_ns,
    )


@lru_cache(maxsize=4)
def _get_cached_backtesting_service(
    database_path: str,
    base_url: str,
    timeout_seconds: float,
    model_config_mtime: int,
    positional_candidate_config_mtime: int,
) -> BacktestingService:
    del model_config_mtime, positional_candidate_config_mtime
    return BacktestingService(
        database=get_database(database_path),
        client=HistoricalDataClient(base_url, timeout_seconds),
    )
