"""Phase 11 official-data squad import and constraint-aware wildcard planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from config.settings import (
    DATABASE_PATH,
    EXTERNAL_PROVIDERS_CONFIG_PATH,
    SCORING_CONFIG_PATH,
)
from src.providers.registry import ProviderStatus, load_provider_statuses
from src.services.decision_tools import DecisionToolsService, get_decision_tools_service
from src.services.fixture_analytics import FixtureAnalyticsService, get_fixture_analytics_service
from src.services.fpl_ingestion import FPLIngestionService, get_fpl_ingestion_service
from src.services.recommendation_engine import RecommendationRow
from src.utils.text import normalize_display_name


SQUAD_REQUIREMENTS: Mapping[str, int] = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
VALID_STARTING_FORMATIONS = (
    {"GK": 1, "DEF": 3, "MID": 4, "FWD": 3},
    {"GK": 1, "DEF": 3, "MID": 5, "FWD": 2},
    {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3},
    {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2},
    {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1},
    {"GK": 1, "DEF": 5, "MID": 2, "FWD": 3},
    {"GK": 1, "DEF": 5, "MID": 3, "FWD": 2},
    {"GK": 1, "DEF": 5, "MID": 4, "FWD": 1},
)


@dataclass(frozen=True)
class SquadPick:
    player: RecommendationRow
    squad_position: int
    multiplier: int
    gameweek_points: int | None
    is_captain: bool
    is_vice_captain: bool


@dataclass(frozen=True)
class ImportedSquad:
    manager_id: int
    manager_name: str
    team_name: str
    gameweek: int
    gameweek_points: int | None
    gameweek_rank: int | None
    bank: float
    current_squad_cost: float
    active_chip: str | None
    picks: tuple[SquadPick, ...]

    @property
    def available_budget(self) -> float:
        return round(self.current_squad_cost + self.bank, 1)


@dataclass(frozen=True)
class OptimizedSquad:
    players: tuple[RecommendationRow, ...]
    starters: tuple[RecommendationRow, ...]
    bench: tuple[RecommendationRow, ...]
    total_cost: float
    remaining_budget: float
    total_score: float
    captain: RecommendationRow
    vice_captain: RecommendationRow
    method: str = "constraint-aware beam search"


@dataclass(frozen=True)
class SquadChange:
    player_out: RecommendationRow
    player_in: RecommendationRow
    price_delta: float
    score_delta: float


@dataclass(frozen=True)
class TransferSuggestion:
    """One legal, score-improving swap for an imported FPL squad."""

    player_out: RecommendationRow
    player_in: RecommendationRow
    price_delta: float
    score_delta: float
    fixture_delta: float
    minutes_delta: float
    priority: float
    reason: str
    base_priority: float = 0.0
    schedule_adjustment: float = 0.0


@dataclass(frozen=True)
class TransferPlan:
    """A small transfer plan that uses only the selected free transfers."""

    transfers: tuple[TransferSuggestion, ...]
    free_transfers_used: int
    bank_after: float
    total_score_gain: float
    schedule_adjustment_active: bool = False


@dataclass(frozen=True)
class _BeamState:
    players: tuple[RecommendationRow, ...]
    total_cost: float
    total_score: float
    team_counts: tuple[tuple[str, int], ...]
    last_index: int = -1


class AdvancedPlannerService:
    """Keep advanced planning official-first and external providers policy-gated."""

    def __init__(
        self,
        ingestion: FPLIngestionService,
        decisions: DecisionToolsService,
        fixture_analytics: FixtureAnalyticsService,
        provider_config_path: Path = EXTERNAL_PROVIDERS_CONFIG_PATH,
    ) -> None:
        self.ingestion = ingestion
        self.decisions = decisions
        self.fixture_analytics = fixture_analytics
        self.provider_config_path = Path(provider_config_path)

    def provider_statuses(self) -> tuple[ProviderStatus, ...]:
        return load_provider_statuses(self.provider_config_path)

    def import_public_squad(self, manager_id: int, horizon: int) -> ImportedSquad:
        """Load a public official FPL squad into memory for the active gameweek."""
        gameweek = self.ingestion.status_store.load().current_gameweek or 0
        if gameweek <= 0:
            raise ValueError("refresh official FPL data before importing a squad")
        entry = self.ingestion.client.get_entry(manager_id)
        payload = self.ingestion.client.get_entry_picks(manager_id, gameweek)
        bootstrap = self.ingestion.client.get_bootstrap()
        rankings = {
            row.player_id: row for row in self.decisions.player_options(horizon)
        }
        latest_points_by_player = {
            int(element["id"]): _optional_int(element.get("event_points"))
            for element in bootstrap["elements"]
            if isinstance(element, Mapping) and isinstance(element.get("id"), int)
        }
        raw_picks = payload["picks"]
        picks = []
        missing_ids = []
        for raw in raw_picks:
            player_id = int(raw["element"])
            player = rankings.get(player_id)
            if player is None:
                missing_ids.append(player_id)
                continue
            picks.append(
                SquadPick(
                    player=player,
                    squad_position=int(raw.get("position", len(picks) + 1)),
                    multiplier=int(raw.get("multiplier", 0)),
                    gameweek_points=latest_points_by_player.get(player_id),
                    is_captain=bool(raw.get("is_captain", False)),
                    is_vice_captain=bool(raw.get("is_vice_captain", False)),
                )
            )
        if missing_ids:
            raise ValueError(
                "squad contains players missing from the current official cache: "
                + ", ".join(str(player_id) for player_id in missing_ids)
            )
        if len(picks) != 15:
            raise ValueError("official squad response must contain 15 current players")

        history = payload.get("entry_history", {})
        bank = float(history.get("bank", 0)) / 10
        current_cost = round(sum(pick.player.price for pick in picks), 1)
        manager_name = normalize_display_name(
            f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}"
        )
        return ImportedSquad(
            manager_id=manager_id,
            manager_name=manager_name or "Unknown manager",
            team_name=str(entry.get("name", "Unnamed team")).strip(),
            gameweek=gameweek,
            gameweek_points=_optional_int(history.get("points")),
            gameweek_rank=_optional_int(history.get("rank")),
            bank=round(bank, 1),
            current_squad_cost=current_cost,
            active_chip=payload.get("active_chip"),
            picks=tuple(sorted(picks, key=lambda pick: pick.squad_position)),
        )
    def optimize_wildcard(
        self,
        budget: float,
        horizon: int,
        beam_width: int = 2500,
    ) -> OptimizedSquad:
        """Build a legal 15-player draft with an auditable heuristic optimizer."""
        if budget <= 0:
            raise ValueError("budget must be positive")
        if beam_width <= 0:
            raise ValueError("beam_width must be positive")
        rankings = tuple(
            row
            for row in self.decisions.player_options(horizon)
            if row.status == "a" and row.price > 0
        )
        pools = {
            position: _candidate_pool(
                row for row in rankings if row.position == position
            )
            for position in SQUAD_REQUIREMENTS
        }
        for position, required in SQUAD_REQUIREMENTS.items():
            if len(pools[position]) < required:
                raise ValueError(f"not enough available {position} players to optimize")
        minimum_cost = sum(
            sum(sorted(row.price for row in pools[position])[:required])
            for position, required in SQUAD_REQUIREMENTS.items()
        )
        if minimum_cost > budget:
            raise ValueError(
                f"budget is below the minimum legal squad cost of £{minimum_cost:.1f}m"
            )

        states = (_BeamState((), 0.0, 0.0, ()),)
        selected_counts = {position: 0 for position in SQUAD_REQUIREMENTS}
        minimum_prices = {
            position: sorted(row.price for row in pool)
            for position, pool in pools.items()
        }
        for position, required in SQUAD_REQUIREMENTS.items():
            states = tuple(replace(state, last_index=-1) for state in states)
            for _ in range(required):
                selected_counts[position] += 1
                remaining_minimum = _remaining_minimum_cost(
                    selected_counts, minimum_prices
                )
                expanded = []
                pool = pools[position]
                for state in states:
                    counts = dict(state.team_counts)
                    for index in range(state.last_index + 1, len(pool)):
                        player = pool[index]
                        if counts.get(player.team, 0) >= 3:
                            continue
                        cost = round(state.total_cost + player.price, 1)
                        if cost + remaining_minimum > budget + 1e-9:
                            continue
                        updated_counts = dict(counts)
                        updated_counts[player.team] = updated_counts.get(player.team, 0) + 1
                        expanded.append(
                            _BeamState(
                                players=state.players + (player,),
                                total_cost=cost,
                                total_score=state.total_score + player.final_score,
                                team_counts=tuple(sorted(updated_counts.items())),
                                last_index=index,
                            )
                        )
                if not expanded:
                    raise ValueError("no legal squad satisfies the selected budget")
                states = tuple(
                    sorted(
                        expanded,
                        key=lambda state: (state.total_score, -state.total_cost),
                        reverse=True,
                    )[:beam_width]
                )

        best = max(states, key=lambda state: (state.total_score, -state.total_cost))
        starters, bench = _best_lineup(best.players)
        captain_pool = [player for player in starters if player.position != "GK"] or list(starters)
        captain_order = sorted(
            captain_pool,
            key=lambda player: (
                player.final_score,
                player.expected_score,
                player.minutes_score,
            ),
            reverse=True,
        )
        return OptimizedSquad(
            players=tuple(sorted(best.players, key=_squad_sort_key)),
            starters=starters,
            bench=bench,
            total_cost=best.total_cost,
            remaining_budget=round(budget - best.total_cost, 1),
            total_score=round(best.total_score, 1),
            captain=captain_order[0],
            vice_captain=captain_order[1],
        )

    def suggest_transfers(
        self,
        imported: ImportedSquad,
        horizon: int,
        free_transfers: int = 1,
        team_priority_adjustments: Mapping[str, float] | None = None,
        schedule_adjustment_validated: bool = False,
    ) -> TransferPlan:
        """Recommend legal, no-hit upgrades tailored to an imported squad.

        The selection is deliberately transparent: an incoming player must be
        available, match the outgoing position, fit the current bank, respect
        the three-per-club rule, and improve the recommendation profile.
        """
        if free_transfers <= 0:
            raise ValueError("free_transfers must be positive")
        if team_priority_adjustments and not schedule_adjustment_validated:
            raise ValueError(
                "schedule adjustments require a passed production validation gate"
            )
        schedule_adjustments = (
            dict(team_priority_adjustments or {}) if schedule_adjustment_validated else {}
        )
        rankings = tuple(self.decisions.player_options(horizon))
        squad = [pick.player for pick in imported.picks]
        squad_ids = {player.player_id for player in squad}
        candidates = [
            player
            for player in rankings
            if player.player_id not in squad_ids and player.status == "a" and player.price > 0
        ]
        bank = imported.bank
        team_counts = _team_counts(squad)
        suggestions = []

        for _ in range(free_transfers):
            best: TransferSuggestion | None = None
            for player_out in squad:
                for player_in in candidates:
                    if player_in.position != player_out.position:
                        continue
                    price_delta = round(player_in.price - player_out.price, 1)
                    if price_delta > bank + 1e-9:
                        continue
                    incoming_count = team_counts.get(player_in.team, 0)
                    if player_in.team == player_out.team:
                        incoming_count -= 1
                    if incoming_count >= 3:
                        continue
                    score_delta = round(player_in.final_score - player_out.final_score, 1)
                    fixture_delta = round(player_in.fixture_score - player_out.fixture_score, 1)
                    minutes_delta = round(player_in.minutes_score - player_out.minutes_score, 1)
                    availability_bonus = 8.0 if player_out.status != "a" else 0.0
                    base_priority = round(
                        score_delta + fixture_delta * 0.12 + minutes_delta * 0.08 + availability_bonus,
                        1,
                    )
                    schedule_adjustment = round(
                        schedule_adjustments.get(player_in.team, 0.0)
                        - schedule_adjustments.get(player_out.team, 0.0),
                        1,
                    )
                    priority = round(base_priority + schedule_adjustment, 1)
                    if priority <= 0:
                        continue
                    reason = _transfer_reason(
                        player_out,
                        player_in,
                        score_delta,
                        fixture_delta,
                        minutes_delta,
                    )
                    if schedule_adjustment_validated:
                        reason += f" · validated schedule {schedule_adjustment:+.1f}"
                    suggestion = TransferSuggestion(
                        player_out=player_out,
                        player_in=player_in,
                        price_delta=price_delta,
                        score_delta=score_delta,
                        fixture_delta=fixture_delta,
                        minutes_delta=minutes_delta,
                        priority=priority,
                        reason=reason,
                        base_priority=base_priority,
                        schedule_adjustment=schedule_adjustment,
                    )
                    if best is None or _transfer_sort_key(suggestion) > _transfer_sort_key(best):
                        best = suggestion
            if best is None:
                break
            suggestions.append(best)
            bank = round(bank - best.price_delta, 1)
            squad = [
                best.player_in if player.player_id == best.player_out.player_id else player
                for player in squad
            ]
            squad_ids = {player.player_id for player in squad}
            candidates = [player for player in candidates if player.player_id not in squad_ids]
            team_counts = _team_counts(squad)

        return TransferPlan(
            transfers=tuple(suggestions),
            free_transfers_used=len(suggestions),
            bank_after=bank,
            total_score_gain=round(sum(item.score_delta for item in suggestions), 1),
            schedule_adjustment_active=schedule_adjustment_validated,
        )

    @staticmethod
    def compare_squads(
        imported: ImportedSquad,
        optimized: OptimizedSquad,
    ) -> tuple[SquadChange, ...]:
        current_ids = {pick.player.player_id for pick in imported.picks}
        optimized_ids = {player.player_id for player in optimized.players}
        outgoing = [
            pick.player for pick in imported.picks if pick.player.player_id not in optimized_ids
        ]
        incoming = [
            player for player in optimized.players if player.player_id not in current_ids
        ]
        changes = []
        for position in SQUAD_REQUIREMENTS:
            outs = sorted(
                (player for player in outgoing if player.position == position),
                key=lambda player: player.final_score,
            )
            ins = sorted(
                (player for player in incoming if player.position == position),
                key=lambda player: player.final_score,
                reverse=True,
            )
            for player_out, player_in in zip(outs, ins):
                changes.append(
                    SquadChange(
                        player_out=player_out,
                        player_in=player_in,
                        price_delta=round(player_in.price - player_out.price, 1),
                        score_delta=round(
                            player_in.final_score - player_out.final_score, 1
                        ),
                    )
                )
        return tuple(sorted(changes, key=lambda item: item.score_delta, reverse=True))


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _candidate_pool(rows: Iterable[RecommendationRow]) -> tuple[RecommendationRow, ...]:
    values = tuple(rows)
    top_scores = sorted(
        values,
        key=lambda row: (row.final_score, row.expected_score, row.minutes_score),
        reverse=True,
    )[:45]
    cheapest = sorted(values, key=lambda row: (row.price, -row.final_score))[:10]
    unique = {row.player_id: row for row in (*top_scores, *cheapest)}
    return tuple(sorted(unique.values(), key=lambda row: row.player_id))


def _team_counts(players: Iterable[RecommendationRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        counts[player.team] = counts.get(player.team, 0) + 1
    return counts


def _transfer_sort_key(suggestion: TransferSuggestion) -> tuple[float, float, float]:
    return (suggestion.priority, suggestion.score_delta, -suggestion.price_delta)


def _transfer_reason(
    player_out: RecommendationRow,
    player_in: RecommendationRow,
    score_delta: float,
    fixture_delta: float,
    minutes_delta: float,
) -> str:
    parts = [f"Model +{score_delta:.0f}"]
    if fixture_delta > 0:
        parts.append(f"fixtures +{fixture_delta:.0f}")
    if minutes_delta > 0:
        parts.append(f"minutes +{minutes_delta:.0f}")
    if player_out.status != "a":
        parts.append("replaces unavailable player")
    if player_in.price < player_out.price:
        parts.append(f"frees £{player_out.price - player_in.price:.1f}m")
    return " · ".join(parts)


def _remaining_minimum_cost(
    selected_counts: Mapping[str, int],
    minimum_prices: Mapping[str, Sequence[float]],
) -> float:
    return round(
        sum(
            sum(minimum_prices[position][: SQUAD_REQUIREMENTS[position] - selected_counts[position]])
            for position in SQUAD_REQUIREMENTS
        ),
        1,
    )


def _best_lineup(
    squad: Sequence[RecommendationRow],
) -> tuple[tuple[RecommendationRow, ...], tuple[RecommendationRow, ...]]:
    by_position = {
        position: sorted(
            (player for player in squad if player.position == position),
            key=lambda player: player.final_score,
            reverse=True,
        )
        for position in SQUAD_REQUIREMENTS
    }
    lineups = []
    for formation in VALID_STARTING_FORMATIONS:
        starters = tuple(
            player
            for position in SQUAD_REQUIREMENTS
            for player in by_position[position][: formation[position]]
        )
        lineups.append((sum(player.final_score for player in starters), starters))
    _, best = max(lineups, key=lambda item: item[0])
    starter_ids = {player.player_id for player in best}
    bench = tuple(
        sorted(
            (player for player in squad if player.player_id not in starter_ids),
            key=_squad_sort_key,
        )
    )
    return tuple(sorted(best, key=_squad_sort_key)), bench


def _squad_sort_key(player: RecommendationRow) -> tuple[int, float]:
    return (tuple(SQUAD_REQUIREMENTS).index(player.position), -player.final_score)


def get_advanced_planner_service(
    database_path: str = str(DATABASE_PATH),
) -> AdvancedPlannerService:
    return _get_cached_advanced_planner_service(
        database_path,
        SCORING_CONFIG_PATH.stat().st_mtime_ns,
        EXTERNAL_PROVIDERS_CONFIG_PATH.stat().st_mtime_ns,
    )


@lru_cache(maxsize=4)
def _get_cached_advanced_planner_service(
    database_path: str,
    scoring_config_mtime: int,
    provider_config_mtime: int,
) -> AdvancedPlannerService:
    del scoring_config_mtime, provider_config_mtime
    return AdvancedPlannerService(
        ingestion=get_fpl_ingestion_service(database_path),
        decisions=get_decision_tools_service(database_path),
        fixture_analytics=get_fixture_analytics_service(database_path),
    )
