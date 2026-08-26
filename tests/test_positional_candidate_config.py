from pathlib import Path

import yaml


def test_positional_candidate_weights_are_explicit_and_not_production() -> None:
    path = Path("config/positional_candidate_weights.yaml")
    with path.open(encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file)

    assert payload["model_version"] == "candidate-v1.3-positional"
    assert payload["status"] == "experimental"
    assert payload["production_model"] == "v1.1"
    for position in ("GK", "DEF", "MID", "FWD"):
        assert sum(payload["position_weights"][position].values()) == 1.0
