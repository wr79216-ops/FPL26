"""Deterministic calendar and fixture engine for the congestion planner.

Phase B detects only official fixture allocation and structural calendar
conflicts. It does not assign probabilities or alter transfer recommendations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from config.settings import (
    COMPETITION_CALENDAR_CONFIG_PATH,
    EUROPEAN_PARTICIPANTS_CONFIG_PATH,
)
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import FixtureRecord, TeamRecord
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
from src.services.application import get_database


OFFICIAL_FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
MIDWEEK_DAYS = {1, 2, 3}


class ScheduleCalendarConfigError(ValueError):
    """Raised when the controlled schedule-risk input is incomplete or unsafe."""


@dataclass(frozen=True)
class ScheduleCalendarCatalog:
    """The complete verified calendar input available to later planner phases."""

    season: str
    events: tuple[CompetitionEvent, ...]
    participants: tuple[TeamCompetitionEntry, ...]


@dataclass(frozen=True)
class PhaseBScheduleSnapshot:
    """Deterministic Phase B outputs, with no probability assignments."""

    catalog: ScheduleCalendarCatalog
    gameweek_risks: tuple[GameweekRiskSummary, ...]
    structural_clashes: tuple[StructuralFixtureClash, ...]
    candidate_slots: tuple[CandidateRescheduleSlot, ...]
    scenarios: tuple[FixtureRiskScenario, ...]


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file) or {}
    except OSError as exc:
        raise ScheduleCalendarConfigError(f"could not read {path.name}") from exc

    if not isinstance(payload, Mapping):
        raise ScheduleCalendarConfigError(f"{path.name} must contain a mapping")
    return payload


def _required(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    value = mapping.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ScheduleCalendarConfigError(f"{context} requires {key}")
    return value


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ScheduleCalendarConfigError(f"{field_name} must be ISO date") from exc
    raise ScheduleCalendarConfigError(f"{field_name} must be ISO date")


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScheduleCalendarConfigError(f"{field_name} must be ISO timestamp") from exc
    else:
        raise ScheduleCalendarConfigError(f"{field_name} must be ISO timestamp")

    if result.tzinfo is None or result.utcoffset() is None:
        raise ScheduleCalendarConfigError(f"{field_name} must include a timezone")
    return result


def _enum(enum_type: type[Any], value: Any, field_name: str) -> Any:
    try:
        return enum_type(str(value))
    except ValueError as exc:
        values = ", ".join(item.value for item in enum_type)
        raise ScheduleCalendarConfigError(
            f"{field_name} must be one of: {values}"
        ) from exc


def _event_from_mapping(raw: Mapping[str, Any], index: int) -> CompetitionEvent:
    context = f"events[{index}]"
    try:
        raw_active_dates = raw.get("active_dates", [])
        if not isinstance(raw_active_dates, list):
            raise ValueError("active_dates must be a list")
        return CompetitionEvent(
            competition=_enum(
                CompetitionCode, _required(raw, "competition", context), f"{context}.competition"
            ),
            stage=_enum(
                CompetitionStage, _required(raw, "stage", context), f"{context}.stage"
            ),
            start_date=_parse_date(_required(raw, "start_date", context), f"{context}.start_date"),
            end_date=_parse_date(_required(raw, "end_date", context), f"{context}.end_date"),
            clash_matchweek=raw.get("clash_matchweek"),
            source_url=str(_required(raw, "source_url", context)),
            last_verified_at=_parse_timestamp(
                _required(raw, "last_verified_at", context), f"{context}.last_verified_at"
            ),
            expires_at=_parse_timestamp(
                _required(raw, "expires_at", context), f"{context}.expires_at"
            ),
            active_dates=tuple(
                _parse_date(value, f"{context}.active_dates")
                for value in raw_active_dates
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ScheduleCalendarConfigError(f"{context} is invalid: {exc}") from exc


def _participant_from_mapping(raw: Mapping[str, Any], index: int) -> TeamCompetitionEntry:
    context = f"participants[{index}]"
    try:
        return TeamCompetitionEntry(
            team_code=str(_required(raw, "team_code", context)),
            fpl_team_id=int(_required(raw, "fpl_team_id", context)),
            competition=_enum(
                CompetitionCode, _required(raw, "competition", context), f"{context}.competition"
            ),
            stage=_enum(
                CompetitionStage, _required(raw, "stage", context), f"{context}.stage"
            ),
            status=_enum(
                ParticipationStatus, _required(raw, "status", context), f"{context}.status"
            ),
            qualification_conditional=raw.get("qualification_conditional"),
            source_url=str(_required(raw, "source_url", context)),
            last_verified_at=_parse_timestamp(
                _required(raw, "last_verified_at", context), f"{context}.last_verified_at"
            ),
            expires_at=_parse_timestamp(
                _required(raw, "expires_at", context), f"{context}.expires_at"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ScheduleCalendarConfigError(f"{context} is invalid: {exc}") from exc


def load_competition_events(
    path: Path = COMPETITION_CALENDAR_CONFIG_PATH,
) -> tuple[str, tuple[CompetitionEvent, ...]]:
    """Load official competition windows and reject malformed dates or enums."""
    payload = _load_yaml_mapping(path)
    season = str(_required(payload, "season", path.name))
    raw_events = _required(payload, "events", path.name)
    if not isinstance(raw_events, list) or not raw_events:
        raise ScheduleCalendarConfigError(f"{path.name} events must be a non-empty list")
    if not all(isinstance(event, Mapping) for event in raw_events):
        raise ScheduleCalendarConfigError(f"{path.name} events must contain mappings")

    events = tuple(_event_from_mapping(event, index) for index, event in enumerate(raw_events))
    event_keys = {
        (event.competition, event.stage, event.start_date, event.end_date)
        for event in events
    }
    if len(event_keys) != len(events):
        raise ScheduleCalendarConfigError(f"{path.name} contains duplicate competition events")
    return season, events


def load_team_competition_entries(
    path: Path = EUROPEAN_PARTICIPANTS_CONFIG_PATH,
) -> tuple[str, tuple[TeamCompetitionEntry, ...]]:
    """Load current European participants with source and freshness metadata."""
    payload = _load_yaml_mapping(path)
    season = str(_required(payload, "season", path.name))
    raw_entries = _required(payload, "participants", path.name)
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ScheduleCalendarConfigError(f"{path.name} participants must be a non-empty list")
    if not all(isinstance(entry, Mapping) for entry in raw_entries):
        raise ScheduleCalendarConfigError(f"{path.name} participants must contain mappings")

    entries = tuple(
        _participant_from_mapping(entry, index) for index, entry in enumerate(raw_entries)
    )
    if len({entry.team_code for entry in entries}) != len(entries):
        raise ScheduleCalendarConfigError(f"{path.name} contains duplicate team_code values")
    if len({entry.fpl_team_id for entry in entries}) != len(entries):
        raise ScheduleCalendarConfigError(f"{path.name} contains duplicate fpl_team_id values")
    return season, entries


def validate_fpl_team_catalog(teams: Iterable[TeamRecord]) -> dict[str, int]:
    """Return the 20-club official FPL code-to-ID catalogue or fail closed."""
    records = tuple(teams)
    if len(records) != 20:
        raise ScheduleCalendarConfigError(
            f"official FPL team catalogue must contain 20 clubs, received {len(records)}"
        )

    mapping = {team.short_name.upper(): team.team_id for team in records}
    if len(mapping) != len(records) or len(set(mapping.values())) != len(records):
        raise ScheduleCalendarConfigError(
            "official FPL team catalogue contains duplicate codes or IDs"
        )
    return mapping


def validate_participant_mappings(
    participants: Iterable[TeamCompetitionEntry], teams: Iterable[TeamRecord]
) -> None:
    """Ensure every controlled participant mapping still matches official FPL data."""
    fpl_teams = validate_fpl_team_catalog(teams)
    for entry in participants:
        actual_team_id = fpl_teams.get(entry.team_code)
        if actual_team_id is None:
            raise ScheduleCalendarConfigError(
                f"participant {entry.team_code} is not in the official FPL team catalogue"
            )
        if actual_team_id != entry.fpl_team_id:
            raise ScheduleCalendarConfigError(
                f"participant {entry.team_code} maps to FPL team ID {actual_team_id}, "
                f"not {entry.fpl_team_id}"
            )


def load_schedule_calendar_catalog(
    teams: Iterable[TeamRecord],
    calendar_path: Path = COMPETITION_CALENDAR_CONFIG_PATH,
    participants_path: Path = EUROPEAN_PARTICIPANTS_CONFIG_PATH,
) -> ScheduleCalendarCatalog:
    """Load Phase A inputs only after both files agree with the live FPL teams."""
    calendar_season, events = load_competition_events(calendar_path)
    participant_season, participants = load_team_competition_entries(participants_path)
    if calendar_season != participant_season:
        raise ScheduleCalendarConfigError(
            "competition calendar and participant mapping must use the same season"
        )
    validate_participant_mappings(participants, teams)
    return ScheduleCalendarCatalog(
        season=calendar_season,
        events=events,
        participants=participants,
    )


def detect_structural_clashes(
    fixtures: Iterable[FixtureRecord], events: Iterable[CompetitionEvent]
) -> tuple[StructuralFixtureClash, ...]:
    """Match official league fixtures to protected domestic cup matchweeks."""
    fixtures_by_gameweek: dict[int, list[FixtureRecord]] = {}
    for fixture in fixtures:
        if fixture.gameweek is not None:
            fixtures_by_gameweek.setdefault(fixture.gameweek, []).append(fixture)

    clashes: list[StructuralFixtureClash] = []
    for event in events:
        if event.clash_matchweek is None:
            continue
        for fixture in fixtures_by_gameweek.get(event.clash_matchweek, []):
            clashes.append(
                StructuralFixtureClash(
                    fixture_id=fixture.fixture_id,
                    source_gameweek=event.clash_matchweek,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    event=event,
                    explanation=(
                        f"GW{event.clash_matchweek} overlaps {event.competition.value} "
                        f"{event.stage.value}; the league fixture moves only if either club "
                        "reaches that stage."
                    ),
                )
            )
    return tuple(sorted(clashes, key=lambda item: (item.source_gameweek, item.fixture_id)))


def summarize_official_gameweeks(
    fixtures: Iterable[FixtureRecord],
    team_ids: Iterable[int],
    as_of: datetime,
    gameweeks: Iterable[int] = range(1, 39),
    require_complete_schedule: bool = True,
) -> tuple[GameweekRiskSummary, ...]:
    """Detect confirmed blanks and doubles from official FPL event allocation."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include a timezone")

    fixture_counts: dict[tuple[int, int], list[int]] = {}
    total_fixtures_by_team: dict[int, int] = {}
    seen_fixture_ids: set[int] = set()
    for fixture in fixtures:
        if fixture.fixture_id in seen_fixture_ids:
            raise ValueError(f"duplicate official fixture ID {fixture.fixture_id}")
        seen_fixture_ids.add(fixture.fixture_id)
        total_fixtures_by_team[fixture.home_team_id] = (
            total_fixtures_by_team.get(fixture.home_team_id, 0) + 1
        )
        total_fixtures_by_team[fixture.away_team_id] = (
            total_fixtures_by_team.get(fixture.away_team_id, 0) + 1
        )
        if fixture.gameweek is None:
            continue
        fixture_counts.setdefault((fixture.home_team_id, fixture.gameweek), []).append(
            fixture.fixture_id
        )
        fixture_counts.setdefault((fixture.away_team_id, fixture.gameweek), []).append(
            fixture.fixture_id
        )

    requested_team_ids = sorted(set(team_ids))
    if require_complete_schedule:
        incomplete = {
            team_id: total_fixtures_by_team.get(team_id, 0)
            for team_id in requested_team_ids
            if total_fixtures_by_team.get(team_id, 0) != 38
        }
        if incomplete:
            details = ", ".join(
                f"{team_id}={count}" for team_id, count in incomplete.items()
            )
            raise ScheduleCalendarConfigError(
                "official FPL fixture feed is incomplete; expected 38 fixtures per "
                f"team, received {details}"
            )

    summaries: list[GameweekRiskSummary] = []
    for team_id in requested_team_ids:
        if team_id <= 0:
            raise ValueError("team IDs must be positive")
        for gameweek in gameweeks:
            fixture_ids = tuple(sorted(fixture_counts.get((team_id, gameweek), [])))
            if not fixture_ids:
                status = ScheduleRiskStatus.CONFIRMED_BLANK
                explanation = (
                    f"Official FPL currently assigns no fixture to team {team_id} "
                    f"in GW{gameweek}."
                )
            elif len(fixture_ids) >= 2:
                status = ScheduleRiskStatus.CONFIRMED_DOUBLE
                explanation = (
                    f"Official FPL currently assigns {len(fixture_ids)} fixtures to team "
                    f"{team_id} in GW{gameweek}."
                )
            else:
                status = ScheduleRiskStatus.NORMAL
                explanation = (
                    f"Official FPL currently assigns one fixture to team {team_id} "
                    f"in GW{gameweek}."
                )
            summaries.append(
                GameweekRiskSummary(
                    team_id=team_id,
                    gameweek=gameweek,
                    status=status,
                    fixture_ids=fixture_ids,
                    source_url=OFFICIAL_FPL_FIXTURES_URL,
                    as_of=as_of,
                    explanation=explanation,
                )
            )
    return tuple(summaries)


