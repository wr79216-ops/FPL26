"""Transform official FPL JSON into stable domain contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.domain.contracts import (
    CurrentPlayerStatsRecord,
    FixtureRecord,
    GameweekHistoryRecord,
    GameweekSnapshotRecord,
    PlayerRecord,
    Position,
    TeamRecord,
)
from src.utils.season import season_label


class DataTransformError(ValueError):
    """Raised when an official payload cannot become a valid domain record."""


POSITION_BY_SHORT_NAME = {
    "GKP": Position.GK,
    "GK": Position.GK,
    "DEF": Position.DEF,
    "MID": Position.MID,
    "FWD": Position.FWD,
}


def _required(record: Mapping[str, Any], field: str, context: str) -> Any:
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DataTransformError(f"{context} missing required field: {field}")
    return value


def _integer(value: Any, field: str, context: str, default: Optional[int] = None) -> int:
    if value is None and default is not None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise DataTransformError(f"{context} has invalid integer field: {field}") from exc


def _number(value: Any, field: str, context: str, default: Optional[float] = None) -> float:
    if value is None and default is not None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DataTransformError(f"{context} has invalid numeric field: {field}") from exc


def _boolean(value: Any) -> bool:
    return bool(value)


def _parse_kickoff(value: Any, context: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise DataTransformError(f"{context} has invalid kickoff_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataTransformError(f"{context} has invalid kickoff_time") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _position_mapping(element_types: Iterable[Mapping[str, Any]]) -> Dict[int, Position]:
    mapping: Dict[int, Position] = {}
    for element_type in element_types:
        context = "element_type"
        element_type_id = _integer(_required(element_type, "id", context), "id", context)
        short_name = str(_required(element_type, "singular_name_short", context)).upper()
        position = POSITION_BY_SHORT_NAME.get(short_name)
        if position is None:
            raise DataTransformError(f"element_type has unsupported position: {short_name}")
        mapping[element_type_id] = position
    return mapping


def current_gameweek(events: Iterable[Mapping[str, Any]]) -> int:
    """Select current GW, then next GW, then the latest event as a safe fallback."""
    event_list = list(events)
    for key in ("is_current", "is_next"):
        matching = [event for event in event_list if event.get(key)]
        if matching:
            return _integer(_required(matching[0], "id", "event"), "id", "event")
    event_ids = [
        _integer(_required(event, "id", "event"), "id", "event") for event in event_list
    ]
    return max(event_ids, default=0)


def transform_teams(teams: Iterable[Mapping[str, Any]]) -> List[TeamRecord]:
    transformed = []
    for raw_team in teams:
        context = f"team[{raw_team.get('id', '?')}]"
        transformed.append(
            TeamRecord(
                team_id=_integer(_required(raw_team, "id", context), "id", context),
                name=str(_required(raw_team, "name", context)),
                short_name=str(_required(raw_team, "short_name", context)),
                strength=_integer(raw_team.get("strength"), "strength", context, default=0),
                strength_overall_home=_integer(
                    raw_team.get("strength_overall_home"),
                    "strength_overall_home",
                    context,
                    default=0,
                ),
                strength_overall_away=_integer(
                    raw_team.get("strength_overall_away"),
                    "strength_overall_away",
                    context,
                    default=0,
                ),
                strength_attack_home=_integer(
                    raw_team.get("strength_attack_home"),
                    "strength_attack_home",
                    context,
                    default=0,
                ),
                strength_attack_away=_integer(
                    raw_team.get("strength_attack_away"),
                    "strength_attack_away",
                    context,
                    default=0,
                ),
                strength_defence_home=_integer(
                    raw_team.get("strength_defence_home"),
                    "strength_defence_home",
                    context,
                    default=0,
                ),
                strength_defence_away=_integer(
                    raw_team.get("strength_defence_away"),
                    "strength_defence_away",
                    context,
                    default=0,
                ),
            )
        )
    return transformed


def transform_players(
    elements: Iterable[Mapping[str, Any]],
    element_types: Iterable[Mapping[str, Any]],
) -> List[PlayerRecord]:
    positions = _position_mapping(element_types)
    transformed = []
    for raw_player in elements:
        context = f"player[{raw_player.get('id', '?')}]"
        position_id = _integer(
            _required(raw_player, "element_type", context), "element_type", context
        )
        position = positions.get(position_id)
        if position is None:
            raise DataTransformError(f"{context} references unknown position id: {position_id}")
        transformed.append(
            PlayerRecord(
                player_id=_integer(_required(raw_player, "id", context), "id", context),
                first_name=str(_required(raw_player, "first_name", context)),
                second_name=str(_required(raw_player, "second_name", context)),
                web_name=str(_required(raw_player, "web_name", context)),
                team_id=_integer(_required(raw_player, "team", context), "team", context),
                position_id=position_id,
                position=position,
                status=str(raw_player.get("status") or "a"),
                news=str(raw_player.get("news") or ""),
                price=_number(_required(raw_player, "now_cost", context), "now_cost", context)
                / 10,
                ownership=_number(
                    raw_player.get("selected_by_percent"),
                    "selected_by_percent",
                    context,
                    default=0.0,
                ),
            )
        )
    return transformed


def transform_current_player_stats(
    elements: Iterable[Mapping[str, Any]],
    gameweek: int,
    snapshot_at: Optional[datetime] = None,
) -> List[CurrentPlayerStatsRecord]:
    captured_at = snapshot_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    transformed = []
    for raw_player in elements:
        context = f"player_stats[{raw_player.get('id', '?')}]"
        transformed.append(
            CurrentPlayerStatsRecord(
                player_id=_integer(_required(raw_player, "id", context), "id", context),
                gameweek=gameweek,
                minutes=_integer(raw_player.get("minutes"), "minutes", context, default=0),
                starts=_integer(raw_player.get("starts"), "starts", context, default=0),
                goals=_integer(raw_player.get("goals_scored"), "goals_scored", context, default=0),
                assists=_integer(raw_player.get("assists"), "assists", context, default=0),
                clean_sheets=_integer(
                    raw_player.get("clean_sheets"), "clean_sheets", context, default=0
                ),
                saves=_integer(raw_player.get("saves"), "saves", context, default=0),
                bonus=_integer(raw_player.get("bonus"), "bonus", context, default=0),
                bps=_integer(raw_player.get("bps"), "bps", context, default=0),
                influence=_number(raw_player.get("influence"), "influence", context, default=0.0),
                creativity=_number(
                    raw_player.get("creativity"), "creativity", context, default=0.0
                ),
                threat=_number(raw_player.get("threat"), "threat", context, default=0.0),
                ict_index=_number(
                    raw_player.get("ict_index"), "ict_index", context, default=0.0
                ),
                expected_goals=_number(
                    raw_player.get("expected_goals"), "expected_goals", context, default=0.0
                ),
                expected_assists=_number(
                    raw_player.get("expected_assists"),
                    "expected_assists",
                    context,
                    default=0.0,
                ),
                expected_goal_involvements=_number(
                    raw_player.get("expected_goal_involvements"),
                    "expected_goal_involvements",
                    context,
                    default=0.0,
                ),
                total_points=_integer(
                    raw_player.get("total_points"), "total_points", context, default=0
                ),
                points_per_game=_number(
                    raw_player.get("points_per_game"), "points_per_game", context, default=0.0
                ),
                form=_number(raw_player.get("form"), "form", context, default=0.0),
                selected_by_percent=_number(
                    raw_player.get("selected_by_percent"),
                    "selected_by_percent",
                    context,
                    default=0.0,
                ),
                price=_number(raw_player.get("now_cost"), "now_cost", context, default=0.0)
                / 10,
                snapshot_at=captured_at,
            )
        )
    return transformed


def transform_gameweek_snapshots(
    current_stats: List[CurrentPlayerStatsRecord], captured_at: datetime
) -> List[GameweekSnapshotRecord]:
    """Project current official values into idempotent gameweek snapshots."""
    season = season_label(captured_at)
    return [
        GameweekSnapshotRecord(
            season=season,
            gameweek=stats.gameweek,
            player_id=stats.player_id,
            price=stats.price,
            ownership=stats.selected_by_percent,
            form=stats.form,
            total_points=stats.total_points,
            minutes=stats.minutes,
            expected_goals=stats.expected_goals,
            expected_assists=stats.expected_assists,
            expected_goal_involvements=stats.expected_goal_involvements,
            ict_index=stats.ict_index,
            captured_at=captured_at,
        )
        for stats in current_stats
    ]


def transform_gameweek_history(
    history: Iterable[Mapping[str, Any]], player_id: int, season: str
) -> List[GameweekHistoryRecord]:
    """Transform an element-summary history payload into stable gameweek records."""
    transformed = []
    for raw_history in history:
        context = f"player_history[{player_id}:{raw_history.get('round', '?')}]"
        transformed.append(
            GameweekHistoryRecord(
                player_id=player_id,
                season=season,
                gameweek=_integer(_required(raw_history, "round", context), "round", context),
                fixture_id=_integer(
                    _required(raw_history, "fixture", context), "fixture", context
                ),
                opponent_team_id=_integer(
                    _required(raw_history, "opponent_team", context),
                    "opponent_team",
                    context,
                ),
                was_home=_boolean(raw_history.get("was_home")),
                minutes=_integer(raw_history.get("minutes"), "minutes", context, default=0),
                goals=_integer(
                    raw_history.get("goals_scored"), "goals_scored", context, default=0
                ),
                assists=_integer(raw_history.get("assists"), "assists", context, default=0),
                clean_sheets=_integer(
                    raw_history.get("clean_sheets"), "clean_sheets", context, default=0
                ),
                bonus=_integer(raw_history.get("bonus"), "bonus", context, default=0),
                bps=_integer(raw_history.get("bps"), "bps", context, default=0),
                xg=_number(raw_history.get("expected_goals"), "expected_goals", context, 0.0),
                xa=_number(
                    raw_history.get("expected_assists"), "expected_assists", context, 0.0
                ),
                xgi=_number(
                    raw_history.get("expected_goal_involvements"),
                    "expected_goal_involvements",
                    context,
                    0.0,
                ),
                xgc=_number(
                    raw_history.get("expected_goals_conceded"),
                    "expected_goals_conceded",
                    context,
                    0.0,
                ),
                total_points=_integer(
                    raw_history.get("total_points"), "total_points", context, default=0
                ),
                value=_number(raw_history.get("value"), "value", context, 0.0) / 10,
            )
        )
    return transformed


def transform_fixtures(fixtures: Iterable[Mapping[str, Any]]) -> List[FixtureRecord]:
    transformed = []
    for raw_fixture in fixtures:
        context = f"fixture[{raw_fixture.get('id', '?')}]"
        event = raw_fixture.get("event")
        transformed.append(
            FixtureRecord(
                fixture_id=_integer(_required(raw_fixture, "id", context), "id", context),
                gameweek=_integer(event, "event", context) if event is not None else None,
                home_team_id=_integer(
                    _required(raw_fixture, "team_h", context), "team_h", context
                ),
                away_team_id=_integer(
                    _required(raw_fixture, "team_a", context), "team_a", context
                ),
                kickoff_time=_parse_kickoff(raw_fixture.get("kickoff_time"), context),
                home_difficulty=_integer(
                    _required(raw_fixture, "team_h_difficulty", context),
                    "team_h_difficulty",
                    context,
                ),
                away_difficulty=_integer(
                    _required(raw_fixture, "team_a_difficulty", context),
                    "team_a_difficulty",
                    context,
                ),
                home_score=_integer(raw_fixture["team_h_score"], "team_h_score", context)
                if raw_fixture.get("team_h_score") is not None
                else None,
                away_score=_integer(raw_fixture["team_a_score"], "team_a_score", context)
                if raw_fixture.get("team_a_score") is not None
                else None,
                finished=_boolean(raw_fixture.get("finished")),
                started=_boolean(raw_fixture.get("started")),
            )
        )
    return transformed
