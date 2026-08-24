from src.data.refresh_status import RefreshStatusStore
from src.database.connection import Database
from src.database.repository import FPLRepository
from src.domain.contracts import FixtureRecord, TeamRecord
from src.services.fixture_analytics import FixtureAnalyticsService


def _team(team_id: int, name: str, short_name: str) -> TeamRecord:
    return TeamRecord(
        team_id=team_id,
        name=name,
        short_name=short_name,
        strength=4,
        strength_overall_home=4,
        strength_overall_away=4,
        strength_attack_home=4,
        strength_attack_away=4,
        strength_defence_home=4,
        strength_defence_away=4,
    )


def test_fixture_matrix_reads_sqlite_and_uses_official_fdr(tmp_path) -> None:
    database = Database(tmp_path / "fpl.db")
    database.initialize()
    status_store = RefreshStatusStore(tmp_path / "refresh.json")
    status_store.record_success(gameweek=1, teams=2, players=0, fixtures=3, current_stats=0)
    with database.session() as session:
        repository = FPLRepository(session)
        repository.upsert_team(_team(1, "Alpha", "ALP"))
        repository.upsert_team(_team(2, "Beta", "BET"))
        repository.upsert_fixture(
            FixtureRecord(101, 1, 1, 2, None, 1, 5, None, None, False, False)
        )
        repository.upsert_fixture(
            FixtureRecord(102, 2, 2, 1, None, 2, 4, None, None, False, False)
        )
        repository.upsert_fixture(
            FixtureRecord(103, 3, 1, 2, None, 3, 3, None, None, False, False)
        )

    matrix = FixtureAnalyticsService(database, status_store).get_matrix(3)
    alpha = matrix.team("Alpha")

    assert alpha is not None
    assert [cell.fixture for cell in alpha.fixtures] == ["Beta (H)", "Beta (A)", "Beta (H)"]
    assert alpha.fixture_score == 72.5
    assert [cell.custom_fdr for cell in alpha.fixtures] == [1.55, 3.85, 2.75]
    assert alpha.custom_fixture_score == 69.1
    assert matrix.to_dataframe().loc[0, "GW+1"] == "Beta (H) · FDR 1"
    assert matrix.to_dataframe().loc[0, "GW+1 custom"] == 1.55