def _gameweek_bounds(
    fixtures: Iterable[FixtureRecord],
) -> tuple[tuple[int, date, date], ...]:
    dates_by_gameweek: dict[int, list[date]] = {}
    for fixture in fixtures:
        if fixture.gameweek is None or fixture.kickoff_time is None:
            continue
        dates_by_gameweek.setdefault(fixture.gameweek, []).append(
            fixture.kickoff_time.date()
        )
    return tuple(
        (gameweek, min(dates), max(dates))
        for gameweek, dates in sorted(dates_by_gameweek.items())
    )


def _event_blocks_teams(
    event: CompetitionEvent,
    candidate_date: date,
    team_ids: set[int],
    participants: Iterable[TeamCompetitionEntry],
) -> bool:
    if not event.blocks_date(candidate_date):
        return False
    if event.competition in {
        CompetitionCode.EFL_CUP,
        CompetitionCode.FA_CUP,
        CompetitionCode.INTERNATIONAL_BREAK,
    }:
        return True
    return any(
        participant.fpl_team_id in team_ids
        and participant.competition is event.competition
        for participant in participants
    )


def find_candidate_reschedule_slots(
    clash: StructuralFixtureClash,
    fixtures: Iterable[FixtureRecord],
    events: Iterable[CompetitionEvent],
    participants: Iterable[TeamCompetitionEntry],
    minimum_date_gap: int = 3,
) -> tuple[CandidateRescheduleSlot, ...]:
    """Find open midweeks after a clash while enforcing deterministic constraints."""
    if minimum_date_gap < 2:
        raise ValueError("minimum_date_gap must be at least 2")

    fixture_records = tuple(fixtures)
    bounds = _gameweek_bounds(fixture_records)
    if len(bounds) < 2:
        return ()

    affected_team_ids = {clash.home_team_id, clash.away_team_id}
    other_match_dates = tuple(
        fixture.kickoff_time.date()
        for fixture in fixture_records
        if fixture.fixture_id != clash.fixture_id
        and fixture.kickoff_time is not None
        and (
            fixture.home_team_id in affected_team_ids
            or fixture.away_team_id in affected_team_ids
        )
    )
    fixture_counts: dict[tuple[int, int], int] = {}
    for fixture in fixture_records:
        if fixture.fixture_id == clash.fixture_id or fixture.gameweek is None:
            continue
        for team_id in (fixture.home_team_id, fixture.away_team_id):
            fixture_counts[(team_id, fixture.gameweek)] = (
                fixture_counts.get((team_id, fixture.gameweek), 0) + 1
            )

    candidates: list[CandidateRescheduleSlot] = []
    earliest_date = clash.event.end_date + timedelta(days=1)
    for (host_gameweek, _, host_end), (_, next_start, _) in zip(bounds, bounds[1:]):
        candidate_date = host_end + timedelta(days=1)
        while candidate_date < next_start:
            if candidate_date >= earliest_date and candidate_date.weekday() in MIDWEEK_DAYS:
                has_rest = all(
                    abs((candidate_date - match_date).days) >= minimum_date_gap
                    for match_date in other_match_dates
                )
                is_blocked = any(
                    _event_blocks_teams(
                        event, candidate_date, affected_team_ids, participants
                    )
                    for event in events
                )
                if has_rest and not is_blocked:
                    target_counts = (
                        fixture_counts.get((clash.home_team_id, host_gameweek), 0),
                        fixture_counts.get((clash.away_team_id, host_gameweek), 0),
                    )
                    would_create_double = any(count >= 1 for count in target_counts)
                    candidates.append(
                        CandidateRescheduleSlot(
                            slot_id=f"fixture-{clash.fixture_id}-{candidate_date.isoformat()}",
                            fixture_id=clash.fixture_id,
                            source_gameweek=clash.source_gameweek,
                            target_gameweek=host_gameweek,
                            candidate_date=candidate_date,
                            would_create_double=would_create_double,
                            explanation=(
                                f"Open midweek after GW{host_gameweek}; both clubs retain at "
                                f"least {minimum_date_gap} calendar days to other official "
                                "fixtures and no configured competition date overlaps."
                            ),
                        )
                    )
            candidate_date += timedelta(days=1)
    return tuple(candidates)


