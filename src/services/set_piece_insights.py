"""Auditable set-piece role snapshots for FPL decision support.

The public FPL feed does not expose a per-player set-piece duty field. This
module therefore keeps an explicit, dated snapshot with a source URL and never
pretends that a listed player is guaranteed to take the next kick.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable, Mapping

import yaml

from config.settings import SET_PIECE_CONFIG_PATH
from src.services.recommendation_engine import RecommendationRow
from src.utils.text import normalize_display_name


ROLE_LABELS = {
    "penalties": "penalties",
    "direct_free_kicks": "direct free-kicks",
    "corners_indirect_free_kicks": "corners / indirect free-kicks",
}
ROLE_WEIGHTS = {
    "penalties": (3.0, 1.5, 0.8),
    "direct_free_kicks": (1.1, 0.6, 0.3),
    "corners_indirect_free_kicks": (0.9, 0.5, 0.3),
}


class SetPieceConfigError(ValueError):
    """Raised when the controlled set-piece role snapshot is invalid."""


@dataclass(frozen=True)
class SetPieceRole:
    player_name: str
    role_type: str
    priority: int
    conditional: bool

    @property
    def label(self) -> str:
        suffix = " (conditional)" if self.conditional else ""
        return f"{ROLE_LABELS[self.role_type]} #{self.priority}{suffix}"


@dataclass(frozen=True)
class TeamSetPieceProfile:
    team_name: str
    aliases: tuple[str, ...]
    roles: tuple[SetPieceRole, ...]


@dataclass(frozen=True)
class SetPieceCatalog:
    season: str
    as_of: str
    source_label: str
    source_url: str
    cross_check_url: str
    limitations: str
    historical_season: str
    historical_source_url: str
    historical_metric_label: str
    historical_definition: str
    historical_goals: Mapping[str, int | None]
    teams: tuple[TeamSetPieceProfile, ...]


@dataclass(frozen=True)
class SetPiecePlayerInsight:
    player_id: int
    player_name: str
    team_name: str
    roles: tuple[SetPieceRole, ...]
    role_signal: float
    historical_set_piece_goals: int | None
    historical_season: str

    @property
    def role_summary(self) -> str:
        return " · ".join(role.label for role in self.roles) or "No listed role"


def _identity_key(value: str) -> str:
    normalized = normalize_display_name(str(value)).casefold()
    return re.sub(r"[^a-z0-9]", "", normalized)


def _role_from_value(role_type: str, raw_name: object, priority: int) -> SetPieceRole:
    name = str(raw_name).strip()
    conditional = name.endswith("*")
    name = name.rstrip("*").strip()
    if not name:
        raise SetPieceConfigError(f"{role_type} has an empty player name")
    return SetPieceRole(
        player_name=name,
        role_type=role_type,
        priority=priority,
        conditional=conditional,
    )


def load_set_piece_catalog(path: Path = SET_PIECE_CONFIG_PATH) -> SetPieceCatalog:
    """Load the dated role snapshot and its historical team context."""
    try:
        with path.open("r", encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file) or {}
    except OSError as exc:
        raise SetPieceConfigError(f"could not read {path.name}") from exc
    if not isinstance(payload, Mapping):
        raise SetPieceConfigError("set-piece config must contain a mapping")

    source = payload.get("source")
    historical = payload.get("historical_context")
    teams = payload.get("teams")
    if not isinstance(source, Mapping) or not isinstance(historical, Mapping) or not isinstance(teams, Mapping):
        raise SetPieceConfigError("set-piece config requires source, historical_context, and teams mappings")

    season = str(payload.get("season", "")).strip()
    as_of = str(payload.get("as_of", "")).strip()
    if not season or not as_of:
        raise SetPieceConfigError("set-piece config requires season and as_of")
    source_url = str(source.get("source_url", "")).strip()
    if not source_url.startswith(("https://", "http://")):
        raise SetPieceConfigError("set-piece source_url must be an absolute HTTP(S) URL")
    historical_goals = historical.get("goals")
    if not isinstance(historical_goals, Mapping):
        raise SetPieceConfigError("historical_context.goals must be a mapping")

    profiles: list[TeamSetPieceProfile] = []
    for team_name, raw_profile in teams.items():
        if not isinstance(raw_profile, Mapping):
            raise SetPieceConfigError(f"team {team_name} must be a mapping")
        aliases = raw_profile.get("aliases", [])
        if not isinstance(aliases, list) or not all(str(alias).strip() for alias in aliases):
            raise SetPieceConfigError(f"team {team_name} aliases must be a non-empty list")
        roles: list[SetPieceRole] = []
        for role_type in ROLE_LABELS:
            raw_players = raw_profile.get(role_type, [])
            if not isinstance(raw_players, list):
                raise SetPieceConfigError(f"team {team_name} {role_type} must be a list")
            roles.extend(
                _role_from_value(role_type, player_name, priority)
                for priority, player_name in enumerate(raw_players, start=1)
            )
        profiles.append(
            TeamSetPieceProfile(
                team_name=str(team_name).strip(),
                aliases=tuple(str(alias).strip() for alias in aliases),
                roles=tuple(roles),
            )
        )

    parsed_historical_goals: dict[str, int | None] = {}
    for team_name, value in historical_goals.items():
        if value is not None and (not isinstance(value, int) or value < 0):
            raise SetPieceConfigError("historical set-piece goals must be non-negative integers or null")
        parsed_historical_goals[str(team_name)] = value
    return SetPieceCatalog(
        season=season,
        as_of=as_of,
        source_label=str(source.get("label", "Set-piece role snapshot")).strip(),
        source_url=source_url,
        cross_check_url=str(source.get("cross_check_url", "")).strip(),
        limitations=str(source.get("limitations", "")).strip(),
        historical_season=str(historical.get("season", "")).strip(),
        historical_source_url=str(historical.get("source_url", "")).strip(),
        historical_metric_label=str(historical.get("metric_label", "Set-piece goals")).strip(),
        historical_definition=str(historical.get("definition", "")).strip(),
        historical_goals=parsed_historical_goals,
        teams=tuple(profiles),
    )


def _role_weight(role: SetPieceRole) -> float:
    weights = ROLE_WEIGHTS[role.role_type]
    base = weights[min(role.priority - 1, len(weights) - 1)]
    return base * (0.60 if role.conditional else 1.0)


def _same_player(snapshot_name: str, official_name: str) -> bool:
    """Match a role snapshot name to FPL's compact web name within one club."""
    left = _identity_key(snapshot_name)
    right = _identity_key(official_name)
    if left == right:
        return True
    # FPL may abbreviate first names (B.Fernandes, E.Le Fee), while supplied
    # snapshots often use the surname. Team matching happens before this check.
    return len(left) >= 5 and len(right) >= 5 and (
        left.endswith(right)
        or right.endswith(left)
        or (len(left) >= 6 and right.startswith(left))
    )


