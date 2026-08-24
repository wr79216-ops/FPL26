from src.services.decision_tools import DecisionToolsService
from src.services.fixture_analytics import FixtureCell, FixtureMatrix, TeamFixtureSummary
from src.services.recommendation_engine import RecommendationRow


def _row(
    player_id: int,
    name: str,
    position: str,
    *,
    team: str,
    price: float,
    final_score: float,
    points_per_game: float,
    fixture_score: float = 60,
    expected_score: float = 60,
    minutes_score: float = 70,
    ownership: float = 20,
    status: str = "a",
) -> RecommendationRow:
    return RecommendationRow(
        player_id=player_id,
        name=name,
        team=team,
        position=position,
        status=status,
        news="",
        price=price,
        ownership=ownership,
        minutes=540,
        form=5.0,
        points_per_game=points_per_game,
        xg_per_90=0.2,
        xa_per_90=0.1,
        xgi_per_90=0.3,
        confidence=1.0,
        next_fixture="Example (H)",
        form_score=60,
        fixture_score=fixture_score,
        expected_score=expected_score,
        minutes_score=minutes_score,
        history_score=50,
        value_score=60,
        bonus_score=50,
        ownership_score=60,
        final_score=final_score,
        category="Good Option",
        reason="Fixtures 60 · xGI / 90 60",
    )


class _Recommendations:
    def __init__(self, rows: tuple[RecommendationRow, ...]) -> None:
        self.rows = rows

    def get_rankings(self, horizon: int):
        return self.rows


class _Fixtures:
    def __init__(self, teams: tuple[TeamFixtureSummary, ...]) -> None:
        self.matrix = FixtureMatrix(gameweek=8, horizon=3, teams=teams)

    def get_matrix(self, horizon: int):
        return self.matrix


def _team(name: str) -> TeamFixtureSummary:
    return TeamFixtureSummary(
        team_id=len(name),
        team_name=name,
        players_tracked=1,
        fixture_score=60,
        fixtures=(
            FixtureCell(9, "Example (H)", "Example", "Home", 2),
            FixtureCell(10, "Other (A)", "Other", "Away", 3),
            FixtureCell(11, "Third (H)", "Third", "Home", 2),
        ),
    )


def test_transfer_finder_returns_affordable_same_position_upgrades() -> None:
    outgoing = _row(1, "Outgoing", "MID", team="Alpha", price=6.0, final_score=50, points_per_game=2.0)
    replacement = _row(2, "Upgrade", "MID", team="Beta", price=6.5, final_score=78, points_per_game=5.0)
    unavailable = _row(3, "Unavailable", "MID", team="Gamma", price=6.2, final_score=90, points_per_game=8.0, status="i")
    different_position = _row(4, "Defender", "DEF", team="Delta", price=6.0, final_score=95, points_per_game=7.0)
    rows = (outgoing, replacement, unavailable, different_position)
    service = DecisionToolsService(_Recommendations(rows), _Fixtures(tuple(_team(row.team) for row in rows)))

    options = service.transfer_recommendations(1, extra_budget=0.5, horizon=3)

    assert len(options) == 1
    assert options[0].replacement.name == "Upgrade"
    assert options[0].price_cap == 6.5
    assert options[0].projected_gain > 0
    assert 0 <= options[0].confidence <= 100


def test_captain_shortlist_exposes_three_distinct_roles_when_possible() -> None:
    safe = _row(1, "Safe", "MID", team="Alpha", price=10.0, final_score=82, points_per_game=6.0, minutes_score=95)
    balanced = _row(2, "Balanced", "FWD", team="Beta", price=9.0, final_score=80, points_per_game=6.0, expected_score=98, fixture_score=85)
    differential = _row(3, "Differential", "MID", team="Gamma", price=7.0, final_score=76, points_per_game=5.0, expected_score=90, ownership=4)
    goalkeeper = _row(4, "Goalkeeper", "GK", team="Delta", price=5.0, final_score=99, points_per_game=8.0, minutes_score=100)
    rows = (safe, balanced, differential, goalkeeper)
    service = DecisionToolsService(_Recommendations(rows), _Fixtures(tuple(_team(row.team) for row in rows)))

    shortlist = service.captain_shortlist(3)

    assert [item.role for item in shortlist] == ["Safe", "Balanced", "Differential"]
    assert shortlist[2].player.ownership < 10
    assert all(item.player.position != "GK" for item in shortlist)
    assert all(item.projected_points > 0 for item in shortlist)
    assert len({item.player.player_id for item in shortlist}) == 3
