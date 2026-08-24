"""Reusable Streamlit components for the frontend shell."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
from typing import Iterable, Mapping, Optional

import streamlit as st
import streamlit.components.v1 as streamlit_components

from config.settings import ScoringConfig


NAV_ITEMS = (
    "Dashboard",
    "Players",
    "Recommendations",
    "Fixtures",
    "Player Detail",
    "Compare",
    "Backtesting",
    "Decision Tools",
    "Advanced Planner",
    "Data Status",
)


@dataclass(frozen=True)
class FPLDeadline:
    """One upcoming official FPL gameweek deadline."""

    gameweek: int
    deadline_at: datetime


def next_fpl_deadline(
    events: Iterable[Mapping[str, object]],
    now: Optional[datetime] = None,
) -> Optional[FPLDeadline]:
    """Return FPL's flagged next event, or the nearest future deadline."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    candidates = []
    for event in events:
        deadline_value = event.get("deadline_time")
        try:
            gameweek = int(event["id"])
            deadline_at = datetime.fromisoformat(str(deadline_value).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if deadline_at.tzinfo is None:
            deadline_at = deadline_at.replace(tzinfo=timezone.utc)
        else:
            deadline_at = deadline_at.astimezone(timezone.utc)
        if deadline_at > current_time:
            candidates.append((bool(event.get("is_next")), FPLDeadline(gameweek, deadline_at)))

    if not candidates:
        return None
    flagged_next = [candidate for flagged, candidate in candidates if flagged]
    return min(flagged_next or [candidate for _, candidate in candidates], key=lambda item: item.deadline_at)


def deadline_countdown_markup(deadline: FPLDeadline) -> str:
    """Build a self-contained, second-by-second deadline header component."""
    deadline_iso = deadline.deadline_at.isoformat().replace("+00:00", "Z")
    return f"""
    <style>
      * {{ box-sizing: border-box; }}
      body {{ background: transparent; margin: 0; }}
      .deadline-banner {{
        align-items: center; background: linear-gradient(105deg, #19201f, #171523 70%);
        border: 1px solid rgba(24,245,155,.35); border-radius: 14px; color: #f7f6fb;
        display: flex; font-family: Inter, ui-sans-serif, system-ui, sans-serif; gap: 1rem;
        justify-content: space-between; min-height: 76px; overflow: hidden; padding: .8rem 1rem;
      }}
      .deadline-intro {{ min-width: 11rem; }}
      .deadline-label {{ color: #18f59b; font-size: .66rem; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }}
      .deadline-title {{ font-size: 1rem; font-weight: 850; margin-top: .2rem; }}
      .deadline-date {{ color: #aaa7b7; font-size: .72rem; margin-top: .15rem; }}
      .deadline-clock {{ display: flex; gap: .35rem; justify-content: flex-end; }}
      .deadline-unit {{ background: rgba(255,255,255,.055); border: 1px solid rgba(255,255,255,.1); border-radius: 9px; min-width: 3.7rem; padding: .32rem .45rem; text-align: center; }}
      .deadline-value {{ color: #18f59b; display: block; font-size: 1.18rem; font-weight: 900; font-variant-numeric: tabular-nums; line-height: 1; }}
      .deadline-unit span {{ color: #aaa7b7; display: block; font-size: .57rem; font-weight: 800; letter-spacing: .08em; margin-top: .22rem; text-transform: uppercase; }}
      @media (max-width: 640px) {{
        .deadline-banner {{ align-items: flex-start; flex-direction: column; gap: .6rem; }}
        .deadline-clock {{ justify-content: flex-start; width: 100%; }}
        .deadline-unit {{ flex: 1; min-width: 0; }}
      }}
    </style>
    <section class="deadline-banner" aria-label="Official FPL deadline countdown" data-deadline="{deadline_iso}">
      <div class="deadline-intro">
        <div class="deadline-label">Official FPL deadline</div>
        <div class="deadline-title">Gameweek {deadline.gameweek}</div>
        <div class="deadline-date" id="deadline-date">Loading deadline…</div>
      </div>
      <div class="deadline-clock" aria-live="polite">
        <div class="deadline-unit"><b class="deadline-value" id="deadline-days">00</b><span>Days</span></div>
        <div class="deadline-unit"><b class="deadline-value" id="deadline-hours">00</b><span>Hours</span></div>
        <div class="deadline-unit"><b class="deadline-value" id="deadline-minutes">00</b><span>Mins</span></div>
        <div class="deadline-unit"><b class="deadline-value" id="deadline-seconds">00</b><span>Secs</span></div>
      </div>
    </section>
    <script>
      const target = new Date({json.dumps(deadline_iso)});
      const units = {{
        days: document.getElementById("deadline-days"),
        hours: document.getElementById("deadline-hours"),
        minutes: document.getElementById("deadline-minutes"),
        seconds: document.getElementById("deadline-seconds"),
      }};
      document.getElementById("deadline-date").textContent = new Intl.DateTimeFormat(undefined, {{
        weekday: "short", day: "2-digit", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      }}).format(target);
      function tick() {{
        let remaining = Math.max(0, target.getTime() - Date.now());
        const days = Math.floor(remaining / 86400000);
        remaining -= days * 86400000;
        const hours = Math.floor(remaining / 3600000);
        remaining -= hours * 3600000;
        const minutes = Math.floor(remaining / 60000);
        remaining -= minutes * 60000;
        const seconds = Math.floor(remaining / 1000);
        units.days.textContent = String(days).padStart(2, "0");
        units.hours.textContent = String(hours).padStart(2, "0");
        units.minutes.textContent = String(minutes).padStart(2, "0");
        units.seconds.textContent = String(seconds).padStart(2, "0");
      }}
      tick();
      window.setInterval(tick, 1000);
    </script>
    """


def render_deadline_countdown(events: Iterable[Mapping[str, object]]) -> None:
    """Show the official deadline clock only when a future event is available."""
    deadline = next_fpl_deadline(events)
    if deadline is not None:
        streamlit_components.html(deadline_countdown_markup(deadline), height=84, scrolling=False)


def render_sidebar(scoring: ScoringConfig) -> str:
    """Render persistent navigation and return the selected page."""
    if "pending_navigation" in st.session_state:
        st.session_state["navigation"] = st.session_state.pop("pending_navigation")
    if "navigation" not in st.session_state:
        st.session_state["navigation"] = "Dashboard"

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">FPL <span>Analyst</span></div>'
            '<div class="sidebar-caption">Decisions backed by transparent signals</div>',
            unsafe_allow_html=True,
        )
        selected = st.radio(
            "Navigation", NAV_ITEMS, key="navigation", label_visibility="collapsed",
            help="Navigate between the official FPL analysis views.",
        )
        st.divider()
        st.caption("CURRENT CONTEXT")
        st.markdown(
            f"**Fixture horizon:** Next {scoring.default_horizon} GW  \n"
            f"**Model version:** {scoring.model_version}"
        )
        st.caption("All pages use the official FPL cache. Recommendation scores are calculated by the transparent v1 model.")
    return selected


