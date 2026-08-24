"""Historical FPL import, identity matching, and stability-score orchestration."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from statistics import mean, pstdev
from typing import Mapping, Sequence

import yaml

from config.settings import (
    DATABASE_PATH,
    HISTORICAL_DATA_DIR,
    HISTORICAL_IDENTITY_OVERRIDES_PATH,
    load_app_settings,
)
from src.api.historical_client import HistoricalDataClient
from src.database.connection import Database
from src.database.models import (
    HistoricalIdentityMappingModel,
    HistoricalPlayerSeasonModel,
    PlayerHistoricalScoreModel,
)
from src.database.repository import FPLRepository
from src.domain.contracts import (
    HistoricalIdentityMappingRecord,
    HistoricalPlayerSeasonRecord,
    PlayerHistoricalScoreRecord,
    Position,
)
from src.features.recommendation import percentile_ranks
from src.services.application import get_database
from src.utils.text import normalize_display_name


HISTORICAL_SOURCE = "vaastav/Fantasy-Premier-League"
MIN_SEASON_MINUTES = 450
HIGH_CONFIDENCE_MATCH_THRESHOLD = 90.0
HISTORICAL_POSITION_MAP = {
    "GK": Position.GK,
    "DEF": Position.DEF,
    "DM": Position.MID,
    "MID": Position.MID,
    "AM": Position.MID,
    "FWD": Position.FWD,
    "FW": Position.FWD,
}


@dataclass(frozen=True)
class HistoricalImportResult:
    seasons: int
    rows: int
    matched: int
    review: int
    unmatched: int
    scores: int


@dataclass(frozen=True)
class HistoricalDataStatus:
    seasons: int
    rows: int
    matched: int
    review: int
    unmatched: int
    scores: int


@dataclass(frozen=True)
class HistoricalMatchReview:
    season: str
    historical_name: str
    position: str
    candidate_name: str
    match_score: float
    match_method: str


def normalize_identity_name(value: str) -> str:
    display_name = normalize_display_name(value).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", display_name).split())


def parse_historical_csv(
    payload: str,
    season: str,
    imported_at: datetime | None = None,
) -> list[HistoricalPlayerSeasonRecord]:
    """Validate and transform one cleaned_players.csv payload."""
    timestamp = imported_at or datetime.now(timezone.utc)
    reader = csv.DictReader(io.StringIO(payload))
    records: list[HistoricalPlayerSeasonRecord] = []
    seen_keys: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        try:
            first_name = str(row["first_name"]).strip()
            second_name = str(row["second_name"]).strip()
            display_name = " ".join(part for part in (first_name, second_name) if part)
            normalized_name = normalize_identity_name(display_name)
            source_position = str(row["element_type"]).strip().upper()
            position = HISTORICAL_POSITION_MAP[source_position]
            minutes = int(float(row["minutes"]))
            total_points = int(float(row["total_points"]))
            price = float(row["now_cost"]) / 10
            points_per_90 = total_points * 90 / minutes if minutes else 0.0
            source_key = f"{normalized_name}|{position.value}"
            if source_key in seen_keys:
                raise ValueError("duplicate player identity")
            seen_keys.add(source_key)
            records.append(
                HistoricalPlayerSeasonRecord(
                    source=HISTORICAL_SOURCE,
                    season=season,
                    source_player_key=source_key,
                    first_name=first_name,
                    second_name=second_name,
                    display_name=normalize_display_name(display_name),
                    normalized_name=normalized_name,
                    position=position,
                    minutes=minutes,
                    total_points=total_points,
                    goals=int(float(row["goals_scored"])),
                    assists=int(float(row["assists"])),
                    clean_sheets=int(float(row["clean_sheets"])),
                    bonus=int(float(row["bonus"])),
                    price=price,
                    points_per_90=points_per_90,
                    imported_at=timestamp,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid historical row {line_number} for {season}"
            ) from exc
    if not records:
        raise ValueError(f"Historical dataset {season} contains no player rows")
    return records


def load_identity_overrides(
    path: Path = HISTORICAL_IDENTITY_OVERRIDES_PATH,
) -> dict[tuple[str, str], int]:
    """Load manually confirmed historical-to-current player mappings."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as override_file:
        payload = yaml.safe_load(override_file) or {}
    entries = payload.get("overrides", [])
    if not isinstance(entries, list):
        raise ValueError("historical identity overrides must be a list")
    overrides: dict[tuple[str, str], int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("historical identity override entries must be mappings")
        name = normalize_identity_name(str(entry.get("historical_name", "")))
        position = str(entry.get("position", "")).strip().upper()
        current_player_id = entry.get("current_player_id")
        if not name or position not in {item.value for item in Position}:
            raise ValueError("historical identity override requires a valid name and position")
        try:
            player_id = int(current_player_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("historical identity override player id must be an integer") from exc
        key = (name, position)
        if key in overrides and overrides[key] != player_id:
            raise ValueError(f"conflicting historical identity override for {name}")
        overrides[key] = player_id
    return overrides


class HistoricalDataService:
    """Import historical seasons and derive conservative current-player signals."""

    def __init__(
        self,
        database: Database,
        client: HistoricalDataClient,
        archive_dir: Path = HISTORICAL_DATA_DIR,
        default_seasons: Sequence[str] = (),
        identity_overrides_path: Path = HISTORICAL_IDENTITY_OVERRIDES_PATH,
    ) -> None:
        self.database = database
        self.client = client
        self.archive_dir = Path(archive_dir)
        self.default_seasons = tuple(default_seasons)
        self.identity_overrides_path = Path(identity_overrides_path)

    def import_default_seasons(self) -> HistoricalImportResult:
        return self.import_seasons(self.default_seasons)

    def import_seasons(self, seasons: Sequence[str]) -> HistoricalImportResult:
        if not seasons:
            raise ValueError("at least one historical season is required")
        imported_at = datetime.now(timezone.utc)
        parsed: list[HistoricalPlayerSeasonRecord] = []
        payloads: dict[str, str] = {}
        for season in seasons:
            payload = self.client.get_cleaned_players(season)
            payloads[season] = payload
            parsed.extend(parse_historical_csv(payload, season, imported_at))

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        for season, payload in payloads.items():
            season_dir = self.archive_dir / season
            season_dir.mkdir(parents=True, exist_ok=True)
            (season_dir / "cleaned_players.csv").write_text(payload, encoding="utf-8")

        with self.database.session() as session:
            repository = FPLRepository(session)
            for record in parsed:
                repository.upsert_historical_player_season(record)
            self._rebuild_identity_mappings(
                repository,
                imported_at,
                load_identity_overrides(self.identity_overrides_path),
            )
            self._rebuild_historical_scores(repository, imported_at)

        status = self.get_status()
        return HistoricalImportResult(
            seasons=status.seasons,
            rows=status.rows,
            matched=status.matched,
            review=status.review,
            unmatched=status.unmatched,
            scores=status.scores,
        )

    def get_status(self) -> HistoricalDataStatus:
        with self.database.session() as session:
            repository = FPLRepository(session)
            mappings = repository.historical_mapping_counts()
            return HistoricalDataStatus(
                seasons=repository.historical_season_count(),
                rows=repository.count(HistoricalPlayerSeasonModel),
                matched=mappings.get("MATCHED", 0),
                review=mappings.get("REVIEW", 0),
                unmatched=mappings.get("UNMATCHED", 0),
                scores=repository.count(PlayerHistoricalScoreModel),
            )

    def get_review_queue(self, limit: int = 20) -> list[HistoricalMatchReview]:
        with self.database.session() as session:
            rows = FPLRepository(session).list_historical_identity_mappings(
                "REVIEW", limit
            )
            return [
                HistoricalMatchReview(
                    season=historical.season,
                    historical_name=historical.display_name,
                    position=historical.position,
                    candidate_name=(
                        normalize_display_name(candidate.web_name)
                        if candidate is not None
                        else "No candidate"
                    ),
                    match_score=mapping.match_score,
                    match_method=mapping.match_method,
                )
                for historical, mapping, candidate in rows
            ]

    @staticmethod
    def _rebuild_identity_mappings(
        repository: FPLRepository,
        matched_at: datetime,
        identity_overrides: Mapping[tuple[str, str], int],
    ) -> None:
        current_players = repository.list_players()
        current_names = {
            player.player_id: normalize_identity_name(
                f"{player.first_name} {player.second_name}"
            )
            for player in current_players
        }
        current_by_id = {player.player_id: player for player in current_players}
        exact_names: dict[str, list[object]] = defaultdict(list)
        for player in current_players:
            exact_names[current_names[player.player_id]].append(player)

        for historical in repository.list_historical_player_seasons():
            override_player_id = identity_overrides.get(
                (historical.normalized_name, str(historical.position))
            )
            exact = exact_names.get(historical.normalized_name, [])
            current_player_id = None
            status = "UNMATCHED"
            score = 0.0
            method = "no_candidate"
            if override_player_id is not None:
                candidate = current_by_id.get(override_player_id)
                if candidate is None:
                    raise ValueError(
                        f"Identity override references unknown current player {override_player_id}"
                    )
                current_player_id = candidate.player_id
                status = "MATCHED"
                score = 100.0
                method = "manual_confirmed_override"
            elif len(exact) == 1 and exact[0].position == historical.position:
                current_player_id = exact[0].player_id
                status = "MATCHED"
                score = 100.0
                method = "exact_name_position"
            elif exact:
                candidate = exact[0]
                current_player_id = candidate.player_id
                score = 95.0
                if score > HIGH_CONFIDENCE_MATCH_THRESHOLD:
                    status = "MATCHED"
                    method = "high_confidence_exact_name"
                else:
                    status = "REVIEW"
                    method = "exact_name_position_mismatch"
            else:
                candidates = [
                    player for player in current_players if player.position == historical.position
                ]
                similarities = sorted(
                    (
                        SequenceMatcher(
                            None,
                            historical.normalized_name,
                            current_names[player.player_id],
                        ).ratio(),
                        player.player_id,
                    )
                    for player in candidates
                )
                if similarities:
                    best_similarity, best_player_id = similarities[-1]
                    second_similarity = similarities[-2][0] if len(similarities) > 1 else 0.0
                    if (
                        best_similarity > HIGH_CONFIDENCE_MATCH_THRESHOLD / 100
                        and best_similarity - second_similarity >= 0.04
                    ):
                        current_player_id = best_player_id
                        status = "MATCHED"
                        method = "high_confidence_fuzzy_name_position"
                    elif best_similarity >= 0.80:
                        current_player_id = best_player_id
                        status = "REVIEW"
                        method = "fuzzy_candidate"
                    score = round(best_similarity * 100, 2)
            repository.upsert_historical_identity_mapping(
                HistoricalIdentityMappingRecord(
                    historical_player_id=historical.historical_player_id,
                    current_player_id=current_player_id,
                    status=status,
                    match_score=score,
                    match_method=method,
                    matched_at=matched_at,
                )
            )

    @staticmethod
    def _rebuild_historical_scores(
        repository: FPLRepository, calculated_at: datetime
    ) -> None:
        repository.clear_player_historical_scores()
        histories: dict[int, list[HistoricalPlayerSeasonModel]] = defaultdict(list)
        for historical, mapping in repository.list_matched_historical_seasons():
            if mapping.current_player_id is not None and historical.minutes >= MIN_SEASON_MINUTES:
                histories[mapping.current_player_id].append(historical)

        current_players = {player.player_id: player for player in repository.list_players()}
        raw: dict[int, tuple[float, float, int, int]] = {}
        by_position: dict[str, list[int]] = defaultdict(list)
        for player_id, seasons in histories.items():
            seasons.sort(key=lambda item: item.season, reverse=True)
            weights = [math.pow(0.6, index) for index in range(len(seasons))]
            weighted_pp90 = sum(
                season.points_per_90 * weight for season, weight in zip(seasons, weights)
            ) / sum(weights)
            outputs = [season.points_per_90 for season in seasons]
            variation = pstdev(outputs) / abs(mean(outputs)) if len(outputs) > 1 and mean(outputs) else 0.0
            consistency = max(0.0, 100.0 - min(100.0, variation * 100))
            total_minutes = sum(season.minutes for season in seasons)
            raw[player_id] = (weighted_pp90, consistency, len(seasons), total_minutes)
            player = current_players.get(player_id)
            if player is not None:
                by_position[player.position].append(player_id)

        for player_ids in by_position.values():
            percentiles = percentile_ranks([raw[player_id][0] for player_id in player_ids])
            for player_id, output_percentile in zip(player_ids, percentiles):
                weighted_pp90, consistency, season_count, total_minutes = raw[player_id]
                base_score = output_percentile * 0.8 + consistency * 0.2
                evidence = min(1.0, season_count / 2) * min(1.0, total_minutes / 1800)
                score = 50 + evidence * (base_score - 50)
                repository.upsert_player_historical_score(
                    PlayerHistoricalScoreRecord(
                        player_id=player_id,
                        score=round(max(0.0, min(100.0, score)), 2),
                        seasons_count=season_count,
                        total_minutes=total_minutes,
                        weighted_points_per_90=round(weighted_pp90, 4),
                        consistency_score=round(consistency, 2),
                        calculated_at=calculated_at,
                    )
                )


def get_historical_data_service(
    database_path: str = str(DATABASE_PATH),
) -> HistoricalDataService:
    settings = load_app_settings()
    return _get_cached_historical_data_service(
        database_path,
        settings.historical_base_url,
        settings.request_timeout_seconds,
        settings.historical_seasons,
    )


@lru_cache(maxsize=4)
def _get_cached_historical_data_service(
    database_path: str,
    base_url: str,
    timeout_seconds: float,
    default_seasons: tuple[str, ...],
) -> HistoricalDataService:
    return HistoricalDataService(
        database=get_database(database_path),
        client=HistoricalDataClient(base_url, timeout_seconds),
        default_seasons=default_seasons,
    )
