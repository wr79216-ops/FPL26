"""Streamlit entry point for the FPL Signal MVP."""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st
import pandas as pd

from config.settings import PROJECT_ROOT, ensure_directories, load_app_settings, load_scoring_config
from src.services.advanced_planner import get_advanced_planner_service
from src.services.application import initialize_core
from src.services.backtesting import get_backtesting_service
from src.services.decision_tools import get_decision_tools_service
from src.services.fixture_analytics import get_fixture_analytics_service
from src.services.fpl_ingestion import get_fpl_ingestion_service
from src.services.historical_data import get_historical_data_service
from src.services.player_analytics import get_player_analytics_service
from src.services.recommendation_engine import get_recommendation_engine_service
from src.services.schedule_congestion import get_schedule_congestion_service
from src.services.set_piece_insights import get_set_piece_insights_service
from src.ui.components import render_deadline_countdown, render_sidebar
from src.ui.pages import PAGE_RENDERERS
from src.ui.theme import apply_theme
from src.utils.logger import configure_logging, get_logger


def main() -> None:
    """Start the frontend shell and initialize Phase 2 infrastructure."""
    ensure_directories()
    settings = load_app_settings()
    scoring = load_scoring_config()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    st.set_page_config(
        page_title=settings.app_name,
        page_icon=str(PROJECT_ROOT / "src" / "ui" / "assets" / "fpl_signal_mark.svg"),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()
    core_status = initialize_core()
    st.session_state["core_status"] = asdict(core_status)
    ingestion_service = get_fpl_ingestion_service()
    st.session_state["fpl_ingestion_service"] = ingestion_service
    st.session_state["ingestion_status"] = asdict(ingestion_service.get_status())
    st.session_state["fixture_analytics_service"] = get_fixture_analytics_service()
    st.session_state["player_analytics_service"] = get_player_analytics_service()
    st.session_state["historical_data_service"] = get_historical_data_service()
    st.session_state["backtesting_service"] = get_backtesting_service()
    st.session_state["recommendation_engine_service"] = get_recommendation_engine_service()
    st.session_state["decision_tools_service"] = get_decision_tools_service()
    st.session_state["advanced_planner_service"] = get_advanced_planner_service()
    st.session_state["schedule_congestion_service"] = get_schedule_congestion_service()
    st.session_state["set_piece_insights_service"] = get_set_piece_insights_service()

    players = pd.DataFrame()
    fixtures = pd.DataFrame()
    selected_page = render_sidebar(scoring)
    try:
        bootstrap = ingestion_service.client.cache.get("bootstrap")
        if bootstrap is None and ingestion_service.client.raw_store is not None:
            bootstrap = ingestion_service.client.raw_store.load_latest("bootstrap")
        if isinstance(bootstrap, dict) and isinstance(bootstrap.get("events"), list):
            render_deadline_countdown(bootstrap["events"])
    except Exception:
        logger.info("Deadline countdown unavailable; rendering page without it")

    try:
        renderer = PAGE_RENDERERS[selected_page]
        with st.spinner("Preparing the interface..."):
            renderer(players, fixtures, scoring)
        logger.info(
            "Frontend page rendered",
            extra={"page": selected_page, "model_version": scoring.model_version},
        )
    except Exception:
        logger.exception("Frontend page failed", extra={"page": selected_page})
        st.error("The page could not be displayed. Open Data Status for details.")
        if st.button("Return to Dashboard", type="primary"):
            st.session_state["pending_navigation"] = "Dashboard"
            st.rerun()

    st.markdown(
        '<div class="app-footer">© 2026 FPL Signal · Local-first decision support · '
        '<a href="https://imam-dwi.vercel.app/" target="_blank" '
        'rel="noopener noreferrer">by idwp11</a></div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
