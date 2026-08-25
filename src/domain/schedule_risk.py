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


class CompetitionStage(str, Enum):
    """Competition stages represented in the official calendar."""

    QUALIFYING_PLAY_OFF = "qualifying_play_off"
    LEAGUE_PHASE = "league_phase"
    KNOCKOUT_PLAY_OFF = "knockout_play_off"
    ROUND_OF_16 = "round_of_16"
    QUARTER_FINAL = "quarter_final"
    SEMI_FINAL = "semi_final"
    FINAL = "final"


class ParticipationStatus(str, Enum):
    """How certain a club's entry in a competition is at the snapshot time."""

    CONFIRMED = "confirmed"
    CONDITIONAL = "conditional"


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
