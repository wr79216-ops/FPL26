"""Service layer for FPL Mini-League and Rival Chip Analytics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.api.fpl_client import FPLClient
from src.services.fpl_ingestion import get_fpl_ingestion_service
from src.utils.logger import get_logger
from src.utils.text import normalize_display_name


logger = get_logger(__name__)


@dataclass(frozen=True)
class ManagerLeague:
    """Metadata for one FPL league a manager participates in."""

    id: int
    name: str
    short_name: Optional[str]
    entry_rank: Optional[int]
    entry_last_rank: Optional[int]
    league_type: str  # 'x' = private/invitational, 's' = public/system
    scoring: str  # 'c' = classic, 'h' = head-to-head
    is_private: bool


@dataclass(frozen=True)
class RivalChipStatus:
    """Status of chips for one manager across both halves of the season (8 chips total)."""

    wc1: Optional[int] = None  # Gameweek played (<= 19) or None if available
    wc2: Optional[int] = None  # Gameweek played (>= 20) or None if available
    fh1: Optional[int] = None  # Free Hit Round 1 (<= 19)
    fh2: Optional[int] = None  # Free Hit Round 2 (>= 20)
    tc1: Optional[int] = None  # Triple Captain Round 1 (<= 19)
    tc2: Optional[int] = None  # Triple Captain Round 2 (>= 20)
    bb1: Optional[int] = None  # Bench Boost Round 1 (<= 19)
    bb2: Optional[int] = None  # Bench Boost Round 2 (>= 20)
    active_chip: Optional[str] = None  # Active chip for the current gameweek

    # Backwards compatibility properties
    @property
    def freehit(self) -> Optional[int]:
        return self.fh1 if self.fh1 is not None else self.fh2

    @property
    def triple_captain(self) -> Optional[int]:
        return self.tc1 if self.tc1 is not None else self.tc2

    @property
    def bench_boost(self) -> Optional[int]:
        return self.bb1 if self.bb1 is not None else self.bb2

    @property
    def round_1_used(self) -> int:
        return sum(1 for c in (self.wc1, self.fh1, self.tc1, self.bb1) if c is not None)

    @property
    def round_1_remaining(self) -> int:
        return 4 - self.round_1_used

    @property
    def round_2_used(self) -> int:
        return sum(1 for c in (self.wc2, self.fh2, self.tc2, self.bb2) if c is not None)

    @property
    def round_2_remaining(self) -> int:
        return 4 - self.round_2_used

    @property
    def total_used(self) -> int:
        return self.round_1_used + self.round_2_used

    @property
    def total_remaining(self) -> int:
        return 8 - self.total_used


@dataclass(frozen=True)
class RivalTeamRow:
    """One row in a mini-league standings with chip intelligence."""

    entry_id: int
    team_name: str
    manager_name: str
    rank: int
    last_rank: int
    total_points: int
    event_points: int
    points_behind_leader: int
    points_diff_from_user: int
    chips: RivalChipStatus
    active_chip: Optional[str] = None
    captain_name: Optional[str] = None
    captain_multiplier: int = 1
    is_user: bool = False

    @property
    def rank_change(self) -> int:
        """Rank change (positive = moved up, negative = dropped)."""
        if self.last_rank <= 0:
            return 0
        return self.last_rank - self.rank


@dataclass(frozen=True)
class LeagueChipSummary:
    """Aggregated chip usage metrics for a mini-league."""

    total_teams: int
    wc1_used_pct: float
    wc2_used_pct: float
    fh_used_pct: float
    tc_used_pct: float
    bb_used_pct: float
    user_chips_remaining: int
    avg_rival_chips_remaining: float

    @property
    def user_chip_advantage(self) -> float:
        """Difference between user remaining chips and league average."""
        return round(self.user_chips_remaining - self.avg_rival_chips_remaining, 1)


@dataclass(frozen=True)
class LeagueRankHistoryEntry:
    """One GW snapshot of a user's rank."""

    gameweek: int
    league_rank: int
    total_points: int
    total_teams: int
    is_overall_rank: bool = False


@dataclass(frozen=True)
class LeagueAnalysisReport:
    """Full analysis report for a mini-league."""

    league_id: int
    league_name: str
    league_type: str
    scoring: str
    page: int
    has_next: bool
    current_gameweek: int
    user_entry_id: int
    leader_points: int
    user_points: int
    run_rate_needed: Optional[float]
    standings: Tuple[RivalTeamRow, ...]
    chip_summary: LeagueChipSummary
    total_league_teams: int = 0
    captain_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RivalComparison:
    """Head-to-head comparison between user's squad and a rival's squad."""

    user_entry_id: int
    user_team_name: str
    user_manager_name: str
    rival_entry_id: int
    rival_team_name: str
    rival_manager_name: str
    gameweek: int
    shared_players: Tuple[str, ...]
    user_differentials: Tuple[str, ...]
    rival_differentials: Tuple[str, ...]
    user_captain: str
    rival_captain: str
    user_active_chip: Optional[str]
    rival_active_chip: Optional[str]
    user_chips: RivalChipStatus
    rival_chips: RivalChipStatus
    user_bank: float
    rival_bank: float
    user_cost: float
    rival_cost: float


class LeagueAnalyticsService:
    """High-level service coordinating league discovery, chip tracking, and rival scouting."""

    def __init__(self, client: FPLClient) -> None:
        self.client = client
        self._league_totals_cache: Dict[int, int] = {}

    def get_manager_leagues(self, manager_id: int) -> Tuple[ManagerLeague, ...]:
        """Fetch and categorize all leagues for a manager."""
        if manager_id <= 0:
            raise ValueError("manager_id must be positive")
        entry = self.client.get_entry(manager_id)
        leagues_data = entry.get("leagues", {})
        if not isinstance(leagues_data, Mapping):
            return ()

        result: List[ManagerLeague] = []

        # Classic leagues
        for raw in leagues_data.get("classic", []):
            if not isinstance(raw, Mapping) or "id" not in raw:
                continue
            ltype = str(raw.get("league_type", "s")).strip().lower()
            result.append(
                ManagerLeague(
                    id=int(raw["id"]),
                    name=normalize_display_name(str(raw.get("name", "Classic League"))),
                    short_name=raw.get("short_name"),
                    entry_rank=raw.get("entry_rank"),
                    entry_last_rank=raw.get("entry_last_rank"),
                    league_type=ltype,
                    scoring="classic",
                    is_private=(ltype == "x"),
                )
            )

        # H2H leagues
        for raw in leagues_data.get("h2h", []):
            if not isinstance(raw, Mapping) or "id" not in raw:
                continue
            ltype = str(raw.get("league_type", "s")).strip().lower()
            result.append(
                ManagerLeague(
                    id=int(raw["id"]),
                    name=normalize_display_name(str(raw.get("name", "H2H League"))),
                    short_name=raw.get("short_name"),
                    entry_rank=raw.get("entry_rank"),
                    entry_last_rank=raw.get("entry_last_rank"),
                    league_type=ltype,
                    scoring="h2h",
                    is_private=(ltype == "x"),
                )
            )

        # Sort: private leagues first, then by rank
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    0 if item.is_private else 1,
                    item.entry_rank if item.entry_rank is not None else 99999999,
                ),
            )
        )

    def parse_entry_chips(
        self,
        manager_id: int,
        active_chip: Optional[str] = None,
    ) -> RivalChipStatus:
        """Parse chip history for one manager, distinguishing WC1 and WC2."""
        try:
            history = self.client.get_entry_history(manager_id)
            raw_chips = history.get("chips", [])
        except Exception as exc:
            logger.warning("Could not fetch chip history for manager %s: %s", manager_id, exc)
            return RivalChipStatus(active_chip=active_chip)

        wc1: Optional[int] = None
        wc2: Optional[int] = None
        fh1: Optional[int] = None
        fh2: Optional[int] = None
        tc1: Optional[int] = None
        tc2: Optional[int] = None
        bb1: Optional[int] = None
        bb2: Optional[int] = None

        for chip in raw_chips:
            if not isinstance(chip, Mapping):
                continue
            name = str(chip.get("name", "")).strip().lower()
            event = chip.get("event")
            if event is None:
                continue
            event_gw = int(event)

            if name == "wildcard":
                if event_gw <= 19:
                    wc1 = event_gw
                else:
                    wc2 = event_gw
            elif name == "freehit":
                if event_gw <= 19:
                    fh1 = event_gw
                else:
                    fh2 = event_gw
            elif name in ("3xc", "triple_captain"):
                if event_gw <= 19:
                    tc1 = event_gw
                else:
                    tc2 = event_gw
            elif name in ("bboost", "bench_boost"):
                if event_gw <= 19:
                    bb1 = event_gw
                else:
                    bb2 = event_gw

        return RivalChipStatus(
            wc1=wc1,
            wc2=wc2,
            fh1=fh1,
            fh2=fh2,
            tc1=tc1,
            tc2=tc2,
            bb1=bb1,
            bb2=bb2,
            active_chip=active_chip,
        )

    def _count_total_league_teams(
        self, league_id: int, first_page_results: list, first_page_has_next: bool
    ) -> int:
        """Count total teams in a league using cached exponential + binary search."""
        if league_id in self._league_totals_cache:
            return self._league_totals_cache[league_id]

        total = len(first_page_results)
        if not first_page_has_next:
            self._league_totals_cache[league_id] = total
            return total

        # Exponential search to bracket the end page
        low = 1
        high = 2
        max_bracket = 100  # Up to 5,000 teams (covers 99.9% of mini-leagues)
        last_known_count = total

        while high <= max_bracket:
            try:
                next_payload = self.client.get_classic_league_standings(league_id, page=high)
                st = next_payload.get("standings", {})
                res = st.get("results", [])
                if not res:
                    break
                last_known_count = (high - 1) * 50 + len(res)
                if not st.get("has_next", False):
                    self._league_totals_cache[league_id] = last_known_count
                    return last_known_count
                low = high
                high *= 2
            except Exception:
                break

        # Binary search between low and min(high, max_bracket)
        high = min(high, max_bracket)
        while low <= high:
            mid = (low + high) // 2
            try:
                next_payload = self.client.get_classic_league_standings(league_id, page=mid)
                st = next_payload.get("standings", {})
                res = st.get("results", [])
                if not res:
                    high = mid - 1
                else:
                    last_known_count = max(last_known_count, (mid - 1) * 50 + len(res))
                    if not st.get("has_next", False):
                        self._league_totals_cache[league_id] = last_known_count
                        return last_known_count
                    low = mid + 1
            except Exception:
                break

        self._league_totals_cache[league_id] = last_known_count
        return last_known_count

    def analyze_classic_league(
        self,
        league_id: int,
        user_entry_id: int,
        current_gameweek: int,
        page: int = 1,
        max_teams_to_enrich: int = 50,
    ) -> LeagueAnalysisReport:
        """Fetch standings and enrich with chip usage and captain distribution."""
        if league_id <= 0:
            raise ValueError("league_id must be positive")

        payload = self.client.get_classic_league_standings(league_id, page=page)
        league_meta = payload.get("league", {})
        standings_obj = payload.get("standings", {})
        raw_results = standings_obj.get("results", [])
        has_next = bool(standings_obj.get("has_next", False))

        # Calculate actual total teams in the league
        total_league_teams = self._count_total_league_teams(
            league_id, raw_results, has_next
        )

        league_name = normalize_display_name(str(league_meta.get("name", f"League {league_id}")))
        league_type = str(league_meta.get("league_type", "x"))

        # Look up player web names from bootstrap for captain resolution
        player_names: Dict[int, str] = {}
        try:
            bootstrap = self.client.get_bootstrap()
            for el in bootstrap.get("elements", []):
                if isinstance(el, Mapping) and "id" in el:
                    player_names[int(el["id"])] = str(el.get("web_name", "Unknown"))
        except Exception:
            pass

        leader_points = int(raw_results[0].get("total", 0)) if raw_results else 0

        # Find user's points if present in standings
        user_points = 0
        for r in raw_results:
            if int(r.get("entry", 0)) == user_entry_id:
                user_points = int(r.get("total", 0))
                break

        # Process each rival row
        rows: List[RivalTeamRow] = []
        captain_distribution: Dict[str, int] = {}
        user_chips_status = RivalChipStatus()

        for idx, item in enumerate(raw_results[:max_teams_to_enrich]):
            entry_id = int(item.get("entry", 0))
            is_user = (entry_id == user_entry_id)
            total = int(item.get("total", 0))
            event_total = int(item.get("event_total", 0))
            rank = int(item.get("rank", idx + 1))
            last_rank = int(item.get("last_rank", rank))

            # Fetch active chip & captain from entry_picks if gameweek > 0
            active_chip: Optional[str] = None
            captain_name: Optional[str] = None
            captain_mult = 1

            if current_gameweek > 0:
                try:
                    picks_payload = self.client.get_entry_picks(entry_id, current_gameweek)
                    active_chip = picks_payload.get("active_chip")
                    for pick in picks_payload.get("picks", []):
                        if pick.get("is_captain"):
                            cap_id = int(pick.get("element", 0))
                            captain_name = player_names.get(cap_id, f"ID {cap_id}")
                            captain_mult = int(pick.get("multiplier", 2))
                            captain_distribution[captain_name] = (
                                captain_distribution.get(captain_name, 0) + 1
                            )
                            break
                except Exception:
                    pass

            chips = self.parse_entry_chips(entry_id, active_chip=active_chip)
            if is_user:
                user_chips_status = chips

            rows.append(
                RivalTeamRow(
                    entry_id=entry_id,
                    team_name=normalize_display_name(str(item.get("entry_name", "Unknown Team"))),
                    manager_name=normalize_display_name(str(item.get("player_name", "Unknown"))),
                    rank=rank,
                    last_rank=last_rank,
                    total_points=total,
                    event_points=event_total,
                    points_behind_leader=max(0, leader_points - total),
                    points_diff_from_user=total - user_points,
                    chips=chips,
                    active_chip=active_chip,
                    captain_name=captain_name,
                    captain_multiplier=captain_mult,
                    is_user=is_user,
                )
            )

        # Aggregate chip summary
        total_enriched = len(rows)
        if total_enriched > 0:
            wc1_pct = round(100 * sum(1 for r in rows if r.chips.wc1 is not None) / total_enriched, 1)
            wc2_pct = round(100 * sum(1 for r in rows if r.chips.wc2 is not None) / total_enriched, 1)
            fh_pct = round(100 * sum(1 for r in rows if r.chips.freehit is not None) / total_enriched, 1)
            tc_pct = round(100 * sum(1 for r in rows if r.chips.triple_captain is not None) / total_enriched, 1)
            bb_pct = round(100 * sum(1 for r in rows if r.chips.bench_boost is not None) / total_enriched, 1)
            rival_rows = [r for r in rows if not r.is_user]
            avg_rival_rem = (
                round(sum(r.chips.total_remaining for r in rival_rows) / len(rival_rows), 1)
                if rival_rows
                else float(user_chips_status.total_remaining)
            )
        else:
            wc1_pct = wc2_pct = fh_pct = tc_pct = bb_pct = 0.0
            avg_rival_rem = 5.0

        summary = LeagueChipSummary(
            total_teams=total_enriched,
            wc1_used_pct=wc1_pct,
            wc2_used_pct=wc2_pct,
            fh_used_pct=fh_pct,
            tc_used_pct=tc_pct,
            bb_used_pct=bb_pct,
            user_chips_remaining=user_chips_status.total_remaining,
            avg_rival_chips_remaining=avg_rival_rem,
        )

        # Run rate needed to catch leader
        run_rate_needed: Optional[float] = None
        if user_points < leader_points and current_gameweek < 38:
            remaining_gws = max(1, 38 - current_gameweek)
            run_rate_needed = round((leader_points - user_points) / remaining_gws, 2)

        return LeagueAnalysisReport(
            league_id=league_id,
            league_name=league_name,
            league_type=league_type,
            scoring="classic",
            page=page,
            has_next=has_next,
            current_gameweek=current_gameweek,
            user_entry_id=user_entry_id,
            leader_points=leader_points,
            user_points=user_points,
            run_rate_needed=run_rate_needed,
            standings=tuple(rows),
            chip_summary=summary,
            total_league_teams=total_league_teams,
            captain_distribution=dict(sorted(captain_distribution.items(), key=lambda x: -x[1])),
        )

    def get_league_rank_history(
        self,
        league_id: int,
        user_entry_id: int,
        current_gameweek: int,
        total_league_teams: int = 0,
        max_teams_for_league_recalc: int = 30,
    ) -> Tuple[LeagueRankHistoryEntry, ...]:
        """Compute per-GW rank history for the user.

        If total_league_teams <= 30 (small mini-league), fetches total_points per GW
        for each league member in parallel, re-ranking them to get the exact league rank.
        If total_league_teams > 30 (large mini-league / broad league), fetches the user's
        official Overall Rank per GW (is_overall_rank=True) to avoid making hundreds of
        requests while still giving a complete, informative time-series.
        """
        if current_gameweek <= 0:
            return ()

        # For larger leagues (> 30 teams), provide Overall Rank history per GW instantly
        if total_league_teams > max_teams_for_league_recalc:
            try:
                user_hist = self.client.get_entry_history(user_entry_id)
                res: List[LeagueRankHistoryEntry] = []
                for gw_item in user_hist.get("current", []):
                    gw = int(gw_item.get("event", 0))
                    if 1 <= gw <= current_gameweek:
                        ov_rank = int(gw_item.get("overall_rank", 0) or gw_item.get("rank", 0))
                        pts = int(gw_item.get("total_points", 0))
                        res.append(
                            LeagueRankHistoryEntry(
                                gameweek=gw,
                                league_rank=ov_rank,
                                total_points=pts,
                                total_teams=total_league_teams,
                                is_overall_rank=True,
                            )
                        )
                return tuple(res)
            except Exception as exc:
                logger.warning("Could not fetch user overall history: %s", exc)
                return ()

        # For small mini-leagues (<= 30 teams), fetch all members on page 1
        try:
            payload = self.client.get_classic_league_standings(league_id, page=1)
            standings_obj = payload.get("standings", {})
            raw_results = standings_obj.get("results", [])
            entry_ids = [int(r["entry"]) for r in raw_results if "entry" in r][:max_teams_for_league_recalc]
            if user_entry_id not in entry_ids:
                entry_ids.append(user_entry_id)
        except Exception as exc:
            logger.warning("Could not fetch standings for rank history: %s", exc)
            return ()

        # Fetch member histories in parallel
        member_gw_points: Dict[int, Dict[int, int]] = {}

        def _fetch_member_hist(eid: int) -> Tuple[int, Dict[int, int]]:
            try:
                hist = self.client.get_entry_history(eid)
                gw_pts: Dict[int, int] = {}
                for gw_data in hist.get("current", []):
                    gw = int(gw_data.get("event", 0))
                    total_pts = int(gw_data.get("total_points", 0))
                    if 1 <= gw <= current_gameweek:
                        gw_pts[gw] = total_pts
                return eid, gw_pts
            except Exception:
                return eid, {}

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(entry_ids)))) as executor:
            futures = [executor.submit(_fetch_member_hist, eid) for eid in entry_ids]
            for f in as_completed(futures):
                eid, gw_pts = f.result()
                if gw_pts:
                    member_gw_points[eid] = gw_pts

        if user_entry_id not in member_gw_points:
            return ()

        # Compute user's league rank per GW
        result: List[LeagueRankHistoryEntry] = []
        for gw in range(1, current_gameweek + 1):
            gw_scores: List[Tuple[int, int]] = []
            for eid, gw_map in member_gw_points.items():
                pts = gw_map.get(gw)
                if pts is not None:
                    gw_scores.append((eid, pts))

            if not gw_scores:
                continue

            gw_scores.sort(key=lambda x: -x[1])
            user_rank = 0
            user_pts = 0
            for rank_idx, (eid, pts) in enumerate(gw_scores, start=1):
                if eid == user_entry_id:
                    user_rank = rank_idx
                    user_pts = pts
                    break

            if user_rank > 0:
                result.append(
                    LeagueRankHistoryEntry(
                        gameweek=gw,
                        league_rank=user_rank,
                        total_points=user_pts,
                        total_teams=len(gw_scores),
                        is_overall_rank=False,
                    )
                )

        return tuple(result)

    def compare_teams(
        self,
        user_entry_id: int,
        rival_entry_id: int,
        gameweek: int,
    ) -> RivalComparison:
        """Compare user squad with a rival squad for the given gameweek."""
        user_entry = self.client.get_entry(user_entry_id)
        rival_entry = self.client.get_entry(rival_entry_id)

        user_picks_data = self.client.get_entry_picks(user_entry_id, gameweek)
        rival_picks_data = self.client.get_entry_picks(rival_entry_id, gameweek)

        bootstrap = self.client.get_bootstrap()
        player_names: Dict[int, str] = {
            int(el["id"]): str(el.get("web_name", "Unknown"))
            for el in bootstrap.get("elements", [])
            if isinstance(el, Mapping) and "id" in el
        }
        player_prices: Dict[int, float] = {
            int(el["id"]): float(el.get("now_cost", 0)) / 10.0
            for el in bootstrap.get("elements", [])
            if isinstance(el, Mapping) and "id" in el
        }

        user_picks = user_picks_data.get("picks", [])
        rival_picks = rival_picks_data.get("picks", [])

        user_ids = {int(p["element"]) for p in user_picks if "element" in p}
        rival_ids = {int(p["element"]) for p in rival_picks if "element" in p}

        shared_ids = user_ids.intersection(rival_ids)
        user_diff_ids = user_ids.difference(rival_ids)
        rival_diff_ids = rival_ids.difference(user_ids)

        # Captains
        user_cap = "None"
        for p in user_picks:
            if p.get("is_captain"):
                user_cap = player_names.get(int(p["element"]), f"ID {p['element']}")
                break

        rival_cap = "None"
        for p in rival_picks:
            if p.get("is_captain"):
                rival_cap = player_names.get(int(p["element"]), f"ID {p['element']}")
                break

        user_hist = user_picks_data.get("entry_history", {})
        rival_hist = rival_picks_data.get("entry_history", {})

        user_bank = round(float(user_hist.get("bank", 0)) / 10.0, 1)
        rival_bank = round(float(rival_hist.get("bank", 0)) / 10.0, 1)

        user_cost = round(sum(player_prices.get(pid, 0.0) for pid in user_ids), 1)
        rival_cost = round(sum(player_prices.get(pid, 0.0) for pid in rival_ids), 1)

        user_chips = self.parse_entry_chips(user_entry_id, user_picks_data.get("active_chip"))
        rival_chips = self.parse_entry_chips(rival_entry_id, rival_picks_data.get("active_chip"))

        return RivalComparison(
            user_entry_id=user_entry_id,
            user_team_name=normalize_display_name(str(user_entry.get("name", "Your Team"))),
            user_manager_name=normalize_display_name(
                f"{user_entry.get('player_first_name', '')} {user_entry.get('player_last_name', '')}"
            ),
            rival_entry_id=rival_entry_id,
            rival_team_name=normalize_display_name(str(rival_entry.get("name", "Rival Team"))),
            rival_manager_name=normalize_display_name(
                f"{rival_entry.get('player_first_name', '')} {rival_entry.get('player_last_name', '')}"
            ),
            gameweek=gameweek,
            shared_players=tuple(sorted(player_names.get(pid, f"ID {pid}") for pid in shared_ids)),
            user_differentials=tuple(sorted(player_names.get(pid, f"ID {pid}") for pid in user_diff_ids)),
            rival_differentials=tuple(sorted(player_names.get(pid, f"ID {pid}") for pid in rival_diff_ids)),
            user_captain=user_cap,
            rival_captain=rival_cap,
            user_active_chip=user_picks_data.get("active_chip"),
            rival_active_chip=rival_picks_data.get("active_chip"),
            user_chips=user_chips,
            rival_chips=rival_chips,
            user_bank=user_bank,
            rival_bank=rival_bank,
            user_cost=user_cost,
            rival_cost=rival_cost,
        )


@lru_cache(maxsize=1)
def get_league_analytics_service() -> LeagueAnalyticsService:
    """Factory creating the league analytics service with official ingestion client."""
    ingestion = get_fpl_ingestion_service()
    return LeagueAnalyticsService(ingestion.client)
