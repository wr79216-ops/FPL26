"""Domain contracts shared across API, database, and service layers."""

from src.domain.contracts import (
    CurrentPlayerStatsRecord,
    FixtureRecord,
    GameweekHistoryRecord,
    PlayerRecord,
    Position,
    RecommendationScoreRecord,
    TeamRecord,
)
from src.domain.schedule_risk import (
    CandidateRescheduleSlot,
    CompetitionCode,
    CompetitionEvent,
    CompetitionStage,
    FixtureRiskScenario,
    GameweekRiskSummary,
    ParticipationStatus,
    ScenarioOutcome,
    ScheduleRiskStatus,
    StructuralFixtureClash,
    TeamCompetitionEntry,
)

__all__ = [
    "CurrentPlayerStatsRecord",
    "FixtureRecord",
    "GameweekHistoryRecord",
    "PlayerRecord",
    "Position",
    "RecommendationScoreRecord",
    "TeamRecord",
    "CandidateRescheduleSlot",
    "CompetitionCode",
    "CompetitionEvent",
    "CompetitionStage",
    "FixtureRiskScenario",
    "GameweekRiskSummary",
    "ParticipationStatus",
    "ScenarioOutcome",
    "ScheduleRiskStatus",
    "StructuralFixtureClash",
    "TeamCompetitionEntry",
]
