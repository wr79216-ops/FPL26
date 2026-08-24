import pytest

from src.features.fixture import custom_fixture_score, difficulty_to_score, fdr_to_score, fixture_score


def test_fdr_maps_to_fixture_ease_score() -> None:
    assert fdr_to_score(1) == 100
    assert fdr_to_score(3) == 60
    assert fdr_to_score(5) == 10


def test_fixture_score_weights_nearest_matches_more_heavily() -> None:
    assert fixture_score([1, 3, 5], 3) == 70.0
    assert fixture_score([1, 5], 3) == 66.2
    assert fixture_score([], 5) is None


def test_fixture_score_rejects_unknown_horizon_and_fdr() -> None:
    with pytest.raises(ValueError):
        fixture_score([1], 2)
    with pytest.raises(ValueError):
        fdr_to_score(0)


def test_custom_difficulty_interpolates_without_replacing_official_fdr() -> None:
    assert difficulty_to_score(1.5) == 90.0
    assert difficulty_to_score(3.5) == 47.5
    assert custom_fixture_score([1.5, 3.5, 5.0], 3) == 61.2
