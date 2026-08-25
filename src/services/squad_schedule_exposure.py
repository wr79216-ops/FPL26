"""Personalised, evidence-gated schedule exposure for imported FPL squads."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from src.domain.schedule_risk import (
    ScheduleRiskStatus,
    SquadScheduleExposure,
    SquadSchedulePlayerExposure,
)
from src.services.advanced_planner import ImportedSquad, SquadPick
from src.services.schedule_congestion import PhaseCScheduleSnapshot


def _team_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _squad_weight(pick: SquadPick) -> float:
    """Use documented starter, bench, and captain exposure weights."""
    if pick.multiplier > 0:
        weight = 1.0
    elif pick.player.position == "GK":
        weight = 0.20
    else:
        weight = 0.35
    if pick.is_captain:
        weight += 1.0
    return weight


def calculate_squad_schedule_exposure(
    imported: ImportedSquad,
    snapshot: PhaseCScheduleSnapshot,
    horizon: int,
) -> SquadScheduleExposure:
    """Calculate confirmed and evidence-backed schedule exposure for an imported squad.

    A projected blank for a team/GW uses the highest available controlled
    probability rather than assuming multiple unresolved cup paths are
    independent. Projected double exposure is additive per distinct fixture.
    """
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    gameweeks = tuple(range(imported.gameweek, min(38, imported.gameweek + horizon - 1) + 1))
    if not gameweeks:
        raise ValueError("imported squad gameweek must be between 1 and 38")

    phase_b = snapshot.phase_b
    team_ids_by_name = {
        _team_key(team_name): team_id
        for team_id, team_name, _ in phase_b.team_names
    }
    risks = {
        (summary.team_id, summary.gameweek): summary
        for summary in phase_b.gameweek_risks
        if summary.gameweek in gameweeks
    }
    clashes_by_fixture = {
        clash.fixture_id: clash for clash in phase_b.structural_clashes
    }
    projected_blank_by_team_gw: dict[tuple[int, int], float] = {}
    for projection in snapshot.fixture_projections:
        clash = clashes_by_fixture.get(projection.fixture_id)
        if clash is None or projection.source_gameweek not in gameweeks:
            continue
        for team_id in (clash.home_team_id, clash.away_team_id):
            key = (team_id, projection.source_gameweek)
            projected_blank_by_team_gw[key] = max(
                projected_blank_by_team_gw.get(key, 0.0), projection.blank_probability
            )
    projected_double_by_team_gw: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    for projection in snapshot.double_gameweek_projections:
        clash = clashes_by_fixture.get(projection.fixture_id)
        if clash is None or projection.target_gameweek not in gameweeks:
            continue
        for team_id in (clash.home_team_id, clash.away_team_id):
            projected_double_by_team_gw[(team_id, projection.target_gameweek)].append(
                projection.double_probability
            )
    congestion_by_team = {
        leader.team_id: leader.congestion_score
        for leader in phase_b.congestion_leaders
    }

    exposures: list[SquadSchedulePlayerExposure] = []
    unresolved_player_ids: list[int] = []
    for pick in imported.picks:
        player = pick.player
        team_id = team_ids_by_name.get(_team_key(player.team))
        weight = _squad_weight(pick)
        if team_id is None:
            unresolved_player_ids.append(player.player_id)
            exposures.append(
                SquadSchedulePlayerExposure(
                    player_id=player.player_id,
                    player_name=player.name,
                    team_name=player.team,
                    team_id=None,
                    position=player.position,
                    squad_weight=weight,
                    confirmed_blank_gameweeks=(),
                    projected_blank_exposure=0.0,
                    confirmed_extra_fixtures=0.0,
                    projected_extra_fixtures=0.0,
                    congestion_score=None,
                    explanation="Player club could not be mapped to the official FPL team catalogue.",
                )
            )
            continue

        confirmed_blanks: list[int] = []
        confirmed_extra = 0.0
        projected_blank = 0.0
        projected_extra = 0.0
        for gameweek in gameweeks:
            summary = risks.get((team_id, gameweek))
            if summary is not None and summary.status is ScheduleRiskStatus.CONFIRMED_BLANK:
                confirmed_blanks.append(gameweek)
                continue
            if summary is not None and summary.status is ScheduleRiskStatus.CONFIRMED_DOUBLE:
                confirmed_extra += weight * max(0, len(summary.fixture_ids) - 1)
                continue
            projected_blank += weight * projected_blank_by_team_gw.get((team_id, gameweek), 0.0)
            projected_extra += weight * sum(projected_double_by_team_gw.get((team_id, gameweek), ()))

        exposure_bits = []
        if confirmed_blanks:
            exposure_bits.append("confirmed blank in " + ", ".join(f"GW{gw}" for gw in confirmed_blanks))
        if projected_blank:
            exposure_bits.append(f"projected blank exposure {projected_blank:.2f}")
        if confirmed_extra:
            exposure_bits.append(f"confirmed extra fixtures {confirmed_extra:.2f}")
        if projected_extra:
            exposure_bits.append(f"projected extra fixtures {projected_extra:.2f}")
        congestion = congestion_by_team.get(team_id)
        if congestion is not None:
            exposure_bits.append(f"14-day congestion {congestion:.1f}/100")
        exposures.append(
            SquadSchedulePlayerExposure(
                player_id=player.player_id,
                player_name=player.name,
                team_name=player.team,
                team_id=team_id,
                position=player.position,
                squad_weight=weight,
                confirmed_blank_gameweeks=tuple(confirmed_blanks),
                projected_blank_exposure=round(projected_blank, 3),
                confirmed_extra_fixtures=round(confirmed_extra, 3),
                projected_extra_fixtures=round(projected_extra, 3),
                congestion_score=congestion,
                explanation="; ".join(exposure_bits) or "No confirmed or evidence-backed schedule exposure in this window.",
            )
        )

    affected = tuple(
        sorted(
            exposures,
            key=lambda item: (
                -(item.expected_blank_fixtures + item.expected_extra_fixtures),
                -(item.congestion_score or 0),
                item.player_name,
            ),
        )
    )
    return SquadScheduleExposure(
        manager_id=imported.manager_id,
        gameweeks=gameweeks,
        expected_blank_starters=round(
            sum(item.expected_blank_fixtures for item in affected), 3
        ),
        expected_extra_fixtures=round(
            sum(item.expected_extra_fixtures for item in affected), 3
        ),
        affected_players=affected,
        unresolved_player_ids=tuple(unresolved_player_ids),
        as_of=(
            phase_b.gameweek_risks[0].as_of
            if phase_b.gameweek_risks
            else (
                snapshot.probability_catalog.inputs[0].as_of
                if snapshot.probability_catalog.inputs
                else datetime.now(timezone.utc)
            )
        ),
        explanation=(
            "Uses official FPL confirmed allocation first, then only current auditable "
            "blank/double projections. Squad data remains in the active app session."
        ),
    )
