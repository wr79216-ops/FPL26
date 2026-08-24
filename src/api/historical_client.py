"""HTTP gateway for validated, season-level historical FPL CSV files."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import requests

from src.api.fpl_client import FPLClient


SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")
REQUIRED_COLUMNS = {
    "first_name",
    "second_name",
    "total_points",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "bonus",
    "now_cost",
    "element_type",
}
GAMEWEEK_REQUIRED_COLUMNS = {
    "name",
    "position",
    "team",
    "element",
    "fixture",
    "round",
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "bonus",
    "saves",
    "ict_index",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "selected",
    "value",
    "kickoff_time",
}
FIXTURE_REQUIRED_COLUMNS = {
    "event",
    "id",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "team_h_score",
    "team_a_score",
    "kickoff_time",
}
TEAM_REQUIRED_COLUMNS = {"id", "name"}


class HistoricalDataClientError(RuntimeError):
    """Raised when a historical season cannot be downloaded or validated."""


class HistoricalDataClient:
    """Fetch historical aggregate CSVs through one retrying gateway."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        retries: int = 3,
        session: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.session = session or FPLClient._build_session(retries, 0.5)
        self._owns_session = session is None
        self.logger = logger or logging.getLogger(__name__)

    def get_cleaned_players(self, season: str) -> str:
        return self._get_csv(season, "cleaned_players.csv", REQUIRED_COLUMNS)

    def get_merged_gameweeks(self, season: str) -> str:
        return self._get_csv(season, "gws/merged_gw.csv", GAMEWEEK_REQUIRED_COLUMNS)

    def get_fixtures(self, season: str) -> str:
        return self._get_csv(season, "fixtures.csv", FIXTURE_REQUIRED_COLUMNS)

    def get_teams(self, season: str) -> str:
        return self._get_csv(season, "teams.csv", TEAM_REQUIRED_COLUMNS)

    def _get_csv(
        self, season: str, path: str, required_columns: set[str]
    ) -> str:
        if not SEASON_PATTERN.fullmatch(season):
            raise ValueError("season must use YYYY-YY format")
        url = f"{self.base_url}{season}/{path}"
        self.logger.info("HISTORICAL_REQUEST season=%s path=%s", season, path)
        try:
            response = self.session.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HistoricalDataClientError(
                f"Historical dataset request failed for {season}"
            ) from exc
        text = response.text
        header = set(text.splitlines()[0].split(",")) if text.strip() else set()
        missing = required_columns - header
        if missing:
            raise HistoricalDataClientError(
                f"Historical dataset {season} is missing columns: {', '.join(sorted(missing))}"
            )
        return text

    def close(self) -> None:
        if self._owns_session:
            self.session.close()
