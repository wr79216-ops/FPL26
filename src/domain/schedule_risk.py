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


class ProbabilityConfidence(str, Enum):
    """Confidence shown separately from the probability value."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProbabilityTargetType(str, Enum):
    """The schedule-risk object a controlled probability input refers to."""

    TEAM_PROGRESSION = "team_progression"
    SCENARIO = "scenario"
    SLOT_ALLOCATION = "slot_allocation"


class ProjectionMethod(str, Enum):
    """Method used to calculate a schedule-risk probability."""

    INDEPENDENT_UNION = "independent_union"
    SCENARIO_TREE = "scenario_tree"


def _require_http_url(value: str, field_name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


def _require_probability(value: float, field_name: str) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


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


@dataclass(frozen=True)
class ScheduleCongestionLeader:
    """A transparent congestion signal for one club over the next 14 days."""

    team_id: int
    team_name: str
    team_code: str
    matches_next_14_days: int
    shortest_rest_days: int | None
    short_rest_count: int
    european_competition: str | None
    congestion_score: float
    explanation: str

    def __post_init__(self) -> None:
        if self.team_id <= 0:
            raise ValueError("team_id must be positive")
        if not self.team_name.strip() or not self.team_code.strip():
            raise ValueError("team name and team code are required")
        if self.matches_next_14_days < 0 or self.short_rest_count < 0:
            raise ValueError("match and rest counts cannot be negative")
        if self.shortest_rest_days is not None and self.shortest_rest_days < 0:
            raise ValueError("shortest_rest_days cannot be negative")
        if not 0 <= self.congestion_score <= 100:
            raise ValueError("congestion_score must be between 0 and 100")
        if not self.explanation.strip():
            raise ValueError("congestion explanation is required")


@dataclass(frozen=True)
class SquadSchedulePlayerExposure:
    """Schedule-risk exposure for a single imported, session-only squad pick."""

    player_id: int
    player_name: str
    team_name: str
    team_id: int | None
    position: str
    squad_weight: float
    confirmed_blank_gameweeks: tuple[int, ...]
    projected_blank_exposure: float
    confirmed_extra_fixtures: float
    projected_extra_fixtures: float
    congestion_score: float | None
    explanation: str

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("player_id must be positive")
        if not self.player_name.strip() or not self.team_name.strip() or not self.position.strip():
            raise ValueError("player identity fields are required")
        if self.team_id is not None and self.team_id <= 0:
            raise ValueError("team_id must be positive when supplied")
        if self.squad_weight <= 0:
            raise ValueError("squad_weight must be positive")
        if any(not 1 <= gameweek <= 38 for gameweek in self.confirmed_blank_gameweeks):
            raise ValueError("confirmed blank gameweeks must be between 1 and 38")
        for value, name in (
            (self.projected_blank_exposure, "projected_blank_exposure"),
            (self.confirmed_extra_fixtures, "confirmed_extra_fixtures"),
            (self.projected_extra_fixtures, "projected_extra_fixtures"),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.congestion_score is not None and not 0 <= self.congestion_score <= 100:
            raise ValueError("congestion_score must be between 0 and 100")
        if not self.explanation.strip():
            raise ValueError("exposure explanation is required")

    @property
    def expected_blank_fixtures(self) -> float:
        return round(
            self.squad_weight * len(self.confirmed_blank_gameweeks)
            + self.projected_blank_exposure,
            3,
        )

    @property
    def expected_extra_fixtures(self) -> float:
        return round(
            self.confirmed_extra_fixtures + self.projected_extra_fixtures,
            3,
        )


@dataclass(frozen=True)
class SquadScheduleExposure:
    """Auditable schedule-risk summary for one imported squad and GW window."""

    manager_id: int
    gameweeks: tuple[int, ...]
    expected_blank_starters: float
    expected_extra_fixtures: float
    affected_players: tuple[SquadSchedulePlayerExposure, ...]
    unresolved_player_ids: tuple[int, ...]
    as_of: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.manager_id <= 0:
            raise ValueError("manager_id must be positive")
        if not self.gameweeks or any(not 1 <= gameweek <= 38 for gameweek in self.gameweeks):
            raise ValueError("gameweeks must be a non-empty GW1-GW38 list")
        if self.expected_blank_starters < 0 or self.expected_extra_fixtures < 0:
            raise ValueError("expected schedule exposures cannot be negative")
        if len(set(self.unresolved_player_ids)) != len(self.unresolved_player_ids):
            raise ValueError("unresolved_player_ids cannot contain duplicates")
        _require_timezone(self.as_of, "as_of")
        if not self.explanation.strip():
            raise ValueError("exposure explanation is required")


@dataclass(frozen=True)
class AuditableProbabilityInput:
    """A manually supplied probability with evidence and a hard expiry."""

    input_id: str
    target_type: ProbabilityTargetType
    target_id: str
    probability: float
    confidence: ProbabilityConfidence
    source_url: str
    as_of: datetime
    expires_at: datetime
    note: str

    def __post_init__(self) -> None:
        if not self.input_id.strip() or not self.target_id.strip() or not self.note.strip():
            raise ValueError("input_id, target_id, and note are required")
        _require_probability(self.probability, "probability")
        _require_http_url(self.source_url, "source_url")
        _require_timezone(self.as_of, "as_of")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at must be after as_of")


@dataclass(frozen=True)
class FractionalOddsOutcome:
    """One outcome in a licensed fractional-odds market."""

    outcome_id: str
    numerator: float
    denominator: float

    def __post_init__(self) -> None:
        if not self.outcome_id.strip():
            raise ValueError("outcome_id is required")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("fractional odds numerator and denominator must be positive")

    @property
    def implied_probability(self) -> float:
        return self.denominator / (self.numerator + self.denominator)


@dataclass(frozen=True)
class LicensedOddsMarket:
    """Provider-supplied odds usable only when the licence is recorded."""

    market_id: str
    outcomes: tuple[FractionalOddsOutcome, ...]
    provider_id: str
    licence_reference: str
    source_url: str
    as_of: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.market_id.strip() or not self.provider_id.strip():
            raise ValueError("market_id and provider_id are required")
        if not self.licence_reference.strip():
            raise ValueError("licensed odds require a licence_reference")
        if len(self.outcomes) < 2:
            raise ValueError("licensed odds market requires at least two outcomes")
        if len({outcome.outcome_id for outcome in self.outcomes}) != len(self.outcomes):
            raise ValueError("licensed odds outcomes cannot contain duplicate IDs")
        _require_http_url(self.source_url, "source_url")
        _require_timezone(self.as_of, "as_of")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at must be after as_of")


@dataclass(frozen=True)
class NormalizedOddsProbability:
    """An overround-adjusted probability from a licensed odds market."""

    market_id: str
    outcome_id: str
    probability: float
    normalisation_power: float

    def __post_init__(self) -> None:
        if not self.market_id.strip() or not self.outcome_id.strip():
            raise ValueError("market_id and outcome_id are required")
        _require_probability(self.probability, "probability")
        if self.normalisation_power <= 0:
            raise ValueError("normalisation_power must be positive")


@dataclass(frozen=True)
class FixtureProbabilityProjection:
    """An auditable blank probability for a structurally-clashing fixture."""

    fixture_id: int
    source_gameweek: int
    blank_probability: float
    method: ProjectionMethod
    confidence: ProbabilityConfidence
    input_ids: tuple[str, ...]
    as_of: datetime
    expires_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.fixture_id <= 0 or not 1 <= self.source_gameweek <= 38:
            raise ValueError("fixture_id and source_gameweek must be valid")
        _require_probability(self.blank_probability, "blank_probability")
        if not self.input_ids or len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("input_ids must be a non-empty unique list")
        _require_timezone(self.as_of, "as_of")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at must be after as_of")
        if not self.explanation.strip():
            raise ValueError("projection explanation is required")


@dataclass(frozen=True)
class DoubleGameweekProbabilityProjection:
    """An auditable probability of a rescheduled fixture creating a DGW."""

    fixture_id: int
    target_gameweek: int
    double_probability: float
    confidence: ProbabilityConfidence
    input_ids: tuple[str, ...]
    as_of: datetime
    expires_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.fixture_id <= 0 or not 1 <= self.target_gameweek <= 38:
            raise ValueError("fixture_id and target_gameweek must be valid")
        _require_probability(self.double_probability, "double_probability")
        if not self.input_ids or len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("input_ids must be a non-empty unique list")
        _require_timezone(self.as_of, "as_of")
        _require_timezone(self.expires_at, "expires_at")
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at must be after as_of")
        if not self.explanation.strip():
            raise ValueError("projection explanation is required")
