"""Pure presentation helpers for the Advanced Planner schedule-risk section."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from src.domain.schedule_risk import (
    DoubleGameweekProbabilityProjection,
    FixtureProbabilityProjection,
    GameweekRiskSummary,
    ScheduleCongestionLeader,
    ScheduleRiskStatus,
    SquadScheduleExposure,
)


RISK_STYLE: Mapping[str, tuple[str, str]] = {
    "confirmed_blank": ("blank", "Confirmed blank"),
    "confirmed_double": ("double", "Confirmed double"),
    "normal": ("normal", "Normal"),
    "incomplete": ("incomplete", "Data incomplete"),
}


def risk_status_help() -> str:
    return (
        "Confirmed blank/double statuses come from the official FPL fixture allocation. "
        "Probability is shown only when an auditable, current input is configured; "
        "the current project intentionally has no invented probability inputs."
    )


def _projection_maps(
    fixture_projections: Iterable[FixtureProbabilityProjection],
    double_projections: Iterable[DoubleGameweekProbabilityProjection],
) -> tuple[dict[int, float], dict[int, float]]:
    blank_by_gw: dict[int, float] = {}
    double_by_gw: dict[int, float] = {}
    for projection in fixture_projections:
        blank_by_gw[projection.source_gameweek] = max(
            blank_by_gw.get(projection.source_gameweek, 0.0), projection.blank_probability
        )
    for projection in double_projections:
        double_by_gw[projection.target_gameweek] = max(
            double_by_gw.get(projection.target_gameweek, 0.0), projection.double_probability
        )
    return blank_by_gw, double_by_gw


def build_risk_strip_rows(
    summaries: Iterable[GameweekRiskSummary],
    fixture_projections: Iterable[FixtureProbabilityProjection] = (),
    double_projections: Iterable[DoubleGameweekProbabilityProjection] = (),
    gameweeks: Iterable[int] = range(1, 39),
) -> tuple[dict[str, object], ...]:
    """Aggregate team-level facts into compact, tooltip-ready GW strip rows."""
    by_gw: dict[int, list[GameweekRiskSummary]] = {}
    for summary in summaries:
        by_gw.setdefault(summary.gameweek, []).append(summary)
    blank_by_gw, double_by_gw = _projection_maps(fixture_projections, double_projections)
    rows: list[dict[str, object]] = []
    for gameweek in gameweeks:
        team_rows = by_gw.get(gameweek, [])
        if not team_rows:
            status_key = "incomplete"
            blank_count = double_count = 0
        else:
            blank_count = sum(item.status is ScheduleRiskStatus.CONFIRMED_BLANK for item in team_rows)
            double_count = sum(item.status is ScheduleRiskStatus.CONFIRMED_DOUBLE for item in team_rows)
            status_key = (
                "confirmed_blank" if blank_count else
                "confirmed_double" if double_count else
                "normal"
            )
        style, label = RISK_STYLE[status_key]
        blank_probability = blank_by_gw.get(gameweek)
        double_probability = double_by_gw.get(gameweek)
        probability_text = ""
        if blank_probability is not None:
            probability_text += f"B {blank_probability:.0%}"
        if double_probability is not None:
            probability_text += f"{' · ' if probability_text else ''}D {double_probability:.0%}"
        if not probability_text:
            probability_text = "No projection"
        rows.append(
            {
                "gameweek": gameweek,
                "status_key": status_key,
                "status_class": style,
                "status_label": label,
                "blank_count": blank_count,
                "double_count": double_count,
                "probability": probability_text,
                "title": (
                    f"GW{gameweek}: {label}. {blank_count} blank club(s), "
                    f"{double_count} double club(s). {probability_text}."
                ),
            }
        )
    return tuple(rows)


def build_team_risk_matrix(
    summaries: Iterable[GameweekRiskSummary],
    team_names: Iterable[tuple[int, str, str]],
    gameweeks: Sequence[int] = tuple(range(1, 39)),
    european_team_ids: set[int] | None = None,
) -> tuple[dict[str, object], ...]:
    """Build stable dataframe rows for the confirmed team/GW matrix."""
    summary_map = {(item.team_id, item.gameweek): item for item in summaries}
    selected_ids = set(european_team_ids) if european_team_ids is not None else None
    rows: list[dict[str, object]] = []
    for team_id, team_name, team_code in sorted(team_names, key=lambda item: item[1]):
        if selected_ids is not None and team_id not in selected_ids:
            continue
        row: dict[str, object] = {"Club": team_name, "Code": team_code}
        for gameweek in gameweeks:
            summary = summary_map.get((team_id, gameweek))
            if summary is None:
                value = "—"
            elif summary.status is ScheduleRiskStatus.CONFIRMED_BLANK:
                value = "B"
            elif summary.status is ScheduleRiskStatus.CONFIRMED_DOUBLE:
                value = "D"
            else:
                value = "·"
            row[f"GW{gameweek}"] = value
        rows.append(row)
    return tuple(rows)


def build_congestion_leader_rows(
    leaders: Iterable[ScheduleCongestionLeader],
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    """Convert typed congestion leaders to a concise table contract."""
    return tuple(
        {
            "Club": leader.team_name,
            "Europe": leader.european_competition or "—",
            "Matches · next 14d": leader.matches_next_14_days,
            "Shortest rest (days)": leader.shortest_rest_days,
            "Short-rest gaps": leader.short_rest_count,
            "Congestion score": leader.congestion_score,
            "Why": leader.explanation,
        }
        for leader in tuple(leaders)[:limit]
    )


def build_squad_exposure_rows(
    exposure: SquadScheduleExposure,
) -> tuple[dict[str, object], ...]:
    """Convert the session-only squad exposure into an auditable player table."""
    return tuple(
        {
            "Player": item.player_name,
            "Team": item.team_name,
            "Pos": item.position,
            "Squad weight": item.squad_weight,
            "Confirmed blank": ", ".join(f"GW{gw}" for gw in item.confirmed_blank_gameweeks) or "—",
            "Expected blank": item.expected_blank_fixtures,
            "Expected extra fixtures": item.expected_extra_fixtures,
            "Congestion": item.congestion_score,
            "Why": item.explanation,
        }
        for item in exposure.affected_players
        if item.expected_blank_fixtures > 0
        or item.expected_extra_fixtures > 0
        or (item.congestion_score or 0) > 0
    )
