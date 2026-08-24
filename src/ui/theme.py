"""Visual theme for the FPL Analyst Streamlit shell."""

from __future__ import annotations

import streamlit as st


def apply_theme() -> None:
    """Apply a compact dark FPL-inspired design system."""
    st.markdown(
        """
        <style>
        :root {
            --ink: #f7f7fb;
            --muted: #a8a6b8;
            --surface: #181622;
            --border: rgba(255,255,255,.09);
            --green: #18f59b;
            --amber: #ffcf5c;
        }
        .stApp {
            background:
                radial-gradient(circle at 85% 0%, rgba(124,58,237,.16), transparent 30rem),
                radial-gradient(circle at 15% 100%, rgba(24,245,155,.07), transparent 32rem),
                #0e0d14;
            color: var(--ink);
        }
        [data-testid="stSidebar"] {
            background: #13111b;
            border-right: 1px solid var(--border);
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #d9d7e3; }
        /* Keep the first page-header line below Streamlit's floating toolbar. */
        [data-testid="stAppViewContainer"] .main .block-container {
            max-width: 1320px;
            padding-top: 4.75rem;
            padding-bottom: 3rem;
        }
        .app-kicker {
            color: var(--green); font-size: .74rem; font-weight: 800;
            letter-spacing: .13em; text-transform: uppercase; margin-bottom: .35rem;
            display: block;
            line-height: 1.35;
            min-height: 1rem;
            overflow: visible;
            position: relative;
            z-index: 1;
        }
        h1, h2, h3 { letter-spacing: -.025em; }
        .app-subtitle {
            color: var(--muted); max-width: 760px; margin-top: -.45rem; margin-bottom: 1.35rem;
        }
        .sample-banner {
            align-items: center;
            background: linear-gradient(90deg, rgba(124,58,237,.24), rgba(24,245,155,.10));
            border: 1px solid rgba(124,58,237,.35); border-radius: 14px; color: #e8e4f5;
            display: flex; font-size: .86rem; justify-content: space-between;
            margin-bottom: 1.4rem; padding: .8rem 1rem;
        }
        .sample-chip {
            background: var(--green); border-radius: 999px; color: #08110d;
            font-size: .67rem; font-weight: 900; letter-spacing: .08em;
            padding: .28rem .55rem; text-transform: uppercase; white-space: nowrap;
        }
        .metric-tile, .player-card {
            background: linear-gradient(145deg, rgba(34,31,46,.96), rgba(23,21,32,.96));
            border: 1px solid var(--border); border-radius: 16px;
            min-height: 100%; padding: 1rem 1.05rem;
        }
        .wrapped-metric, .wrapped-chip {
            background: linear-gradient(145deg, rgba(34,31,46,.96), rgba(23,21,32,.96));
            border: 1px solid var(--border); border-radius: 15px; min-height: 8.2rem;
            padding: .95rem 1rem; position: relative; overflow: hidden;
        }
        .wrapped-metric::before {
            background: var(--wrapped-tone, var(--green)); border-radius: 999px;
            content: ""; height: .48rem; left: 1rem; position: absolute; top: .78rem; width: .48rem;
        }
        .wrapped-metric-label { color: var(--muted); font-size: .69rem; font-weight: 850; letter-spacing: .075em; margin-left: .78rem; text-transform: uppercase; }
        .wrapped-metric strong { display: block; font-size: 1.07rem; line-height: 1.15; margin: 1.15rem 0 .35rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .wrapped-metric span, .wrapped-chip span { color: var(--muted); display: block; font-size: .78rem; }
        .wrapped-tone-green { --wrapped-tone: #18f59b; }
        .wrapped-tone-purple { --wrapped-tone: #a78bfa; }
        .wrapped-tone-amber { --wrapped-tone: #ffcf5c; }
        .wrapped-tone-blue { --wrapped-tone: #5aa7ff; }
        .wrapped-tone-orange { --wrapped-tone: #ff9254; }
        .wrapped-tone-red { --wrapped-tone: #ff7a90; }
        .wrapped-chip { background: linear-gradient(125deg, rgba(68,13,112,.92), rgba(25,17,54,.96)); border-color: rgba(167,139,250,.34); min-height: 6.9rem; }
        .wrapped-chip-label { color: #ddd3ff; font-size: .75rem; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; }
        .wrapped-chip strong { color: var(--green); display: block; font-size: 1.65rem; line-height: 1.1; margin: .85rem 0 .12rem; }
        .metric-label, .card-label {
            color: var(--muted); font-size: .71rem; font-weight: 800;
            letter-spacing: .08em; text-transform: uppercase;
        }
        .has-tooltip {
            cursor: help; position: relative;
            text-decoration: underline dotted rgba(168,166,184,.65);
            text-underline-offset: 3px;
        }
        .has-tooltip::after {
            background: #272334; border: 1px solid rgba(24,245,155,.45);
            border-radius: 8px; box-shadow: 0 10px 24px rgba(0,0,0,.35);
            color: #f7f7fb; content: attr(title); font-size: .76rem;
            font-weight: 500; letter-spacing: 0; line-height: 1.35;
            max-width: 280px; opacity: 0; padding: .55rem .7rem;
            left: 0; pointer-events: none; position: absolute; text-align: left;
            text-transform: none; transform: translateY(4px);
            top: calc(100% + 8px); transition: opacity .12s ease, transform .12s ease;
            visibility: hidden; white-space: normal; width: max-content; z-index: 30;
        }
        .has-tooltip:hover::after {
            opacity: 1; transform: translateY(0); visibility: visible;
        }
        .metric-label .has-tooltip::after { left: 0; top: calc(100% + 8px); }
        .section-heading h3 .has-tooltip::after { left: 0; top: calc(100% + 8px); }
        .metric-value { color: var(--ink); font-size: 1.7rem; font-weight: 800; margin: .18rem 0 .05rem; }
        .metric-detail, .card-meta { color: var(--muted); font-size: .82rem; }
        .player-name { color: var(--ink); font-size: 1.05rem; font-weight: 750; margin-top: .35rem; }
        .score-number { color: var(--green); font-size: 2rem; font-weight: 850; line-height: 1; }
        .score-number small { color: var(--muted); font-size: .7rem; }
        .status-dot {
            background: var(--green); border-radius: 50%; display: inline-block;
            height: .45rem; margin-right: .35rem; width: .45rem;
        }
        .category {
            background: rgba(24,245,155,.10); border: 1px solid rgba(24,245,155,.25);
            border-radius: 999px; color: var(--green); display: inline-block;
            font-size: .68rem; font-weight: 800; margin-top: .65rem; padding: .25rem .55rem;
        }
        .fixture-strip {
            display: grid; gap: .45rem; grid-template-columns: repeat(5, minmax(80px,1fr));
            margin-top: .75rem;
        }
        .fixture-pill {
            background: rgba(255,255,255,.04); border: 1px solid var(--border);
            border-radius: 10px; padding: .55rem .4rem; text-align: center;
        }
        .fixture-pill strong { display: block; font-size: .82rem; }
        .fixture-pill span { color: var(--muted); font-size: .68rem; }
        .squad-visual {
            background: linear-gradient(145deg, rgba(27,25,39,.96), rgba(17,28,30,.96));
            border: 1px solid var(--border); border-radius: 18px; margin: 1rem 0 1.35rem;
            overflow: hidden;
        }
        .squad-visual-header {
            align-items: center; display: flex; gap: 1rem; justify-content: space-between;
            padding: 1rem 1.15rem;
        }
        .squad-visual-header strong { display: block; font-size: 1.3rem; line-height: 1.2; margin: .18rem 0; }
        .squad-visual-header > div > span { color: var(--muted); font-size: .8rem; }
        .squad-visual-stats { display: flex; gap: .55rem; }
        .squad-visual-stats > div {
            background: rgba(255,255,255,.05); border: 1px solid var(--border); border-radius: 10px;
            min-width: 5.75rem; padding: .45rem .65rem; text-align: center;
        }
        .squad-visual-stats b { color: var(--green); display: block; font-size: 1.05rem; }
        .squad-visual-stats span { color: var(--muted); font-size: .68rem; }
        .fpl-pitch {
            background:
                linear-gradient(90deg, transparent 49.7%, rgba(255,255,255,.22) 49.8%, rgba(255,255,255,.22) 50.2%, transparent 50.3%),
                linear-gradient(180deg, transparent 49.7%, rgba(255,255,255,.22) 49.8%, rgba(255,255,255,.22) 50.2%, transparent 50.3%),
                radial-gradient(ellipse at 50% 50%, transparent 0 16%, rgba(255,255,255,.2) 16.2% 16.8%, transparent 17%),
                repeating-linear-gradient(0deg, rgba(255,255,255,.045) 0, rgba(255,255,255,.045) 3.5rem, rgba(0,0,0,.04) 3.5rem, rgba(0,0,0,.04) 7rem),
                linear-gradient(145deg, #116c52, #10955f 52%, #08714b);
            border-bottom: 1px solid rgba(255,255,255,.18); border-top: 1px solid rgba(255,255,255,.18);
            display: flex; flex-direction: column; gap: .65rem; min-height: 29rem;
            justify-content: space-around; padding: 1rem;
        }
        .pitch-row { display: flex; gap: .65rem; justify-content: center; }
        .pitch-row .squad-player { flex: 0 1 145px; width: min(145px, 100%); }
        .pitch-row-gk { margin: 0 auto; max-width: 140px; width: 100%; }
        .squad-player {
            background: rgba(12,24,26,.78); border: 1px solid rgba(255,255,255,.28);
            border-bottom: 3px solid var(--club-color); border-radius: 10px;
            box-shadow: 0 8px 16px rgba(0,0,0,.18); min-width: 0; padding: .48rem .55rem;
            text-align: center;
        }
        .squad-player-top { align-items: center; display: flex; gap: .25rem; justify-content: space-between; min-height: 1rem; }
        .club-mark { color: var(--club-color); font-size: .62rem; font-weight: 900; letter-spacing: .08em; }
        .squad-tag { background: var(--green); border-radius: 999px; color: #07110d; font-size: .6rem; font-weight: 900; padding: .12rem .3rem; }
        .squad-tag-vice { background: var(--amber); }
        .squad-player strong { display: block; font-size: .86rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .squad-player > span { color: #d5d2df; display: block; font-size: .67rem; margin-top: .12rem; }
        .squad-player .squad-gameweek-points {
            align-items: baseline; color: #aeadbc; display: flex; font-size: .63rem;
            justify-content: center; gap: .25rem; margin-top: .32rem;
        }
        .squad-player .squad-gameweek-points b { color: #fff; font-size: .82rem; }
        .squad-player .squad-gameweek-points em { color: var(--green); font-size: .61rem; font-style: normal; font-weight: 850; }
        .squad-bench-heading { color: var(--muted); font-size: .73rem; font-weight: 850; letter-spacing: .1em; padding: .8rem 1.15rem .45rem; text-transform: uppercase; }
        .squad-bench { display: grid; gap: .65rem; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 0 1.15rem 1rem; }
        .squad-player-compact { background: rgba(255,255,255,.04); }
        .squad-visual-note { border-top: 1px solid var(--border); color: var(--muted); font-size: .72rem; line-height: 1.4; padding: .7rem 1.15rem; }
        .section-heading {
            align-items: baseline; display: flex; justify-content: space-between; margin: 1.6rem 0 .75rem;
        }
        .section-heading h3 { margin: 0; }
        .section-heading > span { color: var(--muted); font-size: .78rem; }
        .sidebar-brand {
            color: white; font-size: 1.3rem; font-weight: 850;
            letter-spacing: -.03em; margin-bottom: .1rem;
        }
        .sidebar-brand span { color: var(--green); }
        .sidebar-caption { color: var(--muted); font-size: .76rem; margin-bottom: 1rem; }
        .app-footer {
            border-top: 1px solid var(--border); color: #777487; font-size: .72rem;
            margin-top: 2.5rem; padding-top: 1rem; text-align: center;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--border); border-radius: 14px;
            overflow-x: auto; overflow-y: hidden;
            -webkit-overflow-scrolling: touch;
        }
        div[data-testid="stMetric"] {
            background: rgba(31,29,42,.75); border: 1px solid var(--border);
            border-radius: 14px; padding: .75rem 1rem;
        }
        .stButton > button { border-radius: 10px; font-weight: 700; }
        .action-state {
            background: var(--green); border-radius: 12px; color: #08110d;
            display: flex; flex-direction: column; gap: .2rem; margin: .8rem 0;
            padding: .8rem 1rem;
        }
        .action-state strong { font-size: .95rem; }
        .action-state span { font-size: .86rem; }
        @media (max-width: 1024px) {
            [data-testid="stAppViewContainer"] .main .block-container {
                max-width: none;
                padding-left: 1.25rem;
                padding-right: 1.25rem;
            }
            [data-testid="stAppViewContainer"] .main [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
                gap: .8rem;
            }
            [data-testid="stAppViewContainer"] .main [data-testid="column"] {
                flex: 1 1 220px !important;
                min-width: 0 !important;
            }
        }
        @media (max-width: 760px) {
            [data-testid="stAppViewContainer"] .main .block-container {
                padding: 4.25rem 1rem 2rem;
            }
            [data-testid="stAppViewContainer"] .main [data-testid="stHorizontalBlock"] {
                flex-direction: column;
                flex-wrap: nowrap;
                gap: .75rem;
            }
            [data-testid="stAppViewContainer"] .main [data-testid="column"] {
                flex: 1 1 auto !important;
                width: 100% !important;
            }
            h1 { font-size: clamp(2rem, 9vw, 2.55rem); line-height: 1.08; }
            h2 { font-size: 1.65rem; }
            h3 { font-size: 1.35rem; }
            .app-kicker { font-size: .68rem; letter-spacing: .1em; }
            .app-subtitle { font-size: .95rem; margin-bottom: 1rem; margin-top: -.2rem; }
            .section-heading {
                align-items: flex-start;
                flex-direction: column;
                gap: .3rem;
                margin: 1.3rem 0 .7rem;
            }
            .section-heading > span { font-size: .74rem; }
            .fixture-strip { grid-template-columns: repeat(2, 1fr); }
            .sample-banner { align-items: flex-start; flex-direction: column; gap: .55rem; }
            .metric-tile, .player-card { padding: .9rem; }
            .wrapped-metric, .wrapped-chip { min-height: 0; }
            .metric-value { font-size: 1.55rem; }
            .player-card > div[style*="display:flex"] {
                align-items: flex-start !important;
                flex-wrap: wrap;
                gap: .75rem;
            }
            .player-card > div[style*="display:flex"] > div:last-child { text-align: left !important; }
            .app-footer { font-size: .7rem; line-height: 1.5; margin-top: 1.75rem; }
            .stButton > button { min-height: 2.75rem; width: 100%; }
            .squad-visual-header { align-items: flex-start; flex-direction: column; }
            .squad-visual-stats { width: 100%; }
            .squad-visual-stats > div { flex: 1; }
            .fpl-pitch { min-height: 0; padding: .75rem; }
            .pitch-row { grid-template-columns: repeat(auto-fit, minmax(95px, 1fr)); }
            .squad-bench { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 0 .75rem .8rem; }
            .squad-bench-heading, .squad-visual-note { padding-left: .75rem; padding-right: .75rem; }
        }
        @media (max-width: 420px) {
            .fixture-strip { grid-template-columns: 1fr; }
            [data-testid="stAppViewContainer"] .main .block-container { padding-left: .85rem; padding-right: .85rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
