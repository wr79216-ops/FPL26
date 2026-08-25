from __future__ import annotations

from datetime import date, datetime, timezone

from src.domain.schedule_risk import (
    CompetitionCode,
    CompetitionEvent,
    CompetitionStage,
    DoubleGameweekProbabilityProjection,
    FixtureProbabilityProjection,
    GameweekRiskSummary,
    ProbabilityConfidence,
    ProjectionMethod,
    ScheduleCongestionLeader,
    ScheduleRiskStatus,
    StructuralFixtureClash,
)
from src.services.advanced_planner import ImportedSquad, SquadPick
from src.services.recommendation_engine import RecommendationRow
from src.services.schedule_congestion import (
    PhaseBScheduleSnapshot,
    PhaseCScheduleSnapshot,
    ManualProbabilityCatalog,
    ScheduleCalendarCatalog,
)
from src.services.squad_schedule_exposure import calculate_squad_schedule_exposure
from src.ui.schedule_risk import build_squad_exposure_rows


AS_OF = datetime(2026, 8, 25, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _row(player_id: int, name: str, team: str, position: str) -> RecommendationRow:
    return RecommendationRow(
        player_id=player_id, name=name, team=team, position=position, status="a", news="",
        price=5.0, ownership=10.0, minutes=900, form=5.0, points_per_game=5.0,
        xg_per_90=0.2, xa_per_90=0.1, xgi_per_90=0.3, confidence=1.0,
        next_fixture="Example (H)", form_score=60.0, fixture_score=70.0,
        expected_score=70.0, minutes_score=90.0, history_score=50.0,
        value_score=60.0, bonus_score=50.0, ownership_score=50.0,
        final_score=70.0, category="Strong Buy", reason="Fixture and minutes",
    )


def _summary(team_id: int, gameweek: int, status: ScheduleRiskStatus, fixture_ids: tuple[int, ...]) -> GameweekRiskSummary:
    return GameweekRiskSummary(
        team_id, gameweek, status, fixture_ids,
        "https://fantasy.premierleague.com/api/fixtures/", AS_OF, "Official test allocation.",
    )


def _snapshot() -> PhaseCScheduleSnapshot:
    event = CompetitionEvent(
        CompetitionCode.FA_CUP, CompetitionStage.SEMI_FINAL,
        date(2026, 9, 8), date(2026, 9, 9),
        "https://example.test/calendar", AS_OF, datetime(2027, 1, 1, tzinfo=timezone.utc),
        clash_matchweek=3,
    )
    clash = StructuralFixtureClash(99, 3, 1, 2, event, "Test structural clash.")
    phase_b = PhaseBScheduleSnapshot(
        catalog=ScheduleCalendarCatalog("2026-27", (), ()),
        gameweek_risks=(
            _summary(1, 1, ScheduleRiskStatus.CONFIRMED_BLANK, ()),
            _summary(1, 2, ScheduleRiskStatus.CONFIRMED_DOUBLE, (3, 4)),
            _summary(1, 3, ScheduleRiskStatus.NORMAL, (5,)),
            _summary(1, 4, ScheduleRiskStatus.NORMAL, (6,)),
            *(_summary(2, gw, ScheduleRiskStatus.NORMAL, (100 + gw,)) for gw in range(1, 5)),
        ),
        structural_clashes=(clash,),
        candidate_slots=(),
        scenarios=(),
        team_names=((1, "Arsenal", "ARS"), (2, "Brighton", "BHA")),
        congestion_leaders=(
            ScheduleCongestionLeader(1, "Arsenal", "ARS", 3, 3, 2, "Champions League", 72.0, "Three fixtures and short rest."),
            ScheduleCongestionLeader(2, "Brighton", "BHA", 2, 6, 0, None, 20.0, "Two fixtures."),
        ),
    )
    probability_catalog = ManualProbabilityCatalog("2026-27", "manual-v1", ())
    blank = FixtureProbabilityProjection(
        99, 3, 0.6, ProjectionMethod.INDEPENDENT_UNION, ProbabilityConfidence.MEDIUM,
        ("blank-evidence",), AS_OF, EXPIRES, "Controlled blank projection.",
    )
    double = DoubleGameweekProbabilityProjection(
        99, 4, 0.25, ProbabilityConfidence.MEDIUM,
        ("double-evidence",), AS_OF, EXPIRES, "Controlled double projection.",
    )
    return PhaseCScheduleSnapshot(phase_b, probability_catalog, (blank,), (double,))


def test_squad_exposure_uses_documented_weights_and_keeps_projections_separate() -> None:
    captain = SquadPick(_row(1, "Captain", "Arsenal", "MID"), 1, 2, None, True, False)
    bench = SquadPick(_row(2, "Bench", "Brighton", "DEF"), 12, 0, None, False, False)
    imported = ImportedSquad(11, "Manager", "Test XI", 1, None, None, 0.0, 10.0, None, (captain, bench))

    exposure = calculate_squad_schedule_exposure(imported, _snapshot(), horizon=4)
    captain_exposure = next(item for item in exposure.affected_players if item.player_id == 1)

    assert captain_exposure.squad_weight == 2.0
    assert captain_exposure.confirmed_blank_gameweeks == (1,)
    assert captain_exposure.expected_blank_fixtures == 3.2
    assert captain_exposure.expected_extra_fixtures == 2.5
    assert exposure.expected_blank_starters == 3.41
    assert exposure.expected_extra_fixtures == 2.587
    assert "confirmed blank in GW1" in captain_exposure.explanation
    assert build_squad_exposure_rows(exposure)[0]["Player"] == "Captain"


def test_squad_exposure_keeps_unmapped_player_visible_and_unscored() -> None:
    unknown = SquadPick(_row(3, "Unknown", "Missing FC", "FWD"), 1, 1, None, False, False)
    imported = ImportedSquad(12, "Manager", "Test XI", 1, None, None, 0.0, 5.0, None, (unknown,))

    exposure = calculate_squad_schedule_exposure(imported, _snapshot(), horizon=1)

    assert exposure.unresolved_player_ids == (3,)
    assert exposure.affected_players[0].team_id is None
