"""Typed, source-independent records passed between application layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Position(str, Enum):
    """Supported Fantasy Premier League positions."""

    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


def _require_positive(value: int, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _require_percentage(value: float, field_name: str) -> None:
    if not 0 <= value <= 100:
        raise ValueError(f"{field_name} must be between 0 and 100")


@dataclass(frozen=True)
class TeamRecord:
    team_id: int
    name: str
    short_name: str
    strength: int
    strength_overall_home: int
    strength_overall_away: int
    strength_attack_home: int
    strength_attack_away: int
    strength_defence_home: int
    strength_defence_away: int

    def __post_init__(self) -> None:
        _require_positive(self.team_id, "team_id")
        if not self.name.strip() or not self.short_name.strip():
            raise ValueError("team name and short_name are required")


@dataclass(frozen=True)
class PlayerRecord:
    player_id: int
    first_name: str
    second_name: str
    web_name: str
    team_id: int
    position_id: int
    position: Position
    status: str
    news: str
    price: float
    ownership: float

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        _require_positive(self.team_id, "team_id")
        _require_positive(self.position_id, "position_id")
        if not self.web_name.strip():
            raise ValueError("web_name is required")
        if self.price <= 0:
            raise ValueError("price must be positive")
        _require_percentage(self.ownership, "ownership")


@dataclass(frozen=True)
class FixtureRecord:
    fixture_id: int
    gameweek: Optional[int]
    home_team_id: int
    away_team_id: int
    kickoff_time: Optional[datetime]
    home_difficulty: int
    away_difficulty: int
    home_score: Optional[int]
    away_score: Optional[int]
    finished: bool
    started: bool

    def __post_init__(self) -> None:
        _require_positive(self.fixture_id, "fixture_id")
        _require_positive(self.home_team_id, "home_team_id")
        _require_positive(self.away_team_id, "away_team_id")
        if self.home_team_id == self.away_team_id:
            raise ValueError("fixture teams must be different")
        for value in (self.home_difficulty, self.away_difficulty):
            if value not in range(1, 6):
                raise ValueError("fixture difficulty must be between 1 and 5")


@dataclass(frozen=True)
class CurrentPlayerStatsRecord:
    player_id: int
    gameweek: int
    minutes: int
    starts: int
    goals: int
    assists: int
    clean_sheets: int
    saves: int
    bonus: int
    bps: int
    influence: float
    creativity: float
    threat: float
    ict_index: float
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    total_points: int
    points_per_game: float
    form: float
    selected_by_percent: float
    price: float
    snapshot_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        if self.gameweek < 0 or self.minutes < 0 or self.starts < 0:
            raise ValueError("gameweek, minutes, and starts cannot be negative")
        _require_percentage(self.selected_by_percent, "selected_by_percent")


@dataclass(frozen=True)
class GameweekSnapshotRecord:
    """A point-in-time copy of the current player values for one gameweek."""

    season: str
    gameweek: int
    player_id: int
    price: float
    ownership: float
    form: float
    total_points: int
    minutes: int
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    ict_index: float
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        if not self.season.strip():
            raise ValueError("season is required")
        if self.gameweek < 0 or self.minutes < 0:
            raise ValueError("gameweek and minutes cannot be negative")
        if self.price <= 0:
            raise ValueError("price must be positive")
        _require_percentage(self.ownership, "ownership")


@dataclass(frozen=True)
class GameweekHistoryRecord:
    player_id: int
    season: str
    gameweek: int
    fixture_id: int
    opponent_team_id: int
    was_home: bool
    minutes: int
    goals: int
    assists: int
    clean_sheets: int
    bonus: int
    bps: int
    xg: float
    xa: float
    xgi: float
    xgc: float
    total_points: int
    value: float

    def __post_init__(self) -> None:
        for field_value, field_name in (
            (self.player_id, "player_id"),
            (self.fixture_id, "fixture_id"),
            (self.opponent_team_id, "opponent_team_id"),
        ):
            _require_positive(field_value, field_name)
        if not self.season.strip():
            raise ValueError("season is required")


@dataclass(frozen=True)
class PlayerHistorySyncRecord:
    player_id: int
    season: str
    gameweek: int
    row_count: int
    checked_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        if not self.season.strip():
            raise ValueError("season is required")
        if self.gameweek < 0 or self.row_count < 0:
            raise ValueError("gameweek and row_count cannot be negative")


@dataclass(frozen=True)
class HistoricalPlayerSeasonRecord:
    source: str
    season: str
    source_player_key: str
    first_name: str
    second_name: str
    display_name: str
    normalized_name: str
    position: Position
    minutes: int
    total_points: int
    goals: int
    assists: int
    clean_sheets: int
    bonus: int
    price: float
    points_per_90: float
    imported_at: datetime

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.season.strip() or not self.source_player_key.strip():
            raise ValueError("historical source, season, and source_player_key are required")
        if not self.display_name.strip() or not self.normalized_name.strip():
            raise ValueError("historical player name is required")
        if self.minutes < 0:
            raise ValueError("historical minutes cannot be negative")
        if self.price <= 0:
            raise ValueError("historical price must be positive")


@dataclass(frozen=True)
class HistoricalIdentityMappingRecord:
    historical_player_id: int
    current_player_id: Optional[int]
    status: str
    match_score: float
    match_method: str
    matched_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.historical_player_id, "historical_player_id")
        if self.current_player_id is not None:
            _require_positive(self.current_player_id, "current_player_id")
        if self.status not in {"MATCHED", "REVIEW", "UNMATCHED"}:
            raise ValueError("historical mapping status is invalid")
        if not 0 <= self.match_score <= 100:
            raise ValueError("historical match_score must be between 0 and 100")


@dataclass(frozen=True)
class PlayerHistoricalScoreRecord:
    player_id: int
    score: float
    seasons_count: int
    total_minutes: int
    weighted_points_per_90: float
    consistency_score: float
    calculated_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        if not 0 <= self.score <= 100 or not 0 <= self.consistency_score <= 100:
            raise ValueError("historical scores must be between 0 and 100")
        if self.seasons_count <= 0 or self.total_minutes < 0:
            raise ValueError("historical score requires a season and non-negative minutes")


@dataclass(frozen=True)
class BacktestPlayerGameweekRecord:
    season: str
    player_id: int
    fixture_id: int
    gameweek: int
    player_name: str
    normalized_name: str
    position: Position
    team: str
    minutes: int
    total_points: int
    goals: int
    assists: int
    bonus: int
    saves: int
    ict_index: float
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    selected: int
    price: float
    kickoff_time: Optional[datetime]

    def __post_init__(self) -> None:
        if not self.season.strip() or not self.player_name.strip() or not self.team.strip():
            raise ValueError("backtest season, player_name, and team are required")
        _require_positive(self.player_id, "player_id")
        _require_positive(self.fixture_id, "fixture_id")
        _require_positive(self.gameweek, "gameweek")
        if self.minutes < 0 or self.selected < 0 or self.price <= 0:
            raise ValueError("backtest minutes/selected cannot be negative and price must be positive")


@dataclass(frozen=True)
class BacktestFixtureRecord:
    season: str
    fixture_id: int
    gameweek: int
    home_team: str
    away_team: str
    home_difficulty: int
    away_difficulty: int
    home_score: Optional[int]
    away_score: Optional[int]
    kickoff_time: Optional[datetime]

    def __post_init__(self) -> None:
        if not self.season.strip() or not self.home_team.strip() or not self.away_team.strip():
            raise ValueError("backtest fixture season and teams are required")
        _require_positive(self.fixture_id, "fixture_id")
        _require_positive(self.gameweek, "gameweek")
        if self.home_team == self.away_team:
            raise ValueError("backtest fixture teams must differ")
        if self.home_difficulty not in range(1, 6) or self.away_difficulty not in range(1, 6):
            raise ValueError("backtest fixture difficulty must be between 1 and 5")


@dataclass(frozen=True)
class BacktestPredictionRecord:
    season: str
    as_of_gameweek: int
    horizon: int
    model_version: str
    player_id: int
    player_name: str
    position: str
    recommendation_score: float
    predicted_rank: int
    actual_points: int
    actual_percentile: float
    actual_rank: int
    calculated_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.as_of_gameweek, "as_of_gameweek")
        _require_positive(self.horizon, "horizon")
        _require_positive(self.player_id, "player_id")
        _require_positive(self.predicted_rank, "predicted_rank")
        _require_positive(self.actual_rank, "actual_rank")
        if not 0 <= self.recommendation_score <= 100:
            raise ValueError("backtest recommendation_score must be between 0 and 100")
        if not 0 <= self.actual_percentile <= 100:
            raise ValueError("backtest actual_percentile must be between 0 and 100")


@dataclass(frozen=True)
class BacktestRunRecord:
    season: str
    horizon: int
    model_version: str
    first_as_of_gameweek: int
    last_as_of_gameweek: int
    gameweek_count: int
    prediction_count: int
    mae_percentile: float
    spearman: float
    top_10_hit_rate: float
    average_actual_points_top_10: float
    calculated_at: datetime
    limitations: str

    def __post_init__(self) -> None:
        _require_positive(self.horizon, "horizon")
        _require_positive(self.gameweek_count, "gameweek_count")
        _require_positive(self.prediction_count, "prediction_count")
        if self.first_as_of_gameweek > self.last_as_of_gameweek:
            raise ValueError("backtest gameweek range is invalid")
        if not 0 <= self.mae_percentile <= 100 or not -1 <= self.spearman <= 1:
            raise ValueError("backtest metrics are out of range")
        if not 0 <= self.top_10_hit_rate <= 100:
            raise ValueError("backtest top_10_hit_rate must be between 0 and 100")


@dataclass(frozen=True)
class RecommendationScoreRecord:
    player_id: int
    gameweek: int
    horizon: int
    form_score: float
    fixture_score: float
    expected_score: float
    minutes_score: float
    history_score: float
    value_score: float
    bonus_score: float
    ownership_score: float
    final_score: float
    model_version: str
    calculated_at: datetime

    def __post_init__(self) -> None:
        _require_positive(self.player_id, "player_id")
        _require_positive(self.horizon, "horizon")
        if not self.model_version.strip():
            raise ValueError("model_version is required")
        scores = (
            self.form_score,
            self.fixture_score,
            self.expected_score,
            self.minutes_score,
            self.history_score,
            self.value_score,
            self.bonus_score,
            self.ownership_score,
            self.final_score,
        )
        if any(not 0 <= score <= 100 for score in scores):
            raise ValueError("recommendation component scores must be between 0 and 100")
