"""Central application settings and scoring-configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
HISTORICAL_DATA_DIR = DATA_DIR / "historical"
LOG_DIR = PROJECT_ROOT / "logs"
DATABASE_PATH = DATA_DIR / "fpl.db"
SCORING_CONFIG_PATH = Path(__file__).with_name("scoring.yaml")
HISTORICAL_IDENTITY_OVERRIDES_PATH = Path(__file__).with_name(
    "historical_identity_overrides.yaml"
)
EXTERNAL_PROVIDERS_CONFIG_PATH = Path(__file__).with_name(
    "external_providers.yaml"
)
SUPPORTED_POSITIONS = ("GK", "DEF", "MID", "FWD")


@dataclass(frozen=True)
class AppSettings:
    """Settings that do not require environment-specific secrets."""

    app_name: str = "FPL Analyst"
    log_level: str = "INFO"
    fpl_base_url: str = "https://fantasy.premierleague.com/api/"
    historical_base_url: str = (
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/"
        "master/data/"
    )
    historical_seasons: Tuple[str, ...] = ("2023-24", "2024-25", "2025-26")
    request_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class ScoringConfig:
    """Validated scoring configuration used by future recommendation modules."""

    model_version: str
    default_horizon: int
    minimum_minutes: int
    minutes_security_window: int
    availability_penalty: Dict[str, float]
    position_weights: Dict[str, Dict[str, float]]


def ensure_directories() -> None:
    """Create local runtime directories without creating application data yet."""
    for directory in (DATA_DIR, RAW_DATA_DIR, HISTORICAL_DATA_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_app_settings() -> AppSettings:
    """Return non-secret local application settings."""
    return AppSettings()


def load_scoring_config(path: Path = SCORING_CONFIG_PATH) -> ScoringConfig:
    """Load and validate scoring weights from YAML.

    All supported positions must be present and each position's weights must sum
    to one, so future score calculations cannot silently use invalid settings.
    """
    with path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}

    model_version = str(raw_config.get("model_version", "")).strip()
    default_horizon = raw_config.get("default_horizon")
    feature_engineering = raw_config.get("feature_engineering")
    availability_penalty = raw_config.get("availability_penalty")
    position_weights = raw_config.get("position_weights")

    if not model_version:
        raise ValueError("scoring.yaml requires a non-empty model_version")
    if not isinstance(default_horizon, int) or default_horizon <= 0:
        raise ValueError("scoring.yaml default_horizon must be a positive integer")
    if not isinstance(feature_engineering, dict):
        raise ValueError("scoring.yaml feature_engineering must be a mapping")
    minimum_minutes = feature_engineering.get("minimum_minutes")
    minutes_security_window = feature_engineering.get("minutes_security_window")
    if not isinstance(minimum_minutes, int) or minimum_minutes <= 0:
        raise ValueError("scoring.yaml minimum_minutes must be a positive integer")
    if not isinstance(minutes_security_window, int) or minutes_security_window <= 0:
        raise ValueError("scoring.yaml minutes_security_window must be a positive integer")
    if not isinstance(availability_penalty, dict):
        raise ValueError("scoring.yaml availability_penalty must be a mapping")
    if not isinstance(position_weights, dict):
        raise ValueError("scoring.yaml position_weights must be a mapping")

    missing_positions = set(SUPPORTED_POSITIONS) - set(position_weights)
    if missing_positions:
        missing = ", ".join(sorted(missing_positions))
        raise ValueError(f"scoring.yaml missing position weights for: {missing}")

    validated_weights: Dict[str, Dict[str, float]] = {}
    for position in SUPPORTED_POSITIONS:
        weights = position_weights[position]
        if not isinstance(weights, dict) or not weights:
            raise ValueError(f"scoring.yaml {position} weights must be a non-empty mapping")

        try:
            normalized_weights = {metric: float(weight) for metric, weight in weights.items()}
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring.yaml {position} weights must be numeric") from exc

        if any(weight < 0 for weight in normalized_weights.values()):
            raise ValueError(f"scoring.yaml {position} weights cannot be negative")
        if abs(sum(normalized_weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"scoring.yaml {position} weights must sum to 1.0")

        validated_weights[position] = normalized_weights

    try:
        validated_penalties = {
            status: float(penalty) for status, penalty in availability_penalty.items()
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("scoring.yaml availability penalties must be numeric") from exc

    if any(not 0 <= penalty <= 1 for penalty in validated_penalties.values()):
        raise ValueError("scoring.yaml availability penalties must be between 0 and 1")

    return ScoringConfig(
        model_version=model_version,
        default_horizon=default_horizon,
        minimum_minutes=minimum_minutes,
        minutes_security_window=minutes_security_window,
        availability_penalty=validated_penalties,
        position_weights=validated_weights,
    )
