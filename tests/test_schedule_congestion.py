from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.domain.contracts import TeamRecord
from src.domain.schedule_risk import (
    CompetitionCode,
    CompetitionEvent,
    CompetitionStage,
    ParticipationStatus,
    TeamCompetitionEntry,
)
from src.services.schedule_congestion import (
    ScheduleCalendarConfigError,
    load_schedule_calendar_catalog,
    load_team_competition_entries,
    validate_fpl_team_catalog,
    validate_participant_mappings,
)


FPL_TEAM_CODES = (
    "ARS",
    "AVL",
    "BOU",
    "BRE",
    "BHA",
    "CHE",
    "COV",
    "CRY",
    "EVE",
    "FUL",
    "HUL",
    "IPS",
    "LEE",
    "LIV",
    "MCI",
    "MUN",
    "NEW",
    "NFO",
    "TOT",
    "SUN",
)


def _official_fpl_teams() -> tuple[TeamRecord, ...]:
    return tuple(
        TeamRecord(
            team_id=index,
            name=f"Team {code}",
            short_name=code,
            strength=3,
            strength_overall_home=3,
            strength_overall_away=3,
            strength_attack_home=3,
            strength_attack_away=3,
            strength_defence_home=3,
            strength_defence_away=3,
        )
        for index, code in enumerate(FPL_TEAM_CODES, start=1)
    )


def test_phase_a_catalog_maps_every_participant_to_the_20_club_fpl_catalog() -> None:
    catalog = load_schedule_calendar_catalog(_official_fpl_teams())

    assert catalog.season == "2026-27"
    assert len(validate_fpl_team_catalog(_official_fpl_teams())) == 20
    assert {entry.team_code for entry in catalog.participants} == {
        "ARS",
        "AVL",
        "BOU",
        "BHA",
        "CRY",
        "LIV",
        "MCI",
        "MUN",
        "SUN",
    }
    assert {entry.competition for entry in catalog.participants} == {
        CompetitionCode.CHAMPIONS_LEAGUE,
        CompetitionCode.EUROPA_LEAGUE,
        CompetitionCode.CONFERENCE_LEAGUE,
    }
    assert all(entry.last_verified_at < entry.expires_at for entry in catalog.participants)


def test_calendar_has_valid_dates_and_the_three_structural_domestic_clashes() -> None:
    catalog = load_schedule_calendar_catalog(_official_fpl_teams())

    assert all(event.start_date <= event.end_date for event in catalog.events)
    assert all(event.last_verified_at < event.expires_at for event in catalog.events)
    assert {(event.competition, event.stage, event.clash_matchweek) for event in catalog.events if event.clash_matchweek} == {
        (CompetitionCode.EFL_CUP, CompetitionStage.FINAL, 30),
        (CompetitionCode.FA_CUP, CompetitionStage.SEMI_FINAL, 33),
        (CompetitionCode.FA_CUP, CompetitionStage.FINAL, 37),
    }


def test_invalid_competition_or_status_enum_fails_closed(tmp_path) -> None:
    invalid_participants = tmp_path / "participants.yaml"
    invalid_participants.write_text(
        """
season: "2026-27"
participants:
  - team_code: ARS
    fpl_team_id: 1
    competition: not_a_competition
    stage: league_phase
    status: confirmed
    qualification_conditional: false
    source_url: "https://example.test/source"
    last_verified_at: "2026-08-25T00:00:00+00:00"
    expires_at: "2026-08-26T00:00:00+00:00"
""",
        encoding="utf-8",
    )

    with pytest.raises(ScheduleCalendarConfigError, match="competition must be one of"):
        load_team_competition_entries(invalid_participants)

    invalid_participants.write_text(
        invalid_participants.read_text(encoding="utf-8").replace(
            "competition: not_a_competition", "competition: champions_league"
        ).replace("status: confirmed", "status: unknown"),
        encoding="utf-8",
    )
    with pytest.raises(ScheduleCalendarConfigError, match="status must be one of"):
        load_team_competition_entries(invalid_participants)


def test_invalid_participant_id_mapping_is_rejected_against_fpl_catalog() -> None:
    participants = load_team_competition_entries()[1]
    invalid_mapping = (replace(participants[0], fpl_team_id=99), *participants[1:])

    with pytest.raises(ScheduleCalendarConfigError, match="maps to FPL team ID"):
        validate_participant_mappings(invalid_mapping, _official_fpl_teams())


def test_domain_contract_rejects_invalid_dates_and_status_flags() -> None:
    with pytest.raises(ValueError, match="start_date"):
        CompetitionEvent(
            competition=CompetitionCode.FA_CUP,
            stage=CompetitionStage.FINAL,
            start_date=date(2027, 5, 23),
            end_date=date(2027, 5, 22),
            source_url="https://example.test/source",
            last_verified_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="qualification_conditional"):
        TeamCompetitionEntry(
            team_code="ARS",
            fpl_team_id=1,
            competition=CompetitionCode.CHAMPIONS_LEAGUE,
            stage=CompetitionStage.LEAGUE_PHASE,
            status=ParticipationStatus.CONFIRMED,
            qualification_conditional=True,
            source_url="https://example.test/source",
            last_verified_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )
