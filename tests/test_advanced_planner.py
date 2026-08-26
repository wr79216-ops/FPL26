from collections import Counter

import pytest

from src.services.advanced_planner import (
    AdvancedPlannerService,
    ImportedSquad,
    SQUAD_REQUIREMENTS,
    SquadPick,
)
from src.services.recommendation_engine import RecommendationRow


class _Decisions:
    def __init__(self, rows: tuple[RecommendationRow, ...]) -> None:
        self.rows = rows

    def player_options(self, horizon: int) -> tuple[RecommendationRow, ...]:
        return self.rows


def _row(player_id: int, position: str, team: str, price: float) -> RecommendationRow:
    score = 90 - player_id
    return RecommendationRow(
        player_id=player_id,
        name=f"Player {player_id}",
        team=team,
        position=position,
        status="a",
        news="",
        price=price,
        ownership=10,
        minutes=900,
        form=5,
        points_per_game=5,
        xg_per_90=0.2,
        xa_per_90=0.1,
        xgi_per_90=0.3,
        confidence=1,
        next_fixture="Example (H)",
        form_score=60,
        fixture_score=70,
        expected_score=score,
        minutes_score=90,
        history_score=50,
        value_score=60,
        bonus_score=50,
        ownership_score=50,
        final_score=score,
        category="Strong Buy",
        reason="Fixture and minutes",
    )


def test_wildcard_optimizer_builds_a_legal_squad_and_lineup() -> None:
    rows = []
    player_id = 1
    for position, count in {"GK": 4, "DEF": 8, "MID": 8, "FWD": 6}.items():
        for _ in range(count):
            rows.append(
                _row(
                    player_id,
                    position,
                    f"Team {(player_id - 1) % 8 + 1}",
                    4.0 + (player_id % 5) * 0.5,
                )
            )
            player_id += 1
    service = AdvancedPlannerService(
        ingestion=None,  # type: ignore[arg-type]
        decisions=_Decisions(tuple(rows)),  # type: ignore[arg-type]
        fixture_analytics=None,  # type: ignore[arg-type]
    )

    result = service.optimize_wildcard(100.0, horizon=5, beam_width=500)

    assert len(result.players) == 15
    assert Counter(player.position for player in result.players) == SQUAD_REQUIREMENTS
    assert max(Counter(player.team for player in result.players).values()) <= 3
    assert result.total_cost <= 100
    assert len(result.starters) == 11
    assert len(result.bench) == 4
    assert result.captain.position != "GK"


def test_transfer_suggestions_are_position_matched_affordable_and_personalised() -> None:
    positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    squad_rows = tuple(
        _row(50 + index, position, f"Team {index % 7}", 5.0)
        for index, position in enumerate(positions)
    )
    upgrade = _row(2, "FWD", "Upgrade FC", 6.0)
    service = AdvancedPlannerService(
        ingestion=None,  # type: ignore[arg-type]
        decisions=_Decisions((*squad_rows, upgrade)),  # type: ignore[arg-type]
        fixture_analytics=None,  # type: ignore[arg-type]
    )
    imported = ImportedSquad(
        manager_id=1,
        manager_name="Test Manager",
        team_name="Test XI",
        gameweek=1,
        gameweek_points=None,
        gameweek_rank=None,
        bank=2.0,
        current_squad_cost=75.0,
        active_chip=None,
        picks=tuple(
            SquadPick(
                player=player,
                squad_position=index + 1,
                multiplier=1 if index < 11 else 0,
                gameweek_points=None,
                is_captain=False,
                is_vice_captain=False,
            )
            for index, player in enumerate(squad_rows)
        ),
    )

    plan = service.suggest_transfers(imported, horizon=5, free_transfers=1)

    assert len(plan.transfers) == 1
    suggestion = plan.transfers[0]
    assert suggestion.player_in == upgrade
    assert suggestion.player_out.position == "FWD"
    assert suggestion.price_delta == 1.0
    assert suggestion.score_delta > 0
    assert plan.bank_after == 1.0


def test_schedule_transfer_adjustment_requires_validation_and_is_auditable() -> None:
    positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    squad_rows = tuple(
        _row(70 + index, position, f"Team {index % 7}", 5.0)
        for index, position in enumerate(positions)
    )
    upgrade = _row(2, "FWD", "Schedule FC", 5.0)
    service = AdvancedPlannerService(
        ingestion=None,  # type: ignore[arg-type]
        decisions=_Decisions((*squad_rows, upgrade)),  # type: ignore[arg-type]
        fixture_analytics=None,  # type: ignore[arg-type]
    )
    imported = ImportedSquad(
        2, "Manager", "Test XI", 1, None, None, 0.0, 75.0, None,
        tuple(
            SquadPick(player, index + 1, 1 if index < 11 else 0, None, False, False)
            for index, player in enumerate(squad_rows)
        ),
    )

    with pytest.raises(ValueError, match="passed production validation"):
        service.suggest_transfers(
            imported, 5, team_priority_adjustments={"Schedule FC": 5.0}
        )

    plan = service.suggest_transfers(
        imported,
        5,
        team_priority_adjustments={"Schedule FC": 5.0},
        schedule_adjustment_validated=True,
    )

    assert plan.schedule_adjustment_active is True
    assert plan.transfers[0].schedule_adjustment == 5.0
    assert "validated schedule +5.0" in plan.transfers[0].reason


def test_set_piece_transfer_adjustment_is_small_and_visible() -> None:
    positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    squad_rows = tuple(
        _row(100 + index, position, f"Team {index % 7}", 5.0)
        for index, position in enumerate(positions)
    )
    upgrade = _row(2, "FWD", "Set Piece FC", 5.0)
    service = AdvancedPlannerService(
        ingestion=None,  # type: ignore[arg-type]
        decisions=_Decisions((*squad_rows, upgrade)),  # type: ignore[arg-type]
        fixture_analytics=None,  # type: ignore[arg-type]
    )
    imported = ImportedSquad(
        3, "Manager", "Test XI", 1, None, None, 0.0, 75.0, None,
        tuple(
            SquadPick(player, index + 1, 1 if index < 11 else 0, None, False, False)
            for index, player in enumerate(squad_rows)
        ),
    )

    plan = service.suggest_transfers(
        imported, 5, player_priority_adjustments={upgrade.player_id: 3.0}
    )

    assert plan.set_piece_signal_active is True
    assert plan.transfers[0].set_piece_adjustment == 3.0
    assert "set-piece +3.0" in plan.transfers[0].reason
