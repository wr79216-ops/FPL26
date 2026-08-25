"""Official calendar input loading for the schedule-congestion planner.

This Phase A module deliberately provides only validated data contracts.  It
does not infer blanks, doubles, probabilities, or transfer actions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from config.settings import (
    COMPETITION_CALENDAR_CONFIG_PATH,
    EUROPEAN_PARTICIPANTS_CONFIG_PATH,
)
from src.domain.contracts import TeamRecord
from src.domain.schedule_risk import (
    CompetitionCode,
    CompetitionEvent,
    CompetitionStage,
    ParticipationStatus,
    TeamCompetitionEntry,
)


class ScheduleCalendarConfigError(ValueError):
    """Raised when the controlled schedule-risk input is incomplete or unsafe."""


@dataclass(frozen=True)
class ScheduleCalendarCatalog:
    """The complete verified calendar input available to later planner phases."""

    season: str
    events: tuple[CompetitionEvent, ...]
    participants: tuple[TeamCompetitionEntry, ...]


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
    if len({(event.competition, event.stage, event.start_date, event.end_date) for event in events}) != len(events):
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
        raise ScheduleCalendarConfigError("official FPL team catalogue contains duplicate codes or IDs")
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
