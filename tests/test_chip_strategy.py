"""Unit tests for ChipStrategyService (Round 1 FPL Chip Timing Recommender)."""

from __future__ import annotations

from typing import Any, Dict
import pytest

from src.api.fpl_client import FPLClient
from src.services.chip_strategy import (
    ChipStrategyService,
    Round1ChipInventory,
    GameweekSuitability,
    ScheduledChipPlan,
)


class MockSession:
    def __init__(self, endpoints: Dict[str, Any]) -> None:
        self.endpoints = endpoints

    def get(self, url: str, **kwargs: Any) -> Any:
        for pattern, response_data in self.endpoints.items():
            if pattern in url:
                return MockResponse(response_data)
        raise ValueError(f"Unexpected endpoint requested in test: {url}")


class MockResponse:
    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _mock_element(element_id: int, web_name: str, team: int = 1, ep_next: str = "8.0") -> Dict[str, Any]:
    el = {f: 0 for f in FPLClient.BOOTSTRAP_PLAYER_REQUIRED_FIELDS}
    el.update({
        "id": element_id,
        "first_name": "Test",
        "second_name": web_name,
        "web_name": web_name,
        "team": team,
        "now_cost": 100,
        "status": "a",
        "selected_by_percent": "25.0",
        "element_type": 3,
        "ep_next": ep_next,
    })
    return el


def _build_test_bootstrap() -> Dict[str, Any]:
    return {
        "events": [
            {"id": 1, "is_current": False, "is_next": False, "deadline_time": "2026-08-21T17:30:00Z"},
            {"id": 2, "is_current": False, "is_next": False, "deadline_time": "2026-08-28T17:30:00Z"},
            {"id": 3, "is_current": True, "is_next": False, "deadline_time": "2026-09-04T17:30:00Z"},
            {"id": 4, "is_current": False, "is_next": True, "deadline_time": "2026-09-12T12:30:00Z"},
            {"id": 5, "is_current": False, "is_next": False, "deadline_time": "2026-09-18T17:30:00Z"},
            {"id": 6, "is_current": False, "is_next": False, "deadline_time": "2026-10-10T10:00:00Z"},  # IB 1 (+22 days)
            {"id": 7, "is_current": False, "is_next": False, "deadline_time": "2026-10-17T10:00:00Z"},
            {"id": 8, "is_current": False, "is_next": False, "deadline_time": "2026-10-23T17:30:00Z"},
            {"id": 9, "is_current": False, "is_next": False, "deadline_time": "2026-10-31T11:00:00Z"},
            {"id": 10, "is_current": False, "is_next": False, "deadline_time": "2026-11-07T13:30:00Z"},
            {"id": 11, "is_current": False, "is_next": False, "deadline_time": "2026-11-21T13:30:00Z"}, # IB 2 (+14 days)
            {"id": 12, "is_current": False, "is_next": False, "deadline_time": "2026-11-28T13:30:00Z"},
            {"id": 13, "is_current": False, "is_next": False, "deadline_time": "2026-12-02T18:30:00Z"},
            {"id": 14, "is_current": False, "is_next": False, "deadline_time": "2026-12-05T13:30:00Z"},
            {"id": 15, "is_current": False, "is_next": False, "deadline_time": "2026-12-12T13:30:00Z"},
            {"id": 16, "is_current": False, "is_next": False, "deadline_time": "2026-12-19T13:30:00Z"},
            {"id": 17, "is_current": False, "is_next": False, "deadline_time": "2026-12-26T11:00:00Z"}, # Festive
            {"id": 18, "is_current": False, "is_next": False, "deadline_time": "2026-12-29T18:00:00Z"}, # Festive
            {"id": 19, "is_current": False, "is_next": False, "deadline_time": "2027-01-01T18:30:00Z"}, # Festive Expiry
        ],
        "teams": [
            {"id": 1, "short_name": "ARS", "name": "Arsenal"},
            {"id": 2, "short_name": "MCI", "name": "Man City"},
            {"id": 3, "short_name": "LIV", "name": "Liverpool"},
            {"id": 4, "short_name": "CHE", "name": "Chelsea"},
            {"id": 5, "short_name": "IPS", "name": "Ipswich"},
            {"id": 6, "short_name": "SOU", "name": "Southampton"},
        ],
        "element_types": [
            {"id": 1, "plural_name_short": "GKP"},
            {"id": 2, "plural_name_short": "DEF"},
            {"id": 3, "plural_name_short": "MID"},
            {"id": 4, "plural_name_short": "FWD"},
        ],
        "elements": [
            _mock_element(101, "Haaland", team=2, ep_next="8.5"),
            _mock_element(102, "Salah", team=3, ep_next="8.0"),
            _mock_element(103, "Saka", team=1, ep_next="7.5"),
        ],
    }


