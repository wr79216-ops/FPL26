"""Official-FPL gameweek recap calculations for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class WrappedMetric:
    """One concise, source-backed highlight in a gameweek recap."""

    label: str
    value: str
    detail: str
    tone: str = "green"


@dataclass(frozen=True)
class WrappedChip:
    """A globally active FPL chip for the completed gameweek."""

    name: str
    uses: int


@dataclass(frozen=True)
class GameweekWrapped:
    """Dashboard-ready recap built solely from official FPL payloads."""

    gameweek: int
    average_score: Optional[int]
    metrics: tuple[WrappedMetric, ...]
    chips: tuple[WrappedChip, ...]


def previous_completed_gameweek(events: Iterable[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """Choose the previous event, or the current event while a season is starting.

    FPL keeps ``is_current`` true while the first gameweek is being checked. In
    that short window, the local gameweek snapshot is still the useful recap
    available to the dashboard.
    """
    event_list = [event for event in events if isinstance(event, Mapping)]
    previous = [event for event in event_list if event.get("is_previous")]
    if previous:
        return previous[0]
    finished = [event for event in event_list if event.get("finished")]
    if finished:
        return max(finished, key=lambda event: _integer(event.get("id")))
    current = [event for event in event_list if event.get("is_current")]
    return current[0] if current else None


def build_gameweek_wrapped(
    event: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    live: Mapping[str, Any],
) -> Optional[GameweekWrapped]:
    """Convert one FPL event plus its live player stats into recap highlights.

    The FPL API publishes player-level xG/xA/xGC, not a dedicated team xGC
    table. The defensive tile therefore takes the highest-minute player's xGC
    per club (normally the goalkeeper) as the closest official team proxy.
    """
    gameweek = _integer(event.get("id"))
    if gameweek <= 0:
        return None
    players = {
        _integer(player.get("id")): player
        for player in bootstrap.get("elements", [])
        if isinstance(player, Mapping) and _integer(player.get("id")) > 0
    }
    teams = {
        _integer(team.get("id")): str(team.get("name") or "Unknown team")
        for team in bootstrap.get("teams", [])
        if isinstance(team, Mapping) and _integer(team.get("id")) > 0
    }
    goalkeeper_position_ids = {
        _integer(position.get("id"))
        for position in bootstrap.get("element_types", [])
        if isinstance(position, Mapping)
        and str(position.get("singular_name_short") or "").upper() in {"GK", "GKP"}
    }
    live_rows = []
    for row in live.get("elements", []):
        if not isinstance(row, Mapping):
            continue
        player = players.get(_integer(row.get("id")))
        stats = row.get("stats")
        if player is not None and isinstance(stats, Mapping):
            live_rows.append((player, stats))
    if not live_rows:
        return None
    played_rows = [row for row in live_rows if _integer(row[1].get("minutes")) > 0] or live_rows

    def player_name(player_id: Any) -> str:
        player = players.get(_integer(player_id))
        return _name(player) if player else "—"

    def top_player(stat: str, minimum_minutes: int = 0) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        eligible = [row for row in live_rows if _integer(row[1].get("minutes")) >= minimum_minutes]
        return max(eligible or live_rows, key=lambda row: _number(row[1].get(stat)))

    top_points_player, top_points = top_player("total_points")
    top_xg_player, top_xg = top_player("expected_goals", minimum_minutes=1)
    top_xa_player, top_xa = top_player("expected_assists", minimum_minutes=1)
    over_player, over_stats = max(
        played_rows,
        key=lambda row: _number(row[1].get("goals_scored")) - _number(row[1].get("expected_goals")),
    )
    under_player, under_stats = min(
        played_rows,
        key=lambda row: _number(row[1].get("goals_scored")) - _number(row[1].get("expected_goals")),
    )

    team_xg: dict[int, float] = {}
    team_xgc_candidates: dict[int, list[tuple[bool, int, float]]] = {}
    for player, stats in live_rows:
        team_id = _integer(player.get("team"))
        team_xg[team_id] = team_xg.get(team_id, 0.0) + _number(stats.get("expected_goals"))
        team_xgc_candidates.setdefault(team_id, []).append((
            _integer(player.get("element_type")) in goalkeeper_position_ids,
            _integer(stats.get("minutes")),
            _number(stats.get("expected_goals_conceded")),
        ))
    best_attack_id, best_attack_xg = max(team_xg.items(), key=lambda item: item[1])
    # Goalkeeper xGC is the closest official player-level proxy for team xGC;
    # use the greatest-minute player only when position metadata is unavailable.
    team_xgc = {
        team_id: max(values, key=lambda item: (item[0], item[1]))[2]
        for team_id, values in team_xgc_candidates.items()
        if values
    }
    best_defence_id, best_defence_xgc = min(team_xgc.items(), key=lambda item: item[1])

    captain_id = event.get("most_captained")
    selected_label = "Most captained" if _integer(captain_id) in players else "Most selected"
    selected_id = captain_id if selected_label == "Most captained" else event.get("most_selected")
    most_bought_id = event.get("most_transferred_in")
    metrics = (
        WrappedMetric(selected_label, player_name(selected_id), "Official FPL popularity", "purple"),
        WrappedMetric("Most bought", player_name(most_bought_id), "Official transfers in", "green"),
        WrappedMetric("Most points", _name(top_points_player), f"{_integer(top_points.get('total_points'))} FPL points", "amber"),
        WrappedMetric("Most xG", _name(top_xg_player), f"{_number(top_xg.get('expected_goals')):.2f} xG", "blue"),
        WrappedMetric("Best attack (xG)", teams.get(best_attack_id, "—"), f"{best_attack_xg:.2f} team xG", "green"),
        WrappedMetric("xG over-performer", _name(over_player), _signed(_number(over_stats.get("goals_scored")) - _number(over_stats.get("expected_goals")), " goals vs xG"), "green"),
        WrappedMetric("Most xA", _name(top_xa_player), f"{_number(top_xa.get('expected_assists')):.2f} xA", "orange"),
        WrappedMetric("Best defence (xGC)", teams.get(best_defence_id, "—"), f"{best_defence_xgc:.2f} xGC proxy", "red"),
        WrappedMetric("xG under-performer", _name(under_player), _signed(_number(under_stats.get("goals_scored")) - _number(under_stats.get("expected_goals")), " goals vs xG"), "red"),
    )
    chips = tuple(
        WrappedChip(_chip_name(chip.get("chip_name") or chip.get("name")), _integer(chip.get("num_played")))
        for chip in event.get("chip_plays", [])
        if isinstance(chip, Mapping) and _integer(chip.get("num_played")) > 0
    )
    average_score = event.get("average_entry_score")
    return GameweekWrapped(
        gameweek=gameweek,
        average_score=_integer(average_score) if average_score is not None else None,
        metrics=metrics,
        chips=chips,
    )


def _integer(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _name(player: Optional[Mapping[str, Any]]) -> str:
    if not player:
        return "—"
    return str(player.get("web_name") or player.get("second_name") or "—")


def _signed(value: float, suffix: str) -> str:
    return f"{value:+.2f}{suffix}"


def _chip_name(value: Any) -> str:
    labels = {
        "bboost": "Bench Boost",
        "3xc": "Triple Captain",
        "freehit": "Free Hit",
        "wildcard": "Wildcard",
    }
    raw = str(value or "Chip")
    return labels.get(raw.lower(), raw.replace("_", " ").title())
