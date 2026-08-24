from typing import Optional

from src.ui import components
from src.ui.components import build_squad_pitch_markup


def _pick(
    name: str,
    team: str,
    position: str,
    squad_position: int,
    *,
    multiplier: int = 1,
    gameweek_points: Optional[int] = 0,
    captain: bool = False,
    vice_captain: bool = False,
) -> dict[str, object]:
    return {
        "name": name,
        "team": team,
        "position": position,
        "model_score": 70,
        "squad_position": squad_position,
        "multiplier": multiplier,
        "gameweek_points": gameweek_points,
        "points_multiplier": multiplier,
        "is_captain": captain,
        "is_vice_captain": vice_captain,
    }


def test_squad_pitch_shows_the_official_formation_captaincy_and_bench() -> None:
    picks = [
        _pick("Goalkeeper", "Alpha", "GK", 1, gameweek_points=5),
        _pick("Defender 1", "Beta", "DEF", 2),
        _pick("Defender 2", "Gamma", "DEF", 3),
        _pick("Defender 3", "Delta", "DEF", 4),
        _pick("Midfielder 1", "Alpha", "MID", 5),
        _pick("Midfielder 2", "Beta", "MID", 6),
        _pick("Midfielder 3", "Gamma", "MID", 7, captain=True, multiplier=2, gameweek_points=4),
        _pick("Midfielder 4", "Delta", "MID", 8),
        _pick("Forward 1", "Alpha", "FWD", 9),
        _pick("Forward 2", "Beta", "FWD", 10, vice_captain=True),
        _pick("Forward 3", "Gamma", "FWD", 11),
        _pick("Bench GK", "Delta", "GK", 12, multiplier=0),
        _pick("Bench DEF", "Alpha", "DEF", 13, multiplier=0),
        _pick("Bench MID", "Beta", "MID", 14, multiplier=0),
        _pick("Bench FWD", "Gamma", "FWD", 15, multiplier=0),
    ]

    markup = build_squad_pitch_markup(
        team_name="Example United",
        manager_name="Example Manager",
        gameweek=1,
        gameweek_points=46,
        gameweek_rank=4_900_000,
        picks=picks,
    )

    assert "Example United" in markup
    assert "Formation 3-4-3" in markup
    assert "4,900,000" in markup
    assert 'squad-tag">C</span>' in markup
    assert 'squad-tag squad-tag-vice">VC</span>' in markup
    assert "Bench GK" in markup
    assert "GW points <b>5</b>" in markup
    assert "GW points <b>8</b> <em>×2</em>" in markup


def test_squad_pitch_renders_as_a_single_html_fragment(monkeypatch) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(
        components.st,
        "markdown",
        lambda markup, **_kwargs: rendered.append(markup),
    )

    components.squad_pitch(
        team_name="Test FC",
        manager_name="Manager",
        gameweek=1,
        gameweek_points=46,
        gameweek_rank=123,
        picks=[_pick("Goalkeeper", "Test FC", "GK", 1)],
    )

    assert len(rendered) == 1
    assert 'class="fpl-pitch"' in rendered[0]
    assert "\n" not in rendered[0]
