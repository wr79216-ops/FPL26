from config.settings import SUPPORTED_POSITIONS, ensure_directories, load_scoring_config


def test_scoring_configuration_is_complete_and_normalized() -> None:
    scoring = load_scoring_config()

    assert scoring.model_version == "v1.1"
    assert scoring.default_horizon == 5
    assert scoring.minimum_minutes == 270
    assert scoring.minutes_security_window == 5
    assert set(scoring.position_weights) == set(SUPPORTED_POSITIONS)
    assert all(
        abs(sum(weights.values()) - 1.0) < 1e-9
        for weights in scoring.position_weights.values()
    )


def test_runtime_directories_can_be_created() -> None:
    ensure_directories()
