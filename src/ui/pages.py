"""Page renderers for the Phase 1 Streamlit frontend shell."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
from typing import Callable, Dict

import pandas as pd
import streamlit as st

from config.settings import ScoringConfig
from src.services.advanced_planner import ImportedSquad
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
from src.services.chip_strategy import get_chip_strategy_service
from src.services.gameweek_wrapped import build_gameweek_wrapped, previous_completed_gameweek
from src.services.league_analytics import get_league_analytics_service
from src.services.squad_schedule_exposure import calculate_squad_schedule_exposure
from src.services.schedule_backtesting import current_team_priority_adjustments
from src.services.set_piece_insights import SetPieceInsightsService
from src.features.recommendation import METRIC_LABELS
from src.ui.schedule_risk import (
    build_congestion_leader_rows,
    build_risk_strip_rows,
    build_squad_exposure_rows,
    build_team_risk_matrix,
    risk_status_help,
)


PageRenderer = Callable[[pd.DataFrame, pd.DataFrame, ScoringConfig], None]


ATTRIBUTE_HELP = {
    "position": "Posisi resmi FPL pemain yang digunakan untuk perankingan persentil berbasis posisi.",
    "price": "Harga resmi pemain FPL saat ini dalam jutaan poundsterling.",
    "ownership": "Persentase manajer FPL yang memiliki pemain ini saat ini.",
    "transfers_in_event": "Jumlah transfer masuk untuk Gameweek berjalan dari data resmi FPL. Mengukur tren manajer, bukan proyeksi poin mutlak.",
    "minutes": "Jumlah menit bermain pada snapshot statistik resmi FPL terkini.",
    "form": "Sinyal form resmi FPL berdasarkan rata-rata poin di beberapa laga terakhir.",
    "confidence": "Tingkat reliabilitas data; mencapai 100% jika pemain telah memenuhi batas minimal menit bermain.",
    "score": "Skor akhir rekomendasi dari 0 hingga 100.",
    "fixture_score": "Skor kemudahan fixture berbobot horizon (0-100); semakin tinggi semakin bersahabat jadwalnya.",
    "expected": "Skor komponen expected output (xGI/xG/xA) relatif terhadap posisi.",
    "history": "Skor stabilitas lintas musim dari data histori resmi; bernilai netral 50 jika histori belum tersedia.",
    "value": "Komponen nilai ekonomis berdasarkan poin per match (PPM) dibandingkan dengan harga pemain.",
    "minutes_score": "Skor jaminan menit bermain berdasarkan konsistensi waktu tampil di lapangan.",
    "fdr": "Fixture Difficulty Rating resmi FPL: 1 paling mudah, 5 paling berat.",
    "custom_fdr": "Indeks kesulitan 1–5 internal yang menggabungkan FDR resmi, kekuatan relatif lawan, dan laga kandang/tandang.",
    "mae": "Mean Absolute Error antara skor rekomendasi dan persentil poin aktual masa depan; semakin rendah semakin baik.",
    "spearman": "Korelasi peringkat rata-rata antara skor rekomendasi dan perolehan poin FPL berikutnya; semakin tinggi semakin akurat.",
    "top_10_hit": "Persentase kesesuaian antara prediksi 10 pemain teratas dan daftar 10 pemain terbaik aktual.",
    "top_10_points": "Rata-rata poin FPL aktual yang diraih oleh 10 pemain peringkat teratas di setiap cutoff.",
    "model_lift": "Peningkatan skor rekomendasi (0–100) dari pemain yang dilepas ke pemain yang direkrut.",
    "fixture_lift": "Perubahan skor kemudahan fixture untuk horizon terpilih. Nilai positif berarti jadwal pemain masuk lebih menguntungkan.",
    "minutes_lift": "Perubahan skor jaminan menit bermain. Nilai positif berarti pemain masuk lebih terjamin bermain reguler.",
    "price_change": "Selisih harga pemain masuk dibanding pemain keluar. Positif memakan dana bank; negatif menambah tabungan.",
    "schedule_blank": "Paparan Gameweek kosong (blank). Status terkonfirmasi strictly mengikuti alokasi jadwal resmi FPL.",
    "schedule_double": "Paparan Double Gameweek. Terkonfirmasi berarti FPL menjadwalkan minimal 2 laga untuk tim tersebut di GW terkait.",
    "schedule_congestion": "Indikator beban kerja 14 hari ke depan dari kepadatan jadwal, waktu istirahat, perjalanan, dan fase kompetisi.",
    "brier": "Mean squared error prakiraan probabilitas terhadap hasil biner 0/1. 0 sempurna; semakin rendah semakin bagus.",
    "calibration_error": "Selisih berbobot antara rata-rata probabilitas prediksi dan frekuensi kejadian riil. Semakin rendah semakin baik.",
    "set_piece_signal": "Sinyal peran eksekutor bola mati: penalti, tendangan bebas langsung, dan sepak pojok. Bersifat indikasi peran, bukan jaminan poin.",
    "historical_set_piece_goals": "Total gol set-piece tim di musim historis yang dicatat. Memberikan konteks klub daripada poin individu.",
}


RANKING_METRIC_HELP = {
    "fixture": "Jadwal resmi mendatang dikonversi menjadi skor kemudahan berbobot horizon. Semakin tinggi semakin mudah dan digunakan dalam peringkat aktif.",
    "minutes": "Menit bermain yang sudah dijalani relatif terhadap total menit Gameweek. Nilai lebih tinggi berarti menit bermain lebih aman.",
    "saves": "Total save resmi FPL, diperingkatkan antar kiper dan disesuaikan dengan volume menit bermain. Semakin tinggi semakin baik.",
    "history": "Skor stabilitas performa lintas musim (0–100). Nilai 50 adalah netral jika histori belum tersedia.",
    "bonus": "Total poin bonus resmi FPL, dinormalisasi per posisi dan disesuaikan dengan volume menit bermain.",
    "form": "Form terkini resmi FPL, dinormalisasi per posisi dan disesuaikan dengan volume menit bermain.",
    "value": "Poin per laga resmi dibagi harga FPL saat ini, dinormalisasi per posisi dan disesuaikan dengan volume menit bermain.",
    "attacking_output": "Ekspektasi keterlibatan gol (xGI) resmi dibagi menit × 90, dinormalisasi per posisi dan disesuaikan keandalan menit.",
    "xg": "Expected goals (xG) resmi dibagi menit × 90, dinormalisasi per posisi dan disesuaikan keandalan menit.",
    "xgi": "Expected goal involvements (xGI) resmi dibagi menit × 90, dinormalisasi per posisi dan disesuaikan keandalan menit.",
    "ppm": "Poin per match (PPM) resmi FPL, dinormalisasi per posisi dan disesuaikan keandalan menit.",
    "ict": "ICT Index resmi dibagi menit × 90, dinormalisasi per posisi dan disesuaikan keandalan menit.",
}


POSITIONAL_SIGNAL_FORMULAS = {
    "minutes_played": "Total menit bermain resmi FPL musim ini.",
    "xgc_per_90": "Expected goals conceded resmi ÷ menit × 90.",
    "saves_per_90": "Total save resmi ÷ menit × 90.",
    "clean_sheet_rate": "Clean sheet resmi ÷ jumlah starter resmi. Tidak tersedia bila belum pernah starter.",
    "goals_conceded_per_90": "Kebobolan resmi ÷ menit × 90.",
    "penalties_saved": "Total penalti yang berhasil diselamatkan kiper.",
    "penalties_missed": "Total penalti yang gagal dieksekusi.",
    "defensive_contribution_per_90": "Kontribusi bertahan resmi FPL ÷ menit × 90.",
    "xg_per_90": "Expected goals (xG) resmi ÷ menit × 90.",
    "xa_per_90": "Expected assists (xA) resmi ÷ menit × 90.",
    "xgi_per_90": "Expected goal involvements (xGI) resmi ÷ menit × 90.",
    "goals_per_90": "Gol resmi FPL ÷ menit × 90.",
    "assists_per_90": "Assist resmi FPL ÷ menit × 90.",
    "conversion_rate": "Gol ÷ xG, disesuaikan dengan prior posisi untuk meredam anomali sampel kecil.",
    "yellow_cards": "Total kartu kuning resmi FPL.",
    "red_cards": "Total kartu merah resmi FPL.",
    "discipline_risk_per_90": "(Kartu kuning + 3 × kartu merah) ÷ menit × 90.",
    "bonus_points": "Total poin bonus resmi FPL.",
    "bps": "Total Bonus Point System (BPS) resmi FPL.",
    "influence_per_90": "Influence resmi FPL ÷ menit × 90.",
    "creativity_per_90": "Creativity resmi FPL ÷ menit × 90.",
    "threat_per_90": "Threat resmi FPL ÷ menit × 90.",
    "ict_per_90": "ICT Index resmi FPL ÷ menit × 90.",
}


def _signal_value_display(signal: object) -> str:
    """Format an official positional signal without turning missing data into zero."""
    raw_value = getattr(signal, "raw_value")
    if raw_value is None:
        return "Belum tersedia"
    key = getattr(signal, "key")
    if key in {"clean_sheet_rate", "conversion_rate"}:
        return f"{float(raw_value) * 100:.1f}%"
    if key.endswith("_per_90"):
        return f"{float(raw_value):.2f}"
    return f"{float(raw_value):.0f}" if float(raw_value).is_integer() else f"{float(raw_value):.2f}"


def _signal_help(signal: object, freshness_label: str, freshness_detail: str) -> str:
    """Tooltip copy for every official-season evidence metric."""
    key = getattr(signal, "key")
    direction = getattr(signal, "direction")
    rank_status = (
        "Digunakan dalam perhitungan peringkat aktif."
        if getattr(signal, "used_in_ranking")
        else "Hanya konteks data resmi; tidak mempengaruhi kalkulasi peringkat aktif."
    )
    direction_label = "Semakin tinggi semakin bagus" if direction == "higher_is_better" else "Semakin rendah semakin bagus"
    formula = POSITIONAL_SIGNAL_FORMULAS.get(key, "Statistik resmi FPL musim berjalan.")
    return (
        f"Rumus: {formula} ({direction_label}). {rank_status} "
        f"Sumber: snapshot bootstrap-static resmi FPL musim ini. "
        f"Status: {freshness_label}. {freshness_detail}"
    )


def _status_label(status: str) -> str:
    return {
        "a": "Tersedia",
        "d": "Meragukan",
        "i": "Cedera",
        "s": "Hukuman Kartu",
        "u": "Tidak Tersedia",
        "n": "Tidak Tersedia",
    }.get(status, "Tidak Diketahui")


def _freshness_label(timestamp: str | None) -> tuple[str, str]:
    """Return a short, human-friendly freshness state for an ISO timestamp."""
    if not timestamp:
        return "Tidak Diketahui", "Belum ada riwayat pembaruan resmi yang tercatat."
    try:
        refreshed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "Tidak Diketahui", "Format waktu pembaruan terakhir tidak valid."

    age_minutes = max(0, int((datetime.now(timezone.utc) - refreshed_at).total_seconds() // 60))
    if age_minutes < 2:
        return "Terbaru", "Diperbarui kurang dari 2 menit lalu."
    if age_minutes < 60:
        return "Terbaru", f"Diperbarui {age_minutes} menit lalu."
    if age_minutes < 24 * 60:
        return "Cukup Baru", f"Diperbarui {age_minutes // 60} jam lalu."
    return "Kedaluwarsa", f"Diperbarui {age_minutes // (24 * 60)} hari lalu. Segarkan data untuk analisis terkini."


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
        "Workspace Gameweek",
        "Keputusan tepat dimulai dari konteks.",
        "Peringkat resmi, pergeseran fixture, differential, dan jaminan menit bermain dalam satu ringkasan.",
    )
    service = st.session_state.get("recommendation_engine_service")
    fixture_service = st.session_state.get("fixture_analytics_service")
    if service is None or fixture_service is None:
        render_empty_state("Analisis belum tersedia", "Buka ulang aplikasi untuk menginisialisasi layanan.")
        return
    rankings = service.get_rankings(horizon=scoring.default_horizon)
    if not rankings:
        render_empty_state("Data peringkat belum tersedia", "Silakan refresh data resmi FPL dari menu Data Status.")
        return

    top = rankings[0]
    differential_count = sum(row.ownership < 10 and row.final_score >= 56 for row in rankings)
    safe_minutes = sum(row.minutes_score >= 85 for row in rankings)
    current_gameweek = service.ingestion.status_store.load().current_gameweek or 0
    cols = st.columns(4)
    with cols[0]:
        metric_tile(
            "Gameweek Saat Ini", f"GW {current_gameweek}", "Konteks resmi FPL",
            "Gameweek berjalan atau pekan terdekat yang dibaca langsung dari server resmi FPL.",
        )
    with cols[1]:
        metric_tile(
            "Target Utama", top.name, f"Skor {top.final_score:.0f}",
            ATTRIBUTE_HELP["score"],
        )
    with cols[2]:
        metric_tile(
            "Differential", str(differential_count), "Ownership <10% · Pantauan+",
            "Pemain dengan kepemilikan di bawah 10% yang memiliki skor rekomendasi menjanjikan.",
        )
    with cols[3]:
        metric_tile(
            "Jaminan Menit Bermain", str(safe_minutes), "Skor menit minimal 85",
            "Pemain reguler yang memiliki kepastian starter dan menit bermain konsisten.",
        )

    section_heading(
        "Rekomendasi Teratas",
        f"Semua posisi · {scoring.default_horizon} GW ke depan · Model {scoring.model_version}",
        "Skor akhir tertinggi setelah normalisasi posisi, penyesuaian reliabilitas data, dan status ketersediaan pemain.",
    )
    top_three = rankings[:3]
    card_columns = st.columns(3)
    for column, player in zip(card_columns, top_three):
        with column:
            player_card(_player_card_data(player))

    if st.button("Jelajahi seluruh rekomendasi →", type="primary"):
        navigate_to("Recommendations")

    _render_market_pulse(rankings, current_gameweek)
    _render_gameweek_wrapped()

    left, right = st.columns([1.2, 1])
    with left:
        section_heading(
            "Radar Fixture", "Tingkat kemudahan jadwal berbobot horizon",
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
                "team": st.column_config.TextColumn("Klub"),
                "fixture_score": st.column_config.ProgressColumn(
                    "Skor Fixture", min_value=0, max_value=100, format="%.0f",
                    help=ATTRIBUTE_HELP["fixture_score"],
                ),
            },
        )
    with right:
        section_heading(
            "Pemimpin Sinyal", "Overall · Nilai Ekonomis · Differential",
            "Pilihan terbaik berdasarkan skor akhir, value for money, dan kepemilikan rendah.",
        )
        value_leader = max(rankings, key=lambda row: row.value_score)
        differential_pool = [row for row in rankings if row.ownership < 10]
        differential = differential_pool[0] if differential_pool else rankings[0]
        for label, candidate in (
            ("Overall", top),
            ("Nilai Ekonomis", value_leader),
            ("Differential", differential),
        ):
            st.markdown(
                f"**{label}** · {candidate.name}  \n"
                f"{candidate.team} · Skor **{candidate.final_score:.0f}** · {candidate.reason}"
            )


def _render_market_pulse(rankings: tuple[object, ...], current_gameweek: int) -> None:
    """Show official FPL transfer demand separately from FPL Signal rankings."""
    section_heading(
        "Pergerakan Pasar",
        f"Transfer masuk terbanyak di GW {current_gameweek} · Tren resmi FPL",
        "Aktivitas transfer menunjukkan pergerakan manajer FPL secara umum, bukan prediksi poin mutlak.",
    )
    market_rows = sorted(
        (row for row in rankings if row.transfers_in_event > 0),
        key=lambda row: (row.transfers_in_event, row.final_score),
        reverse=True,
    )[:5]
    if not market_rows:
        st.info("Aktivitas transfer akan muncul setelah sinkronisasi data resmi FPL berikutnya.")
        return

    _CAT_MAP = {
        "Elite Target": "Target Unggulan",
        "Strong Buy": "Prioritas Beli",
        "Good Option": "Pilihan Bagus",
        "Watchlist": "Masuk Pantauan",
        "Neutral": "Netral",
        "Avoid": "Hindari",
    }

    market_frame = pd.DataFrame(
        [
            {
                "Pemain": row.name,
                "Klub": row.team,
                "Pos": row.position,
                "Transfer Masuk": row.transfers_in_event,
                "Skor Model": row.final_score,
                "Kategori": _CAT_MAP.get(str(row.category), str(row.category)),
            }
            for row in market_rows
        ]
    )
    st.dataframe(
        market_frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Transfer Masuk": st.column_config.NumberColumn(
                "Transfer Masuk", format="%,d", help=ATTRIBUTE_HELP["transfers_in_event"]
            ),
            "Skor Model": st.column_config.ProgressColumn(
                "Skor Model", min_value=0, max_value=100, format="%.0f", help=ATTRIBUTE_HELP["score"]
            ),
            "Kategori": st.column_config.TextColumn("Kategori"),
        },
    )
    if st.button("Lihat aktivitas transfer lengkap →", key="dashboard_market_pulse"):
        st.session_state["player_finder_market_pulse"] = True
        navigate_to("Players")


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
        return
    if recap is None:
        return

    average = f" · Rata-rata skor {recap.average_score}" if recap.average_score is not None else ""
    source_label = "Hasil resmi FPL" if event.get("finished") or event.get("is_previous") else "Snapshot resmi FPL"
    section_heading(
        "Rangkuman Gameweek Lalu",
        f"GW {recap.gameweek} · {source_label}{average}",
        "Kilasan performa pekan sebelumnya bersumber dari data resmi FPL API.",
    )
    for start in range(0, len(recap.metrics), 3):
        columns = st.columns(3)
        for column, metric in zip(columns, recap.metrics[start:start + 3]):
            with column:
                wrapped_metric_card(metric.label, metric.value, metric.detail, metric.tone)
    if recap.chips:
        section_heading(
            "Chip Aktif", "Penggunaan global di GW yang baru selesai",
            "Jumlah manajer FPL di seluruh dunia yang mengaktifkan masing-masing chip pekan lalu.",
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
        "Pencarian Pemain",
        "Temukan profil pemain yang pas buat strategi tim kamu.",
        "Saring data resmi pemain FPL berdasarkan posisi, harga, persentase kepemilikan, dan menit bermain.",
    )
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Layanan rekomendasi tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi sistem rekomendasi.")
        return

    if st.session_state.pop("player_finder_market_pulse", False):
        st.session_state["player_finder_sort"] = "Transfers in this GW"
        st.session_state["player_finder_budget"] = 15.0
        st.session_state["player_finder_ownership"] = 100
        st.session_state["player_finder_minutes"] = 0
        st.session_state["player_finder_differentials"] = False

    pos_labels = {"ALL": "Semua Posisi", "GK": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
    sort_labels = {
        "Recommendation": "Skor Rekomendasi",
        "Transfers in this GW": "Transfer Masuk GW Ini",
        "Fixture ease": "Kemudahan Fixture",
        "Value": "Nilai Ekonomis (Value)",
        "Minutes security": "Jaminan Menit Bermain",
        "Price (low)": "Harga Termurah",
        "Ownership (low)": "Ownership Terendah",
    }

    primary_controls = st.columns([1.45, 0.9, 0.85, 1.15])
    with primary_controls[0]:
        search_term = st.text_input(
            "Cari pemain atau klub",
            placeholder="Contoh: Palmer atau Arsenal",
            key="player_finder_search",
            help="Pencarian mencocokkan nama pemain dan klub dari data resmi FPL.",
        )
    with primary_controls[1]:
        position = st.selectbox(
            "Posisi", ["ALL", "GK", "DEF", "MID", "FWD"],
            format_func=lambda p: pos_labels.get(p, p),
            key="player_finder_position",
            help=ATTRIBUTE_HELP["position"],
        )
    with primary_controls[2]:
        horizon = st.selectbox(
            "Horizon fixture", [1, 3, 5, 8], index=2,
            format_func=lambda value: f"{value} GW ke depan",
            key="player_finder_horizon",
            help="Jumlah pekan laga mendatang yang dihitung dalam penilaian fixture dan peringkat akhir.",
        )
    with primary_controls[3]:
        sort_mode = st.selectbox(
            "Urutkan pemain",
            ["Recommendation", "Transfers in this GW", "Fixture ease", "Value", "Minutes security", "Price (low)", "Ownership (low)"],
            format_func=lambda s: sort_labels.get(s, s),
            key="player_finder_sort",
            help="Pilih urutan daftar setelah semua filter pencarian diterapkan.",
        )

    rankings = service.get_rankings(horizon=horizon)
    if not rankings:
        render_empty_state("Belum ada data pemain resmi", "Perbarui data resmi FPL melalui menu Data Status.")
        return
    frame = pd.DataFrame([asdict(row) for row in rankings])

    filter_columns = st.columns([1.35, 1, 1, 1])
    with filter_columns[0]:
        budget = st.slider(
            "Harga maksimal", 4.0, 15.0, 10.0, 0.1, format="£%.1fm",
            key="player_finder_budget",
            help="Saring pemain dengan harga resmi FPL maksimal sesuai nilai ini.",
        )
    with filter_columns[1]:
        max_ownership = st.slider(
            "Ownership maksimal", 1, 100, 50, 1, format="%d%%",
            key="player_finder_ownership",
            help=ATTRIBUTE_HELP["ownership"],
        )
    with filter_columns[2]:
        maximum_minutes = max(90, int(frame["minutes"].max()))
        minimum_minutes = st.slider(
            "Minimal menit bermain", 0, maximum_minutes, 0, 30,
            key="player_finder_minutes",
            help="Pertahankan pemain dengan minimal menit bermain ini pada data resmi musim ini.",
        )
    with filter_columns[3]:
        differential_only = st.checkbox(
            "Hanya pemain differential (<10%)",
            key="player_finder_differentials",
            help="Hanya tampilkan pemain dengan tingkat kepemilikan resmi FPL di bawah 10%.",
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
        "Transfers in this GW": ("transfers_in_event", False),
        "Fixture ease": ("fixture_score", False),
        "Value": ("value_score", False),
        "Minutes security": ("minutes_score", False),
        "Price (low)": ("price", True),
        "Ownership (low)": ("ownership", True),
    }
    sort_column, ascending = sort_columns[sort_mode]
    filtered = filtered.sort_values(sort_column, ascending=ascending)

    section_heading(
        "Daftar Pemain", f"{len(filtered)} profil ditemukan · {horizon} GW ke depan",
        "Data pemain resmi FPL terkini setelah filter aktif dan horizon kalkulasi diterapkan.",
    )
    if filtered.empty:
        render_empty_state("Tidak ada pemain yang cocok", "Coba longgarkan satu atau beberapa kriteria filter pencarian.")
        return
    filtered["confidence_percent"] = filtered["confidence"] * 100
    filtered["category_display"] = filtered["category"].map(
        lambda c: {
            "Elite Target": "Target Unggulan",
            "Strong Buy": "Prioritas Beli",
            "Good Option": "Pilihan Bagus",
            "Watchlist": "Masuk Pantauan",
            "Neutral": "Netral",
            "Avoid": "Sebaiknya Hindari",
        }.get(str(c), str(c))
    )

    display = filtered[
        [
            "name",
            "team",
            "position",
            "price",
            "ownership",
            "transfers_in_event",
            "minutes",
            "form",
            "next_fixture",
            "confidence_percent",
            "final_score",
            "category_display",
            "reason",
        ]
    ]
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Pemain", help="Nama resmi pemain FPL."),
            "team": st.column_config.TextColumn("Klub", help="Klub resmi FPL."),
            "position": st.column_config.TextColumn("Pos", width="small", help=ATTRIBUTE_HELP["position"]),
            "price": st.column_config.NumberColumn("Harga", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
            "ownership": st.column_config.NumberColumn("Ownership", format="%.1f%%", help=ATTRIBUTE_HELP["ownership"]),
            "transfers_in_event": st.column_config.NumberColumn(
                "Transfer GW Ini", format="%,d", help=ATTRIBUTE_HELP["transfers_in_event"]
            ),
            "minutes": st.column_config.NumberColumn("Menit", help=ATTRIBUTE_HELP["minutes"]),
            "form": st.column_config.NumberColumn("Form", format="%.1f", help=ATTRIBUTE_HELP["form"]),
            "next_fixture": st.column_config.TextColumn("Laga Berikutnya", help="Fixture terdekat yang belum dimulai."),
            "confidence_percent": st.column_config.ProgressColumn(
                "Kepercayaan Sinyal", min_value=0, max_value=100, format="%.0f%%", help=ATTRIBUTE_HELP["confidence"]
            ),
            "final_score": st.column_config.ProgressColumn(
                "Skor", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["score"]
            ),
            "category_display": st.column_config.TextColumn("Kategori", help="Kategori rekomendasi berdasarkan skor akhir."),
            "reason": st.column_config.TextColumn("Faktor Penentu", help="Dua komponen skor terbesar yang mendorong peringkat pemain."),
        },
    )

    player_choices = dict(zip(filtered["player_id"], filtered["name"] + " · " + filtered["team"]))
    selected = st.selectbox(
        "Buka profil pemain",
        list(player_choices),
        format_func=lambda player_id: player_choices[player_id],
        help="Pilih pemain untuk melihat histori laga dan analisis metrik resminya.",
    )
    if st.button("Lihat Detail Pemain", type="primary"):
        st.session_state["official_player_id"] = selected
        navigate_to("Player Detail")


def render_chip_strategy_tab(scoring: ScoringConfig) -> None:
    """Render data-driven chip deployment roadmap for Round 1 (GW 1–19)."""
    service = st.session_state.get("chip_strategy_service")
    if service is None:
        service = get_chip_strategy_service()

    # Determine current gameweek
    ingestion = st.session_state.get("fpl_ingestion_service")
    current_gw = 0
    if ingestion is not None and hasattr(ingestion, "status_store"):
        try:
            current_gw = ingestion.status_store.load().current_gameweek or 0
        except Exception:
            current_gw = 0

    if current_gw <= 0:
        try:
            boot = service.client.get_bootstrap()
            for ev in boot.get("events", []):
                if ev.get("is_current"):
                    current_gw = int(ev["id"])
                    break
                if ev.get("is_next") and current_gw <= 0:
                    current_gw = max(1, int(ev["id"]) - 1)
        except Exception:
            current_gw = 4

    default_id = int(st.session_state.get("fpl_manager_id", 1158066))
    col_id, col_btn = st.columns([1, 1.4])
    with col_id:
        manager_id = st.number_input(
            "FPL Manager ID",
            min_value=1,
            value=default_id,
            step=1,
            help="Masukkan FPL Manager ID kamu untuk memuat riwayat pemakaian chip putaran pertama.",
            key="chip_strat_mgr_id_input",
        )
    with col_btn:
        st.caption("Sinkronisasi riwayat chip dengan profil resmi FPL kamu.")
        if st.button("Muat Ulang Strategi Chip", key="btn_reload_chip_strat"):
            st.session_state["fpl_manager_id"] = int(manager_id)

    st.session_state["fpl_manager_id"] = int(manager_id)

    with st.spinner("Menganalisa pergeseran fixture, proyeksi kapten, dan jadwal big match..."):
        try:
            report = service.generate_strategy_report(
                manager_id=int(manager_id),
                current_gw=current_gw,
            )
        except Exception as exc:
            st.error(f"Gagal memuat laporan strategi chip: {exc}")
            return

    # Section 1: Urgency Alert Box
    inv = report.inventory
    if inv.urgency_level == "CRITICAL":
        st.error(inv.urgency_message)
    elif inv.urgency_level == "HIGH":
        st.warning(inv.urgency_message)
    elif inv.urgency_level == "MODERATE":
        st.info(inv.urgency_message)
    else:
        st.success(inv.urgency_message)

    # Metric tiles
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        metric_tile(
            "Batas Akhir Putaran 1",
            "Gameweek 19",
            "Aturan pakai-atau-hangus",
            "Semua chip putaran 1 yang belum dipakai akan otomatis hangus begitu deadline GW 19 lewat.",
        )
    with m2:
        metric_tile(
            "Amunisi Putaran 1",
            f"{inv.remaining_chips_count} dari 4 Tersedia",
            f"{inv.used_chips_count} chip sudah dipakai",
            "Tiap manajer menerima 4 chip untuk GW 1–19 (Wildcard 1, Free Hit 1, Triple Captain 1, Bench Boost 1).",
        )
    with m3:
        metric_tile(
            "Sisa Gameweek",
            f"Sisa {inv.gws_until_expiry} GW",
            f"Saat ini di GW {current_gw}",
            "Jumlah pekan yang tersisa di paruh pertama musim.",
        )
    with m4:
        pace = inv.gws_until_expiry / max(1, inv.remaining_chips_count) if inv.remaining_chips_count > 0 else 0
        pace_str = f"1 chip / {pace:.1f} GW" if inv.remaining_chips_count > 0 else "Semua chip sudah terpakai!"
        metric_tile(
            "Ritme Pemakaian",
            pace_str,
            "Maksimal 1 chip per gameweek",
            "Jarak rata-rata yang pas biar semua sisa chip putaran 1 bisa kepakai maksimal sebelum deadline GW 19.",
        )

    # Section 2: Chip Inventory Badges
    section_heading(
        "Status Amunisi Chip Putaran 1",
        f"ID Manajer {manager_id} · Alokasi Gameweek 1–19",
        "Status resmi 4 chip yang dialokasikan untuk paruh pertama musim.",
    )

    badge_cols = st.columns(4)
    chips_meta = [
        ("Wildcard 1", inv.wc1_gw, "Transfer permanen tanpa batas sampai deadline"),
        ("Triple Captain 1", inv.tc1_gw, "Poin armband dikali 3×"),
        ("Free Hit 1", inv.fh1_gw, "Transfer bebas tanpa batas hanya untuk 1 gameweek"),
        ("Bench Boost 1", inv.bb1_gw, "Poin dari seluruh 15 pemain skuad ikut dihitung"),
    ]
    for idx, (c_label, c_gw, c_desc) in enumerate(chips_meta):
        with badge_cols[idx]:
            if c_gw is not None:
                st.markdown(
                    f"""
                    <div style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:12px; text-align:center;">
                        <div style="color:#8b95a5; font-size:0.75rem; text-transform:uppercase; font-weight:700;">{c_label}</div>
                        <div style="color:#fca5a5; font-size:1.15rem; font-weight:800; margin:4px 0;">TERPAKAI DI GW {c_gw}</div>
                        <div style="color:#8b95a5; font-size:0.72rem;">{c_desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div style="background:rgba(24,245,155,0.1); border:1px solid rgba(24,245,155,0.3); border-radius:10px; padding:12px; text-align:center;">
                        <div style="color:#8b95a5; font-size:0.75rem; text-transform:uppercase; font-weight:700;">{c_label}</div>
                        <div style="color:#18f59b; font-size:1.15rem; font-weight:800; margin:4px 0;">TERSEDIA</div>
                        <div style="color:#8b95a5; font-size:0.72rem;">Wajib pakai sebelum GW 19</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Section 3: AI Master Plan
    if report.master_plan:
        section_heading(
            "Master Plan Rekomendasi AI",
            f"{len(report.master_plan)} chip terjadwal rapi tanpa bentrok",
            "Jadwal pemakaian paling optimal berdasarkan fixture swing, jeda International Break, potensi puncak xP kapten, dan clash big match.",
        )
        plan_cols = st.columns(len(report.master_plan))
        for idx, plan_item in enumerate(report.master_plan):
            with plan_cols[idx]:
                alt_txt = f"<br><span style='color:#8b95a5; font-size:0.72rem;'>Cadangan: GW {plan_item.alternative_gw}</span>" if plan_item.alternative_gw else ""
                st.markdown(
                    f"""
                    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(24,245,155,0.3); border-radius:12px; padding:14px; height:100%;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="background:rgba(24,245,155,0.2); color:#18f59b; padding:2px 8px; border-radius:6px; font-size:0.75rem; font-weight:800;">{plan_item.chip_label}</span>
                            <span style="color:#ffcf5c; font-weight:800; font-size:0.85rem;">Skor {plan_item.suitability_score:.0f}/100</span>
                        </div>
                        <div style="font-size:1.05rem; font-weight:800; color:#fff; margin-bottom:6px;">{escape(plan_item.headline)}</div>
                        <div style="color:#c9d1d9; font-size:0.8rem; line-height:1.35; margin-bottom:8px;">{escape(plan_item.rationale)}</div>
                        <div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:6px; color:#8b95a5; font-size:0.72rem;">
                            <strong>Antisipasi:</strong> {escape(plan_item.contingency_note)}{alt_txt}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    else:
        st.success("Mantap! Semua chip putaran 1 sudah dipakai. Siap-siap amunisi baru untuk putaran 2 mulai GW 20!")

    # Section 4: Gameweek Suitability Heatmap Table
    section_heading(
        f"Kalender Kelayakan Gameweek (GW {current_gw}–19)",
        "Radar lengkap kesiapan untuk 4 chip",
        "Analisa skor kelayakan (0–100) dan alasan strategis tiap gameweek di putaran pertama.",
    )

    _CAL_CSS = """
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: transparent; font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif; color: #e0e6ed; }
        .wrap { overflow-x: auto; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.8rem; text-align: left; }
        thead tr { background: rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.08); }
        thead th { padding: 10px 8px; color: #8b95a5; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.06em; font-weight: 600; white-space: nowrap; }
        tbody tr { border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 0.15s; }
        tbody tr:hover { background: rgba(255,255,255,0.03); }
        td { padding: 8px; vertical-align: middle; }
        .score-high { background: rgba(24,245,155,0.16); border: 1px solid rgba(24,245,155,0.35); border-radius: 6px; color: #18f59b; display: inline-block; font-size: 0.73rem; font-weight: 800; padding: 2px 6px; }
        .score-mid { background: rgba(255,207,92,0.15); border: 1px solid rgba(255,207,92,0.35); border-radius: 6px; color: #ffcf5c; display: inline-block; font-size: 0.73rem; font-weight: 800; padding: 2px 6px; }
        .score-low { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; color: #8b95a5; display: inline-block; font-size: 0.73rem; font-weight: 700; padding: 2px 6px; }
        .tag-ib { background: rgba(139,92,246,0.2); color: #c4b5fd; border: 1px solid rgba(139,92,246,0.4); border-radius: 4px; font-size: 0.65rem; font-weight: 700; padding: 1px 5px; margin-top: 3px; display: inline-block; }
        .tag-festive { background: rgba(239,68,68,0.18); color: #fca5a5; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; font-size: 0.65rem; font-weight: 700; padding: 1px 5px; margin-top: 3px; display: inline-block; }
        .reason-text { font-size: 0.73rem; color: #8b95a5; margin-top: 2px; line-height: 1.25; }
        .center { text-align: center; }
        .bold { font-weight: 800; }
    </style>
    """

    def _score_badge(score: float) -> str:
        if score >= 75:
            return f'<span class="score-high">{score:.0f}</span>'
        if score >= 55:
            return f'<span class="score-mid">{score:.0f}</span>'
        return f'<span class="score-low">{score:.0f}</span>'

    cal_rows_html = []
    for c in report.suitability_matrix:
        tags_html = ""
        if c.is_international_break:
            tags_html += '<br><span class="tag-ib">🌍 Pasca-IB</span>'
        if c.is_festive_period:
            tags_html += '<br><span class="tag-festive">🎄 Rotasi Festive</span>'

        cal_rows_html.append(f"""
        <tr>
            <td class="bold center" style="white-space:nowrap; width:90px;">
                GW {c.gameweek}<br>
                <span style="font-size:0.68rem; color:#8b95a5; font-weight:400;">{c.deadline_display}</span>
                {tags_html}
            </td>
            <td style="width:22%;">
                {_score_badge(c.wc_score)}
                <div class="reason-text">{escape(c.wc_reason)}</div>
            </td>
            <td style="width:24%;">
                {_score_badge(c.tc_score)} <strong style="color:#ffcf5c; font-size:0.75rem;">{escape(c.tc_captain_pick)}</strong>
                <div class="reason-text">{escape(c.tc_reason)}</div>
            </td>
            <td style="width:24%;">
                {_score_badge(c.fh_score)}
                <div class="reason-text">{escape(c.fh_reason)}</div>
            </td>
            <td style="width:24%;">
                {_score_badge(c.bb_score)}
                <div class="reason-text">{escape(c.bb_reason)}</div>
            </td>
        </tr>""")

    num_cal_rows = len(report.suitability_matrix)
    cal_height = min(62 + num_cal_rows * 65, 1200)

    cal_table_html = f"""{_CAL_CSS}
    <div class="wrap">
        <table>
            <thead>
                <tr>
                    <th class="center">Gameweek</th>
                    <th>Wildcard 1 (WC1)</th>
                    <th>Triple Captain 1 (TC1)</th>
                    <th>Free Hit 1 (FH1)</th>
                    <th>Bench Boost 1 (BB1)</th>
                </tr>
            </thead>
            <tbody>{''.join(cal_rows_html)}</tbody>
        </table>
    </div>
    """
    import streamlit.components.v1 as stc
    stc.html(cal_table_html, height=cal_height, scrolling=True)

    # Section 5: Strategic Takeaways & Pro Rules
    if report.key_takeaways:
        with st.expander("📌 Aturan Resmi FPL & Catatan Strategi", expanded=True):
            for t in report.key_takeaways:
                st.markdown(f" • {t}")


def _render_player_recommendations_content(scoring: ScoringConfig) -> None:
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Layanan rekomendasi tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi sistem rekomendasi.")
        return

    rec_sort_labels = {
        "Recommendation": "Skor Rekomendasi",
        "Value": "Nilai Ekonomis (Value)",
        "Fixture": "Kemudahan Fixture",
        "Minutes security": "Jaminan Menit Bermain",
    }

    controls = st.columns([1, 1, 1.4])
    with controls[0]:
        position = st.radio(
            "Posisi", ["GK", "DEF", "MID", "FWD"], index=2, horizontal=True,
            help=ATTRIBUTE_HELP["position"],
        )
    with controls[1]:
        horizon = st.selectbox(
            "Horizon fixture",
            [1, 3, 5, 8],
            index=2,
            format_func=lambda value: f"{value} GW ke depan",
            help="Jumlah pekan laga mendatang yang dihitung dalam penilaian komponen fixture.",
        )
    with controls[2]:
        sort_mode = st.selectbox(
            "Urutkan berdasarkan",
            ["Recommendation", "Value", "Fixture", "Minutes security"],
            format_func=lambda s: rec_sort_labels.get(s, s),
            help="Urutkan daftar pemain pada posisi ini berdasarkan salah satu komponen skor.",
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
        render_empty_state("Rekomendasi tidak tersedia", "Coba pilih posisi atau horizon yang lain.")
        return
    ranked = pd.DataFrame([asdict(row) for row in rows]).sort_values(
        sort_columns[sort_mode], ascending=False
    )
    section_heading(
        f"20 Pemain {position} Teratas", f"{horizon} GW ke depan · Model {scoring.model_version}",
        f"Daftar 20 pemain terbaik di posisi {position} berdasarkan kalkulasi model rekomendasi aktif.",
    )

    cards = st.columns(min(3, len(ranked)))
    row_by_id = {row.player_id: row for row in rows}
    for rank, (column, (_, player)) in enumerate(zip(cards, ranked.head(3).iterrows()), start=1):
        with column:
            player_card(
                _player_card_data(row_by_id[int(player["player_id"])]),
                label=f"Peringkat #{rank}",
            )

    freshness, freshness_detail = _freshness_label(
        service.ingestion.status_store.load().last_successful_at
    )
    section_heading(
        "Komponen Penentu Skor", f"Model aktif · Versi {scoring.model_version}",
        "Bedah skor normalisasi tiap komponen, bobot yang dipakai, dan kontribusi akhir untuk pemain terpilih.",
    )
    player_choices = {
        int(row.player_id): f"{row.name} · {row.team} · {row.position}"
        for row in rows
    }
    selected_player_id = st.selectbox(
        "Pilih pemain untuk dianalisis",
        list(player_choices),
        format_func=lambda player_id: player_choices[player_id],
        key=f"recommendation_evidence_{position}_{horizon}_{sort_mode}",
        help="Pilih pemain untuk melihat bukti statistik resmi FPL dan rincian skornya.",
    )
    selected_row = row_by_id[int(selected_player_id)]
    ranking_rows = [
        {
            "Signal": METRIC_LABELS.get(metric, metric.replace("_", " ").title()),
            "Component score": score,
            "Weight": scoring.position_weights[position][metric],
            "Final contribution": selected_row.metric_contributions[metric],
        }
        for metric, score in selected_row.metric_scores.items()
    ]
    ranking_inputs = pd.DataFrame(ranking_rows)
    trace_columns = st.columns(3)
    trace_columns[0].metric("Skor Akhir", f"{selected_row.final_score:.1f}/100", help=ATTRIBUTE_HELP["score"])
    trace_columns[1].metric(
        "Faktor Ketersediaan",
        f"{selected_row.availability_penalty:.0%}",
        help="Pengali status ketersediaan resmi FPL yang diterapkan setelah penjumlahan komponen bobot.",
    )
    trace_columns[2].metric(
        "Total Kontribusi",
        f"{ranking_inputs['Final contribution'].sum():.1f}",
        help="Total penjumlahan kontribusi terbobot setelah faktor ketersediaan.",
    )
    st.dataframe(
        ranking_inputs,
        hide_index=True,
        width="stretch",
        column_config={
            "Signal": st.column_config.TextColumn("Komponen Sinyal", help="Komponen input aktif model rekomendasi."),
            "Component score": st.column_config.ProgressColumn("Skor Komponen", min_value=0, max_value=100, format="%.1f", help="Skor persentil relatif terhadap posisi (0–100)."),
            "Weight": st.column_config.NumberColumn("Bobot", format="%.0f%%", help="Bobot resmi untuk posisi ini (total 100%)."),
            "Final contribution": st.column_config.NumberColumn("Kontribusi Akhir", format="%.2f", help="Skor komponen × bobot × faktor ketersediaan."),
        },
    )
    st.caption(
        "Bobot posisi kandidat v1.3 disimpan terpisah dan tidak digunakan di sini. Statusnya tetap eksperimental sampai validasi Fase E selesai."
    )
    with st.expander("Definisi Komponen Penentu Skor", expanded=False):
        st.caption("Arahkan kursor ke tiap komponen untuk melihat rumus, arah metrik, sumber data, dan status pembaruan.")
        for start in range(0, len(selected_row.metric_scores), 2):
            definition_columns = st.columns(2)
            metric_items = list(selected_row.metric_scores.items())[start:start + 2]
            for column, (metric, metric_score) in zip(definition_columns, metric_items):
                with column:
                    st.metric(
                        METRIC_LABELS.get(metric, metric.replace("_", " ").title()),
                        f"{metric_score:.1f}/100",
                        delta=f"Bobot {scoring.position_weights[position][metric]:.0%}",
                        help=(
                            f"{RANKING_METRIC_HELP.get(metric, 'Komponen input peringkat aktif.')} "
                            f"Sumber: snapshot bootstrap-static resmi FPL musim ini. "
                            f"Status: {freshness}. {freshness_detail}"
                        ),
                    )

    with st.expander("Bukti Statistik Musim Ini", expanded=False):
        st.caption(
            f"Snapshot data resmi FPL {freshness} · {freshness_detail} "
            "Metrik-metrik ini menjelaskan profil pemain yang dipilih. 'Belum tersedia' bukan berarti nol."
        )
        evidence_rows = []
        for signal in selected_row.positional_signals:
            percentile = signal.normalized_score
            evidence_rows.append(
                {
                    "Metric": signal.label,
                    "Official value": _signal_value_display(signal),
                    "Position score": round(percentile, 1) if percentile is not None else None,
                    "Role": "Digunakan dalam skor" if signal.used_in_ranking else "Konteks resmi",
                    "Direction": "Semakin tinggi semakin bagus" if signal.direction == "higher_is_better" else "Semakin rendah semakin bagus",
                }
            )
        st.dataframe(
            pd.DataFrame(evidence_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Metric": st.column_config.TextColumn("Bukti Statistik Resmi", help="Arahkan kursor ke kartu metrik di bawah untuk formula dan detailnya."),
                "Official value": st.column_config.TextColumn("Nilai Resmi", help="Nilai resmi FPL atau rasio turunan per 90 menit."),
                "Position score": st.column_config.ProgressColumn("Skor Posisi", min_value=0, max_value=100, format="%.1f", help="Persentil relatif terhadap posisi setelah penyesuaian reliabilitas data."),
                "Role": st.column_config.TextColumn("Peran", help="Menunjukkan apakah metrik menjadi input skor utama atau konteks pendukung."),
                "Direction": st.column_config.TextColumn("Arah Metrik", help="Arah acuan yang menguntungkan dalam perbandingan posisi."),
            },
        )
        st.caption("Arahkan kursor ke nama metrik di bawah untuk definisi pasti dan status datanya.")
        for start in range(0, len(selected_row.positional_signals), 2):
            evidence_columns = st.columns(2)
            for column, signal in zip(evidence_columns, selected_row.positional_signals[start:start + 2]):
                delta = "Digunakan dalam skor" if signal.used_in_ranking else "Konteks resmi"
                if signal.normalized_score is not None:
                    delta = f"{delta} · skor posisi {signal.normalized_score:.0f}"
                with column:
                    st.metric(
                        signal.label,
                        _signal_value_display(signal),
                        delta=delta,
                        help=_signal_help(signal, freshness, freshness_detail),
                    )

    section_heading("Rincian Lengkap Skor", "Transparansi penuh tanpa perhitungan tersembunyi")
    st.caption(
        "Skor akhir menggabungkan sinyal fixture, performa yang diharapkan (expected), menit bermain, histori, dan nilai ekonomis. "
        "Faktor utama menampilkan dua pendorong nilai terbesar. Bobot lengkap model dapat dilihat di menu Data Status."
    )
    ranked["category_display"] = ranked["category"].map(
        lambda c: {
            "Elite Target": "Target Unggulan",
            "Strong Buy": "Prioritas Beli",
            "Good Option": "Pilihan Bagus",
            "Watchlist": "Masuk Pantauan",
            "Neutral": "Netral",
            "Avoid": "Sebaiknya Hindari",
        }.get(str(c), str(c))
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
            "category_display",
            "reason",
        ]
    ]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Pemain", help="Nama resmi pemain FPL."),
            "team": st.column_config.TextColumn("Klub", help="Klub resmi pemain di FPL."),
            "price": st.column_config.NumberColumn("Harga", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
            "ownership": st.column_config.NumberColumn("Ownership", format="%.1f%%", help=ATTRIBUTE_HELP["ownership"]),
            "form": st.column_config.NumberColumn("Form", format="%.1f", help=ATTRIBUTE_HELP["form"]),
            "fixture_score": st.column_config.ProgressColumn(
                "Fixture", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["fixture_score"]
            ),
            "expected_score": st.column_config.ProgressColumn(
                "Expected", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["expected"]
            ),
            "minutes_score": st.column_config.ProgressColumn(
                "Menit", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["minutes_score"]
            ),
            "value_score": st.column_config.ProgressColumn(
                "Value", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["value"]
            ),
            "history_score": st.column_config.ProgressColumn(
                "Histori", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["history"]
            ),
            "final_score": st.column_config.ProgressColumn(
                "Skor Akhir", min_value=0, max_value=100, format="%d", help=ATTRIBUTE_HELP["score"]
            ),
            "category_display": st.column_config.TextColumn("Kategori", help="Kategori rekomendasi turunan dari skor akhir."),
            "reason": st.column_config.TextColumn("Faktor Utama", help="Dua komponen berbobot yang paling banyak menyumbang skor pemain ini."),
        },
    )


def render_recommendations(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Recommendation Engine",
        "Peringkat Pemain & Radar Pemakaian Chip",
        "Pantau peringkat pemain terbaik dan roadmap pemakaian chip berbasis data untuk putaran 1 (GW 1–19).",
    )

    tab_players, tab_chips = st.tabs([
        "⭐ Rekomendasi Pemain",
        "🎯 Strategi & Jadwal Chip (GW 1–19)",
    ])

    with tab_players:
        _render_player_recommendations_content(scoring)

    with tab_chips:
        render_chip_strategy_tab(scoring)


def render_fixtures(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures, scoring
    page_header(
        "Perencana Fixture",
        "Pantau rangkaian jadwal, bukan cuma satu laga ke depan.",
        "Jadwal resmi FPL tersimpan di database lokal dan dianalisis untuk horizon 1, 3, 5, atau 8 Gameweek.",
    )
    service = st.session_state.get("fixture_analytics_service")
    if service is None:
        render_empty_state("Layanan fixture tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi layanan database lokal.")
        return

    horizon = st.select_slider(
        "Horizon", [1, 3, 5, 8], value=5, format_func=lambda value: f"{value} GW ke depan",
        help="Jumlah Gameweek mendatang yang dimasukkan dalam matriks fixture dan kalkulasi skor.",
    )
    matrix = service.get_matrix(horizon)
    if not matrix.teams or not any(summary.fixtures for summary in matrix.teams):
        render_empty_state("Tidak ada fixture resmi mendatang", "Segarkan data FPL melalui menu Data Status.")
        return

    teams = [summary.team_name for summary in matrix.teams]
    default_index = teams.index("Arsenal") if "Arsenal" in teams else 0
    selected_team = st.selectbox(
        "Pilih klub", teams, index=default_index,
        help="Pilih klub resmi FPL untuk melihat jadwal laga mendatang.",
    )
    selected = matrix.team(selected_team)
    if selected is None:
        render_empty_state("Klub tidak tersedia", "Pilih klub lainnya.")
        return

    average_fdr = sum(item.fdr for item in selected.fixtures) / len(selected.fixtures)
    summary_columns = st.columns(3)
    summary_columns[0].metric("Skor Fixture", f"{selected.fixture_score or 0:.0f}/100", "Lebih tinggi lebih mudah")
    summary_columns[1].metric("Rata-rata FDR", f"{average_fdr:.1f}", "1 paling mudah · 5 paling sulit")
    summary_columns[2].metric("Pemain Terdaftar", str(selected.players_tracked), "Data skuad resmi FPL")

    section_heading(
        selected_team, f"{horizon} fixture ke depan · Jadwal Resmi FPL",
        "Lawan tanding per laga dan FDR resmi untuk klub terpilih.",
    )
    fixture_strip(
        [
            {"gameweek": f"GW {item.gameweek or 'TBC'}", "fixture": item.fixture, "fdr": item.fdr}
            for item in selected.fixtures
        ]
    )

    section_heading(
        "Matriks Fixture", "FDR resmi · skor berbobot mengutamakan laga terdekat",
        "FDR lebih rendah lebih mudah; laga terdekat memiliki bobot pengaruh lebih besar.",
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
            "team": st.column_config.TextColumn("Klub", pinned=True, help="Nama resmi klub di FPL."),
            "fixture_score": st.column_config.ProgressColumn(
                "Skor Fixture", min_value=0, max_value=100, format="%.0f",
                help=ATTRIBUTE_HELP["fixture_score"],
            ),
            "players_tracked": st.column_config.NumberColumn(
                "Jumlah Pemain", help="Jumlah pemain resmi yang terdaftar di klub ini."
            ),
        },
    )


def render_player_detail(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures, scoring
    service = st.session_state.get("player_analytics_service")
    if service is None:
        render_empty_state("Layanan pemain tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi layanan database lokal.")
        return
    options = service.list_player_options()
    if not options:
        render_empty_state("Belum ada data pemain resmi", "Perbarui data resmi FPL melalui menu Data Status.")
        return

    labels = {option.player_id: option.label for option in options}
    player_ids = list(labels)
    selected_player_id = st.selectbox(
        "Pilih pemain FPL",
        player_ids,
        format_func=lambda player_id: labels[player_id],
        key="official_player_id",
        help="Pilih pemain yang ingin kamu lihat riwayat laga dan detail statistiknya.",
    )

    if st.button("Muat Riwayat Gameweek Resmi", type="primary"):
        try:
            with st.spinner("Mengambil data riwayat laga resmi dari FPL..."):
                result = service.sync_history(selected_player_id)
            if result.from_cache:
                st.info(f"Cache riwayat Gameweek masih valid: {result.row_count} baris data; tidak perlu request ulang ke API FPL.")
            else:
                st.success(f"Riwayat tersimpan: {result.row_count} baris data resmi FPL berhasil disinkronkan.")
        except Exception:
            st.error("Riwayat belum berhasil dimuat. Data lokal yang ada tetap aman.")

    detail = service.get_detail(selected_player_id)
    features = detail.features
    status_labels = {
        "a": "Tersedia",
        "d": "Meragukan",
        "i": "Cedera",
        "s": "Hukuman Kartu",
        "u": "Tidak Tersedia",
        "n": "Tidak Tersedia",
    }
    page_header(
        f"{detail.team} · {detail.position} · Data Resmi FPL",
        detail.name,
        "Statistik total musim ini, riwayat per Gameweek, dan indikator sinyal dengan penyesuaian sampel bermain.",
    )
    if detail.news:
        st.warning(detail.news)

    headline = st.columns(5)
    with headline[0]:
        metric_tile("Harga", f"£{detail.price:.1f}m", f"Ownership {detail.ownership:.1f}%", ATTRIBUTE_HELP["price"])
    with headline[1]:
        metric_tile(
            "Total Poin", str(detail.total_points), f"PPM {detail.points_per_game:.1f}",
            "Total poin resmi FPL pada snapshot statistik terkini.",
        )
    with headline[2]:
        metric_tile(
            "Form Berjalan", f"{features.form_5:.2f}", "5 GW terakhir",
            "Rata-rata total poin pemain di lima Gameweek terakhir dalam database.",
        )
    with headline[3]:
        metric_tile(
            "xGI / 90 Menit", f"{features.xgi_per_90:.2f}", f"xG {features.xg_per_90:.2f} · xA {features.xa_per_90:.2f}",
            "Proyeksi keterlibatan gol per 90 menit dari riwayat laga tersimpan.",
        )
    with headline[4]:
        metric_tile(
            "Jaminan Menit", f"{features.minutes_security:.0f}/100", status_labels.get(detail.status, "Tidak Diketahui"),
            "Keandalan menit bermain terbaru setelah disesuaikan status ketersediaan pemain.",
        )

    period = (
        f"GW {features.period_start_gameweek}–{features.period_end_gameweek}"
        if features.period_start_gameweek is not None
        else "Belum ada riwayat Gameweek tersimpan"
    )
    confidence_percent = features.confidence * 100
    if not features.enough_minutes:
        st.info(
            f"Sampel menit bermain sedikit: baru {features.sample_minutes} dari minimal {service.scoring.minimum_minutes} menit. "
            f"Penyesuaian keandalan saat ini {confidence_percent:.0f}%."
        )

    chart_column, feature_column = st.columns([1.3, 1])
    with chart_column:
        section_heading(
            "Tren Gameweek", f"{period} · Cache Resmi FPL",
            "Poin, menit bermain, dan xGI resmi per Gameweek (dijumlahkan otomatis jika ada Double Gameweek).",
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
                (trend_columns[0], "Points", "#18f59b", "Poin resmi FPL"),
                (trend_columns[1], "Minutes", "#7bbcf0", "Menit bermain"),
                (trend_columns[2], "xGI", "#b28df2", "Ekspektasi keterlibatan gol (xGI)"),
            ):
                with column:
                    st.caption(description)
                    st.line_chart(history_frame[[metric]], color=color, height=190)
        else:
            render_action_state(
                "Riwayat belum tersedia",
                "Klik tombol 'Muat Riwayat Gameweek Resmi' di atas untuk mengunduh data laga pemain ini.",
            )
    with feature_column:
        section_heading(
            "Keandalan Komponen Statistik", f"{features.sample_minutes} menit · {confidence_percent:.0f}% keandalan",
            "Statistik mentah ditampilkan bersanding dengan nilai yang telah disesuaikan dengan volume menit bermain.",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ["Form", features.form_5, features.confidence_adjusted_form, "5 GW terakhir"],
                    ["xGI / 90", features.xgi_per_90, features.confidence_adjusted_xgi_per_90, period],
                    ["Value", features.value, features.confidence_adjusted_value, "PPM / harga"],
                    ["Menit Bermain", features.minutes_security, features.minutes_security, f"{service.scoring.minutes_security_window} fixture terakhir"],
                ],
                columns=["Komponen", "Nilai Mentah", "Setelah Disesuaikan", "Periode / Definisi"],
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Nilai Mentah": st.column_config.NumberColumn(
                    format="%.2f", help="Statistik belum disesuaikan dari periode histori terpilih."
                ),
                "Setelah Disesuaikan": st.column_config.NumberColumn(
                    format="%.2f", help="Nilai setelah penyesuaian batas minimal menit dan ketersediaan."
                ),
            },
        )

    section_heading(
        "Riwayat Laga Resmi", f"{len(detail.history)} laga tersimpan · Cache lokal cepat",
        "Data resmi per pertandingan yang tersimpan di SQLite sehingga halaman terbuka instan tanpa membebani API FPL.",
    )
    if detail.history:
        st.dataframe(
            pd.DataFrame([asdict(row) for row in reversed(detail.history)]),
            hide_index=True,
            width="stretch",
            column_config={
                "gameweek": st.column_config.NumberColumn("GW", help="Nomor Gameweek resmi."),
                "opponent": st.column_config.TextColumn("Lawan", help="Klub lawan pada pertandingan ini."),
                "venue": st.column_config.TextColumn("Kandang/Tandang", help="Status laga kandang (H) atau tandang (A)."),
                "minutes": st.column_config.NumberColumn("Menit", help="Menit bermain pada laga ini."),
                "points": st.column_config.NumberColumn("Poin", help="Poin resmi FPL yang diraih pada laga ini."),
                "xg": st.column_config.NumberColumn("xG", format="%.2f", help="Expected goals pada laga ini."),
                "xa": st.column_config.NumberColumn("xA", format="%.2f", help="Expected assists pada laga ini."),
                "xgi": st.column_config.NumberColumn("xGI", format="%.2f", help="Expected goal involvements pada laga ini."),
                "bonus": st.column_config.NumberColumn("Bonus", help="Poin bonus resmi FPL pada laga ini."),
                "price": st.column_config.NumberColumn("Harga", format="£%.1fm", help="Harga pemain saat laga berlangsung."),
            },
        )

    fixture_service = st.session_state.get("fixture_analytics_service")
    if fixture_service is not None:
        team_summary = fixture_service.get_matrix(5).team(detail.team)
        if team_summary is not None and team_summary.fixtures:
            section_heading("Fixture Berikutnya", "Prospek 5 Gameweek ke depan dari jadwal resmi FPL")
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
        "Head-to-Head",
        "Bandingkan trade-off dua pemain secara objektif.",
        "Pilih dua pemain resmi FPL untuk membandingkan fixture, performa, menit bermain, dan nilainya.",
    )
    service = st.session_state.get("recommendation_engine_service")
    if service is None:
        render_empty_state("Layanan rekomendasi tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi sistem rekomendasi.")
        return
    horizon = st.select_slider(
        "Horizon komparasi", [1, 3, 5, 8], value=scoring.default_horizon,
        format_func=lambda value: f"{value} GW ke depan",
        help="Gunakan horizon fixture yang sama untuk kedua pemain sebelum menilai trade-off.",
    )
    rows = service.get_rankings(horizon=horizon)
    if len(rows) < 2:
        render_empty_state("Jumlah pemain kurang", "Perbarui data resmi FPL.")
        return
    labels = {row.player_id: f"{row.name} · {row.team} · {row.position}" for row in rows}
    row_by_id = {row.player_id: row for row in rows}
    player_ids = list(labels)
    selectors = st.columns(2)
    with selectors[0]:
        player_a_id = st.selectbox(
            "Pemain A", player_ids, index=0, format_func=lambda player_id: labels[player_id],
            help="Pemain resmi FPL pertama dalam perbandingan.",
        )
    with selectors[1]:
        player_b_id = st.selectbox(
            "Pemain B", player_ids, index=1, format_func=lambda player_id: labels[player_id],
            help="Pemain resmi FPL kedua dalam perbandingan.",
        )

    if player_a_id == player_b_id:
        render_empty_state(
            "Pilih dua pemain yang berbeda", "Komparasi membutuhkan dua profil pemain yang berbeda."
        )
        return

    player_a = row_by_id[player_a_id]
    player_b = row_by_id[player_b_id]
    cards = st.columns(2)
    with cards[0]:
        player_card(_player_card_data(player_a), "Pemain A")
    with cards[1]:
        player_card(_player_card_data(player_b), "Pemain B")

    section_heading(
        "Perbandingan Sinyal", "Semakin panjang barnya, semakin kuat sinyalnya",
        "Komponen skor tersimpan yang sama dengan halaman Rekomendasi, disandingkan berdampingan.",
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
        index=["Skor Rekomendasi", "Fixture", "Expected", "Menit", "Value", "Histori"],
    )
    st.bar_chart(comparison, horizontal=True, height=320)

    winner = player_a if player_a.final_score >= player_b.final_score else player_b
    value_winner = player_a if player_a.value_score >= player_b.value_score else player_b
    st.success(
        f"Sinyal Keseluruhan: **{winner.name}** lebih unggul. Sinyal Value: **{value_winner.name}** lebih unggul. "
        f"Model {scoring.model_version} · {horizon} GW ke depan."
    )


def render_backtesting(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    del players, fixtures
    page_header(
        "Validasi Model",
        "Uji performa peringkat sebelum mempercayai kalibrasi model.",
        "Prediksi GW N hanya menggunakan data hingga GW N; hasil aktual diukur dari GW N+1 hingga batas horizon terpilih.",
    )
    service = st.session_state.get("backtesting_service")
    if service is None:
        render_empty_state("Layanan backtest tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi layanan backtesting.")
        return

    status = service.get_status()
    status_columns = st.columns(4)
    with status_columns[0]:
        metric_tile(
            "Baris Histori GW", f"{status.gameweek_rows:,}", "Hasil tervalidasi per pemain-laga",
            "Data historis per pemain-laga untuk memisahkan input sinyal dari hasil masa depan.",
        )
    with status_columns[1]:
        metric_tile(
            "Baris Prediksi", f"{status.prediction_rows:,}", "Tersimpan & bisa diaudit",
            "Peringkat pemain tersimpan lengkap dengan cutoff, horizon, versi model, dan hasil aktual.",
        )
    with status_columns[2]:
        metric_tile(
            "Sesi Evaluasi", str(status.runs), "Baseline & kandidat",
            "Satu evaluasi agregat per musim, horizon, dan versi model.",
        )
    with status_columns[3]:
        metric_tile(
            "Model Produksi", scoring.model_version, "Kandidat masih eksperimental",
            "Bobot produksi belum diubah sebelum teruji di berbagai musim dan batasan.",
        )

    if st.button(
        "Impor & Jalankan Ulang Backtest 2025–26",
        type="primary",
        help="Unduh file hasil laga/Gameweek historis yang telah tervalidasi dan jalankan ulang model produksi serta kandidat eksperimental untuk horizon 1, 3, dan 5 GW.",
    ):
        try:
            with st.spinner("Mengimpor hasil historis dan menjalankan seluruh cutoff bebas-kebocoran data..."):
                result = service.import_and_run()
            st.success(
                f"Backtest selesai: {result.runs} sesi evaluasi, {result.prediction_rows:,} baris prediksi, "
                f"{result.gameweek_rows:,} baris data histori."
            )
        except Exception:
            st.error("Backtest gagal dijalankan. Hasil evaluasi sukses terakhir tetap tersedia.")

    try:
        schedule_report = service.get_schedule_validation_report()
        section_heading(
            "Validasi Penyesuaian Jadwal",
            "Fase F · gate produksi anti-kebocoran data",
            "Jadwal akhir historis hanya berupa hasil. Probabilitas cuma valid diuji jika timestamp membuktikan data itu ada sebelum target GW dimulai.",
        )
        schedule_metrics = st.columns(4)
        with schedule_metrics[0]:
            metric_tile(
                "Prakiraan Layak",
                str(schedule_report.eligible_observations),
                f"{schedule_report.rejected_observations} ditolak · minimal {schedule_report.policy.minimum_observations}",
                "Snapshot probabilitas historis bertimestamp yang lolos uji cutoff tanpa kebocoran data.",
            )
        with schedule_metrics[1]:
            metric_tile(
                "Blank Brier",
                f"{schedule_report.blank_brier:.3f}" if schedule_report.blank_brier is not None else "N/A",
                f"Ambang ≤ {schedule_report.policy.maximum_blank_brier:.2f}",
                ATTRIBUTE_HELP["brier"],
            )
        with schedule_metrics[2]:
            metric_tile(
                "Double Brier",
                f"{schedule_report.double_brier:.3f}" if schedule_report.double_brier is not None else "N/A",
                f"Ambang ≤ {schedule_report.policy.maximum_double_brier:.2f}",
                ATTRIBUTE_HELP["brier"],
            )
        with schedule_metrics[3]:
            metric_tile(
                "Integrasi Transfer",
                "Aktif" if schedule_report.production_active else "Tidak Aktif",
                "Persetujuan eksplisit + seluruh gate kuantitatif lolos",
                "Bobot jadwal belum boleh mengubah urutan transfer sebelum lulus kalibrasi dan disetujui secara eksplisit.",
            )
        if schedule_report.production_active:
            st.success("Semua gate Fase F terpenuhi; bobot penyesuaian jadwal tervalidasi aktif.")
        else:
            st.warning(
                "Bobot jadwal tetap tidak aktif. " + " ".join(schedule_report.reasons)
            )
        if schedule_report.reliability_buckets:
            st.dataframe(
                pd.DataFrame([asdict(item) for item in schedule_report.reliability_buckets]),
                hide_index=True,
                width="stretch",
                column_config={
                    "mean_probability": st.column_config.NumberColumn("Rata-rata Probabilitas", format="%.3f"),
                    "observed_rate": st.column_config.NumberColumn("Tingkat Kejadian Riil", format="%.3f"),
                },
            )
            st.caption(
                "Kelompok reliabilitas membandingkan probabilitas prediksi dengan frekuensi riil. "
                f"Galat kalibrasi terbobot: {schedule_report.calibration_error:.3f}."
            )
        if schedule_report.comparison is not None:
            comparison_result = schedule_report.comparison
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Cutoff": comparison_result.evaluated_cutoffs,
                            "Baseline Top-10 Pts": comparison_result.baseline_top_10_points,
                            "Adjusted Top-10 Pts": comparison_result.adjusted_top_10_points,
                            "Poin Lift": comparison_result.top_10_points_lift,
                            "Baseline Spearman": comparison_result.baseline_spearman,
                            "Adjusted Spearman": comparison_result.adjusted_spearman,
                            "Spearman Lift": comparison_result.spearman_lift,
                        }
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        st.caption(
            "Repositori sengaja tidak memalsukan probabilitas historis retrospektif. "
            "Sebelum snapshot data prakiraan bertimestamp riil terkumpul, opsi paling aman adalah membiarkan penyesuaian tidak aktif."
        )
    except Exception as exc:
        st.warning(f"Laporan validasi jadwal tidak tersedia: {exc}")

    runs = service.list_runs()
    if not runs:
        render_empty_state(
            "Belum ada hasil backtest",
            "Klik tombol 'Impor & Jalankan Ulang Backtest 2025–26' untuk membuat evaluasi baseline dan kandidat.",
        )
        return

    available_horizons = sorted({run.horizon for run in runs})
    horizon = st.select_slider(
        "Horizon evaluasi",
        available_horizons,
        value=5 if 5 in available_horizons else available_horizons[-1],
        format_func=lambda value: f"{value} GW ke depan",
        help="Jumlah Gameweek masa depan yang dihitung pada setiap jendela evaluasi tersimpan.",
    )
    try:
        positional_report = service.get_positional_candidate_validation_report(
            horizon=horizon
        )
        section_heading(
            "Gate Rilis Kandidat Posisi",
            f"{positional_report.candidate_version} vs {positional_report.production_version} · bebas kebocoran data",
            "Setiap posisi harus memenuhi cakupan data dan tanpa regresi material. Laporan ini tidak mengubah peringkat aktif secara sepihak.",
        )
        gate_metrics = st.columns(4)
        with gate_metrics[0]:
            metric_tile(
                "Status Kandidat",
                "Disetujui" if positional_report.production_active else "Eksperimental",
                "Persetujuan eksplisit + semua gate lolos",
                "Skor produksi tetap v1.1 sampai kandidat lolos gate kuantitatif dan keputusan aktivasi dicatat resmi.",
            )
        with gate_metrics[1]:
            metric_tile(
                "Posisi Lolos",
                f"{sum(item.gate_passed for item in positional_report.evaluations)}/4",
                "Pemeriksaan cakupan & regresi",
                "Setiap posisi FPL dinilai independen agar peningkatan pada satu grup tidak menutupi penurunan di grup lain.",
            )
        with gate_metrics[2]:
            metric_tile(
                "Cakupan Minimal",
                f"{min(item.feature_coverage for item in positional_report.evaluations):.0%}",
                f"Ambang ≥ {positional_report.policy.minimum_feature_coverage:.0%}",
                "Tingkat ketersediaan data historis resmi terendah di antara 4 posisi.",
            )
        with gate_metrics[3]:
            metric_tile(
                "Gate Kuantitatif",
                "Lolos" if positional_report.quantitative_gates_passed else "Belum Memenuhi",
                "Tanpa regresi material per posisi",
                "MAE, Spearman, hit rate top-10, dan poin riil top-10 dibandingkan pada cutoff yang sama.",
            )
        evaluation_rows = []
        for item in positional_report.evaluations:
            base = item.baseline
            candidate_metrics = item.candidate
            evaluation_rows.append(
                {
                    "Position": item.position,
                    "Coverage": item.feature_coverage,
                    "Cutoffs": candidate_metrics.cutoffs if candidate_metrics else None,
                    "Predictions": candidate_metrics.predictions if candidate_metrics else None,
                    "MAE Δ": (
                        candidate_metrics.mae_percentile - base.mae_percentile
                        if base and candidate_metrics
                        else None
                    ),
                    "Spearman Δ": (
                        candidate_metrics.spearman - base.spearman
                        if base and candidate_metrics
                        else None
                    ),
                    "Top-10 hit Δ": (
                        candidate_metrics.top_10_hit_rate - base.top_10_hit_rate
                        if base and candidate_metrics
                        else None
                    ),
                    "Top-10 pts Δ": (
                        candidate_metrics.average_actual_points_top_10
                        - base.average_actual_points_top_10
                        if base and candidate_metrics
                        else None
                    ),
                    "Gate": "Pass" if item.gate_passed else "Hold",
                }
            )
        st.dataframe(
            pd.DataFrame(evaluation_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Coverage": st.column_config.NumberColumn("Cakupan Data", format="%.0f%%", help="Tingkat ketersediaan data historis resmi terendah."),
                "Cutoffs": st.column_config.NumberColumn("Cutoff", help="Jumlah snapshot Gameweek yang dievaluasi."),
                "Predictions": st.column_config.NumberColumn("Prediksi", help="Total baris peringkat pemain yang dievaluasi."),
                "MAE Δ": st.column_config.NumberColumn("MAE Δ ↓", format="%+.3f", help="Kandidat dikurangi produksi. Semakin rendah semakin bagus; nilai positif berarti performa memburuk."),
                "Spearman Δ": st.column_config.NumberColumn("Spearman Δ ↑", format="%+.3f", help="Kandidat dikurangi produksi. Semakin tinggi semakin bagus."),
                "Top-10 hit Δ": st.column_config.NumberColumn("Top-10 Hit Δ ↑", format="%+.1f%%", help="Peningkatan persentase kesesuaian top 10 kandidat vs aktual."),
                "Top-10 pts Δ": st.column_config.NumberColumn("Top-10 Poin Δ ↑", format="%+.2f", help="Selisih rata-rata perolehan poin aktual dari top 10 kandidat."),
            },
        )
        if positional_report.production_active:
            st.success("Kandidat model posisi telah memenuhi seluruh gate dan aktivasi resmi telah dicatat.")
        else:
            st.warning(
                "Kandidat model tetap tidak aktif. " + " ".join(positional_report.reasons)
            )
    except Exception as exc:
        st.info(
            "Validasi kandidat model posisi sedang menunggu hasil proses komparasi selesai. "
            f"Detail: {exc}"
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
            "MAE Terendah", f"{best_mae.mae_percentile:.2f}", best_mae.model_version,
            ATTRIBUTE_HELP["mae"],
        )
    with metric_columns[1]:
        metric_tile(
            "Spearman Terbaik", f"{best_spearman.spearman:.3f}", best_spearman.model_version,
            ATTRIBUTE_HELP["spearman"],
        )
    with metric_columns[2]:
        metric_tile(
            "Akurasi Top-10", f"{best_hit.top_10_hit_rate:.1f}%", best_hit.model_version,
            ATTRIBUTE_HELP["top_10_hit"],
        )
    with metric_columns[3]:
        metric_tile(
            "Poin Aktual Top-10", f"{best_points.average_actual_points_top_10:.2f}", best_points.model_version,
            ATTRIBUTE_HELP["top_10_points"],
        )

    section_heading(
        "Perbandingan Model",
        f"Musim 2025–26 · Cutoff GW {selected_runs[0].first_gameweek}–{selected_runs[0].last_gameweek}",
        "Semua metrik dievaluasi menggunakan daftar pemain, cutoff Gameweek, dan jendela hasil masa depan yang persis sama.",
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
            "gameweeks": st.column_config.NumberColumn("Cutoff"),
            "predictions": st.column_config.NumberColumn("Prediksi"),
            "mae_percentile": st.column_config.NumberColumn(
                "MAE ↓", format="%.3f", help=ATTRIBUTE_HELP["mae"]
            ),
            "spearman": st.column_config.NumberColumn(
                "Spearman ↑", format="%.3f", help=ATTRIBUTE_HELP["spearman"]
            ),
            "top_10_hit_rate": st.column_config.NumberColumn(
                "Akurasi Top-10 ↑", format="%.1f%%", help=ATTRIBUTE_HELP["top_10_hit"]
            ),
            "average_actual_points_top_10": st.column_config.NumberColumn(
                "Rata-rata Poin Top-10 ↑", format="%.2f", help=ATTRIBUTE_HELP["top_10_points"]
            ),
        },
    )

    production = next(
        (run for run in selected_runs if run.model_version.startswith("production-")),
        None,
    )
    candidate = next(
        (run for run in selected_runs if run.model_version == "candidate-v1.3-positional"),
        None,
    )
    if production and candidate and candidate.mae_percentile < production.mae_percentile and candidate.spearman > production.spearman:
        st.info(
            f"Keputusan kalibrasi: {candidate.model_version} meningkatkan MAE dan Spearman untuk {horizon} GW ke depan, "
            "namun statusnya tetap eksperimental. Pertahankan model produksi v1.1 sampai musim lain dan data ketersediaan memvalidasi peningkatan ini."
        )

    model_version = st.selectbox(
        "Pilih versi model",
        [run.model_version for run in selected_runs],
        help="Pilih salah satu versi model tersimpan sebelum mengaudit cutoff tertentu.",
    )
    selected_run = next(run for run in selected_runs if run.model_version == model_version)
    as_of_gameweek = st.slider(
        "Cutoff Gameweek",
        selected_run.first_gameweek,
        selected_run.last_gameweek,
        selected_run.last_gameweek,
        help="Hanya data pada atau sebelum Gameweek ini yang boleh digunakan dalam prediksi.",
    )
    predictions = service.list_predictions(
        selected_run.season, horizon, model_version, as_of_gameweek
    )
    section_heading(
        "Audit Prediksi",
        f"Per GW {as_of_gameweek} → hasil aktual GW {as_of_gameweek + 1}–{as_of_gameweek + horizon}",
        "Daftar peringkat prediksi dan hasil aktual masa depan pada satu cutoff tertentu.",
    )
    st.dataframe(
        pd.DataFrame([asdict(row) for row in predictions[:20]]),
        hide_index=True,
        width="stretch",
        column_config={
            "as_of_gameweek": None,
            "player": st.column_config.TextColumn("Pemain"),
            "position": st.column_config.TextColumn("Pos", width="small"),
            "recommendation_score": st.column_config.ProgressColumn(
                "Skor Prediksi", min_value=0, max_value=100, format="%.1f"
            ),
            "predicted_rank": st.column_config.NumberColumn("Peringkat Prediksi"),
            "actual_points": st.column_config.NumberColumn("Poin Aktual"),
            "actual_percentile": st.column_config.ProgressColumn(
                "Persentil Aktual", min_value=0, max_value=100, format="%.1f"
            ),
            "actual_rank": st.column_config.NumberColumn("Peringkat Aktual"),
        },
    )
    with st.expander("Metodologi dan Batasan Model"):
        st.write(selected_run.limitations)
        st.caption(
            "MAE membandingkan skor dengan persentil poin aktual relatif posisi di masa depan. Metrik Spearman dan top-10 "
            "mengevaluasi akurasi urutan pemain; keduanya bukan klaim prediksi poin kausal mutlak."
        )


def render_decision_tools(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    """Render practical Phase 10 transfer and captain decision support."""
    del players, fixtures
    page_header(
        "Alat Bantu Keputusan",
        "Ubah sinyal data jadi langkah transfer berikutnya.",
        "Bandingkan opsi transfer seposisi dan profil kapten menggunakan data resmi FPL, pertimbangan trade-off yang jelas, dan indikator keyakinan objektif.",
    )
    service = st.session_state.get("decision_tools_service")
    if service is None:
        render_empty_state(
            "Layanan keputusan tidak tersedia",
            "Buka kembali aplikasi untuk menginisialisasi layanan pendukung keputusan.",
        )
        return

    horizon = st.select_slider(
        "Horizon keputusan",
        [1, 3, 5, 8],
        value=scoring.default_horizon,
        format_func=lambda value: f"{value} GW ke depan",
        help="Gameweek masa depan yang digunakan untuk perbandingan transfer dan opsi kapten.",
    )
    rankings = service.player_options(horizon)
    if not rankings:
        render_empty_state(
            "Data keputusan belum tersedia",
            "Perbarui data resmi FPL dari menu Data Status sebelum menggunakan fitur ini.",
        )
        return

    st.caption(
        "Ini adalah alat bantu analisis keputusan, bukan instruksi transfer otomatis atau penentu kapten mutlak. Pastikan aturan skuad, kabar cedera terbaru, dan batas waktu deadline sebelum mengeksekusi transfer."
    )

    section_heading(
        "Pencari Opsi Transfer",
        f"Posisi sama · {horizon} GW ke depan",
        "Pemain pengganti harus terjangkau dengan sisa dana bank dan punya skor rekomendasi lebih tinggi dari pemain yang dilepas.",
    )
    transfer_controls = st.columns([1.8, 0.8])
    player_by_id = {row.player_id: row for row in rankings}
    option_ids = list(player_by_id)
    default_out = min(rankings, key=lambda row: row.final_score).player_id
    with transfer_controls[0]:
        player_out_id = st.selectbox(
            "Pemain yang ingin dilepas",
            option_ids,
            index=option_ids.index(default_out),
            format_func=lambda player_id: (
                f"{player_by_id[player_id].name} · {player_by_id[player_id].team} · "
                f"{player_by_id[player_id].position} · £{player_by_id[player_id].price:.1f}m"
            ),
            help="Pilih pemain resmi dari daftar FPL. Fitur ini mencari pengganti di posisi yang sama.",
        )
    with transfer_controls[1]:
        extra_budget = st.number_input(
            "Sisa dana di bank (£m)",
            min_value=0.0,
            max_value=15.0,
            value=0.0,
            step=0.1,
            format="%.1f",
            help="Anggaran tambahan yang tersedia selain hasil penjualan pemain terpilih.",
        )

    outgoing = player_by_id[player_out_id]
    transfers = service.transfer_recommendations(
        player_out_id, float(extra_budget), horizon
    )
    if transfers:
        best = transfers[0]
        transfer_metrics = st.columns(4)
        with transfer_metrics[0]:
            metric_tile("Pengganti Terbaik", best.replacement.name, best.replacement.category, ATTRIBUTE_HELP["score"])
        with transfer_metrics[1]:
            metric_tile("Batas Harga Maksimal", f"£{best.price_cap:.1f}m", f"Jual £{outgoing.price:.1f}m + bank", ATTRIBUTE_HELP["price"])
        with transfer_metrics[2]:
            metric_tile(
                "Proyeksi Peningkatan", f"+{best.projected_gain:.2f} pts", f"Proksi {horizon} GW ke depan",
                "Selisih antara dua proksi poin yang disesuaikan sinyal; bukan jaminan perolehan poin mutlak.",
            )
        with transfer_metrics[3]:
            metric_tile(
                "Keyakinan Keputusan", f"{best.confidence:.0f}/100", "Sinyal & ketersediaan",
                "Kombinasi transparan dari skor rekomendasi, jaminan menit, jadwal fixture, dan status pemain; bukan probabilitas.",
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
                "Replacement": st.column_config.TextColumn("Pemain Pengganti"),
                "Team": st.column_config.TextColumn("Klub"),
                "Price": st.column_config.NumberColumn("Harga", format="£%.1fm", help=ATTRIBUTE_HELP["price"]),
                "Score": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100, format="%.0f", help=ATTRIBUTE_HELP["score"]),
                "Projected points": st.column_config.NumberColumn("Proyeksi Poin", format="%.2f", help="Proksi poin yang disesuaikan sinyal untuk horizon terpilih."),
                "Projected gain": st.column_config.NumberColumn("Potensi Gain", format="%+.2f", help="Proksi pemain masuk dikurangi proksi pemain keluar."),
                "Confidence": st.column_config.ProgressColumn("Keyakinan", min_value=0, max_value=100, format="%.0f", help="Tingkat keyakinan sinyal keputusan, bukan probabilitas statistik."),
                "Trade-off": st.column_config.TextColumn("Trade-off & Pertimbangan"),
                "Model reasons": st.column_config.TextColumn("Alasan Model"),
            },
        )
    else:
        render_empty_state(
            "Tidak ada opsi pengganti seposisi yang terjangkau",
            "Tambah anggaran di bank, pilih pemain lain yang mau dilepas, atau segarkan data resmi FPL.",
        )

    section_heading(
        "Kandidat Kapten",
        f"Safe · Balanced · Differential · {horizon} GW ke depan",
        "Setiap profil memakai data resmi yang sama namun mengutamakan trade-off risiko berbeda.",
    )
    captains = service.captain_shortlist(horizon)
    if captains:
        captain_columns = st.columns(len(captains))
        for column, captain in zip(captain_columns, captains):
            with column:
                player_card(_player_card_data(captain.player), f"Kapten {captain.role}")
                st.markdown(f"**Proyeksi Poin:** {captain.projected_points:.2f} pts")
                st.markdown(f"**Keyakinan Keputusan:** {captain.confidence:.0f}/100")
                st.caption(captain.rationale)
                st.caption(captain.trade_off)
    else:
        render_empty_state(
            "Daftar kandidat kapten belum tersedia",
            "Segarkan data resmi FPL dan periksa ketersediaan pemain.",
        )

    with st.expander("Metodologi Proyeksi & Batasan Penting"):
        st.markdown(
            "**Proksi proyeksi poin** = poin per laga yang disesuaikan reliabilitas × jumlah fixture resmi pada horizon terpilih × pengali fixture. "
            "Pengali fixture bernilai `0.60 + skor fixture / 125`, sehingga skor netral 50 menghasilkan pengali 1.00. "
            "Nilai keyakinan kapten dan transfer menggabungkan skor akhir rekomendasi, jaminan menit, kemudahan fixture, dan status ketersediaan; nilai ini bukan probabilitas atau garansi perolehan poin."
        )
        st.markdown(
            "Halaman ini tidak mengimpor skuad kamu, jatah free transfer, chip, riwayat harga jual, atau bocoran lineup tak resmi. Gunakan menu Advanced Planner untuk mengimpor skuad publik kamu dan merancang draft Wildcard yang sah."
        )


def render_advanced_planner(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    """Render guarded enrichment status, custom FDR, and squad planning."""
    del players, fixtures
    page_header(
        "Perencana Lanjutan",
        "Analisis Skuad Mendalam & Rencana Wildcard",
        "Bandingkan fixture internal, impor skuad resmi FPL kamu, dapatkan rekomendasi free transfer legal, dan racik simulasi skuad wildcard.",
    )
    service = st.session_state.get("advanced_planner_service")
    if service is None:
        render_empty_state(
            "Layanan perencana tidak tersedia",
            "Buka kembali aplikasi untuk menginisialisasi layanan perencana lanjutan.",
        )
        return

    horizon = st.select_slider(
        "Horizon perencanaan",
        [1, 3, 5, 8],
        value=scoring.default_horizon,
        format_func=lambda value: f"{value} GW ke depan",
        help="Jendela fixture resmi FPL yang digunakan untuk kalkulasi tingkat kesulitan dan perankingan skuad.",
        key="advanced_horizon",
    )

    section_heading(
        "Tata Kelola Data Eksternal",
        "Belum ada penyedia data eksternal yang aktif",
        "Data eksternal hanya dapat diaktifkan setelah hak akses, ketentuan layanan, kapabilitas teknis, dan validasi identitas pemain terverifikasi.",
    )
    provider_rows = [
        {
            "Penyedia Data": status.display_name,
            "Status": status.readiness,
            "Mode Akses": status.access_mode,
            "Ketentuan": status.terms_reviewed,
            "Kapabilitas": ", ".join(status.capabilities),
            "Detail": status.detail,
        }
        for status in service.provider_statuses()
    ]
    if provider_rows:
        st.dataframe(pd.DataFrame(provider_rows), hide_index=True, width="stretch")
    st.info(
        "FotMob saat ini berstatus opsi pengembangan masa depan. Aplikasi tidak melakukan scraping atau menggunakan data FotMob sebelum jalur akses resmi dan alur validasi identitas terkonfigurasi."
    )

    section_heading(
        "Tingkat Kesulitan Fixture (Custom FDR)",
        f"Komparasi berbasis data resmi · {horizon} GW ke depan",
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
            "Tidak ada fixture mendatang",
            "Segarkan data resmi FPL dari menu Data Status.",
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
                "Team": st.column_config.TextColumn("Klub"),
                "Official ease": st.column_config.ProgressColumn(
                    "Kemudahan Resmi", min_value=0, max_value=100, format="%.1f",
                    help=ATTRIBUTE_HELP["fixture_score"],
                ),
                "Custom ease": st.column_config.ProgressColumn(
                    "Kemudahan Internal", min_value=0, max_value=100, format="%.1f",
                    help=ATTRIBUTE_HELP["custom_fdr"],
                ),
                "Difference": st.column_config.NumberColumn(
                    "Internal − Resmi", format="%+.1f",
                    help="Nilai positif menandakan model internal menilai jadwal ke depan lebih mudah dibanding FDR resmi FPL.",
                ),
                "Fixtures": st.column_config.TextColumn("Jadwal Fixture"),
            },
        )
        st.caption(
            "Kolom fixture menampilkan lawan tanding diikuti tingkat kesulitan resmi / internal. Recommendation Engine v1.1 tetap menggunakan FDR resmi; kesulitan custom hanya sebagai sinyal pembanding."
        )

    _render_schedule_risk_section(st.session_state.get("schedule_congestion_service"))

    set_piece_service = st.session_state.get("set_piece_insights_service")
    if isinstance(set_piece_service, SetPieceInsightsService):
        try:
            _render_set_piece_market_section(
                set_piece_service, service.decisions.player_options(horizon)
            )
        except Exception as exc:
            st.warning(f"Wawasan bola mati (set-piece) belum tersedia: {exc}")

    section_heading(
        "Impor Skuad & Rencana Wildcard",
        "2 GK · 5 DEF · 5 MID · 3 FWD · maks 3 per klub",
        "Impor skuad publik resmi FPL kamu untuk Gameweek aktif. Data hanya disimpan selama sesi aplikasi berjalan.",
    )
    import_controls = st.columns([1, 1.4])
    with import_controls[0]:
        default_manager_id = int(st.session_state.get("fpl_manager_id", 1))
        manager_id = st.number_input(
            "ID Manajer FPL Publik",
            min_value=1,
            value=default_manager_id,
            step=1,
            help="Nomor ID manajer dari URL resmi fantasy.premierleague.com kamu. Tidak memerlukan login atau password.",
        )
    with import_controls[1]:
        st.caption("Opsional: impor skuad kamu saat ini sebelum menyusun komparasi wildcard.")
        import_squad = st.button("Impor Skuad Resmi FPL")
    if import_squad:
        st.session_state["fpl_manager_id"] = int(manager_id)
        try:
            with st.spinner("Mengambil data skuad publik dari server resmi FPL..."):
                imported = service.import_public_squad(int(manager_id), horizon)
            st.session_state["advanced_imported_squad"] = imported
            st.session_state["advanced_imported_horizon"] = horizon
            st.session_state.pop("advanced_optimized_squad", None)
            st.session_state.pop("advanced_transfer_plan", None)
            st.session_state.pop("advanced_transfer_plan_context", None)
            st.success(
                f"Berhasil mengimpor {imported.team_name} untuk GW {imported.gameweek}: 15 pemain, sisa bank £{imported.bank:.1f}m."
            )
        except Exception as exc:
            st.error(f"Gagal mengimpor skuad: {exc}")

    imported = st.session_state.get("advanced_imported_squad")
    if st.session_state.get("advanced_imported_horizon") != horizon:
        imported = None
    if imported is not None:
        league_shortcut_cols = st.columns([3, 1])
        with league_shortcut_cols[1]:
            if st.button("🏆 Pantau Liga & Chip Rival →", key="btn_goto_leagues", help="Lihat mini-league dan pantau penggunaan chip rival kamu"):
                st.session_state["fpl_manager_id"] = int(imported.manager_id)
                st.session_state["league_auto_load"] = True
                navigate_to("League & Rivals")

        imported_metrics = st.columns(4)
        with imported_metrics[0]:
            metric_tile("Tim", imported.team_name, imported.manager_name)
        with imported_metrics[1]:
            metric_tile("Gameweek", f"GW {imported.gameweek}", "Data picks resmi FPL")
        with imported_metrics[2]:
            metric_tile("Nilai Skuad", f"£{imported.current_squad_cost:.1f}m", "Harga pasar FPL terkini")
        with imported_metrics[3]:
            metric_tile("Sisa Bank", f"£{imported.bank:.1f}m", imported.active_chip or "Tanpa chip aktif")
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

        _render_imported_squad_schedule_exposure(
            imported,
            horizon,
            st.session_state.get("schedule_congestion_service"),
        )
        if isinstance(set_piece_service, SetPieceInsightsService):
            _render_imported_squad_set_piece_insights(set_piece_service, imported)

        section_heading(
            "Rekomendasi Transfer",
            "Khusus untuk skuad kamu · Tanpa penalti poin (hit)",
            "Setiap rekomendasi menggantikan pemain dari skuad kamu dengan pemain berposisi sama yang sesuai sisa bank dan aturan maksimal 3 pemain per klub, lalu diurutkan berdasarkan skor model, jadwal fixture, kepastian menit bermain, dan ketersediaan.",
        )
        transfer_controls = st.columns([1, 1.4])
        with transfer_controls[0]:
            free_transfers = st.selectbox(
                "Jumlah Free Transfer yang Digunakan",
                [1, 2, 3, 4, 5],
                index=0,
                help="Pilih berapa jatah free transfer yang ingin kamu alokasikan. Planner tidak merekomendasikan transfer berbayar (minus poin/hit).",
                key=f"transfer_free_count_{horizon}_{imported.manager_id}",
            )
        with transfer_controls[1]:
            st.caption(
                "Endpoint picks publik FPL tidak menyertakan harga beli historis kamu, sehingga kalkulasi bujet menggunakan harga terkini di cache FPL dan sisa bank resmi."
            )
            suggest_transfers = st.button("Cari Rekomendasi Transfer", type="primary")
        transfer_context = (imported.manager_id, horizon, free_transfers)
        if suggest_transfers:
            try:
                schedule_report = None
                team_priority_adjustments = {}
                player_priority_adjustments = {}
                backtesting_service = st.session_state.get("backtesting_service")
                schedule_service = st.session_state.get("schedule_congestion_service")
                if backtesting_service is not None:
                    schedule_report = backtesting_service.get_schedule_validation_report()
                if (
                    schedule_report is not None
                    and schedule_report.production_active
                    and schedule_service is not None
                ):
                    team_priority_adjustments = current_team_priority_adjustments(
                        schedule_service.get_phase_c_snapshot(),
                        imported.gameweek,
                        horizon,
                        schedule_report,
                    )
                if isinstance(set_piece_service, SetPieceInsightsService):
                    player_priority_adjustments = set_piece_service.priority_adjustments(
                        service.decisions.player_options(horizon)
                    )
                with st.spinner("Mencari opsi upgrade transfer paling optimal untuk skuad ini..."):
                    transfer_plan = service.suggest_transfers(
                        imported,
                        horizon,
                        free_transfers=free_transfers,
                        team_priority_adjustments=team_priority_adjustments,
                        schedule_adjustment_validated=bool(
                            schedule_report and schedule_report.production_active
                        ),
                        player_priority_adjustments=player_priority_adjustments,
                    )
                st.session_state["advanced_transfer_plan"] = transfer_plan
                st.session_state["advanced_transfer_plan_context"] = transfer_context
            except Exception as exc:
                st.error(f"Rekomendasi transfer tidak dapat diproses: {exc}")

        transfer_plan = st.session_state.get("advanced_transfer_plan")
        if st.session_state.get("advanced_transfer_plan_context") != transfer_context:
            transfer_plan = None
        if transfer_plan is not None:
            if not transfer_plan.transfers:
                st.info(
                    "Pertahankan skuad (Hold): belum ada opsi upgrade pemain dengan posisi sama yang meningkatkan profil skor model sesuai sisa bujet bank."
                )
            else:
                transfer_metrics = st.columns(3)
                with transfer_metrics[0]:
                    metric_tile(
                        "Free Transfer Terpakai",
                        str(transfer_plan.free_transfers_used),
                        f"dari {free_transfers} yang dipilih",
                    )
                with transfer_metrics[1]:
                    metric_tile(
                        "Kenaikan Skor Model",
                        f"+{transfer_plan.total_score_gain:.1f}",
                        "Total peningkatan skor rekomendasi",
                        ATTRIBUTE_HELP["model_lift"],
                    )
                with transfer_metrics[2]:
                    metric_tile(
                        "Sisa Bank Setelah Transfer",
                        f"£{transfer_plan.bank_after:.1f}m",
                        "Berdasarkan harga pasar resmi FPL saat ini",
                        "Estimasi sisa saldo bank setelah seluruh opsi transfer dieksekusi.",
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
                                "Base priority": item.base_priority,
                                "Schedule Δ": item.schedule_adjustment,
                                "Set-piece Δ": item.set_piece_adjustment,
                                "Why": item.reason,
                            }
                            for item in transfer_plan.transfers
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Out": st.column_config.TextColumn("Keluar (Out)"),
                        "In": st.column_config.TextColumn("Masuk (In)"),
                        "Pos": st.column_config.TextColumn("Pos"),
                        "Price change": st.column_config.NumberColumn(
                            "Perubahan Harga", format="£%+.1fm", help=ATTRIBUTE_HELP["price_change"]
                        ),
                        "Model lift": st.column_config.NumberColumn(
                            "Kenaikan Skor", format="%+.1f", help=ATTRIBUTE_HELP["model_lift"]
                        ),
                        "Fixture lift": st.column_config.NumberColumn(
                            "Kenaikan Fixture", format="%+.1f", help=ATTRIBUTE_HELP["fixture_lift"]
                        ),
                        "Minutes lift": st.column_config.NumberColumn(
                            "Kenaikan Menit", format="%+.1f", help=ATTRIBUTE_HELP["minutes_lift"]
                        ),
                        "Base priority": st.column_config.NumberColumn(
                            "Prioritas Dasar", format="%.1f",
                            help="Prioritas transfer dasar sebelum penyesuaian risiko jadwal.",
                        ),
                        "Schedule Δ": st.column_config.NumberColumn(
                            "Δ Jadwal", format="%+.1f",
                            help="Hanya diterapkan jika semua kriteria validasi jadwal Fase F terpenuhi.",
                        ),
                        "Set-piece Δ": st.column_config.NumberColumn(
                            "Δ Bola Mati", format="%+.1f",
                            help=ATTRIBUTE_HELP["set_piece_signal"],
                        ),
                        "Why": st.column_config.TextColumn("Alasan"),
                    },
                )
                if transfer_plan.schedule_adjustment_active:
                    st.success("Penyesuaian jadwal tervalidasi aktif pada rencana transfer ini.")
                else:
                    st.caption(
                        "Penyesuaian jadwal tidak aktif: urutan transfer menggunakan formula prioritas transparan standar."
                    )
                if transfer_plan.set_piece_signal_active:
                    st.caption(
                        "Sinyal bola mati (set-piece) aktif sebagai pembeda tambahan; tidak mengubah skor dasar rekomendasi pemain."
                    )

    default_budget = imported.available_budget if imported is not None else 100.0
    planner_controls = st.columns([1, 1.4])
    with planner_controls[0]:
        budget = st.number_input(
            "Bujet Wildcard (£m)",
            min_value=70.0,
            max_value=130.0,
            value=float(default_budget),
            step=0.1,
            format="%.1f",
            help="Total bujet yang tersedia untuk menyusun 15 pemain. Skuad impor menggunakan total harga terkini ditambah sisa bank resmi.",
            key=f"wildcard_budget_{horizon}_{imported.manager_id if imported else 'manual'}",
        )
    with planner_controls[1]:
        st.caption("Optimizer ini menggunakan metode pencarian terukur (heuristik) untuk meracik kombinasi skuad terbaik.")
        build_draft = st.button("Susun Skuad Wildcard", type="primary")
    if build_draft:
        try:
            with st.spinner("Menganalisis kombinasi skuad legal terbaik..."):
                optimized = service.optimize_wildcard(float(budget), horizon)
            st.session_state["advanced_optimized_squad"] = optimized
            st.session_state["advanced_optimized_horizon"] = horizon
        except Exception as exc:
            st.error(f"Gagal menyusun skuad wildcard: {exc}")

    optimized = st.session_state.get("advanced_optimized_squad")
    if st.session_state.get("advanced_optimized_horizon") != horizon:
        optimized = None
    if optimized is not None:
        result_metrics = st.columns(4)
        with result_metrics[0]:
            metric_tile("Biaya Skuad", f"£{optimized.total_cost:.1f}m", f"Sisa bujet £{optimized.remaining_budget:.1f}m")
        with result_metrics[1]:
            metric_tile("Total Skor Skuad", f"{optimized.total_score:.1f}", "Jumlah skor rekomendasi 15 pemain")
        with result_metrics[2]:
            metric_tile("Kapten", optimized.captain.name, f"Skor {optimized.captain.final_score:.0f}")
        with result_metrics[3]:
            metric_tile("Wakil Kapten", optimized.vice_captain.name, f"Skor {optimized.vice_captain.final_score:.0f}")

        squad_rows = []
        starter_ids = {player.player_id for player in optimized.starters}
        for player in optimized.players:
            role = "Starting XI" if player.player_id in starter_ids else "Bench"
            if player.player_id == optimized.captain.player_id:
                role += " · Kapten"
            elif player.player_id == optimized.vice_captain.player_id:
                role += " · Wakil"
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
                "Role": st.column_config.TextColumn("Peran"),
                "Player": st.column_config.TextColumn("Pemain"),
                "Team": st.column_config.TextColumn("Klub"),
                "Pos": st.column_config.TextColumn("Pos"),
                "Price": st.column_config.NumberColumn("Harga", format="£%.1fm"),
                "Score": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100, format="%.0f"),
                "Fixture": st.column_config.ProgressColumn("Fixture", min_value=0, max_value=100, format="%.0f"),
                "Minutes": st.column_config.ProgressColumn("Menit", min_value=0, max_value=100, format="%.0f"),
                "Reason": st.column_config.TextColumn("Alasan"),
            },
        )

        if imported is not None:
            changes = service.compare_squads(imported, optimized)
            section_heading(
                "Perubahan Pemain Wildcard",
                f"{len(changes)} pergantian yang disarankan",
                "Pemain dari skuad lama dipasangkan dengan pemain baru di posisi yang sama untuk memudahkan komparasi.",
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
                        "Out": st.column_config.TextColumn("Keluar (Out)"),
                        "In": st.column_config.TextColumn("Masuk (In)"),
                        "Pos": st.column_config.TextColumn("Pos"),
                        "Price change": st.column_config.NumberColumn("Perubahan Harga", format="%+.1f"),
                        "Score change": st.column_config.NumberColumn("Perubahan Skor", format="%+.1f"),
                    },
                )
            else:
                st.success("Skuad impor kamu sudah identik dengan susunan draf optimizer ini.")

        with st.expander("Metodologi dan batasan perencana"):
            st.markdown(
                "Draf disusun menggunakan daftar pemain resmi FPL yang tersedia, harga terkini, skor Recommendation Engine v1.1, batasan bujet £m, kuota posisi yang tepat, dan aturan maksimal 3 pemain per klub. "
                "Algoritma heuristik mengevaluasi kombinasi kandidat terbaik lalu memilih formasi starting XI dan sinyal kapten paling optimal."
            )
            st.markdown(
                "Fitur ini tidak melakukan eksekusi transfer langsung di situs FPL, tidak mencatat histori harga jual personal, pengurangan poin akibat hit, ataupun berita tim mendadak mendekati deadline. Pastikan untuk selalu memeriksa kembali skuad akhir di website/aplikasi resmi FPL sebelum batas waktu deadline."
            )


def _render_schedule_risk_section(schedule_service: object) -> None:
    """Render Phase D schedule-risk signals without changing transfer priorities."""
    section_heading(
        "Kepadatan Jadwal & Risiko GW",
        "Fase D · Fakta resmi FPL diutamakan, proyeksi hanya berbasis data valid",
        risk_status_help(),
    )
    if schedule_service is None:
        render_empty_state("Data risiko jadwal tidak tersedia", "Buka kembali aplikasi untuk menginisialisasi layanan kepadatan jadwal.")
        return
    try:
        snapshot = schedule_service.get_phase_c_snapshot()  # type: ignore[attr-defined]
    except Exception as exc:
        st.warning(f"Menunggu snapshot kalender resmi FPL yang valid: {exc}")
        return

    phase_b = snapshot.phase_b
    strip_rows = build_risk_strip_rows(
        phase_b.gameweek_risks,
        snapshot.fixture_projections,
        snapshot.double_gameweek_projections,
    )
    strip_html = "".join(
        (
            f'<div class="schedule-risk-pill risk-{row["status_class"]}" title="{row["title"]}">'
            f'<strong>GW{row["gameweek"]}</strong><span>{row["status_label"]}</span>'
            f'<small>B {row["blank_count"]} · D {row["double_count"]}</small>'
            f'<small>{row["probability"]}</small></div>'
        )
        for row in strip_rows
    )
    st.markdown(f'<div class="schedule-risk-strip">{strip_html}</div>', unsafe_allow_html=True)
    st.caption(
        "Arahkan kursor ke pill GW untuk melihat status lengkap. B = blank exposure (laga kosong), D = double exposure (laga ganda). "
        "Warna hijau berarti satu laga resmi per klub; abu-abu berarti jadwal resmi belum lengkap."
    )
    if not snapshot.fixture_projections and not snapshot.double_gameweek_projections:
        st.info(
            "Belum ada proyeksi probabilitas aktif. Status blank/double yang sudah pasti tetap ditampilkan dari alokasi resmi FPL; perkiraan peluang laga tunda hanya muncul jika data terverifikasi telah dikonfigurasi."
        )
    with st.expander("Definisi, sumber data & waktu pembaruan"):
        source_url = phase_b.gameweek_risks[0].source_url if phase_b.gameweek_risks else "Tidak tersedia"
        as_of = phase_b.gameweek_risks[0].as_of.isoformat() if phase_b.gameweek_risks else "Tidak tersedia"
        st.markdown(
            f"**Model:** Analisis deskriptif risiko jadwal Fase D; tidak mengubah skor Recommendation Engine.  \n"
            f"**Probabilitas:** Peluang berbasis data terverifikasi, saat ini belum aktif karena tidak ada data asumsi tanpa bukti.  \n"
            f"**Tingkat Keyakinan:** Ditampilkan pada proyeksi mendatang berdasarkan bukti terlemah.  \n"
            f"**Blank / Double:** Dikonfirmasi pasti hanya saat FPL resmi menetapkan 0 / minimal 2 laga pada suatu GW.  \n"
            f"**Kepadatan:** Skor beban tanding dari densitas laga, jeda istirahat, dan keikutsertaan kompetisi Eropa.  \n"
            f"**Sumber:** [{source_url}]({source_url}) · **Per:** `{as_of}` · **Input probabilitas:** `{snapshot.probability_catalog.model_version}` ({len(snapshot.probability_catalog.inputs)} data)."
        )

    european_ids = {entry.fpl_team_id for entry in phase_b.catalog.participants}
    matrix_controls = st.columns([1, 1, 1])
    with matrix_controls[0]:
        team_filter = st.selectbox(
            "Filter klub", ("Semua klub", "Klub kompetisi Eropa"),
            key="schedule_risk_team_filter",
            help="Klub Eropa mengacu pada daftar peserta kompetisi Eropa terverifikasi pada musim 2026/27.",
        )
    with matrix_controls[1]:
        matrix_window = st.selectbox(
            "Jendela matriks", ("5 GW ke depan", "8 GW ke depan", "Satu musim penuh"),
            key="schedule_risk_matrix_window",
            help="Membatasi kolom yang ditampilkan; tidak mengubah perhitungan risiko jadwal dasar.",
        )
    with matrix_controls[2]:
        st.checkbox(
            "Hanya yang sudah pasti (Confirmed)", value=True, key="schedule_risk_confirmed_only",
            help="Status pasti (confirmed) bersumber langsung dari alokasi fixture resmi FPL.",
        )
    matrix_end = {"5 GW ke depan": 5, "8 GW ke depan": 8, "Satu musim penuh": 38}[matrix_window]
    matrix_rows = build_team_risk_matrix(
        phase_b.gameweek_risks, phase_b.team_names, tuple(range(1, matrix_end + 1)),
        european_ids if team_filter == "Klub kompetisi Eropa" else None,
    )
    if not matrix_rows:
        render_empty_state("Tidak ada klub pada tampilan ini", "Ubah filter klub atau segarkan data resmi FPL.")
    else:
        st.dataframe(
            pd.DataFrame(matrix_rows), hide_index=True, width="stretch",
            height=min(560, 115 + 35 * len(matrix_rows)),
            column_config={
                "Club": st.column_config.TextColumn("Klub", help="Nama resmi klub di FPL."),
                "Code": st.column_config.TextColumn("Kode", help="Singkatan resmi klub di FPL."),
            },
        )
        st.caption(
            "Keterangan matriks: B = confirmed blank (kosong), D = confirmed double (laga ganda), · = satu laga resmi. "
            "Sinyal probabilitas dipisah agar tidak mengubah data resmi secara diam-diam."
        )

    section_heading(
        "Klub Jadwal Terpadat", "14 hari ke depan · Indikator beban tanding",
        "Skor memadukan jumlah laga (40%), jeda istirahat tersingkat (30%), jarak tempuh laga tandang (15%), dan bobot kompetisi (15%). Skor ini bukan prediksi poin atau menit bermain.",
    )
    leader_rows = build_congestion_leader_rows(phase_b.congestion_leaders)
    if not leader_rows:
        render_empty_state("Tidak ada sinyal kepadatan jadwal", "Jadwal kickoff mendatang belum tersedia di cache resmi.")
    else:
        st.dataframe(
            pd.DataFrame(leader_rows), hide_index=True, width="stretch",
            column_config={
                "Club": st.column_config.TextColumn("Klub"),
                "Congestion score": st.column_config.ProgressColumn(
                    "Skor Kepadatan", min_value=0, max_value=100, format="%.1f",
                    help="Skor deskriptif terukur: densitas pertandingan, jeda istirahat singkat, dan keikutsertaan kompetisi Eropa.",
                ),
                "Shortest rest (days)": st.column_config.NumberColumn(
                    "Jeda Singkat (Hari)", help="Jumlah hari istirahat paling sedikit di antara dua pertandingan resmi dalam 14 hari ke depan."
                ),
            },
        )
        st.caption(
            "Sumber: Cache fixture resmi FPL + kalender peserta kompetisi Eropa musim 2026/27 terverifikasi. "
            "Waktu pembaruan dan tautan sumber data tetap tersedia di kontrak integritas data."
        )


def _render_imported_squad_schedule_exposure(
    imported: ImportedSquad,
    horizon: int,
    schedule_service: object,
) -> None:
    """Show a session-only schedule view for the user's imported official squad."""
    section_heading(
        "Eksposur Jadwal Skuad Kamu",
        f"Skuad impor · GW{imported.gameweek}–GW{min(38, imported.gameweek + horizon - 1)}",
        "Hanya menggunakan data skuad impor selama sesi browser ini. Bagian ini merupakan analisis risiko terpisah dan tidak mengubah prioritas transfer.",
    )
    if schedule_service is None:
        st.info("Eksposur jadwal akan muncul setelah layanan kepadatan jadwal terinisialisasi.")
        return
    try:
        snapshot = schedule_service.get_phase_c_snapshot()  # type: ignore[attr-defined]
        exposure = calculate_squad_schedule_exposure(imported, snapshot, horizon)
    except Exception as exc:
        st.warning(f"Tidak dapat menghitung eksposur jadwal skuad: {exc}")
        return

    metrics = st.columns(3)
    with metrics[0]:
        metric_tile(
            "Starter Berpotensi Blank",
            f"{exposure.expected_blank_starters:.2f}",
            "Berbobot antara starter, cadangan, dan kapten",
            ATTRIBUTE_HELP["schedule_blank"],
        )
    with metrics[1]:
        metric_tile(
            "Potensi Laga Ekstra",
            f"{exposure.expected_extra_fixtures:.2f}",
            "Jadwal pasti plus proyeksi berbasis data",
            ATTRIBUTE_HELP["schedule_double"],
        )
    with metrics[2]:
        highest_congestion = max(
            (item.congestion_score or 0 for item in exposure.affected_players),
            default=0,
        )
        metric_tile(
            "Beban Jadwal Tertinggi",
            f"{highest_congestion:.1f}/100",
            "Sinyal beban tanding klub tertinggi di skuad kamu",
            ATTRIBUTE_HELP["schedule_congestion"],
        )

    exposure_rows = build_squad_exposure_rows(exposure)
    if exposure_rows:
        st.dataframe(
            pd.DataFrame(exposure_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Player": st.column_config.TextColumn("Pemain"),
                "Club": st.column_config.TextColumn("Klub"),
                "Role": st.column_config.TextColumn("Peran"),
                "Squad weight": st.column_config.NumberColumn(
                    "Bobot Skuad", format="%.2f",
                    help="Starter 1.00; bench outfield 0.35; bench kiper 0.20; kapten mendapat tambahan 1.00.",
                ),
                "Expected blank": st.column_config.NumberColumn(
                    "Potensi Blank", format="%.2f", help=ATTRIBUTE_HELP["schedule_blank"]
                ),
                "Expected extra fixtures": st.column_config.NumberColumn(
                    "Potensi Laga Ekstra", format="%.2f", help=ATTRIBUTE_HELP["schedule_double"]
                ),
                "Congestion": st.column_config.ProgressColumn(
                    "Kepadatan Jadwal", min_value=0, max_value=100, format="%.1f",
                    help=ATTRIBUTE_HELP["schedule_congestion"],
                ),
            },
        )
    else:
        st.success("Tidak ada potensi laga blank maupun double pada jendela perencanaan ini.")
    if exposure.unresolved_player_ids:
        st.warning(
            "Beberapa pemain di skuad impor tidak dapat dipetakan ke klub resmi FPL: "
            + ", ".join(str(player_id) for player_id in exposure.unresolved_player_ids)
        )
    st.caption(
        "Bagian ini bersifat informatif untuk membantu keputusan manajer tanpa mengubah formula prioritas transfer secara sepihak."
    )


def _render_set_piece_market_section(
    set_piece_service: SetPieceInsightsService,
    rankings: tuple[object, ...],
) -> None:
    """Render a source-dated market view without modifying the base model score."""
    catalog = set_piece_service.catalog
    insights = set_piece_service.player_insights(rankings)  # type: ignore[arg-type]
    section_heading(
        "Wawasan Bola Mati (Set-Piece)",
        f"Peran pengambil · Snapshot musim {catalog.season} · per {catalog.as_of}",
        "Faktor penentu tambahan untuk penalti, tendangan bebas langsung, dan sepak pojok. Ditampilkan terpisah dari skor dasar FPL Signal karena eksekutor dapat berubah tergantung susunan pemain inti dan situasi laga.",
    )
    metrics = st.columns(3)
    with metrics[0]:
        metric_tile(
            "Pemain Terdata",
            str(len(insights)),
            "Disesuaikan dengan cache pemain resmi FPL saat ini",
            ATTRIBUTE_HELP["set_piece_signal"],
        )
    with metrics[1]:
        metric_tile(
            "Klub Terliput",
            str(len(catalog.teams)),
            "Snapshot peran bola mati tim",
        )
    with metrics[2]:
        metric_tile(
            "Konteks Historis",
            catalog.historical_season,
            catalog.historical_metric_label,
            ATTRIBUTE_HELP["historical_set_piece_goals"],
        )
    if not insights:
        st.info("Tidak ada peran pengambil bola mati yang cocok dengan cache pemain FPL saat ini.")
        return
    rows = [
        {
            "Player": insight.player_name,
            "Team": insight.team_name,
            "Expected duties": insight.role_summary,
            "Role signal": insight.role_signal,
            f"{insight.historical_season} SPG": insight.historical_set_piece_goals,
        }
        for insight in insights
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        height=min(520, 115 + 35 * len(rows)),
        column_config={
            "Player": st.column_config.TextColumn("Pemain"),
            "Team": st.column_config.TextColumn("Klub"),
            "Expected duties": st.column_config.TextColumn("Tugas Bola Mati"),
            "Role signal": st.column_config.NumberColumn(
                "Sinyal Peran", format="%.1f", help=ATTRIBUTE_HELP["set_piece_signal"]
            ),
            f"{catalog.historical_season} SPG": st.column_config.NumberColumn(
                f"Gol Bola Mati {catalog.historical_season}",
                help=ATTRIBUTE_HELP["historical_set_piece_goals"],
            ),
        },
    )
    st.caption(catalog.limitations)
    st.markdown(
        f"Sumber peran: [{catalog.source_label}]({catalog.source_url}) · "
        f"Sumber riwayat gol: [konteks tim historis]({catalog.historical_source_url})"
    )


def _render_imported_squad_set_piece_insights(
    set_piece_service: SetPieceInsightsService,
    imported: ImportedSquad,
) -> None:
    """Show only expected set-piece holders from the imported squad."""
    insights = set_piece_service.player_insights(
        (pick.player for pick in imported.picks)
    )
    section_heading(
        "Eksposur Bola Mati Skuad Kamu",
        "Skuad impor · Peran eksekutor di lapangan",
        "Membantu kamu memetakan siapa saja penendang penalti, tendangan bebas, dan sepak pojok di tim kamu saat ini. Tampilan ini adalah proyeksi berdasarkan riwayat dan tidak menjamin eksekutor pasti di laga berikutnya.",
    )
    if not insights:
        st.info("Tidak ada pemain di skuad impor yang terdaftar sebagai eksekutor bola mati pada snapshot saat ini.")
        return
    penalty_holders = sum(
        any(role.role_type == "penalties" for role in insight.roles)
        for insight in insights
    )
    metrics = st.columns(2)
    with metrics[0]:
        metric_tile(
            "Pemain Eksekutor",
            str(len(insights)),
            "Pemain di skuad kamu yang memiliki tugas bola mati",
            ATTRIBUTE_HELP["set_piece_signal"],
        )
    with metrics[1]:
        metric_tile(
            "Eksekutor Penalti",
            str(penalty_holders),
            "Dapat berupa penendang utama, kedua, atau situasional",
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Player": insight.player_name,
                    "Team": insight.team_name,
                    "Expected duties": insight.role_summary,
                    "Role signal": insight.role_signal,
                    f"{insight.historical_season} SPG": insight.historical_set_piece_goals,
                }
                for insight in insights
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Player": st.column_config.TextColumn("Pemain"),
            "Team": st.column_config.TextColumn("Klub"),
            "Expected duties": st.column_config.TextColumn("Tugas Bola Mati"),
            "Role signal": st.column_config.NumberColumn(
                "Sinyal Peran", format="%.1f", help=ATTRIBUTE_HELP["set_piece_signal"]
            ),
            f"{set_piece_service.catalog.historical_season} SPG": st.column_config.NumberColumn(
                f"Gol Bola Mati {set_piece_service.catalog.historical_season}",
                help=ATTRIBUTE_HELP["historical_set_piece_goals"],
            ),
        },
    )


def render_data_status(
    players: pd.DataFrame, fixtures: pd.DataFrame, scoring: ScoringConfig
) -> None:
    page_header(
        "Status Sistem & Data",
        "Transparansi Penuh Sumber & Integritas Data",
        "Pantau sumber data resmi, kesegaran data, cakupan database, versi model, dan batasan data sebelum mengambil keputusan.",
    )
    ingestion_status = st.session_state.get("ingestion_status", {})
    refresh_status = ingestion_status.get("refresh", {})
    last_refresh = refresh_status.get("last_successful_at") or "Belum pernah"
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
            "Mode Aplikasi", "Resmi FPL", "Semua halaman menggunakan cache resmi FPL",
            "Aplikasi tidak menggunakan data pemain atau fixture buatan (mock).",
        )
    with status_columns[1]:
        metric_tile("Kesegaran Data", freshness, freshness_detail, "Usia data sejak pembaruan resmi FPL terakhir yang berhasil.")
    with status_columns[2]:
        metric_tile(
            "Cakupan Data",
            f"{current_stats_count}/{player_count}",
            f"Statistik terkini · {missing_current_stats} belum sinkron",
            "Jumlah statistik pemain resmi yang tersimpan di database SQLite lokal.",
        )
    with status_columns[3]:
        metric_tile("Sinkronisasi Terakhir", last_refresh[:19] if last_refresh != "Belum pernah" else last_refresh, "UTC")

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
    positional_report = None
    if backtesting_service is not None:
        try:
            positional_report = backtesting_service.get_positional_candidate_validation_report(
                horizon=5
            )
        except Exception:
            # Data Status must remain usable when a historical candidate has not
            # been imported yet or its report is unavailable.
            positional_report = None
    action_columns = st.columns(2)
    if fpl_service is not None:
        with action_columns[0]:
            refresh_fpl = st.button("Refresh official FPL data", type="primary")
        if refresh_fpl:
            try:
                with st.spinner("Mengambil, memvalidasi, dan menyimpan data resmi FPL..."):
                    result = fpl_service.refresh()
                st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.success(
                    f"Pembaruan selesai: {result.players} pemain, {result.teams} klub, "
                    f"{result.fixtures} fixture."
                )
            except Exception:
                st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.error("Pembaruan gagal. Data terakhir yang berhasil tetap tersedia; periksa detail error di bawah.")

    if historical_service is not None:
        with action_columns[1]:
            import_history = st.button(
                "Import historical seasons",
                help="Unduh, validasi, arsipkan, dan impor musim historis terkonfigurasi secara aman (idempoten).",
            )
        if import_history:
            try:
                with st.spinner("Mengimpor data musim historis dan memetakan identitas pemain..."):
                    result = historical_service.import_default_seasons()
                recommendation_service = st.session_state.get("recommendation_engine_service")
                if recommendation_service is not None:
                    recommendation_service.clear_cache()
                if fpl_service is not None:
                    st.session_state["ingestion_status"] = asdict(fpl_service.get_status())
                st.success(
                    f"Impor data historis selesai: {result.seasons} musim, {result.rows} baris data, "
                    f"{result.matched} cocok, {result.review} tinjauan, {result.scores} skor."
                )
            except Exception:
                st.error("Validasi impor historis gagal. Dataset dan skor sebelumnya tetap aman.")

    if refresh_status.get("last_error"):
        st.warning(f"Error pembaruan terakhir: {refresh_status['last_error']}")

    core_status = st.session_state.get("core_status", {})
    database_detail = "Skema belum diinisialisasi"
    database_status = "Belum siap"
    if core_status.get("database_ready"):
        database_status = "Siap"
        database_detail = (
            f"Skema v{core_status.get('schema_version')} · "
            f"{core_status.get('table_count')} tabel"
        )

    section_heading(
        "Kesiapan Pipeline & Cakupan Data", "Fase F · Kesiapan operasional sistem",
        "Transparansi data memastikan baris cache yang hilang teridentifikasi jelas; riwayat laga pemain disimpan on-demand sesuai kebutuhan.",
    )
    readiness = pd.DataFrame(
        [
            ["Antarmuka aplikasi", "Siap", "Semua rute MVP berfungsi"],
            ["API Resmi FPL", "Siap", "Pembaruan manual dengan validasi dan mekanisme retry"],
            ["Klien FPL", "Siap", "Timeout, retry, cache, dan validasi"],
            ["SQLite", database_status, database_detail],
            [
                "Statistik pemain saat ini",
                "Siap" if player_count and not missing_current_stats else "Celah data",
                f"{current_stats_count}/{player_count} baris · {missing_current_stats} belum sinkron",
            ],
            [
                "Snapshot Gameweek",
                "Siap" if player_count and not missing_snapshots else "Celah data",
                f"{snapshot_count}/{player_count} baris · {missing_snapshots} belum sinkron",
            ],
            ["Matriks fixture", "Siap", "FDR resmi FPL dihitung untuk 1, 3, 5, dan 8 GW"],
            [
                "Tingkat kesulitan custom (FDR)",
                "Siap",
                "FDR resmi + kekuatan relatif lawan + status kandang/tandang; sinyal pembanding",
            ],
            [
                "Recommendation Engine V1",
                "Siap" if expected_scores and not missing_scores else "Celah data",
                f"{score_count}/{expected_scores} skor tersimpan · {missing_scores} belum ada · {scoring.model_version}",
            ],
            [
                "Kontrak endpoint resmi",
                "Siap",
                "Data utama bootstrap divalidasi sebelum disimpan ke DB lokal",
            ],
            [
                "Gate kandidat posisi",
                (
                    "Disetujui"
                    if positional_report is not None and positional_report.production_active
                    else "Eksperimental"
                ),
                (
                    f"{positional_report.candidate_version} · "
                    f"{sum(item.gate_passed for item in positional_report.evaluations)}/4 posisi lolos gate"
                    if positional_report is not None
                    else "Jalankan impor historis / backtest untuk menghitung gate rilis"
                ),
            ],
            [
                "Riwayat Gameweek pemain",
                "On-demand",
                f"{ingestion_status.get('gameweek_history_in_database', 0)} baris dari "
                f"{ingestion_status.get('history_synced_players_in_database', 0)}/{player_count} pemain tersinkron",
            ],
            [
                "Rekayasa fitur (Features)",
                "Siap",
                f"Rolling 3/5/10 · per-90 · minimal {scoring.minimum_minutes} menit",
            ],
            [
                "Penyimpanan snapshot mentah",
                freshness,
                f"{freshness_detail} Pembaruan terakhir: {last_refresh[:19] if last_refresh != 'Belum pernah' else last_refresh}",
            ],
            [
                "Dataset historis",
                "Siap" if ingestion_status.get("historical_seasons_in_database", 0) else "Belum diimpor",
                f"{ingestion_status.get('historical_seasons_in_database', 0)} musim · "
                f"{ingestion_status.get('historical_rows_in_database', 0)} baris data pemain-musim tervalidasi",
            ],
            [
                "Pemetaan identitas historis",
                "Siap" if ingestion_status.get("historical_matched_in_database", 0) else "Menunggu impor",
                f"{ingestion_status.get('historical_matched_in_database', 0)} cocok · "
                f"{ingestion_status.get('historical_review_in_database', 0)} tinjauan · "
                f"{ingestion_status.get('historical_unmatched_in_database', 0)} tidak cocok",
            ],
            [
                "Skor stabilitas historis",
                "Siap" if ingestion_status.get("historical_scores_in_database", 0) else "Menunggu data cocok",
                f"{ingestion_status.get('historical_scores_in_database', 0)}/{player_count} pemain aktif dinilai · "
                "skor netral 50 jika tidak ada riwayat",
            ],
            [
                "Dataset backtest berbasis waktu",
                "Siap" if backtest_status and backtest_status.gameweek_rows else "Belum diimpor",
                (
                    f"{backtest_status.gameweek_rows} baris pemain-fixture · "
                    f"{backtest_status.fixture_rows} fixture"
                    if backtest_status
                    else "Layanan backtesting tidak tersedia"
                ),
            ],
            [
                "Kalibrasi model",
                "Siap" if backtest_status and backtest_status.runs else "Menunggu pengujian",
                (
                    f"{backtest_status.runs} kali pengujian · {backtest_status.prediction_rows} prediksi tersimpan"
                    if backtest_status
                    else "Layanan backtesting tidak tersedia"
                ),
            ],
            [
                "Impor skuad & perencana wildcard",
                "Siap" if advanced_service is not None else "Tidak tersedia",
                "Picks resmi publik · draf 15 pemain legal · impor khusus sesi aktif",
            ],
            [
                "Pengayaan data FotMob",
                fotmob_status.readiness if fotmob_status is not None else "Belum dikonfigurasi",
                fotmob_status.detail if fotmob_status is not None else "Kebijakan penyedia data belum tersedia",
            ],
        ],
        columns=["Komponen", "Status", "Detail"],
    )
    st.dataframe(readiness, hide_index=True, width="stretch")

    with st.expander("Sumber Data Resmi, Pembaruan & Prosedur Rollback"):
        st.markdown(
            "**Sumber resmi.** Peringkat musim berjalan menggunakan `bootstrap-static` dan jadwal "
            "resmi FPL. Kolom data utama divalidasi sebelum diproses; atribut posisi opsional yang "
            "tidak disediakan oleh FPL ditampilkan sebagai *Tidak tersedia* dan bukan nol.\n\n"
            "**Setelah deployment.** Aplikasi secara otomatis menjalankan migrasi SQLite ke depan. "
            "Setelah migrasi skema, klik **Refresh official FPL data** untuk mengisi data resmi "
            "terbaru. Untuk kandidat model posisi, jalankan impor/backtest agar cakupan data "
            "dan kriteria gate evaluasi dapat dihitung ulang.\n\n"
            "**Status model.** Model `v1.1` aktif di tahap produksi; `candidate-v1.3-positional` berstatus eksperimental "
            "hingga kriteria evaluasi spesifik posisi dan persetujuan aktivasi resmi terpenuhi. Rincian changelog "
            "dan prosedur rollback terdokumentasi di `docs/MODEL_CHANGELOG.md`."
        )

    if historical_service is not None and ingestion_status.get("historical_review_in_database", 0):
        with st.expander(
            f"Antrean tinjauan identitas pemain ({ingestion_status.get('historical_review_in_database', 0)})"
        ):
            st.caption(
                "Hanya kandidat TINJAUAN yang belum terselesaikan yang dikecualikan dari perhitungan skor; kecocokan unik di atas 90% dan penetapan manual diperlakukan sebagai COCOK."
            )
            review_rows = historical_service.get_review_queue(limit=20)
            st.dataframe(
                pd.DataFrame([asdict(row) for row in review_rows]),
                hide_index=True,
                width="stretch",
                column_config={
                    "season": st.column_config.TextColumn("Musim"),
                    "historical_name": st.column_config.TextColumn("Pemain historis"),
                    "position": st.column_config.TextColumn("Pos", width="small"),
                    "candidate_name": st.column_config.TextColumn("Kandidat saat ini"),
                    "match_score": st.column_config.ProgressColumn(
                        "Tingkat kecocokan", min_value=0, max_value=100, format="%.0f%%"
                    ),
                    "match_method": st.column_config.TextColumn("Metode"),
                },
            )

    section_heading("Pratinjau Status", "Alat validasi tampilan UI")
    preview = st.selectbox(
        "Pratinjau status tampilan", ["Normal", "Kosong", "Error"],
        help="Alat bantu untuk memverifikasi tampilan dalam kondisi normal, kosong, dan error.",
    )
    if preview == "Normal":
        st.success("Cache fixture resmi dan seluruh rute navigasi berfungsi normal.")
    elif preview == "Kosong":
        render_empty_state("Tidak ada data tersedia", "Segarkan data atau sesuaikan filter pencarian.")
    else:
        st.error("Contoh tampilan error: dataset terakhir yang berhasil tetap akan terlihat di sini.")

    with st.expander("Konfigurasi pembobotan skor (Scoring configuration)"):
        st.json(scoring.position_weights)


def render_league_rivals(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    scoring: ScoringConfig,
) -> None:
    """Render official mini-league standings with live rival chip tracking."""
    service = st.session_state.get("league_analytics_service")
    if service is None:
        service = get_league_analytics_service()

    ingestion = st.session_state.get("fpl_ingestion_service")
    current_gw = 0
    if ingestion is not None and hasattr(ingestion, "status_store"):
        try:
            current_gw = ingestion.status_store.load().current_gameweek or 0
        except Exception:
            current_gw = 0

    if current_gw <= 0:
        try:
            bootstrap = service.client.get_bootstrap()
            for ev in bootstrap.get("events", []):
                if ev.get("is_current"):
                    current_gw = int(ev["id"])
                    break
                if ev.get("is_next") and current_gw <= 0:
                    current_gw = max(1, int(ev["id"]) - 1)
        except Exception:
            pass

    page_header(
        "Mini-League & Rival Scout",
        "Klasemen Liga & Pelacak Chip",
        "Pantau mini-league kamu, lacak pemakaian chip rival (WC1, WC2, Free Hit, Triple Captain, Bench Boost), pilihan kapten, dan kalkulasi jarak poin ke puncak klasemen.",
    )

    section_heading(
        "Profil Manajer FPL",
        "Data publik resmi FPL",
        "Masukkan FPL Manager ID kamu untuk menemukan seluruh private dan broad mini-league yang kamu ikuti.",
    )

    col_input, col_action = st.columns([1, 1.4])
    default_id = int(st.session_state.get("fpl_manager_id", 1158066))
    with col_input:
        manager_id = st.number_input(
            "FPL Manager ID",
            min_value=1,
            value=default_id,
            step=1,
            help="Nomor ID manajer dari URL tim kamu di fantasy.premierleague.com.",
            key="league_manager_id_input",
        )
    with col_action:
        st.caption("Tarik data liga langsung dari server resmi FPL.")
        load_leagues = st.button("Muat Liga Manajer", type="primary", key="btn_load_leagues")

    auto_load = bool(st.session_state.pop("league_auto_load", False))
    should_load = load_leagues or auto_load

    if should_load:
        st.session_state["fpl_manager_id"] = int(manager_id)
        with st.spinner("Mengambil data liga dari server resmi FPL..."):
            try:
                leagues = service.get_manager_leagues(int(manager_id))
                entry_info = service.client.get_entry(int(manager_id))
                st.session_state["discovered_leagues"] = leagues
                st.session_state["discovered_entry_info"] = entry_info
                st.session_state["league_active_manager_id"] = int(manager_id)
            except Exception as exc:
                st.error(f"Gagal memuat profil manajer: {exc}")
                return

    leagues = st.session_state.get("discovered_leagues", ())
    entry_info = st.session_state.get("discovered_entry_info", {})

    if not leagues:
        if "discovered_leagues" in st.session_state:
            render_empty_state("Tidak ada liga ditemukan", "ID manajer ini belum bergabung ke private maupun public mini-league.")
        else:
            render_action_state(
                "Pantau Mini-League Kamu",
                "Masukkan FPL Manager ID kamu di atas lalu klik 'Muat Liga Manajer' untuk membedah klasemen, riwayat chip rival, dan pilihan kapten.",
            )
        return

    mgr_name = f"{entry_info.get('player_first_name', '')} {entry_info.get('player_last_name', '')}".strip()
    team_name = entry_info.get("name", "Unknown team")
    overall_rank = entry_info.get("summary_overall_rank")
    overall_pts = entry_info.get("summary_overall_points")
    rank_disp = f"#{overall_rank:,}" if overall_rank else "-"

    st.markdown(
        f"""
        <div class="sample-banner" style="margin-top: 0.5rem; margin-bottom: 1.2rem;">
            <div>
                <strong>Manajer:</strong> {escape(mgr_name)} &nbsp;·&nbsp; 
                <strong>Tim:</strong> {escape(team_name)} &nbsp;·&nbsp; 
                <strong>Overall Rank:</strong> {rank_disp} &nbsp;·&nbsp; 
                <strong>Total Poin:</strong> {overall_pts or 0}
            </div>
            <span class="sample-chip">ID {manager_id}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    private_leagues = [l for l in leagues if l.is_private]
    broad_leagues = [l for l in leagues if not l.is_private]

    section_heading(
        "Pilih liga yang ingin dipantau",
        f"{len(private_leagues)} private mini-league · {len(broad_leagues)} broad league",
        "Pilih salah satu liga untuk membedah klasemen, riwayat chip, dan kapten lawan.",
    )

    tab_priv, tab_broad = st.tabs([
        f"🏆 Private Mini-League ({len(private_leagues)})",
        f"🌐 Broad League ({len(broad_leagues)})",
    ])

    selected_league = None

    with tab_priv:
        if private_leagues:
            league_options = {
                f"{l.name} (Rank: #{l.entry_rank or '-'})": l for l in private_leagues
            }
            choice = st.selectbox(
                "Pilih private mini-league",
                options=list(league_options.keys()),
                key="select_priv_league",
            )
            selected_league = league_options[choice]
        else:
            st.info("Tidak ada private mini-league untuk manajer ini.")

    with tab_broad:
        if broad_leagues:
            broad_options = {
                f"{l.name} (Rank: #{l.entry_rank or '-'})": l for l in broad_leagues
            }
            choice_broad = st.selectbox(
                "Pilih broad / public league",
                options=list(broad_options.keys()),
                key="select_broad_league",
            )
            if not private_leagues:
                selected_league = broad_options[choice_broad]
            elif st.checkbox("Analisa broad league ini", key="chk_broad_instead"):
                selected_league = broad_options[choice_broad]
        else:
            st.info("Tidak ada broad league ditemukan.")

    if selected_league is None:
        return

    st.divider()
    report_cache_key = f"league_report_{selected_league.id}_{manager_id}"
    report = st.session_state.get(report_cache_key)
    if report is None or load_leagues:
        with st.spinner(f"Menganalisa klasemen {selected_league.name} dan status chip rival..."):
            try:
                report = service.analyze_classic_league(
                    league_id=selected_league.id,
                    user_entry_id=int(manager_id),
                    current_gameweek=current_gw,
                    page=1,
                    max_teams_to_enrich=50,
                )
                st.session_state[report_cache_key] = report
            except Exception as exc:
                st.error(f"Gagal menganalisa liga {selected_league.name}: {exc}")
                return

    user_row = next((r for r in report.standings if r.is_user), None)
    user_rank_str = f"#{user_row.rank}" if user_row else f"#{selected_league.entry_rank or '-'}"
    rank_change_txt = ""
    if user_row and user_row.last_rank > 0:
        chg = user_row.rank_change
        if chg > 0:
            rank_change_txt = f"▲ +{chg} dari pekan lalu"
        elif chg < 0:
            rank_change_txt = f"▼ {chg} dari pekan lalu"
        else:
            rank_change_txt = "Peringkat tidak berubah"

    total_teams_display = report.total_league_teams or report.chip_summary.total_teams

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        rank_subtitle = rank_change_txt or f"Total {total_teams_display} tim"
        if user_row:
            rank_subtitle = f"dari {total_teams_display} tim" + (f" · {rank_change_txt}" if rank_change_txt else "")
        metric_tile(
            "Peringkat Liga",
            user_rank_str,
            rank_subtitle,
            "Posisi resmi kamu di mini-league ini.",
        )
    with m2:
        m2_sub = (
            f"Top {report.chip_summary.total_teams} rival dianalisa"
            if total_teams_display > report.chip_summary.total_teams
            else f"{report.chip_summary.total_teams} rival dianalisa"
        )
        metric_tile(
            "Wildcard 1 Terpakai",
            f"{report.chip_summary.wc1_used_pct:.0f}%",
            m2_sub,
            "Persentase rival di liga ini yang sudah mengaktifkan Wildcard 1 (GW 1–19).",
        )
    with m3:
        tc_rem = 100 - report.chip_summary.tc_used_pct
        metric_tile(
            "Triple Captain Siap Tempur",
            f"{tc_rem:.0f}%",
            f"Bench Boost tersisa: {100 - report.chip_summary.bb_used_pct:.0f}%",
            "Persentase rival yang masih menyimpan chip Triple Captain dan Bench Boost.",
        )
    with m4:
        if report.run_rate_needed is not None and report.run_rate_needed > 0:
            pts_behind = report.leader_points - report.user_points
            metric_tile(
                "Target Poin Per GW",
                f"+{report.run_rate_needed:.1f} poin/GW",
                f"Tertinggal {pts_behind} poin dari pemuncak #{1}",
                "Rata-rata keunggulan poin per GW yang kamu butuhkan untuk menyalip pemimpin klasemen.",
            )
        else:
            adv = report.chip_summary.user_chip_advantage
            adv_str = f"{adv:+.1f} chip"
            metric_tile(
                "Keunggulan Taktis",
                adv_str,
                f"Sisa {report.chip_summary.user_chips_remaining} chip vs rata-rata {report.chip_summary.avg_rival_chips_remaining:.1f} rival",
                "Selisih simpanan chip kamu dibandingkan rata-rata rival di liga.",
            )

    # ---------- League Rank History Per GW ----------
    if current_gw > 0:
        section_heading(
            "Histori Peringkat Liga Per GW",
            f"{report.league_name} · Perjalanan peringkat kamu",
            "Grafik perubahan posisi kamu di klasemen liga dari Gameweek ke Gameweek.",
        )
        history_cache_key = f"league_rank_history_{selected_league.id}_{manager_id}"
        rank_history = st.session_state.get(history_cache_key)
        if rank_history is None or load_leagues:
            with st.spinner("Menghitung histori peringkat liga..."):
                try:
                    rank_history = service.get_league_rank_history(
                        league_id=selected_league.id,
                        user_entry_id=int(manager_id),
                        current_gameweek=current_gw,
                        max_teams=total_teams_display,
                    )
                    st.session_state[history_cache_key] = rank_history
                except Exception as exc:
                    rank_history = ()
                    st.warning(f"Gagal menghitung histori peringkat: {exc}")

        if rank_history:
            import plotly.graph_objects as go

            is_overall = rank_history[0].is_overall_rank if rank_history else False
            gw_labels = [f"GW{rh.gameweek}" for rh in rank_history]
            ranks = [rh.league_rank for rh in rank_history]
            points = [rh.total_points for rh in rank_history]

            if is_overall:
                last_r = selected_league.entry_last_rank or (user_row.last_rank if user_row else None)
                curr_r = selected_league.entry_rank or (user_row.rank if user_row else None)
                last_r_str = f"#{last_r:,}" if last_r else "-"
                curr_r_str = f"#{curr_r:,} dari {total_teams_display:,} tim" if curr_r else "-"

                rc1, rc2, rc3 = st.columns(3)
                with rc1:
                    metric_tile("Posisi Liga Pekan Lalu", last_r_str, "Peringkat resmi pekan kemarin")
                with rc2:
                    metric_tile("Posisi Liga Saat Ini", curr_r_str, "Peringkat resmi pekan ini")
                with rc3:
                    metric_tile("Pergerakan Liga", rank_change_txt or "Peringkat stabil", "Perubahan posisi dari pekan lalu")

                st.caption(
                    "💡 *Catatan: Server FPL membatasi perankingan historis mini-league skala besar (> 30 tim) pada posisi pekan lalu vs pekan saat ini. Grafik di bawah menyajikan perkembangan resmi Overall Rank kamu per Gameweek:*"
                )

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=gw_labels,
                    y=ranks,
                    mode="lines+markers+text",
                    text=[f"#{r:,}" for r in ranks],
                    textposition="top center",
                    textfont=dict(size=11, color="#18f59b"),
                    line=dict(color="#18f59b", width=3, shape="spline"),
                    marker=dict(size=10, color="#18f59b", line=dict(width=2, color="#0d1117")),
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Overall Rank: #%{y:,}<br>"
                        "Total Poin: %{customdata}<extra></extra>"
                    ),
                    customdata=points,
                ))

                fig.update_layout(
                    yaxis=dict(
                        title="Overall Rank (Global)",
                        autorange="reversed",
                        gridcolor="rgba(255,255,255,0.06)",
                        zeroline=False,
                        title_font=dict(color="#8b95a5"),
                        tickfont=dict(color="#8b95a5"),
                    ),
                    xaxis=dict(
                        title="Gameweek",
                        gridcolor="rgba(255,255,255,0.06)",
                        title_font=dict(color="#8b95a5"),
                        tickfont=dict(color="#8b95a5"),
                    ),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e6ed"),
                    margin=dict(l=50, r=30, t=30, b=50),
                    height=360,
                    showlegend=False,
                    hovermode="x unified",
                )

                st.plotly_chart(fig, use_container_width=True)

            else:
                max_rank = max(rh.total_teams for rh in rank_history)

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=gw_labels,
                    y=ranks,
                    mode="lines+markers+text",
                    text=[f"#{r}" for r in ranks],
                    textposition="top center",
                    textfont=dict(size=11, color="#18f59b"),
                    line=dict(color="#18f59b", width=3, shape="spline"),
                    marker=dict(size=10, color="#18f59b", line=dict(width=2, color="#0d1117")),
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Peringkat Mini-League: #%{y}<br>"
                        "Total Poin: %{customdata}<extra></extra>"
                    ),
                    customdata=points,
                ))

                fig.update_layout(
                    yaxis=dict(
                        title="Peringkat Mini-League",
                        autorange="reversed",
                        range=[0.5, max_rank + 0.5],
                        dtick=1 if max_rank <= 20 else (5 if max_rank <= 50 else 10),
                        gridcolor="rgba(255,255,255,0.06)",
                        zeroline=False,
                        title_font=dict(color="#8b95a5"),
                        tickfont=dict(color="#8b95a5"),
                    ),
                    xaxis=dict(
                        title="Gameweek",
                        gridcolor="rgba(255,255,255,0.06)",
                        title_font=dict(color="#8b95a5"),
                        tickfont=dict(color="#8b95a5"),
                    ),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e6ed"),
                    margin=dict(l=50, r=30, t=30, b=50),
                    height=360,
                    showlegend=False,
                    hovermode="x unified",
                )

                st.plotly_chart(fig, use_container_width=True)

                # Quick rank summary metrics
                best_rank = min(ranks)
                worst_rank = max(ranks)
                current_rank = ranks[-1]
                best_gw = gw_labels[ranks.index(best_rank)]
                worst_gw = gw_labels[ranks.index(worst_rank)]

                rc1, rc2, rc3 = st.columns(3)
                with rc1:
                    metric_tile("Peringkat Terbaik", f"#{best_rank}", f"Tercapai di {best_gw}")
                with rc2:
                    metric_tile("Peringkat Terburuk", f"#{worst_rank}", f"Terjadi di {worst_gw}")
                with rc3:
                    trend = current_rank - ranks[0] if len(ranks) > 1 else 0
                    trend_txt = f"▲ Naik {abs(trend)} posisi" if trend < 0 else (f"▼ Turun {trend} posisi" if trend > 0 else "Stabil")
                    metric_tile("Tren Keseluruhan", trend_txt, f"GW1 #{ranks[0]} → Sekarang #{current_rank}")
        else:
            st.info("Data histori peringkat belum tersedia. Butuh minimal 1 GW yang sudah selesai.")

    section_heading(
        "Klasemen & Matriks Chip Rival",
        f"{report.league_name} · Top {len(report.standings)} dari {total_teams_display} tim",
        "Pantau pemakaian chip tiap rival secara real-time. Label menunjukkan GW saat chip dipakai, ACTIVE jika aktif pekan ini, atau Tersedia.",
    )

    # ---------- inline CSS (iframe can't inherit parent styles) ----------
    _TABLE_CSS = """
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: transparent; font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif; color: #e0e6ed; }
        .wrap { overflow-x: auto; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.82rem; text-align: left; }
        thead tr { background: rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.08); }
        thead th { padding: 10px 8px; color: #8b95a5; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.06em; font-weight: 600; white-space: nowrap; }
        tbody tr { border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 0.15s; }
        tbody tr:hover { background: rgba(255,255,255,0.03); }
        td { padding: 8px; vertical-align: middle; }
        .chip-used { background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.38); border-radius: 6px; color: #fca5a5; display: inline-block; font-size: 0.73rem; font-weight: 700; padding: 2px 7px; letter-spacing: 0.03em; }
        .chip-avail { background: rgba(24,245,155,0.14); border: 1px solid rgba(24,245,155,0.32); border-radius: 6px; color: #18f59b; display: inline-block; font-size: 0.73rem; font-weight: 700; padding: 2px 7px; letter-spacing: 0.03em; }
        .chip-active { background: linear-gradient(90deg,#8b5cf6,#d946ef); border: 1px solid rgba(217,70,239,0.6); border-radius: 6px; box-shadow: 0 0 10px rgba(139,92,246,0.45); color: #fff; display: inline-block; font-size: 0.73rem; font-weight: 850; padding: 2px 8px; letter-spacing: 0.05em; text-transform: uppercase; }
        .captain-tag { background: rgba(255,207,92,0.15); border: 1px solid rgba(255,207,92,0.4); border-radius: 4px; color: #ffcf5c; font-size: 0.72rem; font-weight: 700; padding: 2px 6px; display: inline-block; }
        .you-badge { background: rgba(24,245,155,0.25); color: #18f59b; padding: 2px 6px; border-radius: 4px; font-size: 0.68rem; font-weight: 800; margin-left: 4px; }
        .muted { color: #8b95a5; font-size: 0.75rem; }
        .txt-green { color: #18f59b; }
        .txt-red { color: #ff7a90; }
        .txt-muted { color: #8b95a5; }
        .center { text-align: center; }
        .bold { font-weight: 800; }
    </style>
    """

    def _chip_cell(chip_gw: Optional[int], is_active: bool) -> str:
        if is_active:
            return '<span class="chip-active">ACTIVE</span>'
        if chip_gw is not None:
            return f'<span class="chip-used">GW {chip_gw}</span>'
        return '<span class="chip-avail">Tersedia</span>'

    table_rows_html = []
    for row in report.standings:
        is_me = row.is_user
        bg_style = 'background: rgba(24, 245, 155, 0.08); border-left: 3px solid #18f59b;' if is_me else ''
        me_badge = ' <span class="you-badge">KAMU</span>' if is_me else ''

        diff_str = f"{row.points_diff_from_user:+d}" if not is_me and user_row else "-"
        if not is_me and user_row and row.points_diff_from_user > 0:
            diff_badge = f'<span class="txt-red">{diff_str}</span>'
        elif not is_me and user_row and row.points_diff_from_user < 0:
            diff_badge = f'<span class="txt-green">{diff_str}</span>'
        else:
            diff_badge = f'<span class="txt-muted">{diff_str}</span>'

        gap_lead = f"-{row.points_behind_leader}" if row.points_behind_leader > 0 else "Pemuncak"

        cap_cell = "-"
        if row.captain_name:
            mult_txt = f" ({row.captain_multiplier}x)" if row.captain_multiplier > 1 else ""
            cap_cell = f'<span class="captain-tag">{escape(row.captain_name)}{mult_txt}</span>'

        wc1_cell = _chip_cell(row.chips.wc1, row.active_chip == "wildcard" and current_gw <= 19)
        wc2_cell = _chip_cell(row.chips.wc2, row.active_chip == "wildcard" and current_gw >= 20)
        fh_cell = _chip_cell(row.chips.freehit, row.active_chip == "freehit")
        tc_cell = _chip_cell(row.chips.triple_captain, row.active_chip in ("3xc", "triple_captain"))
        bb_cell = _chip_cell(row.chips.bench_boost, row.active_chip in ("bboost", "bench_boost"))

        table_rows_html.append(f"""
        <tr style="{bg_style}">
            <td class="bold center">{row.rank}</td>
            <td><strong>{escape(row.team_name)}</strong>{me_badge}<br><span class="muted">{escape(row.manager_name)}</span></td>
            <td class="bold center">{row.total_points}</td>
            <td class="center muted">{row.event_points}</td>
            <td class="center" style="color:#ffcf5c; font-size:0.8rem;">{gap_lead}</td>
            <td class="center" style="font-size:0.8rem;">{diff_badge}</td>
            <td class="center">{cap_cell}</td>
            <td class="center">{wc1_cell}</td>
            <td class="center">{wc2_cell}</td>
            <td class="center">{fh_cell}</td>
            <td class="center">{tc_cell}</td>
            <td class="center">{bb_cell}</td>
        </tr>""")

    num_rows = len(report.standings)
    iframe_height = min(62 + num_rows * 50, 1200)

    full_table_html = f"""{_TABLE_CSS}
    <div class="wrap">
        <table>
            <thead>
                <tr>
                    <th class="center">#</th>
                    <th>Tim &amp; Manajer</th>
                    <th class="center">Total</th>
                    <th class="center">GW</th>
                    <th class="center">Jarak #1</th>
                    <th class="center">vs Kamu</th>
                    <th class="center">Kapten</th>
                    <th class="center">WC 1</th>
                    <th class="center">WC 2</th>
                    <th class="center">Free Hit</th>
                    <th class="center">Triple C</th>
                    <th class="center">Bench B</th>
                </tr>
            </thead>
            <tbody>{''.join(table_rows_html)}</tbody>
        </table>
    </div>
    """
    import streamlit.components.v1 as stc
    stc.html(full_table_html, height=iframe_height, scrolling=True)

    # ---------- Dedicated Per-Member Chip Usage Matrix ----------
    section_heading(
        "Tabel Penggunaan Chip Per Anggota",
        f"{report.league_name} · Rincian lengkap seluruh chip",
        "Lihat di Gameweek berapa masing-masing anggota mengaktifkan Wildcard, Free Hit, Triple Captain, dan Bench Boost.",
    )

    chip_matrix_rows = []
    for row in report.standings:
        is_me = row.is_user
        bg_style = 'background: rgba(24,245,155,0.08); border-left: 3px solid #18f59b;' if is_me else ''
        me_badge = ' <span class="you-badge">KAMU</span>' if is_me else ''

        wc1_cell = _chip_cell(row.chips.wc1, row.active_chip == "wildcard" and current_gw <= 19)
        wc2_cell = _chip_cell(row.chips.wc2, row.active_chip == "wildcard" and current_gw >= 20)
        fh_cell = _chip_cell(row.chips.freehit, row.active_chip == "freehit")
        tc_cell = _chip_cell(row.chips.triple_captain, row.active_chip in ("3xc", "triple_captain"))
        bb_cell = _chip_cell(row.chips.bench_boost, row.active_chip in ("bboost", "bench_boost"))

        remaining = row.chips.total_remaining
        if remaining >= 4:
            rem_color = "#18f59b"
        elif remaining >= 2:
            rem_color = "#ffcf5c"
        else:
            rem_color = "#ff7a90"

        chip_matrix_rows.append(f"""
        <tr style="{bg_style}">
            <td class="bold center">{row.rank}</td>
            <td><strong>{escape(row.team_name)}</strong>{me_badge}<br><span class="muted">{escape(row.manager_name)}</span></td>
            <td class="center">{wc1_cell}</td>
            <td class="center">{wc2_cell}</td>
            <td class="center">{fh_cell}</td>
            <td class="center">{tc_cell}</td>
            <td class="center">{bb_cell}</td>
            <td class="center bold" style="color:{rem_color}; font-size:0.9rem;">{remaining}/5</td>
        </tr>""")

    chip_iframe_height = min(62 + num_rows * 50, 1200)

    chip_matrix_html = f"""{_TABLE_CSS}
    <style>
        .chip-header {{ font-size: 0.68rem; }}
        .chip-header span {{ display: block; font-size: 0.62rem; color: #6b7280; font-weight: 400; text-transform: none; letter-spacing: 0; margin-top: 2px; }}
    </style>
    <div class="wrap">
        <table>
            <thead>
                <tr>
                    <th class="center">#</th>
                    <th>Anggota</th>
                    <th class="center chip-header">Wildcard 1<span>GW 1-19</span></th>
                    <th class="center chip-header">Wildcard 2<span>GW 20-38</span></th>
                    <th class="center chip-header">Free Hit<span>Skuad 1 GW</span></th>
                    <th class="center chip-header">Triple Captain<span>Armband 3x</span></th>
                    <th class="center chip-header">Bench Boost<span>15 pemain aktif</span></th>
                    <th class="center chip-header">Sisa Chip<span>dari 5 chip</span></th>
                </tr>
            </thead>
            <tbody>{''.join(chip_matrix_rows)}</tbody>
        </table>
    </div>
    """
    stc.html(chip_matrix_html, height=chip_iframe_height, scrolling=True)

    if report.captain_distribution:
        total_in_league = report.total_league_teams or len(report.standings)
        analyzed_count = len(report.standings)
        if total_in_league > analyzed_count:
            radar_title = f"Radar Pilihan Kapten (Top {analyzed_count} Rival)"
            radar_sub = f"Pilihan armband GW {current_gw} dari Top {analyzed_count} tim teratas (dari total {total_in_league:,} tim di liga)"
            radar_desc = "Konsentrasi armband di papan atas mini-league kamu untuk membaca risiko Effective Ownership (EO) lokal."
            radar_note = f"💡 *Catatan: Pilihan kapten dianalisa dari Top {analyzed_count} tim teratas sebagai sampel persaingan papan atas liga. Karena FPL API mewajibkan 1 request jaringan terpisah untuk setiap tim manajer, pembatasan ini menjaga aplikasi tetap cepat dan mencegah pemblokiran request (rate limit) dari server resmi FPL jika harus menarik seluruh {total_in_league:,} tim.*"
        else:
            radar_title = "Radar Pilihan Kapten Mini-League"
            radar_sub = f"Pilihan armband GW {current_gw} dari seluruh {analyzed_count} rival di liga"
            radar_desc = "Konsentrasi armband di mini-league kamu untuk membaca risiko Effective Ownership (EO) lokal."
            radar_note = None

        section_heading(radar_title, radar_sub, radar_desc)
        if radar_note:
            st.caption(radar_note)

        total_caps = sum(report.captain_distribution.values())
        top_caps = list(report.captain_distribution.items())[:4]
        cap_cols = st.columns(min(len(top_caps), 4))
        for idx, (cap_name, cap_cnt) in enumerate(top_caps):
            pct = round(100 * cap_cnt / max(1, total_caps), 1)
            with cap_cols[idx]:
                metric_tile(
                    f"Pilihan Kapten #{idx + 1}",
                    f"{cap_name}",
                    f"{cap_cnt} rival ({pct}%)",
                )

    rival_candidates = [r for r in report.standings if not r.is_user]
    if rival_candidates and current_gw > 0:
        section_heading(
            "Head-to-Head Lawan Rival",
            "Perbandingan skuad langsung",
            "Pilih salah satu rival untuk membedah pemain sama (shield), pemain diferensial, adu kapten, dan sisa amunisi chip.",
        )
        rival_map = {f"Rank #{r.rank} - {r.team_name} ({r.manager_name})": r.entry_id for r in rival_candidates}
        chosen_rival_label = st.selectbox("Pilih rival untuk dibandingkan:", options=list(rival_map.keys()), key="rival_compare_select")
        chosen_rival_id = rival_map[chosen_rival_label]

        with st.spinner("Membedah skuad rival..."):
            try:
                comp = service.compare_teams(
                    user_entry_id=int(manager_id),
                    rival_entry_id=chosen_rival_id,
                    gameweek=current_gw,
                )
                comp_cols = st.columns(4)
                with comp_cols[0]:
                    metric_tile("Kapten Kamu", comp.user_captain, comp.user_active_chip or "Tanpa chip aktif")
                with comp_cols[1]:
                    metric_tile("Kapten Rival", comp.rival_captain, comp.rival_active_chip or "Tanpa chip aktif")
                with comp_cols[2]:
                    metric_tile("Nilai Skuad", f"£{comp.user_cost:.1f}m vs £{comp.rival_cost:.1f}m", f"Bank: £{comp.user_bank:.1f}m vs £{comp.rival_bank:.1f}m")
                with comp_cols[3]:
                    metric_tile("Sisa Chip", f"{comp.user_chips.total_remaining} vs {comp.rival_chips.total_remaining}", "Simpanan chip yang belum terpakai")

                diff_c1, diff_c2, diff_c3 = st.columns(3)
                with diff_c1:
                    st.markdown(f"**🛡️ Pemain Sama / Shield ({len(comp.shared_players)} pemain)**")
                    st.caption("Poin dari pemain ini saling meniadakan antara kamu dan rival.")
                    if comp.shared_players:
                        st.markdown(" • " + "<br> • ".join(escape(p) for p in comp.shared_players), unsafe_allow_html=True)
                    else:
                        st.write("Tidak ada pemain yang sama.")

                with diff_c2:
                    st.markdown(f"**⚔️ Senjata Kamu ({len(comp.user_differentials)} pemain)**")
                    st.caption("Pemain pembeda yang cuma kamu yang punya untuk mengejar atau memperlebar jarak.")
                    if comp.user_differentials:
                        st.markdown(" • " + "<br> • ".join(escape(p) for p in comp.user_differentials), unsafe_allow_html=True)
                    else:
                        st.write("Tidak ada.")

                with diff_c3:
                    st.markdown(f"**⚠️ Ancaman Rival ({len(comp.rival_differentials)} pemain)**")
                    st.caption("Pemain diferensial milik rival yang berpotensi mengancam peringkatmu.")
                    if comp.rival_differentials:
                        st.markdown(" • " + "<br> • ".join(escape(p) for p in comp.rival_differentials), unsafe_allow_html=True)
                    else:
                        st.write("Tidak ada.")

            except Exception as exc:
                st.info(f"Pemantau skuad rival tidak tersedia: {exc}")


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
    "League & Rivals": render_league_rivals,
    "Data Status": render_data_status,
}
