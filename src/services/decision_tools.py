"""Transparent Phase 10 transfer and captain decision support."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from statistics import mean
from typing import Callable, Iterable, Sequence

from config.settings import DATABASE_PATH, SCORING_CONFIG_PATH
from src.services.fixture_analytics import FixtureAnalyticsService, get_fixture_analytics_service
from src.services.recommendation_engine import (
    RecommendationEngineService,
    RecommendationRow,
    get_recommendation_engine_service,
)


@dataclass(frozen=True)
class TransferRecommendation:
    """One same-position replacement, including a transparent points proxy."""

    player_out: RecommendationRow
    replacement: RecommendationRow
    price_cap: float
    projected_points_out: float
    projected_points_in: float
    projected_gain: float
    confidence: float
    trade_off: str


@dataclass(frozen=True)
class CaptainRecommendation:
    """One role-based captain shortlist option."""

    role: str
    player: RecommendationRow
    projected_points: float
    confidence: float
    rationale: str
    trade_off: str


class DecisionToolsService:
    """Derive practical, non-binding decisions from official persisted rankings."""

    def __init__(
        self,
        recommendation_engine: RecommendationEngineService,
        fixture_analytics: FixtureAnalyticsService,
    ) -> None:
        self.recommendation_engine = recommendation_engine
        self.fixture_analytics = fixture_analytics

    def player_options(self, horizon: int) -> tuple[RecommendationRow, ...]:
        return self.recommendation_engine.get_rankings(horizon=horizon)

    def transfer_recommendations(
        self,
        player_out_id: int,
        extra_budget: float,
        horizon: int,
        limit: int = 5,
    ) -> tuple[TransferRecommendation, ...]:
        """Return affordable, same-position upgrades only.

        The method deliberately does not attempt squad, free-transfer, or chip
        validation because the application does not yet import a user's FPL team.
        """
        if extra_budget < 0:
            raise ValueError("extra_budget cannot be negative")
        rankings = self.player_options(horizon)
        player_out = next((row for row in rankings if row.player_id == player_out_id), None)
        if player_out is None:
            raise ValueError("player_out_id is not in the official ranking cache")

        price_cap = round(player_out.price + extra_budget, 1)
        position_average_ppm = self._position_average_ppm(rankings, player_out.position)
        projected_out = self._projected_points(
            player_out, horizon, rankings, position_average_ppm
        )
        candidates = [
            row
            for row in rankings
            if row.player_id != player_out.player_id
            and row.position == player_out.position
            and row.price <= price_cap
            and row.status == "a"
            and row.final_score > player_out.final_score
        ]
        options = []
        for replacement in candidates:
            projected_in = self._projected_points(
                replacement,
                horizon,
                rankings,
                position_average_ppm,
            )
            confidence = self._decision_confidence(replacement)
            options.append(
                TransferRecommendation(
                    player_out=player_out,
                    replacement=replacement,
                    price_cap=price_cap,
                    projected_points_out=projected_out,
                    projected_points_in=projected_in,
                    projected_gain=round(projected_in - projected_out, 2),
                    confidence=confidence,
                    trade_off=self._trade_off(replacement),
                )
            )
        return tuple(
            sorted(
                options,
                key=lambda option: (
                    option.projected_gain,
                    option.replacement.final_score,
                    option.replacement.expected_score,
                ),
                reverse=True,
            )[:limit]
        )

    def captain_shortlist(self, horizon: int) -> tuple[CaptainRecommendation, ...]:
        """Return distinct safe, balanced, and differential captain profiles."""
        rankings = self.player_options(horizon)
        available = [
            row for row in rankings if row.status == "a" and row.position != "GK"
        ]
        # Goalkeepers remain valid FPL captain choices, but the standard shortlist
        # prioritises outfield upside. Fall back only when no outfield option exists.
        if not available:
            available = [row for row in rankings if row.status == "a"]
        if not available:
            return ()

        selected: set[int] = set()
        safe = self._pick_distinct(
            available,
            selected,
            lambda row: 0.40 * row.final_score + 0.40 * row.minutes_score + 0.20 * row.fixture_score,
        )
        balanced = self._pick_distinct(
            available,
            selected,
            lambda row: 0.50 * row.final_score + 0.30 * row.expected_score + 0.20 * row.fixture_score,
        )
        differential_pool = [row for row in available if row.ownership < 10]
        differential = self._pick_distinct(
            differential_pool or available,
            selected,
            lambda row: 0.45 * row.final_score
            + 0.35 * row.expected_score
            + 0.20 * row.fixture_score,
        )

        role_definitions = (
            (
                "Safe",
                safe,
                "Prioritises minutes security, final recommendation score, and fixture ease.",
            ),
            (
                "Balanced",
                balanced,
                "Balances overall recommendation strength with expected output and fixtures.",
            ),
            (
                "Differential",
                differential,
                "Prioritises expected output and fixtures among low-owned players when available.",
            ),
        )
        shortlist = []
        for role, player, rationale in role_definitions:
            if player is None:
                continue
            baseline = self._position_average_ppm(rankings, player.position)
            shortlist.append(
                CaptainRecommendation(
                    role=role,
                    player=player,
                    projected_points=self._projected_points(player, horizon, rankings, baseline),
                    confidence=self._decision_confidence(player),
                    rationale=rationale,
                    trade_off=self._trade_off(player),
                )
            )
        return tuple(shortlist)

    def _projected_points(
        self,
        player: RecommendationRow,
        horizon: int,
        rankings: Sequence[RecommendationRow],
        position_average_ppm: float,
    ) -> float:
        """Use confidence-shrunk PPM and official fixture availability as a proxy.

        This is intentionally a simple decision-support estimate, not a claim of
        a calibrated FPL-points forecast. Empty fixture lists correctly project
        zero rather than silently assuming one fixture per gameweek.
        """
        matrix = self.fixture_analytics.get_matrix(horizon)
        team = matrix.team(player.team)
        fixture_count = len(team.fixtures) if team is not None else 0
        adjusted_ppm = position_average_ppm + player.confidence * (
            player.points_per_game - position_average_ppm
        )
        fixture_multiplier = 0.60 + player.fixture_score / 125
        return round(max(0.0, adjusted_ppm) * fixture_count * fixture_multiplier, 2)

    @staticmethod
    def _position_average_ppm(
        rankings: Iterable[RecommendationRow], position: str
    ) -> float:
        values = [row.points_per_game for row in rankings if row.position == position]
        return mean(values) if values else 0.0

    @staticmethod
    def _decision_confidence(player: RecommendationRow) -> float:
        availability = 100.0 if player.status == "a" else 0.0
        return round(
            0.45 * player.final_score
            + 0.30 * player.minutes_score
            + 0.15 * player.fixture_score
            + 0.10 * availability,
            1,
        )

    @staticmethod
    def _pick_distinct(
        candidates: Sequence[RecommendationRow],
        selected: set[int],
        key: Callable[[RecommendationRow], float],
    ) -> RecommendationRow | None:
        ordered = sorted(candidates, key=key, reverse=True)
        player = next((row for row in ordered if row.player_id not in selected), None)
        player = player or (ordered[0] if ordered else None)
        if player is not None:
            selected.add(player.player_id)
        return player

    @staticmethod
    def _trade_off(player: RecommendationRow) -> str:
        return (
            f"{player.next_fixture} · Fixture {player.fixture_score:.0f}/100 · "
            f"xGI/90 {player.xgi_per_90:.2f} · Minutes {player.minutes_score:.0f}/100 · "
            f"£{player.price:.1f}m · Owned {player.ownership:.1f}%"
        )


def get_decision_tools_service(
    database_path: str = str(DATABASE_PATH),
) -> DecisionToolsService:
    """Reload the decision service when scoring configuration changes."""
    return _get_cached_decision_tools_service(
        database_path, SCORING_CONFIG_PATH.stat().st_mtime_ns
    )


@lru_cache(maxsize=4)
def _get_cached_decision_tools_service(
    database_path: str, scoring_config_mtime: int
) -> DecisionToolsService:
    del scoring_config_mtime
    return DecisionToolsService(
        get_recommendation_engine_service(database_path),
        get_fixture_analytics_service(database_path),
    )
