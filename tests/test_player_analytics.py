from src.data.refresh_status import RefreshStatusStore
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import FixtureRecord, PlayerRecord, Position, TeamRecord
from src.services.player_analytics import PlayerAnalyticsService
from config.settings import load_scoring_config


class StubPlayerClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_player_summary(self, player_id: int):
        self.calls += 1
        return {
            "fixtures": [],
            "history_past": [],
            "history": [
                {
                    "round": 1,
                    "fixture": 101,
                    "opponent_team": 2,
                    "was_home": True,
                    "minutes": 90,
                    "goals_scored": 1,
                    "assists": 0,
                    "clean_sheets": 0,
                    "bonus": 2,
                    "bps": 30,
                    "expected_goals": "0.50",
                    "expected_assists": "0.10",
                    "expected_goal_involvements": "0.60",
                    "expected_goals_conceded": "1.00",
                    "total_points": 8,
                    "value": 70,
                }
            ],
        }


def _team(team_id: int, name: str, short_name: str) -> TeamRecord:
    return TeamRecord(team_id, name, short_name, 4, 4, 4, 4, 4, 4, 4)


def test_on_demand_history_is_persisted_and_not_requested_twice(tmp_path) -> None:
    database = Database(tmp_path / "fpl.db")
    database.initialize()
    status_store = RefreshStatusStore(tmp_path / "refresh.json")
    status_store.record_success(1, 2, 1, 1, 1)
    with database.session() as session:
        repository = FPLRepository(session)
        repository.upsert_team(_team(1, "Alpha", "ALP"))
        repository.upsert_team(_team(2, "Beta", "BET"))
        repository.upsert_player(
            PlayerRecord(10, "Test", "Player", "Test", 1, 3, Position.MID, "a", "", 7.0, 5.0)
        )
        repository.upsert_fixture(
            FixtureRecord(101, 1, 1, 2, None, 2, 4, 2, 0, True, True)
        )

    client = StubPlayerClient()
    service = PlayerAnalyticsService(database, client, status_store, load_scoring_config())
    first = service.sync_history(10)
    second = service.sync_history(10)
    detail = service.get_detail(10)

    assert client.calls == 1
    assert not first.from_cache
    assert second.from_cache
    assert len(detail.history) == 1
    assert detail.history[0].opponent == "Beta"
    assert detail.features.xgi_per_90 == 0.6
