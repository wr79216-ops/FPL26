from src.database.connection import Database
from src.database.models import (
    HistoricalIdentityMappingModel,
    HistoricalPlayerSeasonModel,
    PlayerHistoricalScoreModel,
)
from src.database.repository import FPLRepository
from src.domain.contracts import PlayerRecord, Position, TeamRecord
from src.services.historical_data import (
    HistoricalDataService,
    load_identity_overrides,
    parse_historical_csv,
)


HEADER = (
    "first_name,second_name,goals_scored,assists,total_points,minutes,"
    "clean_sheets,bonus,now_cost,element_type\n"
)


class FakeHistoricalClient:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads

    def get_cleaned_players(self, season: str) -> str:
        return self.payloads[season]


def _team() -> TeamRecord:
    return TeamRecord(
        team_id=1,
        name="Arsenal",
        short_name="ARS",
        strength=4,
        strength_overall_home=4,
        strength_overall_away=4,
        strength_attack_home=4,
        strength_attack_away=4,
        strength_defence_home=4,
        strength_defence_away=4,
    )


def _player(player_id: int, first_name: str, second_name: str) -> PlayerRecord:
    return PlayerRecord(
        player_id=player_id,
        first_name=first_name,
        second_name=second_name,
        web_name=second_name,
        team_id=1,
        position_id=3,
        position=Position.MID,
        status="a",
        news="",
        price=8.0,
        ownership=10.0,
    )


def test_historical_csv_validation_and_name_normalization() -> None:
    records = parse_historical_csv(
        HEADER + "Martin,Ødegaard,8,10,180,2800,12,20,85,MID\n",
        "2025-26",
    )

    assert len(records) == 1
    assert records[0].display_name == "Martin Odegaard"
    assert records[0].normalized_name == "martin odegaard"
    assert records[0].points_per_90 > 5

    attacking_midfielder = parse_historical_csv(
        HEADER + "Cole,Palmer,15,10,220,3000,8,30,105,AM\n",
        "2024-25",
    )
    assert attacking_midfielder[0].position == Position.MID


def test_import_is_idempotent_and_builds_matched_stability_scores(tmp_path) -> None:
    database = Database(tmp_path / "historical.db")
    database.initialize()
    with database.session() as session:
        repository = FPLRepository(session)
        repository.upsert_team(_team())
        repository.upsert_player(_player(10, "Martin", "Odegaard"))
        repository.upsert_player(_player(11, "Bukayo", "Saka"))

    payloads = {
        "2024-25": HEADER
        + "Martin,Ødegaard,6,8,150,2500,10,15,83,MID\n"
        + "Bukayo,Saka,10,12,210,2700,11,25,100,MID\n",
        "2025-26": HEADER
        + "Martin,Ødegaard,8,10,180,2800,12,20,85,MID\n"
        + "Bukayo,Saka,12,14,230,2900,13,28,105,MID\n",
    }
    service = HistoricalDataService(
        database=database,
        client=FakeHistoricalClient(payloads),  # type: ignore[arg-type]
        archive_dir=tmp_path / "archive",
        default_seasons=("2024-25", "2025-26"),
    )

    first = service.import_default_seasons()
    second = service.import_default_seasons()

    assert first.rows == second.rows == 4
    assert second.matched == 4
    assert second.review == 0
    assert second.unmatched == 0
    assert second.scores == 2
    with database.session() as session:
        repository = FPLRepository(session)
        assert repository.count(HistoricalPlayerSeasonModel) == 4
        scores = repository.get_player_historical_scores()
        assert repository.count(PlayerHistoricalScoreModel) == 2
        assert all(0 <= score.score <= 100 for score in scores.values())
        assert all(score.seasons_count == 2 for score in scores.values())


def test_high_confidence_name_match_is_auto_promoted(tmp_path) -> None:
    database = Database(tmp_path / "high-confidence.db")
    database.initialize()
    with database.session() as session:
        repository = FPLRepository(session)
        repository.upsert_team(_team())
        repository.upsert_player(_player(10, "Martin", "Odegaard"))

    service = HistoricalDataService(
        database=database,
        client=FakeHistoricalClient(
            {"2025-26": HEADER + "Martin,Ødegaard,6,8,150,2500,10,15,83,GK\n"}
        ),  # type: ignore[arg-type]
        archive_dir=tmp_path / "archive",
        default_seasons=("2025-26",),
    )

    result = service.import_default_seasons()

    assert result.matched == 1
    assert result.review == 0
    with database.session() as session:
        mapping = session.get(HistoricalIdentityMappingModel, 1)
        assert mapping is not None
        assert mapping.status == "MATCHED"
        assert mapping.match_method == "high_confidence_exact_name"


def test_confirmed_identity_overrides_are_loaded() -> None:
    overrides = load_identity_overrides()

    assert len(overrides) == 19
    assert overrides[("rodrigo rodri hernandez", "MID")] == 402
    assert overrides[("konstantinos tsimikas", "DEF")] == 364
