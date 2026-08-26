"""Transparent, position-aware signals derived from official current-season data.

These helpers intentionally do not alter the production recommendation score.
They prepare raw and position-relative candidate signals for later validation and UI work.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence

from src.features.recommendation import percentile_ranks


SignalDirection = Literal["higher_is_better", "lower_is_better"]

MINIMUM_MINUTES = 270
CONVERSION_PRIOR_XG = 3.0
CONVERSION_PRIOR_RATE = {"MID": 0.12, "FWD": 0.15}


@dataclass(frozen=True)
class SignalDefinition:
    """Metadata required to explain a positional signal consistently."""

    key: str
    label: str
    direction: SignalDirection
    production_positions: frozenset[str] = frozenset()
    shrink_for_small_sample: bool = True


@dataclass(frozen=True)
class PositionalSignal:
    """One raw official-derived metric and its within-position percentile score."""

    key: str
    label: str
    direction: SignalDirection
    raw_value: float | None
    normalized_score: float | None
    used_in_ranking: bool


@dataclass(frozen=True)
class PositionalSignalProfile:
    """All relevant signals for one player and one FPL position."""

    player_id: int
    position: str
    minutes: int
    confidence: float
    signals: tuple[PositionalSignal, ...]

    def signal(self, key: str) -> PositionalSignal:
        for item in self.signals:
            if item.key == key:
                return item
        raise KeyError(f"Unknown positional signal: {key}")


SIGNAL_DEFINITIONS: Mapping[str, SignalDefinition] = {
    "minutes_played": SignalDefinition(
        "minutes_played", "Minutes played", "higher_is_better", frozenset({"GK", "DEF", "MID", "FWD"}), False
    ),
    "xgc_per_90": SignalDefinition("xgc_per_90", "xGC / 90", "lower_is_better"),
    "saves_per_90": SignalDefinition("saves_per_90", "Saves / 90", "higher_is_better", frozenset({"GK"})),
    "clean_sheet_rate": SignalDefinition("clean_sheet_rate", "Clean-sheet rate", "higher_is_better"),
    "goals_conceded_per_90": SignalDefinition("goals_conceded_per_90", "Goals conceded / 90", "lower_is_better"),
    "penalties_saved": SignalDefinition("penalties_saved", "Penalties saved", "higher_is_better"),
    "penalties_missed": SignalDefinition("penalties_missed", "Penalties missed", "lower_is_better"),
    "defensive_contribution_per_90": SignalDefinition(
        "defensive_contribution_per_90", "Defensive contribution / 90", "higher_is_better"
    ),
    "xg_per_90": SignalDefinition("xg_per_90", "xG / 90", "higher_is_better", frozenset({"FWD"})),
    "xa_per_90": SignalDefinition("xa_per_90", "xA / 90", "higher_is_better"),
    "xgi_per_90": SignalDefinition(
        "xgi_per_90", "xGI / 90", "higher_is_better", frozenset({"DEF", "MID", "FWD"})
    ),
    "goals_per_90": SignalDefinition("goals_per_90", "Goals / 90", "higher_is_better"),
    "assists_per_90": SignalDefinition("assists_per_90", "Assists / 90", "higher_is_better"),
    "conversion_rate": SignalDefinition("conversion_rate", "Goal conversion rate", "higher_is_better"),
    "yellow_cards": SignalDefinition("yellow_cards", "Yellow cards", "lower_is_better"),
    "red_cards": SignalDefinition("red_cards", "Red cards", "lower_is_better"),
    "discipline_risk_per_90": SignalDefinition("discipline_risk_per_90", "Discipline risk / 90", "lower_is_better"),
    "bonus_points": SignalDefinition(
        "bonus_points", "Bonus points", "higher_is_better", frozenset({"GK", "DEF"})
    ),
    "bps": SignalDefinition("bps", "Bonus Point System", "higher_is_better"),
    "influence_per_90": SignalDefinition("influence_per_90", "Influence / 90", "higher_is_better"),
    "creativity_per_90": SignalDefinition("creativity_per_90", "Creativity / 90", "higher_is_better"),
    "threat_per_90": SignalDefinition("threat_per_90", "Threat / 90", "higher_is_better"),
    "ict_per_90": SignalDefinition("ict_per_90", "ICT / 90", "higher_is_better", frozenset({"MID"})),
}


POSITION_SIGNAL_KEYS: Mapping[str, tuple[str, ...]] = {
    "GK": (
        "minutes_played", "xgc_per_90", "saves_per_90", "clean_sheet_rate",
        "goals_conceded_per_90", "penalties_saved", "bonus_points", "bps",
        "yellow_cards", "red_cards", "discipline_risk_per_90", "ict_per_90",
        "influence_per_90", "creativity_per_90", "threat_per_90",
    ),
    "DEF": (
        "minutes_played", "xgc_per_90", "clean_sheet_rate", "xgi_per_90",
        "defensive_contribution_per_90", "goals_conceded_per_90", "bonus_points",
        "bps", "yellow_cards", "red_cards", "discipline_risk_per_90",
        "influence_per_90", "creativity_per_90", "threat_per_90", "ict_per_90",
    ),
    "MID": (
        "minutes_played", "xgi_per_90", "goals_per_90", "assists_per_90",
        "clean_sheet_rate", "bonus_points", "bps", "yellow_cards", "red_cards",
        "discipline_risk_per_90", "influence_per_90", "creativity_per_90",
        "threat_per_90", "ict_per_90",
    ),
    "FWD": (
        "minutes_played", "xg_per_90", "xgi_per_90", "goals_per_90",
        "assists_per_90", "conversion_rate", "bonus_points", "bps",
        "penalties_missed", "yellow_cards", "red_cards", "discipline_risk_per_90",
        "influence_per_90", "creativity_per_90", "threat_per_90", "ict_per_90",
    ),
}


def _optional_float(stats: Any, field: str) -> float | None:
    value = getattr(stats, field, None)
    return float(value) if value is not None else None


def _per_90(value: float | None, minutes: int) -> float | None:
    if value is None or minutes <= 0:
        return None
    return value * 90 / minutes


def _clean_sheet_rate(clean_sheets: float | None, starts: int) -> float | None:
    if clean_sheets is None or starts <= 0:
        return None
    return clean_sheets / starts


def _conversion_rate(goals: float | None, xg: float | None, position: str) -> float | None:
    if goals is None or xg is None or position not in CONVERSION_PRIOR_RATE:
        return None
    prior_rate = CONVERSION_PRIOR_RATE[position]
    return (goals + prior_rate * CONVERSION_PRIOR_XG) / (xg + CONVERSION_PRIOR_XG)


def _discipline_risk_per_90(
    yellow_cards: float | None, red_cards: float | None, minutes: int
) -> float | None:
    if yellow_cards is None or red_cards is None:
        return None
    # A red card is deliberately weighted more heavily as a risk indicator, not as points.
    return _per_90(yellow_cards + 3 * red_cards, minutes)


def _raw_signal_values(stats: Any, position: str) -> Mapping[str, float | None]:
    minutes = max(0, int(getattr(stats, "minutes", 0) or 0))
    starts = max(0, int(getattr(stats, "starts", 0) or 0))
    goals = _optional_float(stats, "goals")
    assists = _optional_float(stats, "assists")
    clean_sheets = _optional_float(stats, "clean_sheets")
    xg = _optional_float(stats, "expected_goals")
    xa = _optional_float(stats, "expected_assists")
    xgi = _optional_float(stats, "expected_goal_involvements")
    yellow_cards = _optional_float(stats, "yellow_cards")
    red_cards = _optional_float(stats, "red_cards")

    return {
        "minutes_played": float(minutes),
        "xgc_per_90": _per_90(_optional_float(stats, "expected_goals_conceded"), minutes),
        "saves_per_90": _per_90(_optional_float(stats, "saves"), minutes),
        "clean_sheet_rate": _clean_sheet_rate(clean_sheets, starts),
        "goals_conceded_per_90": _per_90(_optional_float(stats, "goals_conceded"), minutes),
        "penalties_saved": _optional_float(stats, "penalties_saved"),
        "penalties_missed": _optional_float(stats, "penalties_missed"),
        "defensive_contribution_per_90": _per_90(
            _optional_float(stats, "defensive_contribution"), minutes
        ),
        "xg_per_90": _per_90(xg, minutes),
        "xa_per_90": _per_90(xa, minutes),
        "xgi_per_90": _per_90(xgi, minutes),
        "goals_per_90": _per_90(goals, minutes),
        "assists_per_90": _per_90(assists, minutes),
        "conversion_rate": _conversion_rate(goals, xg, position),
        "yellow_cards": yellow_cards,
        "red_cards": red_cards,
        "discipline_risk_per_90": _discipline_risk_per_90(yellow_cards, red_cards, minutes),
        "bonus_points": _optional_float(stats, "bonus"),
        "bps": _optional_float(stats, "bps"),
        "influence_per_90": _per_90(_optional_float(stats, "influence"), minutes),
        "creativity_per_90": _per_90(_optional_float(stats, "creativity"), minutes),
        "threat_per_90": _per_90(_optional_float(stats, "threat"), minutes),
        "ict_per_90": _per_90(_optional_float(stats, "ict_index"), minutes),
    }


def build_positional_signal_profile(
    player_id: int,
    position: str,
    stats: Any,
    minimum_minutes: int = MINIMUM_MINUTES,
) -> PositionalSignalProfile:
    """Build raw, explainable signals for a player without applying ranking weights."""
    normalized_position = position.upper()
    if normalized_position not in POSITION_SIGNAL_KEYS:
        raise ValueError(f"Unsupported position: {position}")
    if minimum_minutes <= 0:
        raise ValueError("minimum_minutes must be positive")

    minutes = max(0, int(getattr(stats, "minutes", 0) or 0))
    raw_values = _raw_signal_values(stats, normalized_position)
    signals = tuple(
        PositionalSignal(
            key=key,
            label=SIGNAL_DEFINITIONS[key].label,
            direction=SIGNAL_DEFINITIONS[key].direction,
            raw_value=(
                round(raw_values[key], 4) if raw_values[key] is not None else None
            ),
            normalized_score=None,
            used_in_ranking=normalized_position in SIGNAL_DEFINITIONS[key].production_positions,
        )
        for key in POSITION_SIGNAL_KEYS[normalized_position]
    )
    return PositionalSignalProfile(
        player_id=player_id,
        position=normalized_position,
        minutes=minutes,
        confidence=min(1.0, minutes / minimum_minutes),
        signals=signals,
    )


def normalize_positional_signal_profiles(
    profiles: Sequence[PositionalSignalProfile],
) -> tuple[PositionalSignalProfile, ...]:
    """Attach tie-aware, confidence-adjusted percentile scores within each position."""
    updated: dict[int, PositionalSignalProfile] = {profile.player_id: profile for profile in profiles}
    by_position: dict[str, list[PositionalSignalProfile]] = {}
    for profile in profiles:
        by_position.setdefault(profile.position, []).append(profile)

    for position_profiles in by_position.values():
        scores_by_player: dict[int, dict[str, float]] = {
            profile.player_id: {} for profile in position_profiles
        }
        keys = {signal.key for profile in position_profiles for signal in profile.signals}
        for key in keys:
            available = []
            for profile in position_profiles:
                try:
                    signal = profile.signal(key)
                except KeyError:
                    continue
                if signal.raw_value is not None:
                    available.append((profile, signal))
            if not available:
                continue
            definition = SIGNAL_DEFINITIONS[key]
            percentiles = percentile_ranks(
                [signal.raw_value for _, signal in available],
                higher_is_better=definition.direction == "higher_is_better",
            )
            for (profile, _), percentile in zip(available, percentiles):
                score = percentile
                if definition.shrink_for_small_sample:
                    score = 50 + profile.confidence * (score - 50)
                scores_by_player[profile.player_id][key] = round(max(0.0, min(100.0, score)), 2)

        for profile in position_profiles:
            updated[profile.player_id] = replace(
                profile,
                signals=tuple(
                    replace(signal, normalized_score=scores_by_player[profile.player_id].get(signal.key))
                    for signal in profile.signals
                ),
            )
    return tuple(updated[profile.player_id] for profile in profiles)
