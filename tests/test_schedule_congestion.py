from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.domain.contracts import FixtureRecord, TeamRecord
from src.domain.schedule_risk import (
    AuditableProbabilityInput,
    CandidateRescheduleSlot,
    CompetitionCode,
    CompetitionEvent,
    CompetitionStage,
    FractionalOddsOutcome,
    LicensedOddsMarket,
    ParticipationStatus,
    ProbabilityConfidence,
    ProbabilityTargetType,
    ProjectionMethod,
    ScenarioOutcome,
    ScheduleRiskStatus,
    TeamCompetitionEntry,
)
from src.services.schedule_congestion import (
    ScheduleCalendarConfigError,
    ScheduleProbabilityInputError,
    build_progression_scenario_tree,
    calculate_blank_probability,
    calculate_double_gameweek_probabilities,
    detect_structural_clashes,
    find_candidate_reschedule_slots,
    load_schedule_calendar_catalog,
    load_manual_probability_catalog,
    load_team_competition_entries,
    normalize_licensed_fractional_odds,
    slot_allocation_target_id,
    summarize_official_gameweeks,
    team_progression_target_id,
    validate_fpl_team_catalog,
    validate_participant_mappings,
    validate_scenario_tree,
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


def _probability_input(
    input_id: str,
    target_type: ProbabilityTargetType,
    target_id: str,
    probability: float,
    confidence: ProbabilityConfidence = ProbabilityConfidence.MEDIUM,
    expires_at: datetime = datetime(2027, 1, 1, tzinfo=timezone.utc),
) -> AuditableProbabilityInput:
    return AuditableProbabilityInput(
        input_id=input_id,
        target_type=target_type,
        target_id=target_id,
        probability=probability,
        confidence=confidence,
        source_url="https://example.test/evidence",
        as_of=datetime(2026, 8, 25, tzinfo=timezone.utc),
        expires_at=expires_at,
        note="Reviewed manual input for deterministic test coverage.",
    )


def _scenario_fixture_context() -> tuple[
    object,
    tuple[CandidateRescheduleSlot, ...],
    tuple[object, ...],
]:
    event = _event(
        CompetitionCode.FA_CUP,
        CompetitionStage.SEMI_FINAL,
        date(2027, 4, 24),
        date(2027, 4, 25),
        clash_matchweek=33,
    )
    fixture = _fixture(330, 33, 1, 2, datetime(2027, 4, 24, tzinfo=timezone.utc))
    clash = detect_structural_clashes((fixture,), (event,))[0]
    slots = (
        CandidateRescheduleSlot(
            slot_id="slot-gw33",
            fixture_id=330,
            source_gameweek=33,
            target_gameweek=33,
            candidate_date=date(2027, 4, 27),
            would_create_double=False,
            explanation="Fixture remains a single fixture in its source gameweek.",
        ),
        CandidateRescheduleSlot(
            slot_id="slot-gw34",
            fixture_id=330,
            source_gameweek=33,
            target_gameweek=34,
            candidate_date=date(2027, 5, 4),
            would_create_double=True,
            explanation="Open midweek in GW34.",
        ),
        CandidateRescheduleSlot(
            slot_id="slot-gw35",
            fixture_id=330,
            source_gameweek=33,
            target_gameweek=35,
            candidate_date=date(2027, 5, 11),
            would_create_double=True,
            explanation="Open midweek in GW35.",
        ),
    )
    return clash, slots, build_progression_scenario_tree(clash, slots)


def test_independent_blank_union_is_monotonic_and_bounded() -> None:
    clash, _, scenarios = _scenario_fixture_context()
    as_of = datetime(2026, 8, 26, tzinfo=timezone.utc)
    base_inputs = (
        _probability_input(
            "home-base",
            ProbabilityTargetType.TEAM_PROGRESSION,
            team_progression_target_id(clash.home_team_id, clash.event),
            0.2,
        ),
        _probability_input(
            "away-base",
            ProbabilityTargetType.TEAM_PROGRESSION,
            team_progression_target_id(clash.away_team_id, clash.event),
            0.3,
        ),
    )
    higher_home_inputs = (replace(base_inputs[0], probability=0.6), base_inputs[1])

    base = calculate_blank_probability(clash, scenarios, base_inputs, as_of)
    higher_home = calculate_blank_probability(clash, scenarios, higher_home_inputs, as_of)

    assert base is not None and higher_home is not None
    assert base.method is ProjectionMethod.INDEPENDENT_UNION
    assert base.blank_probability == pytest.approx(0.44)
    assert 0 <= base.blank_probability <= 1
    assert higher_home.blank_probability > base.blank_probability
    assert higher_home.blank_probability == pytest.approx(0.72)


def test_scenario_tree_blank_and_dgw_probabilities_sum_without_uniform_slots() -> None:
    clash, slots, scenarios = _scenario_fixture_context()
    as_of = datetime(2026, 8, 26, tzinfo=timezone.utc)
    scenario_probabilities = (0.4, 0.2, 0.3, 0.1)
    inputs = [
        _probability_input(
            f"scenario-{index}",
            ProbabilityTargetType.SCENARIO,
            scenario.scenario_id,
            scenario_probabilities[index],
        )
        for index, scenario in enumerate(scenarios)
    ]
    allocation_by_outcome = {
        ScenarioOutcome.HOME_ONLY_PROGRESS: (0.0, 0.6, 0.4),
        ScenarioOutcome.AWAY_ONLY_PROGRESS: (0.0, 0.5, 0.5),
        ScenarioOutcome.BOTH_PROGRESS: (0.0, 0.2, 0.8),
    }
    for scenario in scenarios:
        if not scenario.requires_reschedule:
            continue
        for slot, probability in zip(slots, allocation_by_outcome[scenario.outcome]):
            inputs.append(
                _probability_input(
                    f"{scenario.scenario_id}-{slot.slot_id}",
                    ProbabilityTargetType.SLOT_ALLOCATION,
                    slot_allocation_target_id(scenario.scenario_id, slot.slot_id),
                    probability,
                    ProbabilityConfidence.LOW,
                )
            )

    blank = calculate_blank_probability(clash, scenarios, inputs, as_of)
    dgw_projections = calculate_double_gameweek_probabilities(
        clash, scenarios, slots, inputs, as_of
    )

    assert blank is not None
    assert blank.method is ProjectionMethod.SCENARIO_TREE
    assert blank.blank_probability == pytest.approx(0.6)
    probabilities_by_gameweek = {
        item.target_gameweek: item.double_probability for item in dgw_projections
    }
    assert probabilities_by_gameweek == {
        34: pytest.approx(0.29),
        35: pytest.approx(0.31),
    }
    assert sum(item.double_probability for item in dgw_projections) == pytest.approx(
        blank.blank_probability
    )
    assert all(0 <= item.double_probability <= 1 for item in dgw_projections)
    assert all(item.confidence is ProbabilityConfidence.LOW for item in dgw_projections)


def test_licensed_odds_power_normalisation_sums_to_one_and_preserves_order() -> None:
    market = LicensedOddsMarket(
        market_id="cup-finalist-market",
        outcomes=(
            FractionalOddsOutcome("home", 1, 1),
            FractionalOddsOutcome("away", 2, 1),
            FractionalOddsOutcome("other", 3, 1),
        ),
        provider_id="licensed-test-provider",
        licence_reference="TEST-LICENCE-001",
        source_url="https://example.test/licensed-odds",
        as_of=datetime(2026, 8, 25, tzinfo=timezone.utc),
        expires_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )

    normalized = normalize_licensed_fractional_odds(
        market, datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    )

    probabilities = [item.probability for item in normalized]
    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities[0] > probabilities[1] > probabilities[2]
    assert all(0 <= probability <= 1 for probability in probabilities)


def test_stale_manual_probability_input_is_rejected(tmp_path) -> None:
    config = tmp_path / "probability-inputs.yaml"
    config.write_text(
        """
season: "2026-27"
model_version: "schedule-probability-v1"
inputs:
  - input_id: stale-input
    target_type: team_progression
    target_id: team:1:fa_cup:semi_final
    probability: 0.4
    confidence: low
    source_url: "https://example.test/evidence"
    as_of: "2026-08-20T00:00:00+00:00"
    expires_at: "2026-08-21T00:00:00+00:00"
    note: "Expired manual estimate."
""",
        encoding="utf-8",
    )

    with pytest.raises(ScheduleProbabilityInputError, match="have expired"):
        load_manual_probability_catalog(
            config, as_of=datetime(2026, 8, 25, tzinfo=timezone.utc)
        )
