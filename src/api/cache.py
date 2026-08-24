"""Small thread-safe TTL cache for official FPL responses."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Dict, Optional


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """In-memory cache that returns copies to prevent accidental mutation."""

    def __init__(self) -> None:
        self._entries: Dict[str, _CacheEntry] = {}
        self._lock = RLock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= monotonic():
                self._entries.pop(key, None)
                return None
            return deepcopy(entry.value)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        with self._lock:
            self._entries[key] = _CacheEntry(
                value=deepcopy(value), expires_at=monotonic() + ttl_seconds
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
