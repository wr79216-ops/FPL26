"""Tests for FPL Mini-League and Rival Chip Analytics."""

from typing import Any, Dict
import pytest

from src.api.fpl_client import FPLClient
from src.services.league_analytics import (
    LeagueAnalyticsService,
    ManagerLeague,
    RivalChipStatus,
)


class MockSession:
    def __init__(self, responses: Dict[str, Any]):
        self.responses = responses
        self.calls = []

    def get(self, url: str, timeout: float):
        self.calls.append((url, timeout))

        class Response:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        for key in sorted(self.responses.keys(), key=len, reverse=True):
            if key in url:
                return Response(self.responses[key])
        return Response({})


def _mock_element(element_id: int, web_name: str, cost: int = 100) -> Dict[str, Any]:
    el = {f: 0 for f in FPLClient.BOOTSTRAP_PLAYER_REQUIRED_FIELDS}
    el.update({
        "id": element_id,
        "first_name": "Test",
        "second_name": web_name,
        "web_name": web_name,
        "team": 1,
        "element_type": 3,
        "now_cost": cost,
        "status": "a",
        "selected_by_percent": "10.0",
        "minutes": 90,
    })
    return el


def test_get_manager_leagues_parses_and_sorts_private_first() -> None:
    payload = {
        "id": 1158066,
        "player_first_name": "Imam",
        "player_last_name": "Purwanto",
        "name": "WB united",
        "leagues": {
            "classic": [
                {
                    "id": 101,
                    "name": "Indonesia Broad League",
                    "league_type": "s",
                    "entry_rank": 500,
                },
                {
                    "id": 202,
                    "name": "Private Office Mini-League",
                    "league_type": "x",
                    "entry_rank": 3,
                },
            ],
            "h2h": [
                {
                    "id": 303,
                    "name": "Friends H2H League",
                    "league_type": "x",
                    "entry_rank": 1,
                }
            ],
        },
    }
    client = FPLClient(session=MockSession({"entry/1158066/": payload}))
    service = LeagueAnalyticsService(client)

    leagues = service.get_manager_leagues(1158066)

    assert len(leagues) == 3
    # Private leagues must come first
    assert leagues[0].name == "Friends H2H League"
    assert leagues[0].is_private is True
    assert leagues[0].scoring == "h2h"
    assert leagues[1].name == "Private Office Mini-League"
    assert leagues[1].is_private is True
    assert leagues[2].name == "Indonesia Broad League"
    assert leagues[2].is_private is False


def test_parse_entry_chips_distinguishes_wc1_and_wc2() -> None:
    history_payload = {
        "current": [],
        "past": [],
        "chips": [
            {"name": "wildcard", "time": "2024-09-01T10:00:00Z", "event": 4},
            {"name": "wildcard", "time": "2025-02-01T10:00:00Z", "event": 24},
            {"name": "3xc", "time": "2024-10-01T10:00:00Z", "event": 7},
            {"name": "bboost", "time": "2025-04-01T10:00:00Z", "event": 32},
        ],
    }
    client = FPLClient(session=MockSession({"entry/1158066/history/": history_payload}))
    service = LeagueAnalyticsService(client)

    status = service.parse_entry_chips(1158066, active_chip=None)

    assert status.wc1 == 4  # GW <= 19 is WC1
    assert status.wc2 == 24  # GW >= 20 is WC2
    assert status.triple_captain == 7
    assert status.bench_boost == 32
    assert status.freehit is None
    assert status.total_used == 4
    assert status.total_remaining == 1


