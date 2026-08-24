from src.features.recommendation import (
    RecommendationCandidate,
    percentile_ranks,
    recommendation_category,
    score_recommendations,
)


def _candidate(player_id: int, xgi: float, fixture: float, availability: float = 1.0):
    return RecommendationCandidate(
        player_id=player_id,
        position="MID",
        metrics={"xgi": xgi, "fixture": fixture},
        confidence=1.0,
        availability_penalty=availability,
    )


def test_percentile_rank_is_position_relative_and_tie_aware() -> None:
    assert percentile_ranks([10, 20, 30]) == [0.0, 50.0, 100.0]
    assert percentile_ranks([10, 10, 30]) == [25.0, 25.0, 100.0]
    assert percentile_ranks([10, 20, 30], higher_is_better=False) == [100.0, 50.0, 0.0]


def test_config_weights_change_ranking_without_code_changes() -> None:
    candidates = [_candidate(1, xgi=1.0, fixture=10), _candidate(2, xgi=0.0, fixture=100)]

    xgi_model = score_recommendations(candidates, {"MID": {"xgi": 0.8, "fixture": 0.2}})
    fixture_model = score_recommendations(
        candidates, {"MID": {"xgi": 0.2, "fixture": 0.8}}
    )

    assert xgi_model[0].final_score > xgi_model[1].final_score
    assert fixture_model[1].final_score > fixture_model[0].final_score
    assert "xGI / 90" in xgi_model[0].reason


def test_availability_penalty_and_categories_are_applied() -> None:
    candidates = [_candidate(1, 1.0, 100, availability=0.2), _candidate(2, 0.0, 10)]
    scores = score_recommendations(candidates, {"MID": {"xgi": 0.5, "fixture": 0.5}})

    assert scores[0].final_score == 20.0
    assert scores[0].category == "Avoid"
    assert recommendation_category(80) == "Elite Target"
    assert recommendation_category(72) == "Strong Buy"
    assert recommendation_category(64) == "Good Option"
    assert recommendation_category(56) == "Watchlist"
    assert recommendation_category(45) == "Neutral"


def test_historical_stability_is_pre_normalized_and_low_weight() -> None:
    candidates = [
        RecommendationCandidate(1, "MID", {"history": 80, "fixture": 50}, 0.1, 1.0),
        RecommendationCandidate(2, "MID", {"history": 50, "fixture": 50}, 1.0, 1.0),
    ]

    scores = score_recommendations(
        candidates, {"MID": {"history": 0.05, "fixture": 0.95}}
    )

    assert scores[0].history_score == 80
    assert scores[1].history_score == 50
    assert scores[0].final_score - scores[1].final_score == 1.5
