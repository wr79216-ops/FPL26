from src.data.sample_data import (
    get_sample_fixtures,
    get_sample_players,
    get_sample_points_history,
)


def test_sample_players_cover_all_positions_and_valid_score_ranges() -> None:
    players = get_sample_players()

    assert set(players["position"]) == {"GK", "DEF", "MID", "FWD"}
    assert players["name"].is_unique
    assert players["player_id"].is_unique
    assert players["recommendation"].between(0, 100).all()
    assert players["minutes_score"].between(0, 100).all()
    assert players["price"].gt(0).all()
    assert players["ownership"].between(0, 100).all()


def test_differential_flag_matches_product_definition() -> None:
    players = get_sample_players()
    expected = (
        (players["ownership"] < 10)
        & (players["recommendation"] >= 75)
        & (players["minutes_score"] >= 75)
    )

    assert players["differential"].equals(expected)


def test_sample_fixture_matrix_has_five_gameweeks_per_team() -> None:
    fixtures = get_sample_fixtures()

    assert fixtures["fdr"].between(1, 5).all()
    assert fixtures.groupby("team")["gameweek_offset"].nunique().eq(5).all()


def test_sample_points_history_is_deterministic_and_non_negative() -> None:
    first = get_sample_points_history(8)
    second = get_sample_points_history(8)

    assert first.equals(second)
    assert len(first) == 8
    assert first["Points"].ge(0).all()