def _build_test_fixtures() -> list[Dict[str, Any]]:
    fixtures = []
    fid = 1
    for gw in range(1, 20):
        # 1 match for MCI vs IPS or similar
        fixtures.append({
            "id": fid,
            "event": gw,
            "team_h": 2,  # MCI
            "team_a": 5,  # IPS
            "team_h_difficulty": 2,
            "team_a_difficulty": 5,
        })
        fid += 1
        fixtures.append({
            "id": fid,
            "event": gw,
            "team_h": 1,  # ARS
            "team_a": 4,  # CHE (Clash)
            "team_h_difficulty": 4 if gw == 16 else 3,
            "team_a_difficulty": 4 if gw == 16 else 3,
        })
        fid += 1
    return fixtures


def test_round_1_inventory_urgency_levels() -> None:
    # 0 chips used, GW 4 (16 GWs left) -> SAFE
    inv_safe = Round1ChipInventory(current_gw=4)
    assert inv_safe.remaining_chips_count == 4
    assert inv_safe.gws_until_expiry == 16
    assert inv_safe.urgency_level == "SAFE"

    # 4 chips remaining, GW 17 (3 GWs left) -> CRITICAL
    inv_crit = Round1ChipInventory(current_gw=17)
    assert inv_crit.remaining_chips_count == 4
    assert inv_crit.gws_until_expiry == 3
    assert inv_crit.urgency_level == "CRITICAL"

    # All chips used -> COMPLETED
    inv_done = Round1ChipInventory(wc1_gw=4, fh1_gw=16, tc1_gw=3, bb1_gw=18, current_gw=18)
    assert inv_done.remaining_chips_count == 0
    assert inv_done.urgency_level == "COMPLETED"


def test_parse_round_1_inventory_from_history() -> None:
    history = {
        "chips": [
            {"name": "3xc", "event": 3},  # TC1 used in GW 3
            {"name": "wildcard", "event": 24}, # WC2 in Round 2 (should not count as Round 1!)
        ]
    }
    client = FPLClient(session=MockSession({
        "entry/1158066/history/": history,
        "bootstrap-static/": _build_test_bootstrap(),
        "fixtures/": _build_test_fixtures(),
    }))
    service = ChipStrategyService(client)

    inv = service.get_round_1_inventory(1158066, current_gw=4)
    assert inv.tc1_gw == 3
    assert inv.tc1_used is True
    assert inv.wc1_gw is None  # Round 1 WC still available
    assert inv.fh1_gw is None
    assert inv.bb1_gw is None
    assert inv.remaining_chips_count == 3
    assert "wildcard" in inv.unplayed_chips
    assert "freehit" in inv.unplayed_chips
    assert "bench_boost" in inv.unplayed_chips
    assert "triple_captain" not in inv.unplayed_chips


def test_suitability_matrix_detects_international_breaks_and_festive() -> None:
    client = FPLClient(session=MockSession({
        "bootstrap-static/": _build_test_bootstrap(),
        "fixtures/": _build_test_fixtures(),
    }))
    service = ChipStrategyService(client)

    calendar = service.calculate_suitability_matrix(current_gw=4)
    assert len(calendar) == 16  # GW 4 to 19 inclusive

    gw6 = next(c for c in calendar if c.gameweek == 6)
    assert gw6.is_international_break is True
    assert gw6.wc_score >= 70.0  # IB boost

    gw11 = next(c for c in calendar if c.gameweek == 11)
    assert gw11.is_international_break is True

    gw18 = next(c for c in calendar if c.gameweek == 18)
    assert gw18.is_festive_period is True

    gw19 = next(c for c in calendar if c.gameweek == 19)
    assert gw19.is_festive_period is True
    # GW 19 must have elevated urgency scores
    assert gw19.wc_score >= 90.0


def test_master_plan_ensures_no_gameweek_conflicts() -> None:
    history = {"chips": [{"name": "3xc", "event": 3}]}  # TC1 used, 3 remain
    client = FPLClient(session=MockSession({
        "entry/1158066/history/": history,
        "bootstrap-static/": _build_test_bootstrap(),
        "fixtures/": _build_test_fixtures(),
    }))
    service = ChipStrategyService(client)

    report = service.generate_strategy_report(1158066, current_gw=4)
    plan = report.master_plan

    # Exactly 3 chips scheduled
    assert len(plan) == 3

    # All scheduled gameweeks must be unique (no 2 chips on the same GW!)
    scheduled_gws = [p.recommended_gw for p in plan]
    assert len(scheduled_gws) == len(set(scheduled_gws))

    # All scheduled gameweeks must be between GW 4 and GW 19
    for gw in scheduled_gws:
        assert 4 <= gw <= 19

    # Each plan item must have valid labels and explanations
    for p in plan:
        assert p.chip_label in ("Wildcard 1", "Free Hit 1", "Bench Boost 1")
        assert p.suitability_score > 0
        assert len(p.headline) > 0
        assert len(p.rationale) > 0

    assert len(report.key_takeaways) > 0