def build_progression_scenario_tree(
    clash: StructuralFixtureClash,
    candidate_slots: Iterable[CandidateRescheduleSlot] = (),
) -> tuple[FixtureRiskScenario, ...]:
    """Build four exhaustive branches without assigning probabilities."""
    slot_ids = tuple(slot.slot_id for slot in candidate_slots)
    group = (
        f"{clash.event.competition.value}-gw{clash.source_gameweek}-"
        f"fixture-{clash.fixture_id}"
    )
    branches = (
        (
            ScenarioOutcome.NEITHER_PROGRESS,
            (),
            False,
            "Neither club reaches the conflicting cup stage; fixture stays.",
        ),
        (
            ScenarioOutcome.HOME_ONLY_PROGRESS,
            (clash.home_team_id,),
            True,
            "Home club reaches the conflicting cup stage; fixture requires rescheduling.",
        ),
        (
            ScenarioOutcome.AWAY_ONLY_PROGRESS,
            (clash.away_team_id,),
            True,
            "Away club reaches the conflicting cup stage; fixture requires rescheduling.",
        ),
        (
            ScenarioOutcome.BOTH_PROGRESS,
            (clash.home_team_id, clash.away_team_id),
            True,
            "Both clubs reach the conflicting cup stage; fixture requires rescheduling.",
        ),
    )
    scenario_ids = tuple(f"{group}-{outcome.value}" for outcome, _, _, _ in branches)
    scenarios = tuple(
        FixtureRiskScenario(
            scenario_id=scenario_id,
            scenario_group=group,
            fixture_id=clash.fixture_id,
            outcome=outcome,
            progressing_team_ids=progressing_team_ids,
            requires_reschedule=requires_reschedule,
            candidate_slot_ids=slot_ids if requires_reschedule else (),
            mutually_exclusive_with=tuple(
                other_id for other_id in scenario_ids if other_id != scenario_id
            ),
            explanation=explanation,
        )
        for scenario_id, (outcome, progressing_team_ids, requires_reschedule, explanation)
        in zip(scenario_ids, branches)
    )
    validate_scenario_tree(scenarios)
    return scenarios


