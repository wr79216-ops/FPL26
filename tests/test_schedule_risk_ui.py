from __future__ import annotations

from datetime import datetime, timezone

from src.domain.contracts import FixtureRecord, TeamRecord
from src.domain.schedule_risk import (
    CompetitionCode,
    CompetitionStage,
    GameweekRiskSummary,
    ParticipationStatus,
    ScheduleRiskStatus,
    TeamCompetitionEntry,
)
from src.services.schedule_congestion import calculate_congestion_leaders
from src.ui.schedule_risk import build_risk_strip_rows, build_team_risk_matrix


def _team(team_id: int, code: str) -> TeamRecord:
    return TeamRecord(team_id, f"Team {code}", code, 3, 3, 3, 3, 3, 3, 3)


def _fixture(fixture_id: int, team_a: int, team_b: int, day: int) -> FixtureRecord:
    return FixtureRecord(
        fixture_id, 1, team_a, team_b,
        datetime(2026, 8, day, tzinfo=timezone.utc),
        3, 3, None, None, False, False,
    )


def _summary(team_id: int, gameweek: int, status: ScheduleRiskStatus) -> GameweekRiskSummary:
    return GameweekRiskSummary(
        team_id, gameweek, status, (team_id * 10 + gameweek,),
        "https://fantasy.premierleague.com/api/fixtures/",
        datetime(2026, 8, 25, tzinfo=timezone.utc), "test summary",
    )


def test_risk_strip_aggregates_confirmed_status_and_keeps_empty_gws_incomplete() -> None:
    rows = build_risk_strip_rows(
        (_summary(1, 1, ScheduleRiskStatus.CONFIRMED_BLANK),
         _summary(2, 1, ScheduleRiskStatus.NORMAL)),
        gameweeks=(1, 2),
    )

    assert rows[0]["status_key"] == "confirmed_blank"
    assert rows[0]["blank_count"] == 1
    assert rows[1]["status_key"] == "incomplete"
    assert rows[1]["probability"] == "No projection"


def test_team_matrix_filters_european_clubs_and_uses_compact_status_cells() -> None:
    rows = build_team_risk_matrix(
        (_summary(1, 1, ScheduleRiskStatus.CONFIRMED_DOUBLE),
         _summary(2, 1, ScheduleRiskStatus.NORMAL)),
        ((1, "Arsenal", "ARS"), (2, "Brighton", "BHA")),
        (1, 2),
        european_team_ids={1},
    )

    assert rows == ({"Club": "Arsenal", "Code": "ARS", "GW1": "D", "GW2": "—"},)


def test_congestion_leaders_explain_density_rest_and_europe() -> None:
    participants = (
        TeamCompetitionEntry(
            "ARS", 1, CompetitionCode.CHAMPIONS_LEAGUE, CompetitionStage.LEAGUE_PHASE,
            ParticipationStatus.CONFIRMED, False, "https://example.test/source",
            datetime(2026, 8, 25, tzinfo=timezone.utc), datetime(2027, 6, 1, tzinfo=timezone.utc),
        ),
    )
    leaders = calculate_congestion_leaders(
        (_fixture(1, 1, 2, 25), _fixture(2, 1, 2, 28), _fixture(3, 1, 2, 31)),
        (_team(1, "ARS"), _team(2, "BHA")),
        participants,
        datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    arsenal = next(leader for leader in leaders if leader.team_id == 1)
    assert arsenal.matches_next_14_days == 3
    assert arsenal.shortest_rest_days == 3
    assert arsenal.short_rest_count == 2
    assert arsenal.european_competition == "Champions League"
    assert arsenal.congestion_score > 0
    assert "shortest rest 3 days" in arsenal.explanation
