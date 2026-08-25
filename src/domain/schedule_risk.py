"""Typed records for auditable schedule-congestion inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from urllib.parse import urlparse


class CompetitionCode(str, Enum):
    """Competitions that can add congestion or cause a domestic clash."""

    CHAMPIONS_LEAGUE = "champions_league"
    EUROPA_LEAGUE = "europa_league"
    CONFERENCE_LEAGUE = "conference_league"
    EFL_CUP = "efl_cup"
    FA_CUP = "fa_cup"
    INTERNATIONAL_BREAK = "international_break"


class CompetitionStage(str, Enum):
    """Competition stages represented in the official calendar."""

    QUALIFYING_PLAY_OFF = "qualifying_play_off"
    LEAGUE_PHASE = "league_phase"
    KNOCKOUT_PLAY_OFF = "knockout_play_off"
    ROUND_OF_16 = "round_of_16"
    ROUND_2 = "round_2"
    ROUND_3 = "round_3"
    ROUND_4 = "round_4"
    ROUND_5 = "round_5"
    QUARTER_FINAL = "quarter_final"
    SEMI_FINAL = "semi_final"
    FINAL = "final"
    INTERNATIONAL_WINDOW = "international_window"


class ParticipationStatus(str, Enum):
    """How certain a club's entry in a competition is at the snapshot time."""

    CONFIRMED = "confirmed"
    CONDITIONAL = "conditional"


class ScheduleRiskStatus(str, Enum):
    """Deterministic statuses derived from the official FPL fixture allocation."""

    NORMAL = "normal"
    CONFIRMED_BLANK = "confirmed_blank"
    CONFIRMED_DOUBLE = "confirmed_double"


class ScenarioOutcome(str, Enum):
    """Exhaustive progression outcomes for one structurally-clashing fixture."""

    NEITHER_PROGRESS = "neither_progress"
    HOME_ONLY_PROGRESS = "home_only_progress"
    AWAY_ONLY_PROGRESS = "away_only_progress"
    BOTH_PROGRESS = "both_progress"


