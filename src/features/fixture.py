"""Fixture Difficulty Rating conversions and horizon-weighted scoring."""

from __future__ import annotations

from collections.abc import Sequence


FDR_TO_SCORE = {1: 100.0, 2: 80.0, 3: 60.0, 4: 35.0, 5: 10.0}
HORIZON_WEIGHTS = {
    1: (1.0,),
    3: (0.50, 0.30, 0.20),
    5: (0.30, 0.25, 0.20, 0.15, 0.10),
    8: (0.24, 0.19, 0.15, 0.12, 0.10, 0.08, 0.07, 0.05),
}


def fdr_to_score(fdr: int) -> float:
    """Map official FDR (1 easiest, 5 hardest) to a 0–100 ease score."""
    try:
        return FDR_TO_SCORE[fdr]
    except KeyError as exc:
        raise ValueError("FDR must be an integer between 1 and 5") from exc


def difficulty_to_score(difficulty: float) -> float:
    """Interpolate a continuous 1–5 difficulty onto the official ease scale."""
    if not 1 <= difficulty <= 5:
        raise ValueError("difficulty must be between 1 and 5")
    lower = int(difficulty)
    upper = min(5, lower + 1)
    if lower == upper:
        return FDR_TO_SCORE[lower]
    fraction = difficulty - lower
    return round(
        FDR_TO_SCORE[lower]
        + fraction * (FDR_TO_SCORE[upper] - FDR_TO_SCORE[lower]),
        2,
    )


def fixture_score(fdr_values: Sequence[int], horizon: int) -> float | None:
    """Score the next fixtures, weighting the nearest fixture most heavily."""
    if horizon not in HORIZON_WEIGHTS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    if not fdr_values:
        return None
    fdrs = list(fdr_values[:horizon])
    weights = HORIZON_WEIGHTS[horizon][: len(fdrs)]
    total_weight = sum(weights)
    return round(
        sum(fdr_to_score(fdr) * weight for fdr, weight in zip(fdrs, weights)) / total_weight,
        1,
    )


def custom_fixture_score(
    difficulty_values: Sequence[float], horizon: int
) -> float | None:
    """Score continuous custom difficulty while retaining horizon weighting."""
    if horizon not in HORIZON_WEIGHTS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    if not difficulty_values:
        return None
    difficulties = list(difficulty_values[:horizon])
    weights = HORIZON_WEIGHTS[horizon][: len(difficulties)]
    total_weight = sum(weights)
    return round(
        sum(
            difficulty_to_score(difficulty) * weight
            for difficulty, weight in zip(difficulties, weights)
        )
        / total_weight,
        1,
    )