class SetPieceInsightsService:
    """Resolve expected dead-ball roles against the current FPL player cache."""

    def __init__(self, catalog: SetPieceCatalog) -> None:
        self.catalog = catalog
        self._profiles_by_alias = {
            _identity_key(alias): profile
            for profile in catalog.teams
            for alias in (profile.team_name, *profile.aliases)
        }
        self._historical_goals_by_team = {
            _identity_key(team): goals
            for team, goals in catalog.historical_goals.items()
        }

    def profile_for_team(self, team_name: str) -> TeamSetPieceProfile | None:
        return self._profiles_by_alias.get(_identity_key(team_name))

    def player_insight(self, player: RecommendationRow) -> SetPiecePlayerInsight:
        profile = self.profile_for_team(player.team)
        roles = tuple(
            role for role in (profile.roles if profile is not None else ())
            if _same_player(role.player_name, player.name)
        )
        role_signal = round(min(4.0, sum(_role_weight(role) for role in roles)), 1)
        historical_goals = self._historical_goals_by_team.get(_identity_key(player.team))
        return SetPiecePlayerInsight(
            player_id=player.player_id,
            player_name=player.name,
            team_name=player.team,
            roles=roles,
            role_signal=role_signal,
            historical_set_piece_goals=historical_goals,
            historical_season=self.catalog.historical_season,
        )

    def player_insights(
        self, players: Iterable[RecommendationRow], known_only: bool = True
    ) -> tuple[SetPiecePlayerInsight, ...]:
        insights = tuple(self.player_insight(player) for player in players)
        if known_only:
            insights = tuple(insight for insight in insights if insight.roles)
        return tuple(
            sorted(
                insights,
                key=lambda insight: (-insight.role_signal, insight.team_name, insight.player_name),
            )
        )

    def priority_adjustments(
        self, players: Iterable[RecommendationRow]
    ) -> dict[int, float]:
        """Return modest, explainable priority adjustments keyed by official FPL ID."""
        return {
            insight.player_id: insight.role_signal
            for insight in self.player_insights(players)
            if insight.role_signal > 0
        }


def get_set_piece_insights_service() -> SetPieceInsightsService:
    return _get_cached_set_piece_insights_service(
        str(SET_PIECE_CONFIG_PATH), SET_PIECE_CONFIG_PATH.stat().st_mtime_ns
    )


@lru_cache(maxsize=4)
def _get_cached_set_piece_insights_service(
    config_path: str, config_mtime: int
) -> SetPieceInsightsService:
    del config_mtime
    return SetPieceInsightsService(load_set_piece_catalog(Path(config_path)))
