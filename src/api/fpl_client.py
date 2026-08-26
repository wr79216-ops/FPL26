"""Single HTTP gateway for the official Fantasy Premier League endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Type, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.api.cache import TTLCache
from src.data.raw_store import RawDataStore


JSONType = Union[Dict[str, Any], list]


class FPLClientError(RuntimeError):
    """Raised when an official FPL request cannot be completed."""


class FPLResponseValidationError(FPLClientError):
    """Raised when an FPL response does not satisfy its endpoint contract."""


class FPLClient:
    """Fetch, validate, cache, and optionally archive official FPL responses."""

    # These fields are the minimum contract required by the transform and the
    # production ranking.  Keeping the contract here makes an upstream rename
    # fail closed instead of converting a missing value into a misleading zero.
    BOOTSTRAP_PLAYER_REQUIRED_FIELDS = frozenset(
        {
            "id",
            "first_name",
            "second_name",
            "web_name",
            "team",
            "element_type",
            "now_cost",
            "status",
            "selected_by_percent",
            "minutes",
            "goals_scored",
            "assists",
            "clean_sheets",
            "saves",
            "bonus",
            "bps",
            "influence",
            "creativity",
            "threat",
            "ict_index",
            "expected_goals",
            "expected_assists",
            "expected_goal_involvements",
        }
    )
    # Positional candidate fields are optional in the official payload.  Their
    # absence is reported as unavailable by the feature/UI layers, never as 0.
    BOOTSTRAP_PLAYER_OPTIONAL_FIELDS = frozenset(
        {
            "expected_goals_conceded",
            "goals_conceded",
            "penalties_saved",
            "penalties_missed",
            "yellow_cards",
            "red_cards",
            "defensive_contribution",
            "starts",
        }
    )

    BOOTSTRAP_PATH = "bootstrap-static/"
    FIXTURES_PATH = "fixtures/"
    EVENT_LIVE_PATH = "event/{gameweek}/live/"
    PLAYER_SUMMARY_PATH = "element-summary/{player_id}/"
    ENTRY_PATH = "entry/{manager_id}/"
    ENTRY_PICKS_PATH = "entry/{manager_id}/event/{gameweek}/picks/"

    def __init__(
        self,
        base_url: str = "https://fantasy.premierleague.com/api/",
        timeout_seconds: float = 10.0,
        retries: int = 3,
        backoff_factor: float = 0.5,
        session: Optional[Any] = None,
        cache: Optional[TTLCache] = None,
        raw_store: Optional[RawDataStore] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.cache = cache or TTLCache()
        self.raw_store = raw_store
        self.logger = logger or logging.getLogger(__name__)
        self._owns_session = session is None
        self.session = session or self._build_session(retries, backoff_factor)

    @staticmethod
    def _build_session(retries: int, backoff_factor: float) -> requests.Session:
        retry_policy = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        session = requests.Session()
        session.headers.update({"User-Agent": "FPL-Signal/0.1 local-first"})
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def get_bootstrap(self) -> Dict[str, Any]:
        payload = self._get_json(
            self.BOOTSTRAP_PATH,
            cache_key="bootstrap",
            ttl_seconds=15 * 60,
            expected_type=dict,
            required_keys=("elements", "teams", "element_types", "events"),
        )
        self.validate_bootstrap_shape(payload)
        return payload  # type: ignore[return-value]

    @classmethod
    def validate_bootstrap_shape(cls, payload: Mapping[str, Any]) -> None:
        """Validate the official player contract before it reaches ETL.

        Optional positional fields deliberately do not fail the request: the
        model can display them as unavailable.  Core ranking fields do fail
        closed, preventing an endpoint shape change from silently flattening
        scores through transform defaults.
        """
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise FPLResponseValidationError("bootstrap elements must be a list")
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                raise FPLResponseValidationError(
                    f"bootstrap element[{index}] must be an object"
                )
            missing = sorted(cls.BOOTSTRAP_PLAYER_REQUIRED_FIELDS - element.keys())
            if missing:
                player_id = element.get("id", index)
                raise FPLResponseValidationError(
                    "bootstrap player "
                    f"{player_id} missing required fields: {', '.join(missing)}"
                )

    def get_fixtures(self) -> list:
        payload = self._get_json(
            self.FIXTURES_PATH,
            cache_key="fixtures",
            ttl_seconds=30 * 60,
            expected_type=list,
        )
        return payload  # type: ignore[return-value]

    def get_event_live(self, gameweek: int) -> Dict[str, Any]:
        """Fetch the official player-stat snapshot for one gameweek.

        Completed gameweeks are immutable once FPL marks their data as checked,
        so a longer cache keeps the dashboard responsive without compromising the
        official source of truth.
        """
        if gameweek <= 0:
            raise ValueError("gameweek must be positive")
        payload = self._get_json(
            self.EVENT_LIVE_PATH.format(gameweek=gameweek),
            cache_key=f"event_live:{gameweek}",
            ttl_seconds=24 * 60 * 60,
            expected_type=dict,
            required_keys=("elements",),
        )
        elements = payload.get("elements", [])
        if not isinstance(elements, list) or any(
            not isinstance(element, dict) or not isinstance(element.get("id"), int)
            for element in elements
        ):
            raise FPLResponseValidationError("event live response must contain player IDs")
        return payload  # type: ignore[return-value]

    def get_player_summary(self, player_id: int) -> Dict[str, Any]:
        if player_id <= 0:
            raise ValueError("player_id must be positive")
        payload = self._get_json(
            self.PLAYER_SUMMARY_PATH.format(player_id=player_id),
            cache_key=f"player_summary:{player_id}",
            ttl_seconds=4 * 60 * 60,
            expected_type=dict,
            required_keys=("fixtures", "history", "history_past"),
        )
        return payload  # type: ignore[return-value]

    def get_entry(self, manager_id: int) -> Dict[str, Any]:
        """Fetch public manager metadata without persisting personal data."""
        if manager_id <= 0:
            raise ValueError("manager_id must be positive")
        payload = self._get_json(
            self.ENTRY_PATH.format(manager_id=manager_id),
            cache_key=f"entry:{manager_id}",
            ttl_seconds=5 * 60,
            expected_type=dict,
            required_keys=("id", "player_first_name", "player_last_name", "name"),
            archive=False,
        )
        return payload  # type: ignore[return-value]

    def get_entry_picks(self, manager_id: int, gameweek: int) -> Dict[str, Any]:
        """Fetch one public FPL squad for an explicit manager and gameweek."""
        if manager_id <= 0:
            raise ValueError("manager_id must be positive")
        if gameweek <= 0:
            raise ValueError("gameweek must be positive")
        payload = self._get_json(
            self.ENTRY_PICKS_PATH.format(manager_id=manager_id, gameweek=gameweek),
            cache_key=f"entry_picks:{manager_id}:{gameweek}",
            ttl_seconds=5 * 60,
            expected_type=dict,
            required_keys=("picks", "entry_history", "active_chip"),
            archive=False,
        )
        picks = payload.get("picks", {})
        if not isinstance(picks, list) or any(
            not isinstance(pick, dict) or not isinstance(pick.get("element"), int)
            for pick in picks
        ):
            raise FPLResponseValidationError("entry picks must contain integer element IDs")
        return payload  # type: ignore[return-value]

    def _get_json(
        self,
        path: str,
        cache_key: str,
        ttl_seconds: int,
        expected_type: Type[Any],
        required_keys: Sequence[str] = (),
        archive: bool = True,
    ) -> JSONType:
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.logger.info("API_CACHE_HIT source=%s", cache_key)
            return cached

        url = self.base_url + path.lstrip("/")
        self.logger.info("API_REQUEST method=GET source=%s", cache_key)
        try:
            response = self.session.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("API_ERROR source=%s error=%s", cache_key, type(exc).__name__)
            raise FPLClientError(f"FPL request failed for {cache_key}") from exc

        self._validate_payload(payload, expected_type, required_keys, cache_key)
        self.cache.set(cache_key, payload, ttl_seconds)
        if archive and self.raw_store is not None:
            self.raw_store.save(cache_key.replace(":", "_"), payload)
        return payload

    @staticmethod
    def _validate_payload(
        payload: Any,
        expected_type: Type[Any],
        required_keys: Sequence[str],
        source: str,
    ) -> None:
        if not isinstance(payload, expected_type):
            raise FPLResponseValidationError(
                f"{source} response must be {expected_type.__name__}"
            )
        if expected_type is dict:
            missing = [key for key in required_keys if key not in payload]
            if missing:
                raise FPLResponseValidationError(
                    f"{source} response missing required keys: {', '.join(missing)}"
                )

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def clear_cache(self) -> None:
        """Force the next manual refresh to use the current official response."""
        self.cache.clear()

    def __enter__(self) -> "FPLClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
