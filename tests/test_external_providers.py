from src.providers.registry import load_provider_statuses


def test_fotmob_provider_is_disabled_until_access_is_approved() -> None:
    status = load_provider_statuses()[0]

    assert status.provider_id == "fotmob"
    assert status.readiness == "Disabled"
    assert not status.enabled


def test_enabled_provider_fails_closed_without_terms_review(tmp_path) -> None:
    config = tmp_path / "providers.yaml"
    config.write_text(
        """
providers:
  example:
    enabled: true
    access_mode: licensed_api
    terms_reviewed: false
    adapter_implemented: true
    capabilities: [lineups]
""",
        encoding="utf-8",
    )

    status = load_provider_statuses(config)[0]

    assert status.readiness == "Blocked by policy"
