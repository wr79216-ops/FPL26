"""SQLAlchemy models for the Phase 2 baseline schema."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SchemaMetadataModel(Base):
    __tablename__ = "schema_metadata"

    metadata_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TeamModel(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    short_name: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_overall_home: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_overall_away: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_attack_home: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_attack_away: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_defence_home: Mapped[int] = mapped_column(Integer, nullable=False)
    strength_defence_away: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PlayerModel(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    second_name: Mapped[str] = mapped_column(String(100), nullable=False)
    web_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), nullable=False, index=True)
    position_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    news: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[float] = mapped_column(Float, nullable=False)
    ownership: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class FixtureModel(Base):
    __tablename__ = "fixtures"

    fixture_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), nullable=False)
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    home_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    away_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    finished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CurrentPlayerStatsModel(Base):
    __tablename__ = "player_current_stats"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True
    )
    gameweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    starts: Mapped[int] = mapped_column(Integer, nullable=False)
    goals: Mapped[int] = mapped_column(Integer, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, nullable=False)
    clean_sheets: Mapped[int] = mapped_column(Integer, nullable=False)
    saves: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    bps: Mapped[int] = mapped_column(Integer, nullable=False)
    influence: Mapped[float] = mapped_column(Float, nullable=False)
    creativity: Mapped[float] = mapped_column(Float, nullable=False)
    threat: Mapped[float] = mapped_column(Float, nullable=False)
    ict_index: Mapped[float] = mapped_column(Float, nullable=False)
    expected_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_assists: Mapped[float] = mapped_column(Float, nullable=False)
    expected_goal_involvements: Mapped[float] = mapped_column(Float, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    points_per_game: Mapped[float] = mapped_column(Float, nullable=False)
    form: Mapped[float] = mapped_column(Float, nullable=False)
    selected_by_percent: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transfers_in_event: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    goals_conceded: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    penalties_saved: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    penalties_missed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    defensive_contribution: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expected_goals_conceded: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class GameweekSnapshotModel(Base):
    __tablename__ = "gameweek_snapshots"
    __table_args__ = (
        UniqueConstraint("season", "gameweek", "player_id", name="uq_gameweek_snapshot"),
    )

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[str] = mapped_column(String(9), nullable=False, index=True)
    gameweek: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id"), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    ownership: Mapped[float] = mapped_column(Float, nullable=False)
    form: Mapped[float] = mapped_column(Float, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_assists: Mapped[float] = mapped_column(Float, nullable=False)
    expected_goal_involvements: Mapped[float] = mapped_column(Float, nullable=False)
    ict_index: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GameweekHistoryModel(Base):
    __tablename__ = "player_gameweek_history"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True
    )
    season: Mapped[str] = mapped_column(String(9), primary_key=True)
    gameweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(
        ForeignKey("fixtures.fixture_id"), primary_key=True
    )
    opponent_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), nullable=False)
    was_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    goals: Mapped[int] = mapped_column(Integer, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, nullable=False)
    clean_sheets: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    bps: Mapped[int] = mapped_column(Integer, nullable=False)
    xg: Mapped[float] = mapped_column(Float, nullable=False)
    xa: Mapped[float] = mapped_column(Float, nullable=False)
    xgi: Mapped[float] = mapped_column(Float, nullable=False)
    xgc: Mapped[float] = mapped_column(Float, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    goals_conceded: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    penalties_saved: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    penalties_missed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    defensive_contribution: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PlayerHistorySyncModel(Base):
    __tablename__ = "player_history_sync"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True
    )
    season: Mapped[str] = mapped_column(String(9), nullable=False)
    gameweek: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HistoricalPlayerSeasonModel(Base):
    __tablename__ = "historical_player_seasons"
    __table_args__ = (
        UniqueConstraint(
            "source", "season", "source_player_key", name="uq_historical_player_season"
        ),
    )

    historical_player_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(9), nullable=False, index=True)
    source_player_key: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    second_name: Mapped[str] = mapped_column(String(150), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    position: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    goals: Mapped[int] = mapped_column(Integer, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, nullable=False)
    clean_sheets: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    points_per_90: Mapped[float] = mapped_column(Float, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HistoricalIdentityMappingModel(Base):
    __tablename__ = "historical_identity_mappings"

    historical_player_id: Mapped[int] = mapped_column(
        ForeignKey("historical_player_seasons.historical_player_id"), primary_key=True
    )
    current_player_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("players.player_id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlayerHistoricalScoreModel(Base):
    __tablename__ = "player_historical_scores"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    seasons_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    weighted_points_per_90: Mapped[float] = mapped_column(Float, nullable=False)
    consistency_score: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestPlayerGameweekModel(Base):
    __tablename__ = "backtest_player_gameweeks"

    season: Mapped[str] = mapped_column(String(9), primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    position: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    team: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    goals: Mapped[int] = mapped_column(Integer, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    saves: Mapped[int] = mapped_column(Integer, nullable=False)
    ict_index: Mapped[float] = mapped_column(Float, nullable=False)
    expected_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_assists: Mapped[float] = mapped_column(Float, nullable=False)
    expected_goal_involvements: Mapped[float] = mapped_column(Float, nullable=False)
    selected: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestFixtureModel(Base):
    __tablename__ = "backtest_fixtures"

    season: Mapped[str] = mapped_column(String(9), primary_key=True)
    fixture_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    home_team: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    home_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    away_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestPredictionModel(Base):
    __tablename__ = "backtest_predictions"

    season: Mapped[str] = mapped_column(String(9), primary_key=True)
    as_of_gameweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(50), primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    recommendation_score: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_points: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_percentile: Mapped[float] = mapped_column(Float, nullable=False)
    actual_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestRunModel(Base):
    __tablename__ = "backtest_runs"

    season: Mapped[str] = mapped_column(String(9), primary_key=True)
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(50), primary_key=True)
    first_as_of_gameweek: Mapped[int] = mapped_column(Integer, nullable=False)
    last_as_of_gameweek: Mapped[int] = mapped_column(Integer, nullable=False)
    gameweek_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mae_percentile: Mapped[float] = mapped_column(Float, nullable=False)
    spearman: Mapped[float] = mapped_column(Float, nullable=False)
    top_10_hit_rate: Mapped[float] = mapped_column(Float, nullable=False)
    average_actual_points_top_10: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)


class RecommendationScoreModel(Base):
    __tablename__ = "recommendation_scores"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True
    )
    gameweek: Mapped[int] = mapped_column(Integer, primary_key=True)
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(30), primary_key=True)
    form_score: Mapped[float] = mapped_column(Float, nullable=False)
    fixture_score: Mapped[float] = mapped_column(Float, nullable=False)
    expected_score: Mapped[float] = mapped_column(Float, nullable=False)
    minutes_score: Mapped[float] = mapped_column(Float, nullable=False)
    history_score: Mapped[float] = mapped_column(Float, nullable=False)
    value_score: Mapped[float] = mapped_column(Float, nullable=False)
    bonus_score: Mapped[float] = mapped_column(Float, nullable=False)
    ownership_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
