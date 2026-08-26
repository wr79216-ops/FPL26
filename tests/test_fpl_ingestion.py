import pytest

from src.data.refresh_status import RefreshStatusStore
from src.database.connection import Database
from src.database.models import CurrentPlayerStatsModel
from src.services.fpl_ingestion import FPLIngestionError, FPLIngestionService
from tests.test_transform import ELEMENTS, ELEMENT_TYPES, FIXTURES, TEAMS


class StubClient:
    def __init__(self, bootstrap, fixtures, error=None):
        self.bootstrap = bootstrap
        self.fixtures = fixtures
        self.error = error
        self.cache_cleared = 0

    def clear_cache(self) -> None:
        self.cache_cleared += 1

    def get_bootstrap(self):
        if self.error:
            raise self.error
        return self.bootstrap

    def get_fixtures(self):
        if self.error:
            raise self.error
        return self.fixtures


def bootstrap_payload():
    return {
        "elements": ELEMENTS,
        "teams": TEAMS,
        "element_types": ELEMENT_TYPES,
        "events": [{"id": 8, "is_current": True}],
    }


def test_refresh_loads_official_records_and_persists_status(tmp_path) -> None:
    database = Database(tmp_path / "fpl.db")
    database.initialize()
    client = StubClient(bootstrap_payload(), FIXTURES)
    store = RefreshStatusStore(tmp_path / "refresh.json")
    service = FPLIngestionService(database, client, store)

    result = service.refresh()
    status = service.get_status()

    assert client.cache_cleared == 1
    assert result.current_gameweek == 8
    assert result.teams == 2
    assert result.players == 1
    assert result.fixtures == 1
    assert status.teams_in_database == 2
    assert status.players_in_database == 1
    assert status.fixtures_in_database == 1
    assert status.current_stats_in_database == 1
    assert status.gameweek_snapshots_in_database == 1
    with database.session() as session:
        stored_stats = session.get(CurrentPlayerStatsModel, (ELEMENTS[0]["id"], 8))
        assert stored_stats is not None
        assert stored_stats.goals_conceded == 2
        assert stored_stats.penalties_saved == 1
        assert stored_stats.defensive_contribution == 37
        assert stored_stats.expected_goals_conceded == 5.24
    local_live = service.get_local_gameweek_live(8)
    assert local_live["elements"][0]["id"] == ELEMENTS[0]["id"]
    assert local_live["elements"][0]["stats"]["total_points"] == ELEMENTS[0]["total_points"]
    assert status.refresh.last_successful_at is not None
    assert status.refresh.last_error is None

    service.refresh()
    assert service.get_status().gameweek_snapshots_in_database == 1


def test_failed_refresh_retains_last_known_good_status_and_rows(tmp_path) -> None:
    database = Database(tmp_path / "fpl.db")
    database.initialize()
    store = RefreshStatusStore(tmp_path / "refresh.json")
    successful_service = FPLIngestionService(
        database, StubClient(bootstrap_payload(), FIXTURES), store
    )
    successful_service.refresh()
    previous_status = successful_service.get_status()

    failing_service = FPLIngestionService(
        database,
        StubClient(bootstrap_payload(), FIXTURES, error=RuntimeError("offline")),
        store,
    )
    with pytest.raises(FPLIngestionError):
        failing_service.refresh()

    current_status = failing_service.get_status()
    assert current_status.players_in_database == 1
    assert current_status.refresh.last_successful_at == previous_status.refresh.last_successful_at
    assert "offline" in (current_status.refresh.last_error or "")