def navigate_to(page: str) -> None:
    """Queue navigation before the sidebar widget is recreated on rerun."""
    if page not in NAV_ITEMS:
        raise ValueError(f"Unknown page: {page}")
    st.session_state["pending_navigation"] = page
    st.rerun()


def page_header(kicker: str, title: str, description: str) -> None:
    st.markdown(f'<div class="app-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="app-subtitle">{escape(description)}</div>', unsafe_allow_html=True)


def section_heading(title: str, detail: str = "", help_text: str | None = None) -> None:
    title_html = escape(title)
    if help_text:
        title_html = f'<span class="has-tooltip" title="{escape(help_text)}">{title_html}</span>'
    st.markdown(
        f'<div class="section-heading"><h3>{title_html}</h3><span>{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )


def metric_tile(label: str, value: str, detail: str, help_text: str | None = None) -> None:
    label_html = escape(label)
    if help_text:
        label_html = f'<span class="has-tooltip" title="{escape(help_text)}">{label_html}</span>'
    st.markdown(
        f"""
        <div class="metric-tile">
            <div class="metric-label">{label_html}</div>
            <div class="metric-value">{escape(value)}</div>
            <div class="metric-detail">{escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def wrapped_metric_card(label: str, value: str, detail: str, tone: str = "green") -> None:
    """Render a compact official-data highlight for Gameweek Wrapped."""
    st.markdown(
        f'''<div class="wrapped-metric wrapped-tone-{escape(tone)}">
            <div class="wrapped-metric-label">{escape(label)}</div>
            <strong>{escape(value)}</strong>
            <span>{escape(detail)}</span>
        </div>''',
        unsafe_allow_html=True,
    )


def wrapped_chip_card(name: str, uses: int) -> None:
    """Render a global chip-use highlight from the official event payload."""
    st.markdown(
        f'''<div class="wrapped-chip">
            <div class="wrapped-chip-label">{escape(name)}</div>
            <strong>{uses:,}</strong><span>managers played it</span>
        </div>''',
        unsafe_allow_html=True,
    )


def player_card(player: Mapping[str, object], label: str = "Recommendation") -> None:
    status = str(player["status"])
    status_html = f'<span class="status-dot"></span>{escape(status)}'
    if status != "Available":
        status_html = f'<span style="color:#ffcf5c">● {escape(status)}</span>'
    st.markdown(
        f"""
        <div class="player-card">
            <div class="card-label has-tooltip" title="Ranking category from the recommendation model">{escape(label)}</div>
            <div class="player-name has-tooltip" title="Official FPL player name">{escape(str(player['name']))}</div>
            <div class="card-meta has-tooltip" title="Official club, position, and current FPL price">{escape(str(player['team']))} · {escape(str(player['position']))} · £{float(player['price']):.1f}m</div>
            <div style="display:flex;justify-content:space-between;align-items:end;margin-top:1rem">
                <div><div class="score-number has-tooltip" title="Final recommendation score from 0 to 100">{int(player['recommendation'])}<small>/100</small></div><div class="card-meta">{status_html}</div></div>
                <div style="text-align:right"><strong class="has-tooltip" title="The team's nearest unstarted official fixture">{escape(str(player['next_fixture']))}</strong><div class="card-meta">Next fixture</div></div>
            </div>
            <div class="category">{escape(str(player['category']))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def fixture_strip(fixtures: Iterable[Mapping[str, object]]) -> None:
    pills = []
    for fixture in fixtures:
        fdr = int(fixture["fdr"])
        color = "#18f59b" if fdr <= 2 else "#ffcf5c" if fdr == 3 else "#ff7a90"
        pills.append(
            f'<div class="fixture-pill"><span>{escape(str(fixture["gameweek"]))}</span>'
            f'<strong>{escape(str(fixture["fixture"]))}</strong>'
            f'<span class="has-tooltip" title="Official Fixture Difficulty Rating: 1 is easiest, 5 is hardest; lower is easier" style="color:{color}">FDR {fdr}</span></div>'
        )
    st.markdown(f'<div class="fixture-strip">{"".join(pills)}</div>', unsafe_allow_html=True)


def squad_pitch(
    *,
    team_name: str,
    manager_name: str,
    gameweek: int,
    gameweek_points: int | None,
    gameweek_rank: int | None,
    picks: Iterable[Mapping[str, object]],
) -> None:
    """Render the imported official squad in a formation-first pitch layout."""
    # Markdown ends an HTML block at a blank line, which made every card after
    # the first one appear as literal ``<div>`` text. Keep it as one contiguous
    # fragment so Streamlit preserves both the full pitch height and all cards.
    markup = build_squad_pitch_markup(
        team_name=team_name,
        manager_name=manager_name,
        gameweek=gameweek,
        gameweek_points=gameweek_points,
        gameweek_rank=gameweek_rank,
        picks=picks,
    )
    st.markdown("".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def build_squad_pitch_markup(
    *,
    team_name: str,
    manager_name: str,
    gameweek: int,
    gameweek_points: int | None,
    gameweek_rank: int | None,
    picks: Iterable[Mapping[str, object]],
) -> str:
    """Build safe HTML for a squad view without relying on third-party imagery."""
    ordered = sorted(picks, key=lambda item: int(item["squad_position"]))
    starters = [item for item in ordered if int(item["multiplier"]) > 0]
    bench = [item for item in ordered if int(item["multiplier"]) == 0]
    counts = {
        position: sum(str(item["position"]) == position for item in starters)
        for position in ("GK", "DEF", "MID", "FWD")
    }
    formation = (
        f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
        if counts["GK"] == 1 and len(starters) == 11
        else f"{len(starters)} active players"
    )
    pitch_rows = "".join(
        _pitch_row(position, [item for item in starters if item["position"] == position])
        for position in ("GK", "DEF", "MID", "FWD")
    )
    bench_markup = "".join(_squad_player_markup(item, compact=True) for item in bench)
    points = str(gameweek_points) if gameweek_points is not None else "—"
    rank = f"{gameweek_rank:,}" if gameweek_rank is not None else "—"
    return f"""
        <section class="squad-visual" aria-label="Official FPL squad formation">
            <div class="squad-visual-header">
                <div>
                    <div class="card-label">Official current squad · GW {gameweek}</div>
                    <strong>{escape(team_name)}</strong>
                    <span>{escape(manager_name)} · Formation {formation}</span>
                </div>
                <div class="squad-visual-stats">
                    <div><b>{points}</b><span>GW points</span></div>
                    <div><b>{rank}</b><span>GW rank</span></div>
                </div>
            </div>
            <div class="fpl-pitch">
                {pitch_rows}
            </div>
            <div class="squad-bench-heading">Bench</div>
            <div class="squad-bench">{bench_markup}</div>
            <div class="squad-visual-note">Player layout, captaincy, points, and rank come from the official FPL picks response. Model score is shown separately for analysis.</div>
        </section>
    """


def _pitch_row(position: str, picks: list[Mapping[str, object]]) -> str:
    if not picks:
        return ""
    cards = "".join(_squad_player_markup(item) for item in picks)
    return f'<div class="pitch-row pitch-row-{position.lower()}">{cards}</div>'


def _squad_player_markup(item: Mapping[str, object], compact: bool = False) -> str:
    team = str(item["team"])
    player_name = str(item["name"])
    position = str(item["position"])
    model_score = float(item["model_score"])
    gameweek_points = item.get("gameweek_points")
    points_multiplier = int(item.get("points_multiplier", 1))
    tags = []
    if bool(item.get("is_captain")):
        tags.append('<span class="squad-tag">C</span>')
    if bool(item.get("is_vice_captain")):
        tags.append('<span class="squad-tag squad-tag-vice">VC</span>')
    team_code = "".join(part[0] for part in team.split()[:3]).upper() or "FPL"
    color = _club_color(team)
    compact_class = " squad-player-compact" if compact else ""
    if gameweek_points is None:
        points_markup = '<span class="squad-gameweek-points">GW points <b>—</b></span>'
    else:
        raw_points = int(gameweek_points)
        displayed_points = raw_points * points_multiplier if points_multiplier > 0 else raw_points
        multiplier_note = f' <em>×{points_multiplier}</em>' if points_multiplier > 1 else ""
        points_markup = (
            f'<span class="squad-gameweek-points">GW points <b>{displayed_points}</b>{multiplier_note}</span>'
        )
    return f"""
        <div class="squad-player{compact_class}" style="--club-color:{color}">
            <div class="squad-player-top"><span class="club-mark">{escape(team_code)}</span>{''.join(tags)}</div>
            <strong>{escape(player_name)}</strong>
            <span>{escape(position)} · Model {model_score:.0f}</span>
            {points_markup}
        </div>
    """


def _club_color(team: str) -> str:
    palette = ("#18f59b", "#7c5cff", "#54b8ff", "#ff6f91", "#ffcf5c", "#ff8b5c")
    return palette[sum(ord(character) for character in team) % len(palette)]


def render_empty_state(title: str, detail: str) -> None:
    st.info(f"{title} — {detail}")


def render_action_state(title: str, detail: str) -> None:
    """Render an actionable empty state using the primary button color."""
    st.markdown(
        f'<div class="action-state"><strong>{escape(title)}</strong><span>{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )
