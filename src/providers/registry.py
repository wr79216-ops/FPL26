"""Configuration-backed status registry for optional enrichment providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from config.settings import EXTERNAL_PROVIDERS_CONFIG_PATH


ALLOWED_ACCESS_MODES = {"licensed_api", "user_supplied_export"}


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    display_name: str
    enabled: bool
    readiness: str
    access_mode: str
    terms_reviewed: bool
    adapter_implemented: bool
    identity_validation_required: bool
    capabilities: tuple[str, ...]
    detail: str


def load_provider_statuses(
    path: Path = EXTERNAL_PROVIDERS_CONFIG_PATH,
) -> tuple[ProviderStatus, ...]:
    """Load provider policy without creating clients or making network calls."""
    with path.open("r", encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file) or {}
    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("external providers configuration must be a mapping")

    statuses = []
    for provider_id, raw in providers.items():
        if not isinstance(raw, dict):
            raise ValueError(f"provider {provider_id} configuration must be a mapping")
        enabled = bool(raw.get("enabled", False))
        access_mode = str(raw.get("access_mode", "disabled")).strip()
        terms_reviewed = bool(raw.get("terms_reviewed", False))
        adapter_implemented = bool(raw.get("adapter_implemented", False))
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise ValueError(f"provider {provider_id} capabilities must be strings")

        if not enabled:
            readiness = "Disabled"
        elif access_mode not in ALLOWED_ACCESS_MODES or not terms_reviewed:
            readiness = "Blocked by policy"
        elif not adapter_implemented:
            readiness = "Adapter required"
        else:
            readiness = "Ready"

        statuses.append(
            ProviderStatus(
                provider_id=str(provider_id),
                display_name=str(raw.get("display_name", provider_id)).strip(),
                enabled=enabled,
                readiness=readiness,
                access_mode=access_mode,
                terms_reviewed=terms_reviewed,
                adapter_implemented=adapter_implemented,
                identity_validation_required=bool(
                    raw.get("identity_validation_required", True)
                ),
                capabilities=tuple(item.strip() for item in capabilities),
                detail=str(raw.get("detail", "")).strip(),
            )
        )
    return tuple(statuses)
