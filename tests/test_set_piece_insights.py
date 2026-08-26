from src.services.recommendation_engine import RecommendationRow
from src.services.set_piece_insights import (
    SetPieceInsightsService,
    load_set_piece_catalog,
)


def _row(player_id: int, name: str, team: str) -> RecommendationRow:
    return RecommendationRow(
        player_id=player_id,
        name=name,
        team=team,
        position="MID",
        status="a",
        news="",
        price=7.0,
        ownership=10.0,
        minutes=900,
        form=5.0,
        points_per_game=5.0,
        xg_per_90=0.2,
        xa_per_90=0.2,
        xgi_per_90=0.4,
        confidence=1.0,
        next_fixture="Example (H)",
        form_score=60.0,
        fixture_score=60.0,
        expected_score=60.0,
        minutes_score=90.0,
        history_score=50.0,
        value_score=60.0,
        bonus_score=50.0,
        ownership_score=50.0,
        final_score=60.0,
        category="Strong Buy",
        reason="Test row",
    )


def test_expected_roles_resolve_against_official_fpl_style_names() -> None:
    service = SetPieceInsightsService(load_set_piece_catalog())

    saka = service.player_insight(_row(1, "Saka", "Arsenal"))
    fernandes = service.player_insight(_row(2, "B.Fernandes", "Man Utd"))
    kroupi = service.player_insight(_row(3, "Kroupi.Jr", "Bournemouth"))

    assert any(role.role_type == "penalties" and role.priority == 1 for role in saka.roles)
    assert saka.role_signal == 4.0
    assert fernandes.role_signal == 4.0
    assert len(kroupi.roles) == 1
    assert kroupi.roles[0].conditional is True
    assert kroupi.role_signal == 1.8


def test_historical_context_is_team_level_and_adjustments_are_small_and_auditable() -> None:
    service = SetPieceInsightsService(load_set_piece_catalog())
    arsenal = _row(10, "Saka", "Arsenal")
    leeds = _row(11, "Stach", "Leeds")

    arsenal_insight = service.player_insight(arsenal)
    leeds_insight = service.player_insight(leeds)
    adjustments = service.priority_adjustments((arsenal, leeds))

    assert arsenal_insight.historical_set_piece_goals == 20
    assert leeds_insight.historical_set_piece_goals is None
    assert adjustments == {10: 4.0, 11: 2.0}
