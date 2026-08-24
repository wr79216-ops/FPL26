"""Page renderers for the Phase 1 Streamlit frontend shell."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, Dict

import pandas as pd
import streamlit as st

from config.settings import ScoringConfig
from src.ui.components import (
    fixture_strip,
    metric_tile,
    navigate_to,
    page_header,
    player_card,
    render_action_state,
    render_empty_state,
    section_heading,
    squad_pitch,
    wrapped_chip_card,
    wrapped_metric_card,
)
from src.services.gameweek_wrapped import build_gameweek_wrapped, previous_completed_gameweek


PageRenderer = Callable[[pd.DataFrame, pd.DataFrame, ScoringConfig], None]


ATTRIBUTE_HELP = {
    "position": "FPL position used for position-relative percentile ranking.",
    "price": "Current official FPL player price in millions.",
    "ownership": "Percentage of FPL managers currently owning the player.",
    "minutes": "Minutes played in the latest official current-stat snapshot.",
    "form": "Official FPL form signal based on recent points output.",
    "confidence": "How much evidence supports the signal; it reaches 100% at the configured minimum minutes.",
    "score": "Final Recommendation Engine V1 score from 0 to 100.",
    "fixture_score": "Horizon-weighted fixture ease score from 0 to 100; higher is easier.",
    "expected": "Position-specific expected-output component score.",
    "history": "Cross-season stability score from validated MATCHED history; neutral 50 is used when history is unavailable.",
    "value": "Value component based on points per match relative to price.",
    "minutes_score": "Minutes-security component score based on playing time.",
    "fdr": "Official Fixture Difficulty Rating: 1 is easiest and 5 is hardest.",
    "custom_fdr": "Internal 1–5 difficulty blending official FDR, relative opponent strength, and venue; it does not replace official FDR.",
    "mae": "Mean absolute error between recommendation score and actual position-relative points percentile; lower is better.",
    "spearman": "Average rank correlation between recommendation score and future FPL points; 1 is perfect and higher is better.",
    "top_10_hit": "Average percentage overlap between the predicted top 10 and actual top 10 players.",
    "top_10_points": "Average future FPL points scored by the ten highest-ranked players at each cutoff.",
    "model_lift": "Kenaikan skor rekomendasi FPL Analyst (0–100) dari pemain Out ke pemain In. Skor ini menggabungkan performa, fixture, value, minutes, riwayat, dan availability; bukan prediksi poin pasti.",
    "fixture_lift": "Perubahan skor kemudahan fixture untuk horizon yang dipilih. Angka positif berarti jadwal pemain In dinilai lebih mudah.",
    "minutes_lift": "Perubahan skor keamanan menit bermain. Angka positif berarti pemain In dinilai lebih mungkin mendapat menit bermain reguler.",
    "price_change": "Selisih harga pemain In dikurangi pemain Out. Positif memakai bank, negatif menambah bank. Harga jual historis tidak tersedia dari public FPL picks endpoint.",
}


def _status_label(status: str) -> str:
    return {
        "a": "Available",
        "d": "Doubtful",
        "i": "Injured",
        "s": "Suspended",
        "u": "Unavailable",
        "n": "Unavailable",
    }.get(status, "Unknown")


def _freshness_label(timestamp: str | None) -> tuple[str, str]:
    """Return a short, human-friendly freshness state for an ISO timestamp."""
    if not timestamp:
        return "Unknown", "No successful official refresh has been recorded."
    try:
        refreshed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "Unknown", "The last refresh timestamp could not be read."

    age_minutes = max(0, int((datetime.now(timezone.utc) - refreshed_at).total_seconds() // 60))
    if age_minutes < 2:
        return "Fresh", "Updated less than 2 minutes ago."
    if age_minutes < 60:
        return "Fresh", f"Updated {age_minutes} minutes ago."
    if age_minutes < 24 * 60:
        return "Aging", f"Updated {age_minutes // 60} hours ago."
    return "Stale", f"Updated {age_minutes // (24 * 60)} days ago. Refresh before using time-sensitive insight."


def _player_card_data(row: object) -> dict[str, object]:
    return {
        "name": row.name,
        "team": row.team,
        "position": row.position,
        "price": row.price,
        "recommendation": row.final_score,
        "status": _status_label(row.status),
        "next_fixture": row.next_fixture,
        "category": row.category,
    }


def render_dashboard(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Gameweek workspace",
        "Good decisions start with context.",
        "Official rankings, fixture swing, differentials, and minutes security in one summary.",
    )
    service = st.session_state.get("recommendation_engine_service")
    fixture_service = st.session_state.get("fixture_analytics_service")
    if service is None or fixture_service is None:
        render_empty_state("Analytics unavailable", "Reopen the app to initialize the required services.")
        return
    rankings = service.get_rankings(horizon=scoring.default_horizon)
    if not rankings:
        render_empty_state("No rankings available", "Refresh official FPL data from Data Status.")
        return

    top = rankings[0]
    differential_count = sum(row.ownership < 10 and row.final_score >= 56 for row in rankings)
    safe_minutes = sum(row.minutes_score >= 85 for row in rankings)
    current_gameweek = service.ingestion.status_store.load().current_gameweek or 0
    cols = st.columns(4)
    with cols[0]:
        metric_tile(
            "Current gameweek", f"GW {current_gameweek}", "Official FPL context",
            "The current or next gameweek identified from the official FPL events feed.",
        )
    with cols[1]:
        metric_tile(
            "Top target", top.name, f"Score {top.final_score:.0f}",
            ATTRIBUTE_HELP["score"],
        )
    with cols[2]:
        metric_tile(
            "Differentials", str(differential_count), "Owned <10% · Watchlist+",
            "Players owned by fewer than 10% of managers with at least a Watchlist score.",
        )
    with cols[3]:
        metric_tile(
            "Minutes-safe", str(safe_minutes), "Score at least 85",
            "Players whose minutes-security component reaches 85 or higher.",
        )

    section_heading(
        "Top recommendations",
        f"Across all positions · Next {scoring.default_horizon} GW · {scoring.model_version}",
        "The highest final scores after position-relative normalization, confidence adjustment, and availability penalty.",
    )
    top_three = rankings[:3]
    card_columns = st.columns(3)
    for column, player in zip(card_columns, top_three):
        with column:
            player_card(_player_card_data(player))

    if st.button("Explore all recommendations →", type="primary"):
        navigate_to("Recommendations")

    _render_gameweek_wrapped()

    left, right = st.columns([1.2, 1])
    with left:
        section_heading(
            "Fixture radar", "Official horizon-weighted fixture score",
            ATTRIBUTE_HELP["fixture_score"],
        )
        fixture_summary = fixture_service.get_matrix(scoring.default_horizon).to_dataframe()
        st.dataframe(
            fixture_summary[["team", "fixture_score"]]
            .sort_values("fixture_score", ascending=False)
            .head(5),
            hide_index=True,
            width="stretch",
            column_config={
                "team": st.column_config.TextColumn("Team"),
                "fixture_score": st.column_config.ProgressColumn(
                    "Fixture score", min_value=0, max_value=100, format="%.0f",
                    help=ATTRIBUTE_HELP["fixture_score"],
                ),
            },
        )
    with right:
        section_heading(
            "Signal leaders", "Overall · Value · Differential",
            "Quick leaders by final score, value component, and low ownership.",
        )
        value_leader = max(rankings, key=lambda row: row.value_score)
        differential_pool = [row for row in rankings if row.ownership < 10]
        differential = differential_pool[0] if differential_pool else rankings[0]
        for label, candidate in (
            ("Overall", top),
            ("Value", value_leader),
            ("Differential", differential),
        ):
            st.markdown(
                f"**{label}** · {candidate.name}  \n"
                f"{candidate.team} · Score **{candidate.final_score:.0f}** · {candidate.reason}"
            )


def _render_gameweek_wrapped() -> None:
    """Show a previous-gameweek recap when official FPL results are available."""
    ingestion = st.session_state.get("fpl_ingestion_service")
    if ingestion is None:
        return
    client = ingestion.client
    bootstrap = client.cache.get("bootstrap")
    if bootstrap is None and client.raw_store is not None:
        bootstrap = client.raw_store.load_latest("bootstrap")
    try:
        if not isinstance(bootstrap, dict):
            bootstrap = client.get_bootstrap()
        event = previous_completed_gameweek(bootstrap.get("events", []))
        if event is None:
            return
        gameweek = int(event["id"])
        try:
            live = client.get_event_live(gameweek)
        except Exception:
            live = None
            if client.raw_store is not None:
                live = client.raw_store.load_latest(f"event_live_{gameweek}")
            if not isinstance(live, dict):
                live = ingestion.get_local_gameweek_live(gameweek)
        recap = build_gameweek_wrapped(
            event,
            bootstrap,
            live,
        )
    except Exception:
        # The recommendation dashboard remains useful when a historical FPL
        # endpoint is temporarily unavailable; the recap will return on retry.
        return
    if recap is None:
        return

    average = f" · Average score {recap.average_score}" if recap.average_score is not None else ""
    source_label = "Official FPL results" if event.get("finished") or event.get("is_previous") else "Official FPL snapshot"
    section_heading(
        "Gameweek wrapped",
        f"GW {recap.gameweek} · {source_label}{average}",
        "A recap of the last completed gameweek. Player and event metrics are sourced from the official FPL API.",
    )
    for start in range(0, len(recap.metrics), 3):
        columns = st.columns(3)
        for column, metric in zip(columns, recap.metrics[start:start + 3]):
            with column:
                wrapped_metric_card(metric.label, metric.value, metric.detail, metric.tone)
    if recap.chips:
        section_heading(
            "Chips active", "Global use in the completed gameweek",
            "The number of FPL managers who activated each chip, as reported in the official event payload.",
        )
        columns = st.columns(min(3, len(recap.chips)))
        for column, chip in zip(columns, recap.chips):
            with column:
                wrapped_chip_card(chip.name, chip.uses)


def render_players(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Player finder",
        "Find the profile that fits your plan.",
        "Filter the official roster by position, budget, ownership, and playing minutes.",
    )
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Recommendation engine unavailable", "Reopen the app to initialize the recommendation engine.")
        return

    primary_controls = st.columns([1.45, 0.9, 0.85, 1.15])
    with primary_controls[0]:
        search_term = st.text_input(
            "Search player or team",
            placeholder="e.g. Odegaard or Arsenal",
            key="player_finder_search",
            help="Search uses the display-friendly player and team names shown in the official cache.",
        )
    with primary_controls[1]:
        position = st.selectbox(
            "Position", ["ALL", "GK", "DEF", "MID", "FWD"],
            key="player_finder_position",
            help=ATTRIBUTE_HELP["position"],
        )
    with primary_controls[2]:
        horizon = st.selectbox(
            "Fixture horizon", [1, 3, 5, 8], index=2,
            format_func=lambda value: f"Next {value} GW",
            key="player_finder_horizon",
            help="How many upcoming gameweeks are included in the fixture component and final ranking.",
        )
    with primary_controls[3]:
        sort_mode = st.selectbox(
            "Sort matching players",
            ["Recommendation", "Fixture ease", "Value", "Minutes security", "Price (low)", "Ownership (low)"],
            key="player_finder_sort",
            help="Choose the ordering after all finder filters are applied.",
        )

    rankings = service.get_rankings(horizon=horizon)
    if not rankings:
        render_empty_state("No official players", "Refresh official FPL data from Data Status.")
        return
    frame = pd.DataFrame([asdict(row) for row in rankings])

    filter_columns = st.columns([1.35, 1, 1, 1])
    with filter_columns[0]:
        budget = st.slider(
            "Maximum price", 4.0, 15.0, 10.0, 0.1, format="£%.1fm",
            key="player_finder_budget",
            help="Exclude players priced above this official FPL value.",
        )
    with filter_columns[1]:
        max_ownership = st.slider(
            "Max ownership", 1, 100, 50, 1, format="%d%%",
            key="player_finder_ownership",
            help=ATTRIBUTE_HELP["ownership"],
        )
    with filter_columns[2]:
        maximum_minutes = max(90, int(frame["minutes"].max()))
        minimum_minutes = st.slider(
            "Minimum minutes", 0, maximum_minutes, 0, 30,
            key="player_finder_minutes",
            help="Keep players with at least this many minutes in the latest current-stat snapshot.",
        )
    with filter_columns[3]:
        differential_only = st.checkbox(
            "Differentials only",
            key="player_finder_differentials",
            help="Only show players with official FPL ownership below 10%.",
        )

    filtered = frame.loc[
        (frame["price"] <= budget)
        & (frame["ownership"] <= max_ownership)
        & (frame["minutes"] >= minimum_minutes)
    ].copy()
    if position != "ALL":
        filtered = filtered.loc[filtered["position"] == position]
    if search_term.strip():
        search_match = search_term.strip()
        filtered = filtered.loc[
            filtered["name"].str.contains(search_match, case=False, na=False, regex=False)
            | filtered["team"].str.contains(search_match, case=False, na=False, regex=False)
        ]
    if differential_only:
        filtered = filtered.loc[filtered["ownership"] < 10]

    sort_columns = {
        "Recommendation": ("final_score", False),
        "Fixture ease": ("fixture_score", False),
        "Value": ("value_score", False),
        "Minutes security": ("minutes_score", False),
        "Price (low)": ("price", True),
        "Ownership (low)": ("ownership", True),
    }
    sort_column, ascending = sort_columns[sort_mode]
    filtered = filtered.sort_values(sort_column, ascending=ascending)

    section_heading(
        "Matching players", f"{len(filtered)} profiles · Next {horizon} GW",
        "The live official roster after the active filters and selected ranking horizon are applied.",
    )
    if filtered.empty:
        render_empty_state("No players match", "Relax one or more filters.")
        return
    filtered["confidence_percent"] = filtered["confidence"] * 100

    display = filtered[
        [
            "name",
            "team",
            "position",
            "price",
            "ownership",
            "minutes",
            "form",
            "next_fixture",
            "confidence_percent",
            "final_score",
            "category",
            "reason",
        ]
    ]
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Player", help="Official FPL player display name."),
            "team": st.column_config.TextColumn("Team", help="The player's official FPL club."),
            "position": st.column_config.TextColumn("Pos", width="small", help=ATTRIBUTE_HELP["position"]),
            "price": st.column_config.NumberColumn("Price", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
            "ownership": st.column_config.NumberColumn("Owned", format="%.1f%%", help=ATTRIBUTE_HELP["ownership"]),
            "minutes": st.column_config.NumberColumn("Minutes", help=ATTRIBUTE_HELP["minutes"]),
            "form": st.column_config.NumberColumn("Form", format="%.1f", help=ATTRIBUTE_HELP["form"]),
            "next_fixture": st.column_config.TextColumn("Next", help="The team's nearest unstarted official fixture."),
            "confidence_percent": st.column_config.ProgressColumn(
                "Confidence", min_value=0, max_value=100, format="%.0f%%", help=ATTRIBUTE_HELP["confidence"]
            ),
            "final_score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["score"]
            ),
            "category": st.column_config.TextColumn("Verdict", help="Human-readable category derived from the final score."),
            "reason": st.column_config.TextColumn("Top reasons", help="The two weighted components contributing most to this player's score."),
        },
    )

    player_choices = dict(zip(filtered["player_id"], filtered["name"] + " · " + filtered["team"]))
    selected = st.selectbox(
        "Open a player profile",
        list(player_choices),
        format_func=lambda player_id: player_choices[player_id],
        help="Choose a player to inspect official history and feature details.",
    )
    if st.button("View player detail", type="primary"):
        st.session_state["official_player_id"] = selected
        navigate_to("Player Detail")


def render_recommendations(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Recommendation engine",
        "A ranking you can interrogate.",
        "Compare official position-relative scores and understand why each ranking appears.",
    )
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Recommendation engine unavailable", "Reopen the app to initialize the recommendation engine.")
        return

    controls = st.columns([1, 1, 1.4])
    with controls[0]:
        position = st.radio(
            "Position", ["GK", "DEF", "MID", "FWD"], index=2, horizontal=True,
            help=ATTRIBUTE_HELP["position"],
        )
    with controls[1]:
        horizon = st.selectbox(
            "Fixture horizon",
            [1, 3, 5, 8],
            index=2,
            format_func=lambda value: f"Next {value} GW",
            help="How many upcoming gameweeks are included in the fixture component.",
        )
    with controls[2]:
        sort_mode = st.selectbox(
            "Rank by", ["Recommendation", "Value", "Fixture", "Minutes security"],
            help="Sort the visible position ranking by one scoring component.",
        )

    position = position or "MID"
    sort_columns = {
        "Recommendation": "final_score",
        "Value": "value_score",
        "Fixture": "fixture_score",
        "Minutes security": "minutes_score",
    }
    rows = service.get_rankings(position=position, horizon=horizon, limit=20)
    if not rows:
        render_empty_state("No recommendation available", "Try another position or horizon.")
        return
    ranked = pd.DataFrame([asdict(row) for row in rows]).sort_values(
        sort_columns[sort_mode], ascending=False
    )
    section_heading(
        f"Top 20 {position}", f"Next {horizon} GW · Model {scoring.model_version}",
        "Top 20 players in this position after the configured recommendation model is applied.",
    )

    cards = st.columns(min(3, len(ranked)))
    row_by_id = {row.player_id: row for row in rows}
    for rank, (column, (_, player)) in enumerate(zip(cards, ranked.head(3).iterrows()), start=1):
        with column:
            player_card(
                _player_card_data(row_by_id[int(player["player_id"])]),
                label=f"Rank #{rank}",
            )

    section_heading("Score breakdown", "Every component is visible")
    st.caption(
        "Final score combines position-relative fixture, expected output, minutes, history, and value signals; "
        "the visible reason names the strongest contributors. Full model weights are available in Data Status."
    )
    table = ranked[
        [
            "name",
            "team",
            "price",
            "ownership",
            "form",
            "fixture_score",
            "expected_score",
            "minutes_score",
            "history_score",
            "value_score",
            "final_score",
            "category",
            "reason",
        ]
    ]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Player", help="Official FPL player display name."),
            "team": st.column_config.TextColumn("Team", help="The player's official FPL club."),
            "price": st.column_config.NumberColumn("Price", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
            "ownership": st.column_config.NumberColumn("Owned", format="%.1f%%", help=ATTRIBUTE_HELP["ownership"]),
            "form": st.column_config.NumberColumn("Form", format="%.1f", help=ATTRIBUTE_HELP["form"]),
            "fixture_score": st.column_config.ProgressColumn(
                "Fixture", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["fixture_score"]
            ),
            "expected_score": st.column_config.ProgressColumn(
                "Expected", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["expected"]
            ),
            "minutes_score": st.column_config.ProgressColumn(
                "Minutes", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["minutes_score"]
            ),
            "value_score": st.column_config.ProgressColumn(
                "Value", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["value"]
            ),
            "history_score": st.column_config.ProgressColumn(
                "History", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["history"]
            ),
            "final_score": st.column_config.ProgressColumn(
                "Final", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["score"]
            ),
            "category": st.column_config.TextColumn("Verdict", help="Human-readable category derived from the final score."),
            "reason": st.column_config.TextColumn("Top reasons", help="The two weighted components contributing most to this player's score."),
        },
    )


def render_fixtures(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures, scoring
    page_header(
        "Fixture planner",
        "See the run, not just the next match.",
        "Official FPL fixtures are stored in SQLite and scored for 1, 3, 5, or 8-gameweek horizons.",
    )
    service = st.session_state.get("fixture_analytics_service")
    if service is None:
        render_empty_state("Fixture service unavailable", "Reopen the app to initialize the SQLite service.")
        return

    horizon = st.select_slider(
        "Horizon", [1, 3, 5, 8], value=5, format_func=lambda value: f"Next {value} GW",
        help="Number of upcoming gameweeks included in the fixture matrix and score.",
    )
    matrix = service.get_matrix(horizon)
    if not matrix.teams or not any(summary.fixtures for summary in matrix.teams):
        render_empty_state("No upcoming official fixtures", "Refresh FPL data from the Data Status page.")
        return

    teams = [summary.team_name for summary in matrix.teams]
    default_index = teams.index("Arsenal") if "Arsenal" in teams else 0
    selected_team = st.selectbox(
        "Team", teams, index=default_index,
        help="Select an official FPL club to inspect its upcoming fixtures.",
    )
    selected = matrix.team(selected_team)
    if selected is None:
        render_empty_state("Team unavailable", "Choose another team.")
        return

    average_fdr = sum(item.fdr for item in selected.fixtures) / len(selected.fixtures)
    summary_columns = st.columns(3)
    summary_columns[0].metric("Fixture score", f"{selected.fixture_score or 0:.0f}/100", "Higher is easier")
    summary_columns[1].metric("Average FDR", f"{average_fdr:.1f}", "1 easiest · 5 hardest")
    summary_columns[2].metric("Players tracked", str(selected.players_tracked), "Official FPL roster")

    section_heading(
        selected_team, f"Next {horizon} fixtures · Official FPL",
        "Fixture-by-fixture opponent and official FDR for the selected club.",
    )
    fixture_strip(
        [
            {"gameweek": f"GW {item.gameweek or 'TBC'}", "fixture": item.fixture, "fdr": item.fdr}
            for item in selected.fixtures
        ]
    )

    section_heading(
        "Fixture matrix", "Official FDR · fixture score weighted toward nearer matches",
        "Lower FDR is easier; the fixture score weights nearer fixtures more heavily.",
    )
    dataframe = matrix.to_dataframe()
    ordered_columns = ["team", "fixture_score", "players_tracked"] + [
        f"GW+{offset}" for offset in range(1, horizon + 1)
    ]
    available_columns = [column for column in ordered_columns if column in dataframe.columns]
    st.dataframe(
        dataframe[available_columns].sort_values("fixture_score", ascending=False, na_position="last"),
        hide_index=True,
        width="stretch",
        column_config={
            "team": st.column_config.TextColumn("Team", pinned=True, help="Official FPL club name."),
            "fixture_score": st.column_config.ProgressColumn(
                "Fixture score", min_value=0, max_value=100, format="%.0f",
                help=ATTRIBUTE_HELP["fixture_score"],
            ),
            "players_tracked": st.column_config.NumberColumn(
                "Players", help="Number of official players currently assigned to this club."
            ),
        },
    )


def render_player_detail(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures, scoring
    service = st.session_state.get("player_analytics_service")
    if service is None:
        render_empty_state("Player service unavailable", "Reopen the app to initialize the SQLite service.")
        return
    options = service.list_player_options()
    if not options:
        render_empty_state("No official players", "Refresh official FPL data from Data Status.")
        return

    labels = {option.player_id: option.label for option in options}
    player_ids = list(labels)
    selected_player_id = st.selectbox(
        "Official FPL player",
        player_ids,
        format_func=lambda player_id: labels[player_id],
        key="official_player_id",
        help="Select a player whose official element-summary history you want to inspect.",
    )

    if st.button("Load official gameweek history", type="primary"):
        try:
            with st.spinner("Fetching element-summary and saving history..."):
                result = service.sync_history(selected_player_id)
            if result.from_cache:
                st.info(f"The gameweek cache is still valid: {result.row_count} history rows; no new API request was needed.")
            else:
                st.success(f"History saved: {result.row_count} rows from official FPL.")
        except Exception:
            st.error("History could not be loaded. Existing local data remains safe.")

    detail = service.get_detail(selected_player_id)
    features = detail.features
    status_labels = {
        "a": "Available",
        "d": "Doubtful",
        "i": "Injured",
        "s": "Suspended",
        "u": "Unavailable",
        "n": "Unavailable",
    }
    page_header(
        f"{detail.team} · {detail.position} · Official FPL",
        detail.name,
        "Current totals, cached gameweek history, and confidence-adjusted features with visible periods.",
    )
    if detail.news:
        st.warning(detail.news)

    headline = st.columns(5)
    with headline[0]:
        metric_tile("Price", f"£{detail.price:.1f}m", f"Owned {detail.ownership:.1f}%", ATTRIBUTE_HELP["price"])
    with headline[1]:
        metric_tile(
            "Total points", str(detail.total_points), f"PPM {detail.points_per_game:.1f}",
            "Official FPL total points in the latest current-stat snapshot.",
        )
    with headline[2]:
        metric_tile(
            "Rolling form", f"{features.form_5:.2f}", "Last 5 cached GW",
            "Average total points across the player's latest five cached gameweeks.",
        )
    with headline[3]:
        metric_tile(
            "xGI / 90", f"{features.xgi_per_90:.2f}", f"xG {features.xg_per_90:.2f} · xA {features.xa_per_90:.2f}",
            "Expected goal involvements projected to 90 minutes from cached history.",
        )
    with headline[4]:
        metric_tile(
            "Minutes security", f"{features.minutes_security:.0f}/100", status_labels.get(detail.status, "Unknown"),
            "Recent playing-time reliability adjusted by the official availability status.",
        )

    period = (
        f"GW {features.period_start_gameweek}–{features.period_end_gameweek}"
        if features.period_start_gameweek is not None
        else "No gameweek history cached"
    )
    confidence_percent = features.confidence * 100
    if not features.enough_minutes:
        st.info(
            f"Small sample: {features.sample_minutes} of {service.scoring.minimum_minutes} minimum minutes. "
            f"Confidence adjustment currently {confidence_percent:.0f}%."
        )

    chart_column, feature_column = st.columns([1.3, 1])
    with chart_column:
        section_heading(
            "Gameweek trends", f"{period} · element-summary cache",
            "Official points, minutes, and xGI by gameweek; values are aggregated for double gameweeks.",
        )
        if detail.history:
            history_frame = pd.DataFrame(
                [
                    {
                        "Gameweek": row.gameweek,
                        "Points": row.points,
                        "Minutes": row.minutes,
                        "xGI": row.xgi,
                    }
                    for row in detail.history
                ]
            ).groupby("Gameweek", as_index=False)[["Points", "Minutes", "xGI"]].sum().set_index("Gameweek")
            trend_columns = st.columns(3)
            for column, metric, color, description in (
                (trend_columns[0], "Points", "#18f59b", "Official FPL points"),
                (trend_columns[1], "Minutes", "#7bbcf0", "Minutes played"),
                (trend_columns[2], "xGI", "#b28df2", "Expected goal involvements"),
            ):
                with column:
                    st.caption(description)
                    st.line_chart(history_frame[[metric]], color=color, height=190)
        else:
            render_action_state(
                "History not available",
                "Click Load official gameweek history. Early-season players may return 0 rows.",
            )
    with feature_column:
        section_heading(
            "Feature confidence", f"{features.sample_minutes} minutes · {confidence_percent:.0f}% confidence",
            "Raw signals are shown beside confidence-adjusted values to make small samples visible.",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ["Form", features.form_5, features.confidence_adjusted_form, "Last 5 GW"],
                    ["xGI / 90", features.xgi_per_90, features.confidence_adjusted_xgi_per_90, period],
                    ["Value", features.value, features.confidence_adjusted_value, "PPM / price"],
                    ["Minutes", features.minutes_security, features.minutes_security, f"Last {service.scoring.minutes_security_window} fixtures"],
                ],
                columns=["Feature", "Raw", "Adjusted", "Period / definition"],
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Raw": st.column_config.NumberColumn(
                    format="%.2f", help="Unadjusted feature calculated from the selected history period."
                ),
                "Adjusted": st.column_config.NumberColumn(
                    format="%.2f", help="Feature after minimum-minutes confidence and availability adjustment."
                ),
            },
        )

    section_heading(
        "Official match history", f"{len(detail.history)} persisted rows · idempotent cache",
        "Validated element-summary rows saved locally so repeated page loads do not repeat API requests.",
    )
    if detail.history:
        st.dataframe(
            pd.DataFrame([asdict(row) for row in reversed(detail.history)]),
            hide_index=True,
            width="stretch",
            column_config={
                "gameweek": st.column_config.NumberColumn("GW", help="Official FPL gameweek number."),
                "opponent": st.column_config.TextColumn("Opponent", help="Opponent club in this fixture."),
                "venue": st.column_config.TextColumn("Venue", help="Whether the player was home or away."),
                "minutes": st.column_config.NumberColumn("Min", help="Minutes played in this fixture."),
                "points": st.column_config.NumberColumn("Pts", help="Official FPL points scored in this fixture."),
                "xg": st.column_config.NumberColumn("xG", format="%.2f", help="Expected goals in this fixture."),
                "xa": st.column_config.NumberColumn("xA", format="%.2f", help="Expected assists in this fixture."),
                "xgi": st.column_config.NumberColumn("xGI", format="%.2f", help="Expected goal involvements in this fixture."),
                "bonus": st.column_config.NumberColumn("Bonus", help="Official FPL bonus points in this fixture."),
                "price": st.column_config.NumberColumn("Price", format="£%.1fm", help="Player value recorded for this fixture."),
            },
        )

    fixture_service = st.session_state.get("fixture_analytics_service")
    if fixture_service is not None:
        team_summary = fixture_service.get_matrix(5).team(detail.team)
        if team_summary is not None and team_summary.fixtures:
            section_heading("Next fixtures", "Five-gameweek official FPL outlook")
            fixture_strip(
                [
                    {"gameweek": f"GW {item.gameweek or 'TBC'}", "fixture": item.fixture, "fdr": item.fdr}
                    for item in team_summary.fixtures
                ]
            )


def render_compare(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Head-to-head",
        "Compare the trade-off, not just the total.",
        "Choose two official players to compare fixture, output, minutes, and value trade-offs.",
    )
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Recommendation engine unavailable", "Reopen the app to initialize the recommendation engine.")
        return
    horizon = st.select_slider(
        "Comparison horizon", [1, 3, 5, 8], value=scoring.default_horizon,
        format_func=lambda value: f"Next {value} GW",
        help="Use the same fixture horizon for both players before judging the trade-off.",
    )
    rows = service.get_rankings(horizon=horizon)
    if len(rows) < 2:
        render_empty_state("Not enough players", "Refresh official FPL data.")
        return
    labels = {row.player_id: f"{row.name} · {row.team} · {row.position}" for row in rows}
    row_by_id = {row.player_id: row for row in rows}
    player_ids = list(labels)
    selectors = st.columns(2)
    with selectors[0]:
        player_a_id = st.selectbox(
            "Player A", player_ids, index=0, format_func=lambda player_id: labels[player_id],
            help="First official player in the comparison.",
        )
    with selectors[1]:
        player_b_id = st.selectbox(
            "Player B", player_ids, index=1, format_func=lambda player_id: labels[player_id],
            help="Second official player in the comparison.",
        )

    if player_a_id == player_b_id:
        render_empty_state(
            "Choose two different players", "The comparison requires two different player profiles."
        )
        return

    player_a = row_by_id[player_a_id]
    player_b = row_by_id[player_b_id]
    cards = st.columns(2)
    with cards[0]:
        player_card(_player_card_data(player_a), "Player A")
    with cards[1]:
        player_card(_player_card_data(player_b), "Player B")

    section_heading(
        "Signal comparison", "Higher bars indicate stronger signals",
        "The same persisted component scores used by Recommendations, shown side by side.",
    )
    comparison = pd.DataFrame(
        {
            player_a.name: [
                player_a.final_score,
                player_a.fixture_score,
                player_a.expected_score,
                player_a.minutes_score,
                player_a.value_score,
                player_a.history_score,
            ],
            player_b.name: [
                player_b.final_score,
                player_b.fixture_score,
                player_b.expected_score,
                player_b.minutes_score,
                player_b.value_score,
                player_b.history_score,
            ],
        },
        index=["Recommendation", "Fixture", "Expected", "Minutes", "Value", "History"],
    )
    st.bar_chart(comparison, horizontal=True, height=320)

    winner = player_a if player_a.final_score >= player_b.final_score else player_b
    value_winner = player_a if player_a.value_score >= player_b.value_score else player_b
    st.success(
        f"Overall signal: {winner.name} leads. Value signal: {value_winner.name} leads. "
        f"Model {scoring.model_version} · Next {horizon} GW."
    )


def render_backtesting(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Model validation",
        "Test the ranking before trusting the calibration.",
        "GW N predictions use data through GW N only; outcomes come from GW N+1 through the selected horizon.",
    )
    service = st.session_state.get("backtesting_service")
    if service is None:
        render_empty_state("Backtesting unavailable", "Reopen the app to initialize the backtesting service.")
        return

    status = service.get_status()
    status_columns = st.columns(4)
    with status_columns[0]:
        metric_tile(
            "Historical GW rows", f"{status.gameweek_rows:,}", "Validated player-fixture outcomes",
            "Historical player rows at player-fixture grain used to separate features from future outcomes.",
        )
    with status_columns[1]:
        metric_tile(
            "Prediction rows", f"{status.prediction_rows:,}", "Persisted and auditable",
            "Saved player rankings with cutoff, horizon, model version, and actual future outcome.",
        )
    with status_columns[2]:
        metric_tile(
            "Evaluation runs", str(status.runs), "Baseline and candidate",
            "One aggregate evaluation per season, horizon, and model version.",
        )
    with status_columns[3]:
        metric_tile(
            "Production model", scoring.model_version, "Candidate remains experimental",
            "Production weights are unchanged until evidence covers more seasons and limitations.",
        )

    if st.button(
        "Import & rerun 2025–26 backtests",
        type="primary",
        help="Download validated historical gameweek/fixture files and rerun both models for horizons 1, 3, and 5.",
    ):
        try:
            with st.spinner("Importing historical outcomes and running all time-safe cutoffs..."):
                result = service.import_and_run()
            st.success(
                f"Backtest complete: {result.runs} runs, {result.prediction_rows:,} predictions, "
                f"{result.gameweek_rows:,} historical rows."
            )
        except Exception:
            st.error("Backtest failed. The latest successful run remains available.")

    runs = service.list_runs()
    if not runs:
        render_empty_state(
            "No backtest results",
            "Click Import & rerun to create the baseline and candidate evaluations.",
        )
        return

    available_horizons = sorted({run.horizon for run in runs})
    horizon = st.select_slider(
        "Evaluation horizon",
        available_horizons,
        value=5 if 5 in available_horizons else available_horizons[-1],
        format_func=lambda value: f"Next {value} GW",
        help="Future gameweeks included in each stored outcome window.",
    )
    selected_runs = [run for run in runs if run.horizon == horizon]
    comparison = pd.DataFrame([asdict(run) for run in selected_runs])

    best_mae = min(selected_runs, key=lambda run: run.mae_percentile)
    best_spearman = max(selected_runs, key=lambda run: run.spearman)
    best_hit = max(selected_runs, key=lambda run: run.top_10_hit_rate)
    best_points = max(selected_runs, key=lambda run: run.average_actual_points_top_10)
    metric_columns = st.columns(4)
    with metric_columns[0]:
        metric_tile(
            "Lowest MAE", f"{best_mae.mae_percentile:.2f}", best_mae.model_version,
            ATTRIBUTE_HELP["mae"],
        )
    with metric_columns[1]:
        metric_tile(
            "Best Spearman", f"{best_spearman.spearman:.3f}", best_spearman.model_version,
            ATTRIBUTE_HELP["spearman"],
        )
    with metric_columns[2]:
        metric_tile(
            "Top-10 hit", f"{best_hit.top_10_hit_rate:.1f}%", best_hit.model_version,
            ATTRIBUTE_HELP["top_10_hit"],
        )
    with metric_columns[3]:
        metric_tile(
            "Top-10 actual pts", f"{best_points.average_actual_points_top_10:.2f}", best_points.model_version,
            ATTRIBUTE_HELP["top_10_points"],
        )

    section_heading(
        "Model comparison",
        f"2025–26 · GW {selected_runs[0].first_gameweek}–{selected_runs[0].last_gameweek} cutoffs",
        "All metrics use the same eligible players, cutoff gameweeks, and future outcome windows.",
    )
    st.dataframe(
        comparison[
            [
                "model_version",
                "gameweeks",
                "predictions",
                "mae_percentile",
                "spearman",
                "top_10_hit_rate",
                "average_actual_points_top_10",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "model_version": st.column_config.TextColumn("Model"),
            "gameweeks": st.column_config.NumberColumn("Cutoffs"),
            "predictions": st.column_config.NumberColumn("Predictions"),
            "mae_percentile": st.column_config.NumberColumn(
                "MAE ↓", format="%.3f", help=ATTRIBUTE_HELP["mae"]
            ),
            "spearman": st.column_config.NumberColumn(
                "Spearman ↑", format="%.3f", help=ATTRIBUTE_HELP["spearman"]
            ),
            "top_10_hit_rate": st.column_config.NumberColumn(
                "Top-10 hit ↑", format="%.1f%%", help=ATTRIBUTE_HELP["top_10_hit"]
            ),
            "average_actual_points_top_10": st.column_config.NumberColumn(
                "Avg top-10 pts ↑", format="%.2f", help=ATTRIBUTE_HELP["top_10_points"]
            ),
        },
    )

    production = next(
        (run for run in selected_runs if run.model_version.startswith("production-")),
        None,
    )
    candidate = next(
        (run for run in selected_runs if run.model_version.startswith("candidate-")),
        None,
    )
    if production and candidate and candidate.mae_percentile < production.mae_percentile and candidate.spearman > production.spearman:
        st.info(
            f"Calibration decision: {candidate.model_version} improves MAE and Spearman for Next {horizon} GW, "
            "but remains experimental. Keep production v1.1 until another season and availability data validate the gain."
        )

    model_version = st.selectbox(
        "Inspect model predictions",
        [run.model_version for run in selected_runs],
        help="Choose one persisted model version before inspecting an individual cutoff.",
    )
    selected_run = next(run for run in selected_runs if run.model_version == model_version)
    as_of_gameweek = st.slider(
        "As-of gameweek",
        selected_run.first_gameweek,
        selected_run.last_gameweek,
        selected_run.last_gameweek,
        help="Only data at or before this gameweek was available to the prediction.",
    )
    predictions = service.list_predictions(
        selected_run.season, horizon, model_version, as_of_gameweek
    )
    section_heading(
        "Prediction audit",
        f"As of GW {as_of_gameweek} → actual GW {as_of_gameweek + 1}–{as_of_gameweek + horizon}",
        "Stored predicted ranks and future outcomes at one exact cutoff.",
    )
    st.dataframe(
        pd.DataFrame([asdict(row) for row in predictions[:20]]),
        hide_index=True,
        width="stretch",
        column_config={
            "as_of_gameweek": None,
            "player": st.column_config.TextColumn("Player"),
            "position": st.column_config.TextColumn("Pos", width="small"),
            "recommendation_score": st.column_config.ProgressColumn(
                "Predicted score", min_value=0, max_value=100, format="%.1f"
            ),
            "predicted_rank": st.column_config.NumberColumn("Pred rank"),
            "actual_points": st.column_config.NumberColumn("Actual points"),
            "actual_percentile": st.column_config.ProgressColumn(
                "Actual percentile", min_value=0, max_value=100, format="%.1f"
            ),
            "actual_rank": st.column_config.NumberColumn("Actual rank"),
        },
    )
    with st.expander("Methodology and required caveats"):
        st.write(selected_run.limitations)
        st.caption(
            "MAE compares score with position-relative future-points percentile. Spearman and top-10 metrics "
            "evaluate ordering and shortlist usefulness; they do not claim causal player performance prediction."
        )


def render_decision_tools(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    """Render practical Phase 10 transfer and captain decision support."""
    del players, fixtures
    page_header(
        "Decision support",
        "Turn signals into a considered next move.",
        "Compare same-position transfers and captain profiles using official FPL data, visible trade-offs, and non-binding confidence.",
    )
    service = st.session_state.get("decision_tools_service")
    if service is None:
        render_empty_state(
            "Decision tools unavailable",
            "Reopen the app to initialize the decision-support service.",
        )
        return

    horizon = st.select_slider(
        "Decision horizon",
        [1, 3, 5, 8],
        value=scoring.default_horizon,
        format_func=lambda value: f"Next {value} GW",
        help="The future gameweeks used for transfer and captain comparisons.",
    )
    rankings = service.player_options(horizon)
    if not rankings:
        render_empty_state(
            "No decision data available",
            "Refresh official FPL data from Data Status before using decision tools.",
        )
        return

    st.caption(
        "These are decision aids, not automatic transfers or captain instructions. Confirm squad rules, injury news, and deadlines before acting."
    )

    section_heading(
        "Transfer finder",
        f"Same position · Next {horizon} GW",
        "Replacements must be affordable with the selected bank and have a higher recommendation score than the outgoing player.",
    )
    transfer_controls = st.columns([1.8, 0.8])
    player_by_id = {row.player_id: row for row in rankings}
    option_ids = list(player_by_id)
    default_out = min(rankings, key=lambda row: row.final_score).player_id
    with transfer_controls[0]:
        player_out_id = st.selectbox(
            "Player to transfer out",
            option_ids,
            index=option_ids.index(default_out),
            format_func=lambda player_id: (
                f"{player_by_id[player_id].name} · {player_by_id[player_id].team} · "
                f"{player_by_id[player_id].position} · £{player_by_id[player_id].price:.1f}m"
            ),
            help="Choose an official player from the cached FPL roster. The tool only searches same-position replacements.",
        )
    with transfer_controls[1]:
        extra_budget = st.number_input(
            "Budget in bank (£m)",
            min_value=0.0,
            max_value=15.0,
            value=0.0,
            step=0.1,
            format="%.1f",
            help="Additional budget available after selling the selected player.",
        )

    outgoing = player_by_id[player_out_id]
    transfers = service.transfer_recommendations(
        player_out_id, float(extra_budget), horizon
    )
    if transfers:
        best = transfers[0]
        transfer_metrics = st.columns(4)
        with transfer_metrics[0]:
            metric_tile("Best replacement", best.replacement.name, best.replacement.category, ATTRIBUTE_HELP["score"])
        with transfer_metrics[1]:
            metric_tile("Price cap", f"£{best.price_cap:.1f}m", f"Out £{outgoing.price:.1f}m + bank", ATTRIBUTE_HELP["price"])
        with transfer_metrics[2]:
            metric_tile(
                "Projected gain", f"+{best.projected_gain:.2f} pts", f"Next {horizon} GW proxy",
                "Difference between the two signal-adjusted points proxies; it is not a guaranteed FPL-points forecast.",
            )
        with transfer_metrics[3]:
            metric_tile(
                "Decision confidence", f"{best.confidence:.0f}/100", "Signals and availability",
                "A transparent blend of recommendation score, minutes security, fixture ease, and available status; it is not a probability.",
            )

        transfer_table = pd.DataFrame(
            [
                {
                    "Replacement": item.replacement.name,
                    "Team": item.replacement.team,
                    "Price": item.replacement.price,
                    "Score": item.replacement.final_score,
                    "Projected points": item.projected_points_in,
                    "Projected gain": item.projected_gain,
                    "Confidence": item.confidence,
                    "Trade-off": item.trade_off,
                    "Model reasons": item.replacement.reason,
                }
                for item in transfers
            ]
        )
        st.dataframe(
            transfer_table,
            hide_index=True,
            width="stretch",
            column_config={
                "Price": st.column_config.NumberColumn("Price", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f", help=ATTRIBUTE_HELP["score"]),
                "Projected points": st.column_config.NumberColumn("Projected pts", format="%.2f", help="Signal-adjusted points proxy for the selected horizon."),
                "Projected gain": st.column_config.NumberColumn("Gain", format="%+.2f", help="Replacement proxy minus outgoing-player proxy."),
                "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.0f", help="Decision-signal confidence, not a probability."),
            },
        )
    else:
        render_empty_state(
            "No affordable same-position upgrade",
            "Increase the budget, choose another outgoing player, or refresh official FPL data.",
        )

    section_heading(
        "Captain shortlist",
        f"Safe · Balanced · Differential · Next {horizon} GW",
        "Each role uses the same official rankings but emphasises a different trade-off.",
    )
    captains = service.captain_shortlist(horizon)
    if captains:
        captain_columns = st.columns(len(captains))
        for column, captain in zip(captain_columns, captains):
            with column:
                player_card(_player_card_data(captain.player), f"{captain.role} captain")
                st.markdown(f"**Projected proxy:** {captain.projected_points:.2f} pts")
                st.markdown(f"**Decision confidence:** {captain.confidence:.0f}/100")
                st.caption(captain.rationale)
                st.caption(captain.trade_off)
    else:
        render_empty_state(
            "No captain shortlist available",
            "Refresh official FPL data and check player availability.",
        )

    with st.expander("Projection method and important limits"):
        st.markdown(
            "**Projected points proxy** = confidence-adjusted points per match × number of official fixtures in the selected horizon × fixture multiplier. "
            "The fixture multiplier is `0.60 + fixture score / 125`, so a neutral fixture score of 50 gives a multiplier of 1.00. "
            "The captain and transfer confidence values combine final score, minutes security, fixture ease, and availability; they are not probabilities or guarantees."
        )
        st.markdown(
            "This page does not import your squad, free transfers, chips, selling-price history, price changes, or latest unofficial team news. Use Advanced Planner for optional public squad import and a legal wildcard draft."
        )


def render_advanced_planner(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    """Render guarded enrichment status, custom FDR, and squad planning."""
    del players, fixtures
    page_header(
        "Advanced planning",
        "Plan deeper without blurring the source of truth.",
        "Compare an internal fixture view, import a public official FPL squad, suggest legal free transfers, and build a constraint-aware wildcard draft.",
    )
    service = st.session_state.get("advanced_planner_service")
    if service is None:
        render_empty_state(
            "Advanced planner unavailable",
            "Reopen the app to initialize the Phase 11 service.",
        )
        return

    horizon = st.select_slider(
        "Planning horizon",
        [1, 3, 5, 8],
        value=scoring.default_horizon,
        format_func=lambda value: f"Next {value} GW",
        help="The official fixture window used for custom difficulty and squad rankings.",
        key="advanced_horizon",
    )

    section_heading(
        "External provider governance",
        "No external provider is active",
        "External data can only be enabled after access rights, terms, capabilities, and player identity validation are documented.",
    )
    provider_rows = [
        {
            "Provider": status.display_name,
            "Status": status.readiness,
            "Access mode": status.access_mode,
            "Terms reviewed": status.terms_reviewed,
            "Capabilities": ", ".join(status.capabilities),
            "Detail": status.detail,
        }
        for status in service.provider_statuses()
    ]
    if provider_rows:
        st.dataframe(pd.DataFrame(provider_rows), hide_index=True, width="stretch")
    st.info(
        "FotMob remains a future option only. The app does not scrape it or use its data until an allowed access route and identity-validation workflow are configured."
    )

    section_heading(
        "Custom fixture difficulty",
        f"Official-first comparison · Next {horizon} GW",
        ATTRIBUTE_HELP["custom_fdr"],
    )
    matrix = service.fixture_analytics.get_matrix(horizon)
    fixture_rows = [
        {
            "Team": team.team_name,
            "Official ease": team.fixture_score,
            "Custom ease": team.custom_fixture_score,
            "Difference": (
                round(team.custom_fixture_score - team.fixture_score, 1)
                if team.custom_fixture_score is not None
                and team.fixture_score is not None
                else None
            ),
            "Fixtures": " · ".join(
                f"{cell.fixture} {cell.fdr}/{cell.custom_fdr:.2f}"
                for cell in team.fixtures
                if cell.custom_fdr is not None
            ),
        }
        for team in matrix.teams
    ]
    fixture_frame = pd.DataFrame(fixture_rows)
    if fixture_frame.empty:
        render_empty_state(
            "No upcoming fixtures",
            "Refresh official FPL data from Data Status.",
        )
    else:
        fixture_frame = fixture_frame.sort_values(
            ["Custom ease", "Official ease"], ascending=False
        )
        st.dataframe(
            fixture_frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Official ease": st.column_config.ProgressColumn(
                    "Official ease", min_value=0, max_value=100, format="%.1f",
                    help=ATTRIBUTE_HELP["fixture_score"],
                ),
                "Custom ease": st.column_config.ProgressColumn(
                    "Custom ease", min_value=0, max_value=100, format="%.1f",
                    help=ATTRIBUTE_HELP["custom_fdr"],
                ),
                "Difference": st.column_config.NumberColumn(
                    "Custom − official", format="%+.1f",
                    help="Positive means the internal view rates the horizon easier than official FDR does.",
                ),
            },
        )
        st.caption(
            "Fixture cells show opponent followed by official/custom difficulty. Recommendation Engine v1.1 continues to use official FDR; custom difficulty is a comparison signal only."
        )

    section_heading(
        "Squad import & wildcard planner",
        "2 GK · 5 DEF · 5 MID · 3 FWD · max 3 per club",
        "Imports one public official FPL squad for the active gameweek and keeps it only in the current app session.",
    )
    import_controls = st.columns([1, 1.4])
    with import_controls[0]:
        manager_id = st.number_input(
            "Public FPL manager ID",
            min_value=1,
            value=1,
            step=1,
            help="Numeric ID from the manager's official fantasy.premierleague.com URL. No login or credential is required.",
        )
    with import_controls[1]:
        st.caption("Optional: import a current squad before building the wildcard comparison.")
        import_squad = st.button("Import public official squad")
    if import_squad:
        try:
            with st.spinner("Loading the public squad from official FPL..."):
                imported = service.import_public_squad(int(manager_id), horizon)
            st.session_state["advanced_imported_squad"] = imported
            st.session_state["advanced_imported_horizon"] = horizon
            st.session_state.pop("advanced_optimized_squad", None)
            st.session_state.pop("advanced_transfer_plan", None)
            st.session_state.pop("advanced_transfer_plan_context", None)
            st.success(
                f"Imported {imported.team_name} for GW {imported.gameweek}: 15 players, £{imported.bank:.1f}m bank."
            )
        except Exception as exc:
            st.error(f"Squad import failed: {exc}")

    imported = st.session_state.get("advanced_imported_squad")
    if st.session_state.get("advanced_imported_horizon") != horizon:
        imported = None
    if imported is not None:
        imported_metrics = st.columns(4)
        with imported_metrics[0]:
            metric_tile("Team", imported.team_name, imported.manager_name)
        with imported_metrics[1]:
            metric_tile("Gameweek", f"GW {imported.gameweek}", "Official picks endpoint")
        with imported_metrics[2]:
            metric_tile("Squad cost", f"£{imported.current_squad_cost:.1f}m", "Current cached prices")
        with imported_metrics[3]:
            metric_tile("Bank", f"£{imported.bank:.1f}m", imported.active_chip or "No active chip")
        squad_pitch(
            team_name=imported.team_name,
            manager_name=imported.manager_name,
            gameweek=imported.gameweek,
            gameweek_points=imported.gameweek_points,
            gameweek_rank=imported.gameweek_rank,
            picks=(
                {
                    "name": pick.player.name,
                    "team": pick.player.team,
                    "position": pick.player.position,
                    "model_score": pick.player.final_score,
                    "squad_position": pick.squad_position,
                    "multiplier": pick.multiplier,
                    "gameweek_points": pick.gameweek_points,
                    "points_multiplier": pick.multiplier,
                    "is_captain": pick.is_captain,
                    "is_vice_captain": pick.is_vice_captain,
                }
                for pick in imported.picks
            ),
        )

        section_heading(
            "Transfer suggestions",
            "Personalised to your imported squad · No points hit",
            "Each suggestion replaces a player from the imported squad with a same-position player who fits the bank and three-per-club rule, then ranks the move by the recommendation model, fixtures, minutes security, and availability.",
        )
        transfer_controls = st.columns([1, 1.4])
        with transfer_controls[0]:
            free_transfers = st.selectbox(
                "Free transfers to use",
                [1, 2, 3, 4, 5],
                index=0,
                help="Choose the number of available free transfers you want this plan to use. The planner does not recommend paid transfers or calculate points hits.",
                key=f"transfer_free_count_{horizon}_{imported.manager_id}",
            )
        with transfer_controls[1]:
            st.caption(
                "The public FPL picks endpoint does not provide your historical selling prices, so affordability uses the current cached FPL price and official bank."
            )
            suggest_transfers = st.button("Suggest transfers", type="primary")
        transfer_context = (imported.manager_id, horizon, free_transfers)
        if suggest_transfers:
            try:
                with st.spinner("Finding the best legal upgrades for this squad..."):
                    transfer_plan = service.suggest_transfers(
                        imported,
                        horizon,
                        free_transfers=free_transfers,
                    )
                st.session_state["advanced_transfer_plan"] = transfer_plan
                st.session_state["advanced_transfer_plan_context"] = transfer_context
            except Exception as exc:
                st.error(f"Transfer suggestions could not be prepared: {exc}")

        transfer_plan = st.session_state.get("advanced_transfer_plan")
        if st.session_state.get("advanced_transfer_plan_context") != transfer_context:
            transfer_plan = None
        if transfer_plan is not None:
            if not transfer_plan.transfers:
                st.info(
                    "Hold the transfer: no legal same-position upgrade improves the current model profile within your bank."
                )
            else:
                transfer_metrics = st.columns(3)
                with transfer_metrics[0]:
                    metric_tile(
                        "Free transfers used",
                        str(transfer_plan.free_transfers_used),
                        f"of {free_transfers} selected",
                    )
                with transfer_metrics[1]:
                    metric_tile(
                        "Model lift",
                        f"+{transfer_plan.total_score_gain:.1f}",
                        "Sum of recommendation-score improvements",
                        ATTRIBUTE_HELP["model_lift"],
                    )
                with transfer_metrics[2]:
                    metric_tile(
                        "Bank after moves",
                        f"£{transfer_plan.bank_after:.1f}m",
                        "Using current cached FPL prices",
                        "Sisa dana setelah seluruh transfer yang disarankan, dihitung dari harga FPL cache saat ini dan bank resmi saat squad diimpor.",
                    )
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Out": item.player_out.name,
                                "In": item.player_in.name,
                                "Pos": item.player_in.position,
                                "Price change": item.price_delta,
                                "Model lift": item.score_delta,
                                "Fixture lift": item.fixture_delta,
                                "Minutes lift": item.minutes_delta,
                                "Why": item.reason,
                            }
                            for item in transfer_plan.transfers
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Price change": st.column_config.NumberColumn(
                            "Price Δ", format="£%+.1fm", help=ATTRIBUTE_HELP["price_change"]
                        ),
                        "Model lift": st.column_config.NumberColumn(
                            "Model Δ", format="%+.1f", help=ATTRIBUTE_HELP["model_lift"]
                        ),
                        "Fixture lift": st.column_config.NumberColumn(
                            "Fixture Δ", format="%+.1f", help=ATTRIBUTE_HELP["fixture_lift"]
                        ),
                        "Minutes lift": st.column_config.NumberColumn(
                            "Minutes Δ", format="%+.1f", help=ATTRIBUTE_HELP["minutes_lift"]
                        ),
                    },
                )

    default_budget = imported.available_budget if imported is not None else 100.0
    planner_controls = st.columns([1, 1.4])
    with planner_controls[0]:
        budget = st.number_input(
            "Wildcard budget (£m)",
            min_value=70.0,
            max_value=130.0,
            value=float(default_budget),
            step=0.1,
            format="%.1f",
            help="Total spend available for all 15 players. Imported squads use cached current prices plus official bank.",
            key=f"wildcard_budget_{horizon}_{imported.manager_id if imported else 'manual'}",
        )
    with planner_controls[1]:
        st.caption("The optimizer is a deterministic heuristic and does not claim a mathematically unique optimum.")
        build_draft = st.button("Build wildcard draft", type="primary")
    if build_draft:
        try:
            with st.spinner("Searching legal squad combinations..."):
                optimized = service.optimize_wildcard(float(budget), horizon)
            st.session_state["advanced_optimized_squad"] = optimized
            st.session_state["advanced_optimized_horizon"] = horizon
        except Exception as exc:
            st.error(f"Wildcard draft could not be built: {exc}")

    optimized = st.session_state.get("advanced_optimized_squad")
    if st.session_state.get("advanced_optimized_horizon") != horizon:
        optimized = None
    if optimized is not None:
        result_metrics = st.columns(4)
        with result_metrics[0]:
            metric_tile("Draft cost", f"£{optimized.total_cost:.1f}m", f"£{optimized.remaining_budget:.1f}m remaining")
        with result_metrics[1]:
            metric_tile("Squad signal", f"{optimized.total_score:.1f}", "Sum of 15 recommendation scores")
        with result_metrics[2]:
            metric_tile("Captain", optimized.captain.name, f"Score {optimized.captain.final_score:.0f}")
        with result_metrics[3]:
            metric_tile("Vice-captain", optimized.vice_captain.name, f"Score {optimized.vice_captain.final_score:.0f}")

        squad_rows = []
        starter_ids = {player.player_id for player in optimized.starters}
        for player in optimized.players:
            role = "Starting XI" if player.player_id in starter_ids else "Bench"
            if player.player_id == optimized.captain.player_id:
                role += " · Captain"
            elif player.player_id == optimized.vice_captain.player_id:
                role += " · Vice"
            squad_rows.append(
                {
                    "Role": role,
                    "Player": player.name,
                    "Team": player.team,
                    "Pos": player.position,
                    "Price": player.price,
                    "Score": player.final_score,
                    "Fixture": player.fixture_score,
                    "Minutes": player.minutes_score,
                    "Reason": player.reason,
                }
            )
        st.dataframe(
            pd.DataFrame(squad_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Price": st.column_config.NumberColumn("Price", format="£%.1fm"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                "Fixture": st.column_config.ProgressColumn("Fixture", min_value=0, max_value=100, format="%.0f"),
                "Minutes": st.column_config.ProgressColumn("Minutes", min_value=0, max_value=100, format="%.0f"),
            },
        )

        if imported is not None:
            changes = service.compare_squads(imported, optimized)
            section_heading(
                "Wildcard changes",
                f"{len(changes)} proposed swaps",
                "Players outside the optimized 15 are paired with same-position additions for an auditable comparison.",
            )
            if changes:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Out": change.player_out.name,
                                "In": change.player_in.name,
                                "Pos": change.player_in.position,
                                "Price change": change.price_delta,
                                "Score change": change.score_delta,
                            }
                            for change in changes
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Price change": st.column_config.NumberColumn(format="%+.1f"),
                        "Score change": st.column_config.NumberColumn(format="%+.1f"),
                    },
                )
            else:
                st.success("The imported squad already matches this optimizer draft.")

        with st.expander("Planner method and limits"):
            st.markdown(
                "The draft uses available official players, cached prices, Recommendation Engine v1.1 scores, a £ budget, exact position quotas, and the three-per-club constraint. "
                "A beam-search heuristic evaluates a broad candidate pool, then chooses the strongest valid starting formation and captain signals."
            )
            st.markdown(
                "It does not execute transfers and does not model selling-price history, free transfers, transfer hits, chips, future price changes, or late team news. Verify the final draft in official FPL before acting."
            )


def render_data_status(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    page_header(
        "System status",
        "Know what the app knows.",
        "Monitor sources, freshness, coverage, model version, and data limitations before trusting insights.",
    )
    ingestion_status = st.session_state.get("ingestion_status", {})
    refresh_status = ingestion_status.get("refresh", {})
    last_refresh = refresh_status.get("last_successful_at") or "Never"
    freshness, freshness_detail = _freshness_label(refresh_status.get("last_successful_at"))
    player_count = int(ingestion_status.get("players_in_database", 0))
    current_stats_count = int(ingestion_status.get("current_stats_in_database", 0))
    snapshot_count = int(ingestion_status.get("gameweek_snapshots_in_database", 0))
    score_count = int(ingestion_status.get("recommendation_scores_in_database", 0))
    expected_scores = player_count * 4
    missing_current_stats = max(0, player_count - current_stats_count)
    missing_snapshots = max(0, player_count - snapshot_count)
    missing_scores = max(0, expected_scores - score_count)
    status_columns = st.columns(4)
    with status_columns[0]:
        metric_tile(
            "App mode", "Official", "All pages use the official FPL cache",
            "No MVP page depends on mock player or fixture data.",
        )
    with status_columns[1]:
        metric_tile("Data freshness", freshness, freshness_detail, "Age of the last successful official FPL refresh.")
    with status_columns[2]:
        metric_tile(
            "Data coverage",
            f"{current_stats_count}/{player_count}",
            f"Current stats · {missing_current_stats} missing",
            "Official current-stat rows available out of the roster stored in SQLite.",
        )
    with status_columns[3]:
        metric_tile("Last success", last_refresh[:19] if last_refresh != "Never" else last_refresh, "UTC")

    fpl_service = st.session_state.get("fpl_ingestion_service")
    historical_service = st.session_state.get("historical_data_service")
    backtesting_service = st.session_state.get("backtesting_service")
    advanced_service = st.session_state.get("advanced_planner_service")
    provider_statuses = (
        advanced_service.provider_statuses() if advanced_service is not None else ()
    )
    fotmob_status = next(
        (status for status in provider_statuses if status.provider_id == "fotmob"),
        None,
    )
    backtest_status = (
        backtesting_service.get_status() if backtesting_service is not None else None
    )
    action_columns = st.columns(2)
    if fpl_service is not None:
        with action_columns[0]:
            refresh_fpl = st.button("Refresh official FPL data", type="primary")
        if refresh_fpl:
            try:
                with st.spinner("Fetching, validating, and saving official FPL data..."):
                    result = fpl_service.refresh()
                st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.success(
                    f"Refresh complete: {result.players} players, {result.teams} teams, "
                    f"{result.fixtures} fixtures."
                )
            except Exception:
                st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.error("Refresh failed. The last successful data remains available; see the latest error below.")

    if historical_service is not None:
        with action_columns[1]:
            import_history = st.button(
                "Import historical seasons",
                help="Download, validate, archive, and idempotently import the configured completed seasons.",
            )
        if import_history:
            try:
                with st.spinner("Importing historical seasons and calculating identity mappings..."):
                    result = historical_service.import_default_seasons()
                recommendation_service = st.session_state.get("recommendation_engine_service")
                if recommendation_service is not None:
                    recommendation_service.clear_cache()
                if fpl_service is not None:
                    st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.success(
                    f"Historical import complete: {result.seasons} seasons, {result.rows} rows, "
                    f"{result.matched} matched, {result.review} review, {result.scores} scores."
                )
            except Exception:
                st.error("Historical import failed validation. The previous dataset and scores remain safe.")

    if refresh_status.get("last_error"):
        st.warning(f"Last refresh error: {refresh_status['last_error']}")

    core_status = st.session_state.get("core_status", {})
    database_detail = "Schema not initialized"
    database_status = "Not ready"
    if core_status.get("database_ready"):
        database_status = "Ready"
        database_detail = (
            f"Schema v{core_status.get('schema_version')} · "
            f"{core_status.get('table_count')} tables"
        )

    section_heading(
        "Data coverage & pipeline readiness", "Phase 11",
        "Coverage makes missing cache rows explicit; player history remains an on-demand cache by design.",
    )
    readiness = pd.DataFrame(
        [
            ["Frontend shell", "Ready", "All planned MVP routes"],
            ["Official FPL API", "Ready", "Manual refresh with validation and retry"],
            ["FPL client", "Ready", "Timeout, retry, cache, and validation"],
            ["SQLite", database_status, database_detail],
            [
                "Current player stats",
                "Ready" if player_count and not missing_current_stats else "Coverage gap",
                f"{current_stats_count}/{player_count} rows · {missing_current_stats} missing",
            ],
            [
                "Gameweek snapshots",
                "Ready" if player_count and not missing_snapshots else "Coverage gap",
                f"{snapshot_count}/{player_count} rows · {missing_snapshots} missing",
            ],
            ["Fixture matrix", "Ready", "Official FDR scored across 1, 3, 5, and 8 GW"],
            [
                "Custom fixture difficulty",
                "Ready",
                "Official FDR + relative opponent strength + venue; comparison signal only",
            ],
            [
                "Recommendation Engine V1",
                "Ready" if expected_scores and not missing_scores else "Coverage gap",
                f"{score_count}/{expected_scores} persisted scores · {missing_scores} missing · {scoring.model_version}",
            ],
            [
                "Player gameweek history",
                "On demand",
                f"{ingestion_status.get('gameweek_history_in_database', 0)} rows across "
                f"{ingestion_status.get('history_synced_players_in_database', 0)}/{player_count} synced players",
            ],
            [
                "Feature engineering",
                "Ready",
                f"Rolling 3/5/10 · per-90 · minimum {scoring.minimum_minutes} minutes",
            ],
            [
                "Raw snapshot store",
                freshness,
                f"{freshness_detail} Last refresh: {last_refresh[:19] if last_refresh != 'Never' else last_refresh}",
            ],
            [
                "Historical dataset",
                "Ready" if ingestion_status.get("historical_seasons_in_database", 0) else "Not imported",
                f"{ingestion_status.get('historical_seasons_in_database', 0)} seasons · "
                f"{ingestion_status.get('historical_rows_in_database', 0)} validated player-season rows",
            ],
            [
                "Historical identity mapping",
                "Ready" if ingestion_status.get("historical_matched_in_database", 0) else "Waiting for import",
                f"{ingestion_status.get('historical_matched_in_database', 0)} matched · "
                f"{ingestion_status.get('historical_review_in_database', 0)} review · "
                f"{ingestion_status.get('historical_unmatched_in_database', 0)} unmatched",
            ],
            [
                "Historical stability score",
                "Ready" if ingestion_status.get("historical_scores_in_database", 0) else "Waiting for matches",
                f"{ingestion_status.get('historical_scores_in_database', 0)}/{player_count} current players scored · "
                "neutral 50 fallback for missing history",
            ],
            [
                "Time-safe backtest dataset",
                "Ready" if backtest_status and backtest_status.gameweek_rows else "Not imported",
                (
                    f"{backtest_status.gameweek_rows} player-fixture rows · "
                    f"{backtest_status.fixture_rows} fixtures"
                    if backtest_status
                    else "Backtesting service unavailable"
                ),
            ],
            [
                "Model calibration runs",
                "Ready" if backtest_status and backtest_status.runs else "Waiting for run",
                (
                    f"{backtest_status.runs} runs · {backtest_status.prediction_rows} persisted predictions"
                    if backtest_status
                    else "Backtesting service unavailable"
                ),
            ],
            [
                "Squad import & wildcard planner",
                "Ready" if advanced_service is not None else "Unavailable",
                "Public official picks · legal 15-player heuristic draft · session-only import",
            ],
            [
                "FotMob enrichment",
                fotmob_status.readiness if fotmob_status is not None else "Not configured",
                fotmob_status.detail if fotmob_status is not None else "Provider policy unavailable",
            ],
        ],
        columns=["Component", "Status", "Detail"],
    )
    st.dataframe(readiness, hide_index=True, width="stretch")

    if historical_service is not None and ingestion_status.get("historical_review_in_database", 0):
        with st.expander(
            f"Identity review queue ({ingestion_status.get('historical_review_in_database', 0)})"
        ):
            st.caption(
                "Only unresolved REVIEW candidates are excluded from scoring; unique matches above 90% and manually confirmed identity overrides are treated as MATCHED."
            )
            review_rows = historical_service.get_review_queue(limit=20)
            st.dataframe(
                pd.DataFrame([asdict(row) for row in review_rows]),
                hide_index=True,
                width="stretch",
                column_config={
                    "season": st.column_config.TextColumn("Season"),
                    "historical_name": st.column_config.TextColumn("Historical player"),
                    "position": st.column_config.TextColumn("Pos", width="small"),
                    "candidate_name": st.column_config.TextColumn("Current candidate"),
                    "match_score": st.column_config.ProgressColumn(
                        "Match confidence", min_value=0, max_value=100, format="%.0f%%"
                    ),
                    "match_method": st.column_config.TextColumn("Method"),
                },
            )

    section_heading("State preview", "UX validation utilities")
    preview = st.selectbox(
        "Preview application state", ["Normal", "Empty", "Error"],
        help="UX utility for previewing normal, empty, and error messaging states.",
    )
    if preview == "Normal":
        st.success("Official fixture cache and all frontend routes are available.")
    elif preview == "Empty":
        render_empty_state("No data available", "Refresh data or adjust the active filters.")
    else:
        st.error("Example error state: the last successful dataset would remain visible here.")

    with st.expander("Scoring configuration"):
        st.json(scoring.position_weights)


PAGE_RENDERERS: Dict[str, PageRenderer] = {
    "Dashboard": render_dashboard,
    "Players": render_players,
    "Recommendations": render_recommendations,
    "Fixtures": render_fixtures,
    "Player Detail": render_player_detail,
    "Compare": render_compare,
    "Backtesting": render_backtesting,
    "Decision Tools": render_decision_tools,
    "Advanced Planner": render_advanced_planner,
    "Data Status": render_data_status,
}
