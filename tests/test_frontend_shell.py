from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.ui.components import NAV_ITEMS, deadline_countdown_markup, next_fpl_deadline


def test_next_fpl_deadline_prefers_the_official_next_event() -> None:
    deadline = next_fpl_deadline(
        [
            {"id": 2, "deadline_time": "2026-08-30T12:00:00Z"},
            {"id": 3, "deadline_time": "2026-09-06T12:00:00Z", "is_next": True},
        ],
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    assert deadline is not None
    assert deadline.gameweek == 3
    assert deadline.deadline_at == datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def test_deadline_countdown_markup_includes_live_clock_target() -> None:
    deadline = next_fpl_deadline(
        [{"id": 2, "deadline_time": "2026-08-30T12:00:00Z", "is_next": True}],
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    assert deadline is not None
    markup = deadline_countdown_markup(deadline)
    assert "Gameweek 2" in markup
    assert "deadline-seconds" in markup
    assert "setInterval(tick, 1000)" in markup


def test_all_frontend_routes_render_without_exceptions() -> None:
    app = AppTest.from_file("app.py", default_timeout=10).run()

    assert not app.exception
    for page in NAV_ITEMS[1:]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, f"Frontend route failed: {page}"


def test_data_status_exposes_manual_official_refresh() -> None:
    app = AppTest.from_file("app.py", default_timeout=10).run()

    app.sidebar.radio[0].set_value("Data Status").run()

    assert any(button.label == "Refresh official FPL data" for button in app.button)
    assert any(button.label == "Import historical seasons" for button in app.button)
