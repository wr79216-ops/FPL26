"""Deterministic fictional data for validating the Phase 1 experience."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Tuple

import pandas as pd


PLAYER_COLUMNS = [
    "player_id",
    "name",
    "team",
    "position",
    "price",
    "ownership",
    "minutes",
    "form",
    "total_points",
    "ppm",
    "xg",
    "xa",
    "xgi",
    "fixture_score",
    "minutes_score",
    "value_score",
    "history_score",
    "recommendation",
    "captain_score",
    "category",
    "next_fixture",
    "status",
]

# Every profile and metric below is fictional. Familiar club names only help
# validate the product experience; the rows are never presented as live data.
PLAYER_ROWS: List[Tuple[object, ...]] = [
    (1, "Elliot Ward", "Arsenal", "GK", 5.5, 18.4, 720, 6.1, 54, 6.0, 0.0, 0.1, 0.1, 87, 98, 79, 84, 86, 54, "Strong Buy", "BOU (H)", "Available"),
    (2, "Noah Bennett", "Brighton", "GK", 4.6, 6.2, 720, 5.2, 46, 5.1, 0.0, 0.0, 0.0, 82, 96, 92, 71, 82, 48, "Strong Buy", "FUL (H)", "Available"),
    (3, "Hugo Silva", "Chelsea", "GK", 5.0, 9.7, 630, 4.8, 39, 4.3, 0.0, 0.0, 0.0, 73, 84, 76, 68, 74, 42, "Good Option", "EVE (A)", "Available"),
    (4, "Marcus Reed", "Arsenal", "DEF", 6.1, 24.8, 705, 7.0, 62, 6.9, 1.8, 1.2, 3.0, 87, 96, 81, 86, 89, 69, "Strong Buy", "BOU (H)", "Available"),
    (5, "Theo Grant", "Liverpool", "DEF", 5.4, 13.6, 672, 6.4, 57, 6.3, 0.9, 2.4, 3.3, 81, 91, 88, 78, 86, 67, "Strong Buy", "WHU (A)", "Available"),
    (6, "Samir Okafor", "Crystal Palace", "DEF", 4.8, 4.1, 698, 5.9, 51, 5.7, 1.4, 1.0, 2.4, 84, 94, 94, 70, 84, 61, "Strong Buy", "LEE (H)", "Available"),
    (7, "Ben Cole", "Aston Villa", "DEF", 4.5, 3.5, 540, 4.3, 38, 4.2, 0.5, 0.8, 1.3, 76, 77, 86, 62, 72, 44, "Good Option", "BRE (H)", "Doubtful"),
    (8, "Adrian Vale", "Chelsea", "MID", 7.0, 8.6, 686, 8.2, 71, 7.9, 4.8, 4.1, 8.9, 83, 93, 91, 74, 91, 88, "Elite Target", "EVE (A)", "Available"),
    (9, "Liam Mercer", "Arsenal", "MID", 9.8, 31.2, 714, 8.0, 76, 8.4, 5.5, 3.7, 9.2, 87, 97, 73, 92, 90, 92, "Elite Target", "BOU (H)", "Available"),
    (10, "Kenji Mori", "Brighton", "MID", 6.2, 5.4, 648, 6.9, 58, 6.4, 3.9, 3.0, 6.9, 82, 88, 93, 69, 85, 76, "Strong Buy", "FUL (H)", "Available"),
    (11, "Owen Price", "Newcastle", "MID", 5.8, 2.9, 508, 5.6, 44, 4.9, 3.1, 2.2, 5.3, 79, 76, 89, 58, 76, 63, "Good Option", "SUN (A)", "Available"),
    (12, "Rafael Costa", "Man City", "MID", 8.3, 19.5, 512, 6.2, 55, 6.1, 3.8, 4.6, 8.4, 78, 69, 77, 83, 78, 75, "Good Option", "TOT (H)", "Doubtful"),
    (13, "Mateo Cruz", "Liverpool", "FWD", 8.7, 17.9, 691, 8.4, 74, 8.2, 7.7, 1.9, 9.6, 81, 94, 84, 82, 92, 91, "Elite Target", "WHU (A)", "Available"),
    (14, "Isaac Stone", "Newcastle", "FWD", 7.4, 9.2, 665, 7.1, 63, 7.0, 6.1, 1.3, 7.4, 79, 91, 90, 75, 86, 82, "Strong Buy", "SUN (A)", "Available"),
    (15, "Dylan Fox", "Aston Villa", "FWD", 6.5, 4.7, 612, 6.5, 54, 6.0, 5.0, 1.6, 6.6, 76, 86, 92, 67, 82, 74, "Strong Buy", "BRE (H)", "Available"),
    (16, "Jonas Berg", "Crystal Palace", "FWD", 5.9, 1.8, 371, 5.1, 33, 4.7, 3.8, 0.9, 4.7, 84, 58, 85, 50, 67, 57, "Watchlist", "LEE (H)", "Available"),
]


FIXTURE_SETS: Dict[str, List[Tuple[str, str, int]]] = {
    "Arsenal": [("BOU", "H", 2), ("FUL", "A", 2), ("LIV", "H", 4), ("EVE", "A", 2), ("WHU", "H", 2)],
    "Liverpool": [("WHU", "A", 2), ("BRE", "H", 2), ("ARS", "A", 4), ("LEE", "H", 2), ("CHE", "A", 3)],
    "Chelsea": [("EVE", "A", 2), ("WOL", "H", 2), ("MCI", "A", 5), ("SUN", "H", 2), ("LIV", "H", 4)],
    "Man City": [("TOT", "H", 3), ("NEW", "A", 3), ("CHE", "H", 2), ("AVL", "A", 3), ("BOU", "H", 2)],
    "Newcastle": [("SUN", "A", 2), ("MCI", "H", 4), ("FUL", "A", 3), ("WOL", "H", 2), ("EVE", "A", 2)],
    "Brighton": [("FUL", "H", 2), ("BOU", "A", 3), ("LEE", "H", 2), ("WHU", "A", 3), ("WOL", "H", 2)],
    "Crystal Palace": [("LEE", "H", 2), ("EVE", "A", 3), ("SUN", "H", 2), ("BRE", "A", 3), ("FUL", "H", 2)],
    "Aston Villa": [("BRE", "H", 2), ("WOL", "A", 2), ("TOT", "H", 3), ("MCI", "H", 4), ("SUN", "A", 2)],
}


POINT_PATTERNS = [
    [3, 8, 6, 2, 10, 7, 5, 9],
    [6, 2, 9, 5, 4, 8, 6, 7],
    [2, 5, 3, 11, 6, 4, 8, 6],
    [7, 6, 2, 9, 8, 5, 10, 7],
]


@lru_cache(maxsize=1)
def _players_frame() -> pd.DataFrame:
    frame = pd.DataFrame(PLAYER_ROWS, columns=PLAYER_COLUMNS)
    frame["differential"] = (
        (frame["ownership"] < 10)
        & (frame["recommendation"] >= 75)
        & (frame["minutes_score"] >= 75)
    )
    return frame


def get_sample_players() -> pd.DataFrame:
    """Return a copy so page-level filtering cannot mutate cached sample data."""
    return _players_frame().copy(deep=True)


@lru_cache(maxsize=1)
def _fixtures_frame() -> pd.DataFrame:
    rows = []
    for team, team_fixtures in FIXTURE_SETS.items():
        for offset, (opponent, venue, fdr) in enumerate(team_fixtures, start=1):
            rows.append(
                {
                    "team": team,
                    "gameweek": f"GW+{offset}",
                    "gameweek_offset": offset,
                    "opponent": opponent,
                    "venue": venue,
                    "fdr": fdr,
                    "fixture": f"{opponent} ({venue})",
                }
            )
    return pd.DataFrame(rows)


def get_sample_fixtures() -> pd.DataFrame:
    return _fixtures_frame().copy(deep=True)


def get_sample_points_history(player_id: int) -> pd.DataFrame:
    """Return eight deterministic sample gameweeks for a player."""
    pattern = POINT_PATTERNS[(player_id - 1) % len(POINT_PATTERNS)]
    modifier = ((player_id - 1) % 3) - 1
    points = [max(0, value + modifier) for value in pattern]
    return pd.DataFrame(
        {"Gameweek": [f"GW{gameweek}" for gameweek in range(1, 9)], "Points": points}
    )
