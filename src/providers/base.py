"""Contracts for optional, policy-gated external enrichment providers."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence


class ExternalEnrichmentProvider(Protocol):
    """Adapter contract; provider implementations may not leak into UI/services."""

    provider_id: str

    def capabilities(self) -> Sequence[str]:
        """Return the enrichment fields this adapter is allowed to supply."""

    def enrich_players(
        self, official_player_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, object]]:
        """Return enrichment keyed only by validated official FPL player IDs."""