def _require_http_url(value: str, field_name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


@dataclass(frozen=True)
class CompetitionEvent:
    """A dated official competition window that may affect FPL planning."""

    competition: CompetitionCode
    stage: CompetitionStage
    start_date: date
    end_date: date
    source_url: str
    last_verified_at: datetime
    expires_at: datetime
    clash_matchweek: int | None = None
    active_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("competition event start_date must not be after end_date")
        if self.clash_matchweek is not None and not 1 <= self.clash_matchweek <= 38:
            raise ValueError("clash_matchweek must be between 1 and 38")
        _require_http_url(self.source_url, "source_url")
        _require_timezone(self.last_verified_at, "last_verified_at")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.last_verified_at:
            raise ValueError("expires_at must be after last_verified_at")
        if len(set(self.active_dates)) != len(self.active_dates):
            raise ValueError("active_dates cannot contain duplicates")
        if any(not self.start_date <= item <= self.end_date for item in self.active_dates):
            raise ValueError("active_dates must fall within start_date and end_date")

    def blocks_date(self, candidate_date: date) -> bool:
        """Return whether this official event occupies a candidate date."""
        if self.active_dates:
            return candidate_date in self.active_dates
        return self.start_date <= candidate_date <= self.end_date


@dataclass(frozen=True)
class TeamCompetitionEntry:
    """A verified mapping between a European participant and an FPL team ID."""

    team_code: str
    fpl_team_id: int
    competition: CompetitionCode
    stage: CompetitionStage
    status: ParticipationStatus
    qualification_conditional: bool
    source_url: str
    last_verified_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if len(self.team_code) != 3 or not self.team_code.isupper() or not self.team_code.isalpha():
            raise ValueError("team_code must be a three-letter uppercase FPL short name")
        if self.fpl_team_id <= 0:
            raise ValueError("fpl_team_id must be positive")
        if not isinstance(self.qualification_conditional, bool):
            raise ValueError("qualification_conditional must be a boolean")
        if (self.status is ParticipationStatus.CONDITIONAL) != self.qualification_conditional:
            raise ValueError(
                "qualification_conditional must match whether status is conditional"
            )
        _require_http_url(self.source_url, "source_url")
        _require_timezone(self.last_verified_at, "last_verified_at")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.last_verified_at:
            raise ValueError("expires_at must be after last_verified_at")


@dataclass(frozen=True)
class StructuralFixtureClash:
    """A league fixture occupying a matchweek protected for a cup event."""

    fixture_id: int
    source_gameweek: int
    home_team_id: int
    away_team_id: int
    event: CompetitionEvent
    explanation: str

    def __post_init__(self) -> None:
        if self.fixture_id <= 0:
            raise ValueError("fixture_id must be positive")
        if not 1 <= self.source_gameweek <= 38:
            raise ValueError("source_gameweek must be between 1 and 38")
        if self.home_team_id <= 0 or self.away_team_id <= 0:
            raise ValueError("clash team IDs must be positive")
        if self.home_team_id == self.away_team_id:
            raise ValueError("clash teams must be different")
        if self.event.clash_matchweek != self.source_gameweek:
            raise ValueError("event clash_matchweek must match source_gameweek")
        if not self.explanation.strip():
            raise ValueError("clash explanation is required")


@dataclass(frozen=True)
class CandidateRescheduleSlot:
    """A calendar-feasible midweek, without an attached probability claim."""

    slot_id: str
    fixture_id: int
    source_gameweek: int
    target_gameweek: int
    candidate_date: date
    would_create_double: bool
    explanation: str

    def __post_init__(self) -> None:
        if not self.slot_id.strip() or not self.explanation.strip():
            raise ValueError("slot_id and explanation are required")
        if self.fixture_id <= 0:
            raise ValueError("fixture_id must be positive")
        if not 1 <= self.source_gameweek <= 38 or not 1 <= self.target_gameweek <= 38:
            raise ValueError("slot gameweeks must be between 1 and 38")


@dataclass(frozen=True)
class FixtureRiskScenario:
    """One probability-free branch in a mutually-exclusive fixture scenario tree."""

    scenario_id: str
    scenario_group: str
    fixture_id: int
    outcome: ScenarioOutcome
    progressing_team_ids: tuple[int, ...]
    requires_reschedule: bool
    candidate_slot_ids: tuple[str, ...]
    mutually_exclusive_with: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or not self.scenario_group.strip():
            raise ValueError("scenario_id and scenario_group are required")
        if self.fixture_id <= 0:
            raise ValueError("fixture_id must be positive")
        if len(set(self.progressing_team_ids)) != len(self.progressing_team_ids):
            raise ValueError("progressing_team_ids cannot contain duplicates")
        if any(team_id <= 0 for team_id in self.progressing_team_ids):
            raise ValueError("progressing_team_ids must be positive")
        if not self.requires_reschedule and self.candidate_slot_ids:
            raise ValueError("a non-reschedule branch cannot contain candidate slots")
        if self.scenario_id in self.mutually_exclusive_with:
            raise ValueError("a scenario cannot be mutually exclusive with itself")
        if not self.explanation.strip():
            raise ValueError("scenario explanation is required")


@dataclass(frozen=True)
class GameweekRiskSummary:
    """Official FPL fixture count for one team and one gameweek."""

    team_id: int
    gameweek: int
    status: ScheduleRiskStatus
    fixture_ids: tuple[int, ...]
    source_url: str
    as_of: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.team_id <= 0:
            raise ValueError("team_id must be positive")
        if not 1 <= self.gameweek <= 38:
            raise ValueError("gameweek must be between 1 and 38")
        if len(set(self.fixture_ids)) != len(self.fixture_ids):
            raise ValueError("fixture_ids cannot contain duplicates")
        _require_http_url(self.source_url, "source_url")
        _require_timezone(self.as_of, "as_of")
        if not self.explanation.strip():
            raise ValueError("summary explanation is required")