def validate_scenario_tree(scenarios: Iterable[FixtureRiskScenario]) -> None:
    """Reject incomplete or non-mutually-exclusive progression trees."""
    branches = tuple(scenarios)
    expected_outcomes = set(ScenarioOutcome)
    if len(branches) != len(expected_outcomes):
        raise ValueError("scenario tree must contain exactly four branches")
    if len({branch.scenario_group for branch in branches}) != 1:
        raise ValueError("scenario tree branches must share one group")
    if len({branch.fixture_id for branch in branches}) != 1:
        raise ValueError("scenario tree branches must share one fixture")
    if {branch.outcome for branch in branches} != expected_outcomes:
        raise ValueError("scenario tree must contain every progression outcome once")

    scenario_ids = {branch.scenario_id for branch in branches}
    if len(scenario_ids) != len(branches):
        raise ValueError("scenario tree contains duplicate scenario IDs")
    for branch in branches:
        if set(branch.mutually_exclusive_with) != scenario_ids - {branch.scenario_id}:
            raise ValueError("scenario branches must be pairwise mutually exclusive")


class ScheduleCongestionService:
    """Read persisted official FPL fixtures and build Phase B outputs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_phase_b_snapshot(
        self, as_of: datetime | None = None
    ) -> PhaseBScheduleSnapshot:
        snapshot_at = as_of or datetime.now(timezone.utc)
        with self.database.session() as session:
            repository = FPLRepository(session)
            teams = repository.list_teams()
            fixtures = repository.list_fixtures()

        catalog = load_schedule_calendar_catalog(teams)
        gameweek_risks = summarize_official_gameweeks(
            fixtures, (team.team_id for team in teams), snapshot_at
        )
        structural_clashes = detect_structural_clashes(fixtures, catalog.events)
        candidate_slots: list[CandidateRescheduleSlot] = []
        scenarios: list[FixtureRiskScenario] = []
        for clash in structural_clashes:
            clash_slots = find_candidate_reschedule_slots(
                clash, fixtures, catalog.events, catalog.participants
            )
            candidate_slots.extend(clash_slots)
            scenarios.extend(build_progression_scenario_tree(clash, clash_slots))
        return PhaseBScheduleSnapshot(
            catalog=catalog,
            gameweek_risks=gameweek_risks,
            structural_clashes=structural_clashes,
            candidate_slots=tuple(candidate_slots),
            scenarios=tuple(scenarios),
        )


def get_schedule_congestion_service() -> ScheduleCongestionService:
    return ScheduleCongestionService(get_database())
