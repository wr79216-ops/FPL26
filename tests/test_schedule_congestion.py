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
    ScenarioOutcome,
    ScheduleRiskStatus,
    TeamCompetitionEntry,
)
from src.services.schedule_congestion import (
    ScheduleCalendarConfigError,
    build_progression_scenario_tree,
    detect_structural_clashes,
    find_candidate_reschedule_slots,
    load_schedule_calendar_catalog,
    load_team_competition_entries,
    summarize_official_gameweeks,
    validate_fpl_team_catalog,
    validate_participant_mappings,
    validate_scenario_tree,
)
from src.domain.contracts import FixtureRecord


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
    structural_events = {
        (event.competition, event.stage, event.clash_matchweek)
        for event in catalog.events
        if event.clash_matchweek
    }
    assert structural_events == {
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


def _fixture(
    fixture_id: int,
    gameweek: int | None,
    home_team_id: int,
    away_team_id: int,
    kickoff: datetime | None,
) -> FixtureRecord:
    return FixtureRecord(
        fixture_id=fixture_id,
        gameweek=gameweek,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        kickoff_time=kickoff,
        home_difficulty=3,
        away_difficulty=3,
        home_score=None,
        away_score=None,
        finished=False,
        started=False,
    )


def _event(
    competition: CompetitionCode,
    stage: CompetitionStage,
    start_date: date,
    end_date: date,
    clash_matchweek: int | None = None,
) -> CompetitionEvent:
    return CompetitionEvent(
        competition=competition,
        stage=stage,
        start_date=start_date,
        end_date=end_date,
        clash_matchweek=clash_matchweek,
        source_url="https://example.test/calendar",
        last_verified_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        expires_at=datetime(2027, 6, 30, tzinfo=timezone.utc),
    )


def test_official_fixture_allocation_detects_confirmed_blank_and_double() -> None:
    fixtures = (
        _fixture(1, 1, 1, 2, datetime(2026, 8, 22, tzinfo=timezone.utc)),
        _fixture(2, 3, 1, 3, datetime(2026, 9, 5, tzinfo=timezone.utc)),
        _fixture(3, 3, 4, 1, datetime(2026, 9, 8, tzinfo=timezone.utc)),
    )

    summaries = summarize_official_gameweeks(
        fixtures,
        team_ids=(1,),
        as_of=datetime(2026, 8, 25, tzinfo=timezone.utc),
        gameweeks=(1, 2, 3),
        require_complete_schedule=False,
    )

    assert [summary.status for summary in summaries] == [
        ScheduleRiskStatus.NORMAL,
        ScheduleRiskStatus.CONFIRMED_BLANK,
        ScheduleRiskStatus.CONFIRMED_DOUBLE,
    ]
    assert summaries[2].fixture_ids == (2, 3)
    assert all("Official FPL" in summary.explanation for summary in summaries)


def test_official_status_detection_fails_closed_for_partial_fixture_feed() -> None:
    fixtures = (
        _fixture(1, 1, 1, 2, datetime(2026, 8, 22, tzinfo=timezone.utc)),
    )

    with pytest.raises(ScheduleCalendarConfigError, match="fixture feed is incomplete"):
        summarize_official_gameweeks(
            fixtures,
            team_ids=(1, 2),
            as_of=datetime(2026, 8, 25, tzinfo=timezone.utc),
            gameweeks=(1,),
        )


def test_structural_engine_detects_mw30_mw33_and_mw37() -> None:
    catalog = load_schedule_calendar_catalog(_official_fpl_teams())
    fixtures = (
        _fixture(30, 30, 1, 2, datetime(2027, 3, 20, tzinfo=timezone.utc)),
        _fixture(33, 33, 3, 4, datetime(2027, 4, 24, tzinfo=timezone.utc)),
        _fixture(37, 37, 5, 6, datetime(2027, 5, 23, tzinfo=timezone.utc)),
    )

    clashes = detect_structural_clashes(fixtures, catalog.events)

    assert [clash.source_gameweek for clash in clashes] == [30, 33, 37]
    assert [clash.fixture_id for clash in clashes] == [30, 33, 37]


def test_candidate_slots_filter_blocked_dates_and_mark_future_double() -> None:
    conflict = _event(
        CompetitionCode.EFL_CUP,
        CompetitionStage.FINAL,
        date(2027, 1, 10),
        date(2027, 1, 10),
        clash_matchweek=2,
    )
    blocked = _event(
        CompetitionCode.INTERNATIONAL_BREAK,
        CompetitionStage.INTERNATIONAL_WINDOW,
        date(2027, 1, 20),
        date(2027, 1, 20),
    )
    fixtures = (
        _fixture(1, 1, 1, 3, datetime(2027, 1, 3, tzinfo=timezone.utc)),
        _fixture(2, 1, 2, 4, datetime(2027, 1, 3, tzinfo=timezone.utc)),
        _fixture(10, 2, 1, 2, datetime(2027, 1, 10, tzinfo=timezone.utc)),
        _fixture(3, 3, 1, 3, datetime(2027, 1, 17, tzinfo=timezone.utc)),
        _fixture(4, 3, 2, 4, datetime(2027, 1, 17, tzinfo=timezone.utc)),
        _fixture(5, 4, 1, 3, datetime(2027, 1, 24, tzinfo=timezone.utc)),
        _fixture(6, 4, 2, 4, datetime(2027, 1, 24, tzinfo=timezone.utc)),
    )
    clash = detect_structural_clashes(fixtures, (conflict,))[0]

    slots = find_candidate_reschedule_slots(
        clash, fixtures, (conflict, blocked), participants=()
    )

    assert date(2027, 1, 20) not in {slot.candidate_date for slot in slots}
    assert {slot.candidate_date for slot in slots} >= {
        date(2027, 1, 12),
        date(2027, 1, 14),
        date(2027, 1, 21),
    }
    assert date(2027, 1, 19) not in {slot.candidate_date for slot in slots}
    assert all(
        slot.would_create_double
        for slot in slots
        if slot.target_gameweek == 3
    )
    assert all(
        not slot.would_create_double
        for slot in slots
        if slot.target_gameweek == 2
    )


def test_progression_scenario_tree_is_exhaustive_and_mutually_exclusive() -> None:
    event = _event(
        CompetitionCode.FA_CUP,
        CompetitionStage.SEMI_FINAL,
        date(2027, 4, 24),
        date(2027, 4, 25),
        clash_matchweek=33,
    )
    fixture = _fixture(33, 33, 1, 2, datetime(2027, 4, 24, tzinfo=timezone.utc))
    clash = detect_structural_clashes((fixture,), (event,))[0]

    scenarios = build_progression_scenario_tree(clash)

    assert {scenario.outcome for scenario in scenarios} == set(ScenarioOutcome)
    assert sum(not scenario.requires_reschedule for scenario in scenarios) == 1
    assert all(len(scenario.mutually_exclusive_with) == 3 for scenario in scenarios)
    validate_scenario_tree(scenarios)

    invalid = (replace(scenarios[0], mutually_exclusive_with=()), *scenarios[1:])
    with pytest.raises(ValueError, match="pairwise mutually exclusive"):
        validate_scenario_tree(invalid)
