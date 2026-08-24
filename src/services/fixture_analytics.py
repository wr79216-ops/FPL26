"""Read-only fixture matrix derived from persisted official FPL data."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import DATABASE_PATH
from src.data.refresh_status import RefreshStatusStore
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.features.fixture import custom_fixture_score, fixture_score
from src.services.application import get_database


@dataclass(frozen=True)
class FixtureCell:
    gameweek: Optional[int]
    fixture: str
    opponent: str
    venue: str
    fdr: int
    custom_fdr: float | None = None


@dataclass(frozen=True)
class TeamFixtureSummary:
    team_id: int
    team_name: str
    players_tracked: int
    fixture_score: float | None
    fixtures: tuple[FixtureCell, ...]
    custom_fixture_score: float | None = None


@dataclass(frozen=True)
class FixtureMatrix:
    gameweek: Optional[int]
    horizon: int
    teams: tuple[TeamFixtureSummary, ...]

    def team(self, team_name: str) -> TeamFixtureSummary | None:
        return next((item for item in self.teams if item.team_name == team_name), None)

    def to_dataframe(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for team in self.teams:
            row: dict[str, object] = {
                "team": team.team_name,
                "fixture_score": team.fixture_score,
                "custom_fixture_score": team.custom_fixture_score,
                "players_tracked": team.players_tracked,
            }
            for index, fixture in enumerate(team.fixtures, start=1):
                row[f"GW+{index}"] = f"{fixture.fixture} · FDR {fixture.fdr}"
                row[f"GW+{index} custom"] = fixture.custom_fdr
            rows.append(row)
        return pd.DataFrame(rows)


class FixtureAnalyticsService:
    """Build a team-centric matrix from the SQLite official data cache."""

    def __init__(self, database: Database, status_store: RefreshStatusStore) -> None:
        self.database = database
        self.status_store = status_store

    def get_matrix(self, horizon: int) -> FixtureMatrix:
        with self.database.session() as session:
            repository = FPLRepository(session)
            current_gameweek = self.status_store.load().current_gameweek
            teams = repository.list_teams()
            players = repository.list_players()
            team_names = {team.team_id: team.name for team in teams}
            player_counts = {
                team_id: sum(player.team_id == team_id for player in players)
                for team_id in team_names
            }
            upcoming = repository.list_upcoming_fixtures(current_gameweek)

        overall_strengths = [
            value
            for team in teams
            for value in (team.strength_overall_home, team.strength_overall_away)
        ]
        minimum_strength = min(overall_strengths, default=0)
        maximum_strength = max(overall_strengths, default=0)
        teams_by_id = {team.team_id: team for team in teams}

        by_team: dict[int, list[FixtureCell]] = {team_id: [] for team_id in team_names}
        for fixture in upcoming:
            home_name = team_names.get(fixture.home_team_id)
            away_name = team_names.get(fixture.away_team_id)
            if home_name is None or away_name is None:
                continue
            home_opponent = teams_by_id[fixture.away_team_id]
            away_opponent = teams_by_id[fixture.home_team_id]
            by_team[fixture.home_team_id].append(
                FixtureCell(
                    fixture.gameweek,
                    f"{away_name} (H)",
                    away_name,
                    "Home",
                    fixture.home_difficulty,
                    _custom_fdr(
                        fixture.home_difficulty,
                        home_opponent.strength_overall_away,
                        minimum_strength,
                        maximum_strength,
                        "Home",
                    ),
                )
            )
            by_team[fixture.away_team_id].append(
                FixtureCell(
                    fixture.gameweek,
                    f"{home_name} (A)",
                    home_name,
                    "Away",
                    fixture.away_difficulty,
                    _custom_fdr(
                        fixture.away_difficulty,
                        away_opponent.strength_overall_home,
                        minimum_strength,
                        maximum_strength,
                        "Away",
                    ),
                )
            )

        summaries = tuple(
            TeamFixtureSummary(
                team_id=team.team_id,
                team_name=team.name,
                players_tracked=player_counts[team.team_id],
                fixture_score=fixture_score([cell.fdr for cell in by_team[team.team_id]], horizon),
                fixtures=tuple(by_team[team.team_id][:horizon]),
                custom_fixture_score=custom_fixture_score(
                    [
                        cell.custom_fdr
                        for cell in by_team[team.team_id]
                        if cell.custom_fdr is not None
                    ],
                    horizon,
                ),
            )
            for team in teams
        )
        return FixtureMatrix(current_gameweek, horizon, summaries)


def _custom_fdr(
    official_fdr: int,
    opponent_strength: int,
    minimum_strength: int,
    maximum_strength: int,
    venue: str,
) -> float:
    """Blend official FDR with relative opponent strength and a venue adjustment."""
    if maximum_strength == minimum_strength:
        strength_difficulty = 3.0
    else:
        strength_difficulty = 1 + 4 * (
            (opponent_strength - minimum_strength)
            / (maximum_strength - minimum_strength)
        )
    venue_adjustment = -0.25 if venue == "Home" else 0.25
    return round(
        min(5.0, max(1.0, 0.60 * official_fdr + 0.40 * strength_difficulty + venue_adjustment)),
        2,
    )


@lru_cache(maxsize=4)
def get_fixture_analytics_service(
    database_path: str = str(DATABASE_PATH),
) -> FixtureAnalyticsService:
    return FixtureAnalyticsService(
        get_database(database_path),
        RefreshStatusStore(Path(database_path).parent / "fpl_refresh_status.json"),
    )