def test_analyze_classic_league_calculates_metrics_and_standings() -> None:
    standings_payload = {
        "league": {"id": 555, "name": "Work League", "league_type": "x"},
        "standings": {
            "has_next": False,
            "results": [
                {
                    "entry": 1001,
                    "entry_name": "Leader FC",
                    "player_name": "Alice Leader",
                    "rank": 1,
                    "last_rank": 1,
                    "total": 150,
                    "event_total": 60,
                },
                {
                    "entry": 1158066,
                    "entry_name": "WB united",
                    "player_name": "Imam Purwanto",
                    "rank": 2,
                    "last_rank": 3,
                    "total": 130,
                    "event_total": 55,
                },
            ],
        },
    }
    bootstrap_payload = {
        "elements": [
            _mock_element(10, "Haaland", 150),
            _mock_element(20, "Salah", 130),
        ],
        "teams": [],
        "element_types": [],
        "events": [],
    }
    picks_1001 = {
        "picks": [{"element": 10, "is_captain": True, "multiplier": 2}],
        "entry_history": {"bank": 10},
        "active_chip": "3xc",
    }
    picks_user = {
        "picks": [{"element": 20, "is_captain": True, "multiplier": 2}],
        "entry_history": {"bank": 5},
        "active_chip": None,
    }
    history_1001 = {"chips": [{"name": "wildcard", "event": 3}]}
    history_user = {"chips": []}

    responses = {
        "leagues-classic/555/standings/": standings_payload,
        "bootstrap-static/": bootstrap_payload,
        "entry/1001/event/3/picks/": picks_1001,
        "entry/1158066/event/3/picks/": picks_user,
        "entry/1001/history/": history_1001,
        "entry/1158066/history/": history_user,
    }

    client = FPLClient(session=MockSession(responses))
    service = LeagueAnalyticsService(client)

    report = service.analyze_classic_league(
        league_id=555,
        user_entry_id=1158066,
        current_gameweek=3,
        page=1,
    )

    assert report.league_name == "Work League"
    assert len(report.standings) == 2
    leader = report.standings[0]
    user = report.standings[1]

    # Leader checks
    assert leader.entry_id == 1001
    assert leader.rank == 1
    assert leader.captain_name == "Haaland"
    assert leader.chips.wc1 == 3
    assert leader.active_chip == "3xc"
    assert leader.points_behind_leader == 0
    assert leader.points_diff_from_user == 20

    # User checks
    assert user.entry_id == 1158066
    assert user.is_user is True
    assert user.captain_name == "Salah"
    assert user.points_behind_leader == 20
    assert user.rank_change == 1  # moved up from 3 to 2

    # Chip Summary
    assert report.chip_summary.total_teams == 2
    assert report.chip_summary.wc1_used_pct == 50.0  # 1 of 2
    assert report.chip_summary.user_chips_remaining == 5  # 0 used
    assert report.chip_summary.user_chip_advantage > 0

    # Run rate needed (20 points behind with 35 GWs left)
    assert report.run_rate_needed is not None
    assert report.run_rate_needed == round(20 / 35, 2)


def test_compare_teams_detects_shield_and_differentials() -> None:
    bootstrap_payload = {
        "elements": [
            _mock_element(1, "Raya", 55),
            _mock_element(2, "Gabriel", 60),
            _mock_element(3, "Salah", 130),
            _mock_element(4, "Palmer", 105),
            _mock_element(5, "Haaland", 150),
            _mock_element(6, "Isak", 85),
        ],
        "teams": [],
        "element_types": [],
        "events": [],
    }
    user_entry = {"id": 1158066, "name": "WB united", "player_first_name": "Imam", "player_last_name": "Purwanto"}
    rival_entry = {"id": 2002, "name": "Rival FC", "player_first_name": "John", "player_last_name": "Doe"}

    # User has Raya (1), Gabriel (2), Salah (3), Haaland (5)
    user_picks = {
        "picks": [
            {"element": 1, "is_captain": False},
            {"element": 2, "is_captain": False},
            {"element": 3, "is_captain": True},
            {"element": 5, "is_captain": False},
        ],
        "entry_history": {"bank": 15},
        "active_chip": None,
    }
    # Rival has Raya (1), Palmer (4), Haaland (5), Isak (6)
    rival_picks = {
        "picks": [
            {"element": 1, "is_captain": False},
            {"element": 4, "is_captain": False},
            {"element": 5, "is_captain": True},
            {"element": 6, "is_captain": False},
        ],
        "entry_history": {"bank": 5},
        "active_chip": "3xc",
    }
    user_hist = {"chips": []}
    rival_hist = {"chips": [{"name": "wildcard", "event": 2}]}

    responses = {
        "bootstrap-static/": bootstrap_payload,
        "entry/1158066/": user_entry,
        "entry/2002/": rival_entry,
        "entry/1158066/event/3/picks/": user_picks,
        "entry/2002/event/3/picks/": rival_picks,
        "entry/1158066/history/": user_hist,
        "entry/2002/history/": rival_hist,
    }

    client = FPLClient(session=MockSession(responses))
    service = LeagueAnalyticsService(client)

    comp = service.compare_teams(
        user_entry_id=1158066,
        rival_entry_id=2002,
        gameweek=3,
    )

    assert comp.user_captain == "Salah"
    assert comp.rival_captain == "Haaland"
    assert comp.shared_players == ("Haaland", "Raya")
    assert comp.user_differentials == ("Gabriel", "Salah")
    assert comp.rival_differentials == ("Isak", "Palmer")
    assert comp.user_bank == 1.5
    assert comp.rival_bank == 0.5
    assert comp.user_chips.total_remaining == 5
    assert comp.rival_chips.total_remaining == 4
