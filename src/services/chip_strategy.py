"""Service layer for FPL Round 1 Chip Strategy and Optimal Timing Recommender."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from src.api.fpl_client import FPLClient
from src.services.fpl_ingestion import get_fpl_ingestion_service
from src.utils.logger import get_logger


logger = get_logger(__name__)


# Big clubs used for assessing fixture swings and heavyweight clashes
TOP_CLUBS: Set[str] = {"ARS", "MCI", "LIV", "CHE", "TOT", "NEW", "AVL", "MUN"}


@dataclass(frozen=True)
class Round1ChipInventory:
    """Inventory and urgency analysis for the 4 Round 1 chips (GW 1–19)."""

    wc1_gw: Optional[int] = None
    fh1_gw: Optional[int] = None
    tc1_gw: Optional[int] = None
    bb1_gw: Optional[int] = None
    current_gw: int = 1

    @property
    def wc1_used(self) -> bool:
        return self.wc1_gw is not None

    @property
    def fh1_used(self) -> bool:
        return self.fh1_gw is not None

    @property
    def tc1_used(self) -> bool:
        return self.tc1_gw is not None

    @property
    def bb1_used(self) -> bool:
        return self.bb1_gw is not None

    @property
    def used_chips_count(self) -> int:
        return sum(1 for c in (self.wc1_gw, self.fh1_gw, self.tc1_gw, self.bb1_gw) if c is not None)

    @property
    def remaining_chips_count(self) -> int:
        return 4 - self.used_chips_count

    @property
    def gws_until_expiry(self) -> int:
        """Number of gameweeks remaining in Round 1 including current GW."""
        return max(0, 19 - self.current_gw + 1)

    @property
    def unplayed_chips(self) -> Tuple[str, ...]:
        unplayed: List[str] = []
        if not self.wc1_used:
            unplayed.append("wildcard")
        if not self.fh1_used:
            unplayed.append("freehit")
        if not self.tc1_used:
            unplayed.append("triple_captain")
        if not self.bb1_used:
            unplayed.append("bench_boost")
        return tuple(unplayed)

    @property
    def urgency_level(self) -> str:
        """Urgency tier: COMPLETED, CRITICAL, HIGH, MODERATE, or SAFE."""
        if self.remaining_chips_count == 0:
            return "COMPLETED"
        if self.gws_until_expiry <= self.remaining_chips_count:
            return "CRITICAL"
        if self.gws_until_expiry <= self.remaining_chips_count + 2:
            return "HIGH"
        if self.gws_until_expiry <= self.remaining_chips_count + 5:
            return "MODERATE"
        return "SAFE"

    @property
    def urgency_message(self) -> str:
        if self.remaining_chips_count == 0:
            return "Mantap! Semua 4 chip putaran 1 sudah kamu pakai dengan aman. Siap-siap dapat 4 chip baru lagi di putaran kedua (GW 20–38)."
        if self.urgency_level == "CRITICAL":
            return (
                f"🚨 Waspada! Sisa {self.gws_until_expiry} GW lagi untuk pakai {self.remaining_chips_count} chip! "
                "Ingat, aturan FPL cuma boleh 1 chip per GW. Kamu WAJIB pasang chip pekan ini biar nggak hangus pas deadline GW 19!"
            )
        if self.urgency_level == "HIGH":
            return (
                f"⚠️ Waktunya tancap gas! Masih ada {self.remaining_chips_count} chip yang belum terpakai padahal sisa {self.gws_until_expiry} pekan lagi. "
                "Jangan sampai numpuk di akhir, mulai pilih fixture terbaik sekarang!"
            )
        if self.urgency_level == "MODERATE":
            return (
                f"💡 Perlu dicatat: Kamu masih pegang {self.remaining_chips_count} chip dengan sisa {self.gws_until_expiry} GW. "
                "Yuk mulai atur jadwal biar chip-mu bisa keluar di pekan yang paling nguntungin."
            )
        return (
            f"✅ Aman terkendali: Masih ada {self.remaining_chips_count} chip untuk sisa {self.gws_until_expiry} GW ke depan. "
            "Kamu masih punya waktu leluasa buat nunggu momentum fixture paling gurih."
        )


@dataclass(frozen=True)
class GameweekSuitability:
    """Suitability scores (0–100) and rationale for a single Gameweek in Round 1."""

    gameweek: int
    deadline_display: str
    is_international_break: bool
    is_festive_period: bool
    wc_score: float
    wc_reason: str
    tc_score: float
    tc_reason: str
    tc_captain_pick: str
    fh_score: float
    fh_reason: str
    bb_score: float
    bb_reason: str


@dataclass(frozen=True)
class ScheduledChipPlan:
    """Optimal assignment of an unplayed chip to a specific Gameweek."""

    chip_key: str
    chip_label: str
    recommended_gw: int
    suitability_score: float
    headline: str
    rationale: str
    alternative_gw: Optional[int] = None
    contingency_note: str = ""


@dataclass(frozen=True)
class ChipStrategyReport:
    """Comprehensive strategic roadmap for Round 1 chips."""

    manager_id: Optional[int]
    current_gameweek: int
    inventory: Round1ChipInventory
    suitability_matrix: Tuple[GameweekSuitability, ...]
    master_plan: Tuple[ScheduledChipPlan, ...]
    key_takeaways: Tuple[str, ...]


class ChipStrategyService:
    """Evaluates upcoming gameweeks and formulates a conflict-free deployment schedule."""

    def __init__(self, client: FPLClient) -> None:
        self.client = client

    def get_round_1_inventory(
        self,
        manager_id: Optional[int],
        current_gw: int,
    ) -> Round1ChipInventory:
        """Parse manager history to find which of the 4 Round 1 chips have been played."""
        wc1: Optional[int] = None
        fh1: Optional[int] = None
        tc1: Optional[int] = None
        bb1: Optional[int] = None

        if manager_id and manager_id > 0:
            try:
                hist = self.client.get_entry_history(manager_id)
                for chip in hist.get("chips", []):
                    if not isinstance(chip, Mapping):
                        continue
                    name = str(chip.get("name", "")).strip().lower()
                    event = chip.get("event")
                    if event is None:
                        continue
                    event_gw = int(event)
                    if event_gw <= 19:
                        if name == "wildcard":
                            wc1 = event_gw
                        elif name == "freehit":
                            fh1 = event_gw
                        elif name in ("3xc", "triple_captain"):
                            tc1 = event_gw
                        elif name in ("bboost", "bench_boost"):
                            bb1 = event_gw
            except Exception as exc:
                logger.warning("Could not fetch chip history for manager %s: %s", manager_id, exc)

        return Round1ChipInventory(
            wc1_gw=wc1,
            fh1_gw=fh1,
            tc1_gw=tc1,
            bb1_gw=bb1,
            current_gw=current_gw,
        )

    def calculate_suitability_matrix(self, current_gw: int) -> Tuple[GameweekSuitability, ...]:
        """Calculate chip suitability scores (0-100) for every GW from current_gw to 19."""
        bootstrap = self.client.get_bootstrap()
        all_fixtures = self.client.get_fixtures()

        events_dict: Dict[int, Dict[str, Any]] = {
            int(e["id"]): e for e in bootstrap.get("events", []) if "id" in e
        }
        teams_dict: Dict[int, Dict[str, Any]] = {
            int(t["id"]): t for t in bootstrap.get("teams", []) if "id" in t
        }

        # Identify premium captains
        premium_targets = [
            el for el in bootstrap.get("elements", [])
            if el.get("web_name") in ("Haaland", "Salah", "Saka", "Palmer", "Watkins", "Isak", "Son")
        ]

        # Group fixtures by event
        gw_fixtures: Dict[int, List[Dict[str, Any]]] = {gw: [] for gw in range(1, 39)}
        for f in all_fixtures:
            ev = f.get("event")
            if ev and int(ev) in gw_fixtures:
                gw_fixtures[int(ev)].append(f)

        start_gw = max(1, current_gw)
        result: List[GameweekSuitability] = []

        for gw in range(start_gw, 20):
            ev_meta = events_dict.get(gw, {})
            deadline_raw = ev_meta.get("deadline_time", "")
            deadline_disp = ""
            if deadline_raw:
                try:
                    dt = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
                    deadline_disp = dt.strftime("%a %d %b %H:%M")
                except Exception:
                    deadline_disp = deadline_raw[:16]

            # Detect International Break: gap between this event and previous > 10 days
            is_ib = False
            prev_meta = events_dict.get(gw - 1, {})
            if deadline_raw and prev_meta.get("deadline_time"):
                try:
                    dt_curr = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
                    dt_prev = datetime.fromisoformat(prev_meta["deadline_time"].replace("Z", "+00:00"))
                    if (dt_curr - dt_prev).days >= 11:
                        is_ib = True
                except Exception:
                    pass

            # Festive period: GW 17-19 (tight turnaround in late Dec/early Jan)
            is_festive = gw in (17, 18, 19)

            fixtures_this_gw = gw_fixtures.get(gw, [])

            # -------------------------------------------------------------
            # 1. WILDCARD 1 (WC1)
            # Factors: IB bonus (+26), Top clubs entering easy 5-GW runs (+16),
            # GW 19 expiry urgency bonus.
            # -------------------------------------------------------------
            wc_score = 48.0
            wc_reasons: List[str] = []

            if is_ib:
                wc_score += 26.0
                wc_reasons.append("Pasca-International Break (jeda transfer 2 pekan & pantau cedera)")

            # Check fixture swings for top teams in next 5 GWs
            fdr_sums: List[float] = []
            for tid, tmeta in teams_dict.items():
                if tmeta.get("short_name") in TOP_CLUBS:
                    future_diffs = []
                    for fgw in range(gw, min(39, gw + 5)):
                        for f in gw_fixtures.get(fgw, []):
                            if f.get("team_h") == tid:
                                future_diffs.append(f.get("team_h_difficulty", 3))
                            elif f.get("team_a") == tid:
                                future_diffs.append(f.get("team_a_difficulty", 3))
                    if future_diffs:
                        fdr_sums.append(sum(future_diffs) / len(future_diffs))

            avg_top_fdr = sum(fdr_sums) / max(1, len(fdr_sums))
            if avg_top_fdr <= 2.8:
                wc_score += 16.0
                wc_reasons.append("Jadwal 5 GW ke depan sangat empuk buat klub top")
            elif avg_top_fdr >= 3.4:
                wc_score -= 8.0

            # Urgency ramp up as GW 19 approaches
            if gw == 19:
                wc_score = max(wc_score, 92.0)
                wc_reasons.append("DEADLINE TERAKHIR: Wajib aktifkan sebelum hangus!")
            elif gw == 18:
                wc_score = max(wc_score, 82.0)
                wc_reasons.append("Pekan krusial menjelang deadline batas akhir GW 19")

            wc_score = min(98.0, max(25.0, wc_score))
            wc_reason_str = " · ".join(wc_reasons) if wc_reasons else "Jadwal standar; amunisi bisa disimpan untuk momentum lebih baik."

            # -------------------------------------------------------------
            # 2. TRIPLE CAPTAIN 1 (TC1)
            # Factors: Peak expected points for premier captains (Haaland, Salah, etc.)
            # Home match against difficulty 2 / weak defense.
            # -------------------------------------------------------------
            tc_score = 40.0
            best_cap_name = "Haaland"
            best_cap_reason = "Jadwal reguler"

            top_picks: List[Tuple[float, str, str]] = []
            for p in premium_targets:
                p_name = p.get("web_name", "Kapten")
                p_team_id = p.get("team")
                ep = float(p.get("ep_next") or 5.0)

                for f in fixtures_this_gw:
                    if f.get("team_h") == p_team_id:
                        opp = teams_dict.get(f.get("team_a", 0), {}).get("short_name", "OPP")
                        diff = f.get("team_h_difficulty", 3)
                        # Home match bonus
                        score = 50.0 + ep * 4.0
                        if diff <= 2:
                            score += 24.0
                            top_picks.append((score, p_name, f"{p_name} (H vs {opp}) · Lawan FDR 2 di kandang"))
                        elif diff == 3:
                            score += 8.0
                            top_picks.append((score, p_name, f"{p_name} (H vs {opp}) · Laga kandang"))
                    elif f.get("team_a") == p_team_id:
                        opp = teams_dict.get(f.get("team_h", 0), {}).get("short_name", "OPP")
                        diff = f.get("team_a_difficulty", 3)
                        score = 42.0 + ep * 3.5
                        if diff <= 2:
                            score += 15.0
                            top_picks.append((score, p_name, f"{p_name} (A vs {opp}) · Lawan FDR 2 saat away"))

            if top_picks:
                top_picks.sort(key=lambda x: -x[0])
                tc_score = min(96.0, top_picks[0][0])
                best_cap_name = top_picks[0][1]
                best_cap_reason = top_picks[0][2]
            else:
                tc_score = 45.0
                best_cap_reason = "Belum ada kapten dengan peluang poin mencolok pekan ini"

            if gw == 19:
                tc_score = max(tc_score, 88.0)
                best_cap_reason += " (Deadline akhir GW 19)"

            # -------------------------------------------------------------
            # 3. FREE HIT 1 (FH1)
            # Factors: Heavyweight clashes (Top-6 head to head) where template
            # cancels out, or festive rotation chaos.
            # -------------------------------------------------------------
            fh_score = 42.0
            fh_reasons: List[str] = []

            clashes: List[str] = []
            for f in fixtures_this_gw:
                th = teams_dict.get(f.get("team_h", 0), {}).get("short_name", "")
                ta = teams_dict.get(f.get("team_a", 0), {}).get("short_name", "")
                if th in TOP_CLUBS and ta in TOP_CLUBS:
                    clashes.append(f"{th} vs {ta}")

            if len(clashes) >= 3:
                fh_score += 34.0
                fh_reasons.append(f"Clash akbar ({len(clashes)} big match: {', '.join(clashes[:2])}) · Potensi diferensial masif")
            elif len(clashes) == 2:
                fh_score += 22.0
                fh_reasons.append(f"2 laga antar klub top ({', '.join(clashes)}) · Pemain template berpotensi saling meniadakan poin")

            if is_festive:
                fh_score += 18.0
                fh_reasons.append("Periode padat festive (Boxing Day / Tahun Baru) · Banyak rotasi starter mendadak")

            if gw == 19:
                fh_score = max(fh_score, 90.0)
                fh_reasons.append("Deadline GW 19: Aktifkan Free Hit biar nggak hangus!")

            fh_score = min(95.0, max(30.0, fh_score))
            fh_reason_str = " · ".join(fh_reasons) if fh_reasons else "Pekan standar; tim template bermain normal tanpa krisis."

            # -------------------------------------------------------------
            # 4. BENCH BOOST 1 (BB1)
            # Factors: Budget/bench fodder teams with FDR <= 2 at home.
            # GW 18/19 festive rotation mitigation.
            # -------------------------------------------------------------
            bb_score = 40.0
            bb_reasons: List[str] = []

            easy_home_count = 0
            for f in fixtures_this_gw:
                diff = f.get("team_h_difficulty", 3)
                th = teams_dict.get(f.get("team_h", 0), {}).get("short_name", "")
                if diff <= 2 and th not in ("MCI", "ARS", "LIV"):
                    easy_home_count += 1

            if easy_home_count >= 4:
                bb_score += 26.0
                bb_reasons.append(f"{easy_home_count} tim medioker main kandang dengan FDR 2 (potensi clean sheet & poin bangku cadangan melimpah)")
            elif easy_home_count >= 2:
                bb_score += 15.0
                bb_reasons.append("Beberapa pemain cadangan memiliki jadwal kandang menguntungkan")

            if is_festive:
                bb_score += 14.0
                bb_reasons.append("Penyelamat rotasi skuad 15 pemain di jadwal padat akhir tahun")

            if gw == 19:
                bb_score = max(bb_score, 90.0)
                bb_reasons.append("Kesempatan terakhir pasang Bench Boost 1 sebelum hangus")

            bb_score = min(94.0, max(28.0, bb_score))
            bb_reason_str = " · ".join(bb_reasons) if bb_reasons else "Pemain cadangan menghadapi fixture yang cukup berimbang."

            result.append(
                GameweekSuitability(
                    gameweek=gw,
                    deadline_display=deadline_disp,
                    is_international_break=is_ib,
                    is_festive_period=is_festive,
                    wc_score=round(wc_score, 1),
                    wc_reason=wc_reason_str,
                    tc_score=round(tc_score, 1),
                    tc_reason=best_cap_reason,
                    tc_captain_pick=best_cap_name,
                    fh_score=round(fh_score, 1),
                    fh_reason=fh_reason_str,
                    bb_score=round(bb_score, 1),
                    bb_reason=bb_reason_str,
                )
            )

        return tuple(result)

    def build_master_plan(
        self,
        inventory: Round1ChipInventory,
        calendar: Tuple[GameweekSuitability, ...],
    ) -> Tuple[ScheduledChipPlan, ...]:
        """Produce a conflict-free deployment schedule for all unplayed Round 1 chips."""
        unplayed = inventory.unplayed_chips
        if not unplayed or not calendar:
            return ()

        cal_dict = {row.gameweek: row for row in calendar}
        available_gws = sorted(cal_dict.keys())

        # Collect suitability scores per chip for every available GW
        chip_scores: Dict[str, List[Tuple[int, float]]] = {}
        for chip_key in unplayed:
            scores: List[Tuple[int, float]] = []
            for gw in available_gws:
                c = cal_dict[gw]
                if chip_key == "wildcard":
                    scores.append((gw, c.wc_score))
                elif chip_key == "triple_captain":
                    scores.append((gw, c.tc_score))
                elif chip_key == "freehit":
                    scores.append((gw, c.fh_score))
                elif chip_key == "bench_boost":
                    scores.append((gw, c.bb_score))
            # Sort highest score first
            scores.sort(key=lambda item: -item[1])
            chip_scores[chip_key] = scores

        # Strategic Priority Order: Wildcard early to form foundation, then TC, FH, BB.
        strategic_order = ["wildcard", "triple_captain", "freehit", "bench_boost"]
        ordered_chips = [c for c in strategic_order if c in unplayed]

        assigned_gws: Set[int] = set()
        plan: List[ScheduledChipPlan] = []

        for chip_key in ordered_chips:
            candidates = chip_scores[chip_key]
            chosen_gw: Optional[int] = None
            chosen_score: float = 50.0
            alt_gw: Optional[int] = None

            for gw, score in candidates:
                if gw not in assigned_gws and chosen_gw is None:
                    chosen_gw = gw
                    chosen_score = score
                elif gw not in assigned_gws and alt_gw is None:
                    alt_gw = gw

            if chosen_gw is None:
                remaining_gws = [g for g in available_gws if g not in assigned_gws]
                chosen_gw = remaining_gws[0] if remaining_gws else available_gws[-1]
                chosen_score = 50.0

            assigned_gws.add(chosen_gw)
            c_meta = cal_dict.get(chosen_gw)

            if chip_key == "wildcard":
                label = "Wildcard 1"
                headline = f"GW {chosen_gw} · Rombak Total Skuad"
                rationale = c_meta.wc_reason if c_meta else "Waktu paling ideal buat rombak formasi & manfaatkan fixture swing."
                contingency = "Jika skuad terkena badai cedera massal lebih awal, aktifkan 1 pekan lebih cepat."
            elif chip_key == "triple_captain":
                label = "Triple Captain 1"
                headline = f"GW {chosen_gw} · Armband ke {c_meta.tc_captain_pick if c_meta else 'Haaland'}"
                rationale = c_meta.tc_reason if c_meta else "Laga kandang dengan proyeksi potensi gol dan poin tertinggi."
                contingency = "Jika kapten utama mendadak cedera atau diragukan di konferensi pers, geser ke jadwal cadangan."
            elif chip_key == "freehit":
                label = "Free Hit 1"
                headline = f"GW {chosen_gw} · Skuad Khusus 1 Pekan"
                rationale = c_meta.fh_reason if c_meta else "Manfaatkan big match berat untuk panen poin dari pemain diferensial."
                contingency = "Simpan sebagai kartu penyelamat jika terjadi penundaan laga atau krisis mendadak."
            else:  # bench_boost
                label = "Bench Boost 1"
                headline = f"GW {chosen_gw} · 15 Pemain Aktif Mendulang Poin"
                rationale = c_meta.bb_reason if c_meta else "Maksimalkan poin cadangan saat seluruh pemain bench dapat jadwal empuk."
                contingency = "Pastikan seluruh 4 pemain cadangan berstatus starter reguler tanpa cedera."

            plan.append(
                ScheduledChipPlan(
                    chip_key=chip_key,
                    chip_label=label,
                    recommended_gw=chosen_gw,
                    suitability_score=chosen_score,
                    headline=headline,
                    rationale=rationale,
                    alternative_gw=alt_gw,
                    contingency_note=contingency,
                )
            )

        # Sort final plan chronologically by recommended_gw
        plan.sort(key=lambda item: item.recommended_gw)
        return tuple(plan)

    def generate_strategy_report(
        self,
        manager_id: Optional[int],
        current_gw: int,
    ) -> ChipStrategyReport:
        """Produce the complete chip strategy analysis report."""
        inventory = self.get_round_1_inventory(manager_id, current_gw)
        calendar = self.calculate_suitability_matrix(current_gw)
        plan = self.build_master_plan(inventory, calendar)

        takeaways: List[str] = []
        if inventory.urgency_level == "CRITICAL":
            takeaways.append(
                f"🚨 **Wajib Pasang Pekan Ini**: Kamu masih punya {inventory.remaining_chips_count} chip dengan sisa cuma {inventory.gws_until_expiry} GW di putaran pertama. Harus langsung pasang chip pekan ini biar nggak hangus!"
            )
        elif inventory.remaining_chips_count > 0:
            takeaways.append(
                f"⏱️ **Batas Waktu GW 19**: Semua {inventory.remaining_chips_count} chip putaran 1 yang belum terpakai akan **otomatis hangus** jika tidak diaktifkan sebelum deadline GW 19."
            )

        wc_plan = next((p for p in plan if p.chip_key == "wildcard"), None)
        if wc_plan:
            takeaways.append(
                f"🃏 **Target Wildcard 1**: GW {wc_plan.recommended_gw} direkomendasikan sebagai momentum terbaik buat rombak total susunan tim ({wc_plan.rationale})."
            )

        tc_plan = next((p for p in plan if p.chip_key == "triple_captain"), None)
        if tc_plan:
            takeaways.append(
                f"👑 **Target Triple Captain 1**: GW {tc_plan.recommended_gw} ({tc_plan.headline}) menawarkan potensi perolehan poin tertinggi."
            )

        takeaways.append(
            "🔄 **Putaran Kedua (GW 20–38)**: Kamu bakal otomatis mendapatkan 4 chip baru lagi (WC2, FH2, TC2, BB2) untuk dipakai sampai akhir musim di GW 38."
        )

        return ChipStrategyReport(
            manager_id=manager_id,
            current_gameweek=current_gw,
            inventory=inventory,
            suitability_matrix=calendar,
            master_plan=plan,
            key_takeaways=tuple(takeaways),
        )


@lru_cache(maxsize=1)
def get_chip_strategy_service() -> ChipStrategyService:
    """Factory creating the singleton ChipStrategyService instance."""
    ingestion = get_fpl_ingestion_service()
    return ChipStrategyService(ingestion.client)
