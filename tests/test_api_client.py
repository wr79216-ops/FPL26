from datetime import datetime, timezone

import pytest

from src.api.fpl_client import FPLClient, FPLResponseValidationError
from src.data.raw_store import RawDataStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append((url, timeout))
        return FakeResponse(self.payload)


def test_bootstrap_response_is_validated_cached_and_archived(tmp_path) -> None:
    payload = {
        "elements": [],
        "teams": [],
        "element_types": [],
        "events": [],
    }
    session = FakeSession(payload)
    client = FPLClient(
        session=session,
        raw_store=RawDataStore(tmp_path),
        timeout_seconds=7.5,
    )

    first = client.get_bootstrap()
    first["elements"].append({"id": 999})
    second = client.get_bootstrap()

    assert len(session.calls) == 1
    assert session.calls[0][1] == 7.5
    assert second["elements"] == []
    assert len(list(tmp_path.rglob("bootstrap.json"))) == 1


def test_invalid_bootstrap_response_fails_closed() -> None:
    client = FPLClient(session=FakeSession({"elements": []}))

    with pytest.raises(FPLResponseValidationError, match="missing required keys"):
        client.get_bootstrap()


def test_bootstrap_player_shape_change_fails_closed() -> None:
    payload = {
        "elements": [{"id": 10, "team": 1, "element_type": 3}],
        "teams": [],
        "element_types": [],
        "events": [],
    }
    client = FPLClient(session=FakeSession(payload))

    with pytest.raises(FPLResponseValidationError, match="missing required fields"):
        client.get_bootstrap()


def test_player_summary_rejects_invalid_player_id() -> None:
    client = FPLClient(session=FakeSession({}))

    with pytest.raises(ValueError, match="player_id must be positive"):
        client.get_player_summary(0)


def test_player_summary_is_cached_per_player() -> None:
    session = FakeSession({"fixtures": [], "history": [], "history_past": []})
    client = FPLClient(session=session)

    client.get_player_summary(10)
    client.get_player_summary(10)

    assert len(session.calls) == 1


def test_event_live_is_validated_and_cached_per_gameweek() -> None:
    session = FakeSession({"elements": [{"id": 10, "stats": {"total_points": 5}}]})
    client = FPLClient(session=session)

    client.get_event_live(4)
    client.get_event_live(4)

    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("event/4/live/")


def test_public_squad_payload_is_validated_but_not_archived(tmp_path) -> None:
    payload = {
        "picks": [{"element": player_id} for player_id in range(1, 16)],
        "entry_history": {"bank": 10},
        "active_chip": None,
    }
    session = FakeSession(payload)
    client = FPLClient(session=session, raw_store=RawDataStore(tmp_path))

    result = client.get_entry_picks(12, 4)

    assert len(result["picks"]) == 15
    assert len(session.calls) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_public_squad_rejects_invalid_pick_ids() -> None:
    client = FPLClient(
        session=FakeSession(
            {"picks": [{"element": "12"}], "entry_history": {}, "active_chip": None}
        )
    )

    with pytest.raises(FPLResponseValidationError, match="integer element IDs"):
        client.get_entry_picks(12, 4)


def test_raw_store_preserves_multiple_snapshots_at_same_timestamp(tmp_path) -> None:
    store = RawDataStore(tmp_path)
    timestamp = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    first = store.save("fixtures", [{"id": 1}], timestamp)
    second = store.save("fixtures", [{"id": 2}], timestamp)

    assert first.name == "fixtures.json"
    assert second.name == "fixtures_2.json"
    assert first.read_text(encoding="utf-8") != second.read_text(encoding="utf-8")


def test_raw_store_loads_the_newest_valid_snapshot(tmp_path) -> None:
    store = RawDataStore(tmp_path)
    first = store.save("bootstrap", {"events": [{"id": 1}]})
    second = store.save("bootstrap", {"events": [{"id": 2}]})

    assert first.exists()
    assert second.exists()
    assert store.load_latest("bootstrap") == {"events": [{"id": 2}]}
