from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import httpx

from db import RATE_LIMITER, cache_get_json, cache_set_json
from models import ParetoBlueprint, TimelineStop
from providers.geo_routing import USER_AGENT, DiscoveredPOI, haversine_km


@dataclass
class ScheduledStopSpec:
    poi: DiscoveredPOI
    open_min: int
    close_min: int
    service_mins: int


def format_clock_min(mins_from_midnight: int) -> str:
    clamped = max(0, min(23 * 60 + 59, int(round(mins_from_midnight))))
    h24, m = divmod(clamped, 60)
    suffix = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {suffix}"


def parse_departure_pref_minutes(pref: str, default_min: int = 540) -> int:
    """Parses user departure preference strings like '2pm', '9:30 AM', 'Early afternoon' into minutes."""
    low = (pref or "").strip().lower()
    explicit = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    if explicit:
        hh = int(explicit.group(1))
        mm = int(explicit.group(2) or "0")
        mer = explicit.group(3)
        if mer == "pm" and hh != 12:
            hh += 12
        elif mer == "am" and hh == 12:
            hh = 0
        return hh * 60 + mm
    if "early morning" in low or "dawn" in low:
        return 6 * 60 + 30
    if "morning" in low:
        return 9 * 60
    if "after lunch" in low or "post lunch" in low:
        return 14 * 60
    if "early afternoon" in low:
        return 13 * 60 + 15
    if "afternoon" in low:
        return 14 * 60 + 15
    if "evening" in low:
        return 17 * 60
    return default_min


def parse_osm_time_window(oh_raw: Optional[str], category: str) -> Tuple[int, int]:
    """Parses OpenStreetMap `opening_hours` syntax into (open_mins, close_mins)."""
    if category == "dining":
        # Lunch anchor window [12:15 PM, 2:45 PM] even if restaurant stays open till night
        return 12 * 60 + 15, 14 * 60 + 45

    if oh_raw:
        m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", oh_raw)
        if m:
            o_min = int(m.group(1)) * 60 + int(m.group(2))
            c_min = int(m.group(3)) * 60 + int(m.group(4))
            if c_min > o_min + 60:
                # Cap outdoor climbs/trails at 17:30 dusk safety cutoff
                if category == "climb":
                    c_min = min(c_min, 17 * 60 + 30)
                return o_min, c_min

    if category == "climb":
        return 8 * 60, 16 * 60 + 45
    if category == "heritage":
        return 9 * 60 + 30, 18 * 60
    return 8 * 60 + 30, 18 * 60 + 15


async def fetch_osrm_table_matrix(
    coords_lat_lng: List[Tuple[float, float]],
) -> Tuple[List[List[float]], List[List[float]], str]:
    """Fetches asymmetric N×N travel duration (mins) and distance (km) matrices from Project OSRM Table API."""
    n = len(coords_lat_lng)
    if n == 0:
        return [], [], "empty"

    # Limit to 24 nodes for public OSRM table endpoint etiquette
    pts = coords_lat_lng[:24]
    n = len(pts)

    sig_raw = ";".join(f"{lat:.4f},{lng:.4f}" for lat, lng in pts)
    digest = hashlib.sha256(sig_raw.encode("utf-8")).hexdigest()[:14]
    cache_key = f"osrm_table:v3:{n}:{digest}"

    cached = cache_get_json(cache_key)
    if isinstance(cached, dict) and cached.get("durations") and cached.get("distances"):
        return cached["durations"], cached["distances"], "osrm_table_cached"

    def _fallback_matrices() -> Tuple[List[List[float]], List[List[float]]]:
        dur_m: List[List[float]] = [[0.0] * n for _ in range(n)]
        dist_m: List[List[float]] = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                gc = haversine_km(pts[i][0], pts[i][1], pts[j][0], pts[j][1])
                road_km = round(max(1.2, gc * 1.34), 2)
                mins = round(max(4.0, (road_km / 34.0) * 60.0), 1)
                dist_m[i][j] = road_km
                dur_m[i][j] = mins
        return dur_m, dist_m

    try:
        await RATE_LIMITER.acquire("osrm_table", min_interval_sec=0.15)
        coord_path = ";".join(f"{lng:.5f},{lat:.5f}" for lat, lng in pts)
        url = f"https://router.project-osrm.org/table/v1/driving/{coord_path}"
        async with httpx.AsyncClient(timeout=4.5, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(url, params={"annotations": "duration,distance"})
            if resp.status_code == 200:
                body = resp.json() or {}
                raw_durs = body.get("durations")
                raw_dists = body.get("distances")
                if raw_durs and len(raw_durs) == n:
                    fb_dur, fb_dist = _fallback_matrices()
                    dur_m = [[0.0] * n for _ in range(n)]
                    dist_m = [[0.0] * n for _ in range(n)]
                    for i in range(n):
                        for j in range(n):
                            if i == j:
                                continue
                            d_sec = raw_durs[i][j]
                            m_val = raw_dists[i][j] if (raw_dists and raw_dists[i][j] is not None) else None
                            dur_m[i][j] = (
                                round(max(3.0, float(d_sec) / 60.0), 1)
                                if d_sec is not None
                                else fb_dur[i][j]
                            )
                            dist_m[i][j] = (
                                round(max(0.8, float(m_val) / 1000.0), 2)
                                if m_val is not None
                                else fb_dist[i][j]
                            )
                    cache_set_json(
                        cache_key,
                        "osrm_table",
                        {"durations": dur_m, "distances": dist_m},
                        ttl_seconds=86400,
                    )
                    return dur_m, dist_m, "osrm_table_live"
    except Exception:
        pass

    fb_dur, fb_dist = _fallback_matrices()
    return fb_dur, fb_dist, "geodesic_matrix_fallback"


def cluster_pois_kmedoids(
    excursions: List[DiscoveredPOI],
    k_days: int,
    dist_lookup: Callable[[DiscoveredPOI, DiscoveredPOI], float],
) -> List[List[DiscoveredPOI]]:
    """Partitions excursion POIs into `k_days` spatially compact daily clusters via PAM K-Medoids."""
    if k_days <= 1 or len(excursions) <= 2:
        return [list(excursions)]

    k = min(k_days, len(excursions))
    # Deterministic farthest-first medoid seeding
    medoids: List[int] = [0]
    while len(medoids) < k:
        best_idx = 0
        best_min_d = -1.0
        for idx, cand in enumerate(excursions):
            if idx in medoids:
                continue
            min_d = min(dist_lookup(cand, excursions[m]) for m in medoids)
            if min_d > best_min_d:
                best_min_d = min_d
                best_idx = idx
        medoids.append(best_idx)

    # PAM refinement (up to 8 iterations)
    for _ in range(8):
        clusters_idx: List[List[int]] = [[] for _ in range(k)]
        for i, poi in enumerate(excursions):
            best_c = min(range(k), key=lambda c: dist_lookup(poi, excursions[medoids[c]]))
            clusters_idx[best_c].append(i)

        changed = False
        for c in range(k):
            members = clusters_idx[c]
            if not members:
                continue
            best_medoid = min(
                members,
                key=lambda m_cand: sum(dist_lookup(excursions[m_cand], excursions[o]) for o in members),
            )
            if best_medoid != medoids[c]:
                medoids[c] = best_medoid
                changed = True
        if not changed:
            break

    # Balanced assignment so every exploration day gets at least 2 excursions when pool allows
    cap = max(2, (len(excursions) + k - 1) // k)
    buckets: List[List[DiscoveredPOI]] = [[] for _ in range(k)]
    for poi in excursions:
        ranked_clusters = sorted(range(k), key=lambda c: dist_lookup(poi, excursions[medoids[c]]))
        placed = False
        for c in ranked_clusters:
            if len(buckets[c]) < cap:
                buckets[c].append(poi)
                placed = True
                break
        if not placed:
            buckets[ranked_clusters[0]].append(poi)

    return [b for b in buckets if b]


def _evaluate_tour_cost(
    seq_indices: List[int],
    specs: List[ScheduledStopSpec],
    dur_from_depot: List[float],
    dur_to_depot: List[float],
    pair_dur: List[List[float]],
    day_start_min: int = 525,  # 08:45 AM departure from stay
    gate_close_min: int = 1230,  # 08:30 PM safe return buffer before 21:00 forest checkpost ban
) -> Tuple[float, float, List[Tuple[int, int, int]]]:
    """Evaluates (time_window_penalty, total_drive_mins, [(arrive, start, depart), ...]) for a candidate tour."""
    if not seq_indices:
        return 0.0, 0.0, []

    penalty = 0.0
    total_drive = 0.0
    continuous_drive = 0.0
    cur_clock = float(day_start_min)
    timings: List[Tuple[int, int, int]] = []

    for pos, node_i in enumerate(seq_indices):
        leg_drive = dur_from_depot[node_i] if pos == 0 else pair_dur[seq_indices[pos - 1]][node_i]
        total_drive += leg_drive
        continuous_drive += leg_drive
        if continuous_drive > 210.0:
            penalty += (continuous_drive - 210.0) * 12.0

        arr = cur_clock + leg_drive
        st_spec = specs[node_i]
        start_srv = max(arr, float(st_spec.open_min))
        wait_mins = start_srv - arr
        if wait_mins > 45.0:
            penalty += (wait_mins - 45.0) * 1.5

        end_srv = start_srv + st_spec.service_mins
        if end_srv > st_spec.close_min:
            penalty += (end_srv - st_spec.close_min) * 18.0

        # Encourage climbs in cooler morning slot before 12:30 PM
        if st_spec.poi.category == "climb" and start_srv > 750:
            penalty += (start_srv - 750) * 2.5

        timings.append((int(round(arr)), int(round(start_srv)), int(round(end_srv))))
        cur_clock = end_srv
        if st_spec.poi.category == "dining":
            continuous_drive = 0.0

    ret_drive = dur_to_depot[seq_indices[-1]]
    total_drive += ret_drive
    back_at_stay = cur_clock + ret_drive
    if back_at_stay > gate_close_min:
        penalty += (back_at_stay - gate_close_min) * 25.0

    return penalty, total_drive, timings


def solve_daily_vrptw_2opt(
    day_num: int,
    city_short: str,
    depot_lat: float,
    depot_lng: float,
    day_excursions: List[DiscoveredPOI],
    restaurants: List[DiscoveredPOI],
    pace: str,
    node_index_map: dict[str, int],
    dur_matrix: List[List[float]],
    dist_matrix: List[List[float]],
    used_restaurant_ids: set[str],
) -> Tuple[List[TimelineStop], float, int, List[List[float]]]:
    """Solves exact daily POI + lunch routing using 2-Opt local search with OSM opening-hour time windows."""
    target_exc = 2 if pace == "relaxed" else (3 if pace == "explorer" else 2)
    chosen_exc = day_excursions[: max(1, target_exc)]

    def _dur(id_a: Optional[str], id_b: Optional[str]) -> float:
        ia = 0 if id_a is None else node_index_map.get(id_a, 0)
        ib = 0 if id_b is None else node_index_map.get(id_b, 0)
        return dur_matrix[ia][ib]

    def _dist(id_a: Optional[str], id_b: Optional[str]) -> float:
        ia = 0 if id_a is None else node_index_map.get(id_a, 0)
        ib = 0 if id_b is None else node_index_map.get(id_b, 0)
        return dist_matrix[ia][ib]

    # Pick minimum-detour restaurant relative to today's excursion cluster
    avail_rests = [r for r in restaurants if r.id not in used_restaurant_ids] or restaurants
    best_lunch = min(
        avail_rests,
        key=lambda r: sum(_dist(e.id, r.id) for e in chosen_exc) + _dist(None, r.id) * 0.35,
    )
    used_restaurant_ids.add(best_lunch.id)

    day_pois = list(chosen_exc) + [best_lunch]
    specs: List[ScheduledStopSpec] = []
    for p in day_pois:
        o_min, c_min = parse_osm_time_window(p.opening_hours_raw, p.category)
        srv = 75 if p.category == "dining" else (130 if p.category == "climb" else 105)
        specs.append(ScheduledStopSpec(poi=p, open_min=o_min, close_min=c_min, service_mins=srv))

    m = len(specs)
    dur_from_depot = [_dur(None, s.poi.id) for s in specs]
    dur_to_depot = [_dur(s.poi.id, None) for s in specs]
    pair_dur = [[_dur(specs[i].poi.id, specs[j].poi.id) for j in range(m)] for i in range(m)]

    # Nearest-window feasible initial sequence
    seq = sorted(range(m), key=lambda idx: (specs[idx].open_min, dur_from_depot[idx]))
    best_pen, best_drv, best_timings = _evaluate_tour_cost(
        seq, specs, dur_from_depot, dur_to_depot, pair_dur
    )

    # 2-Opt + adjacent swap local search guaranteeing local optimality on (penalty, total_drive)
    improved = True
    while improved:
        improved = False
        for i in range(m):
            for j in range(i + 1, m):
                cand_seq = seq[:i] + list(reversed(seq[i : j + 1])) + seq[j + 1 :]
                pen, drv, tim = _evaluate_tour_cost(
                    cand_seq, specs, dur_from_depot, dur_to_depot, pair_dur
                )
                if (pen, drv) < (best_pen - 1e-6, best_drv - 1e-6) or (
                    abs(pen - best_pen) <= 1e-6 and drv < best_drv - 0.05
                ):
                    seq = cand_seq
                    best_pen, best_drv, best_timings = pen, drv, tim
                    improved = True

    # Assemble TimelineStops + exact routed loop distance & polyline
    stops_out: List[TimelineStop] = []
    loop_coords: List[List[float]] = [[round(depot_lng, 4), round(depot_lat, 4)]]
    total_km = 0.0

    for pos, node_i in enumerate(seq):
        sp = specs[node_i]
        p = sp.poi
        prev_id = None if pos == 0 else specs[seq[pos - 1]].poi.id
        leg_km = _dist(prev_id, p.id)
        leg_mins = int(round(_dur(prev_id, p.id)))
        total_km += leg_km
        loop_coords.append([round(p.lng, 4), round(p.lat, 4)])

        _, start_m, end_m = best_timings[pos]
        dur_h, dur_rem = divmod(sp.service_mins, 60)
        dur_lbl = f"{dur_h}h {dur_rem:02d}m" if dur_h > 0 else f"{dur_rem}m"
        title_str = f"Regional Lunch at {p.name}" if p.category == "dining" else p.name

        tip_parts = []
        if leg_mins > 0:
            tip_parts.append(f"{leg_mins}m drive ({leg_km:.1f} km)")
        if p.insider_tip:
            tip_parts.append(p.insider_tip)

        stops_out.append(
            TimelineStop(
                id=f"d{day_num}-s{pos + 1}",
                time_window=f"{format_clock_min(start_m)} – {format_clock_min(end_m)}",
                title=title_str,
                location_label=f"{city_short} ({p.cuisine_or_tag})",
                category=p.category,  # type: ignore[arg-type]
                lat=round(p.lat, 4),
                lng=round(p.lng, 4),
                duration_label=dur_lbl,
                description=p.description,
                dietary_note=p.dietary_note,
                kid_note=p.kid_note,
                insider_tip=" · ".join(tip_parts) if tip_parts else None,
                drive_from_prev_mins=leg_mins,
            )
        )

    total_km += _dist(specs[seq[-1]].poi.id, None)
    loop_coords.append([round(depot_lng, 4), round(depot_lat, 4)])

    return stops_out, round(max(12.0, total_km), 1), max(20, int(round(best_drv))), loop_coords


def strict_pareto_rank_and_filter(candidates: List[ParetoBlueprint]) -> List[ParetoBlueprint]:
    """NSGA-II Non-Dominated Sorting + Crowding Distance over 3D objectives:
    Minimize (total_core_landed_inr, fatigue_score, -composite_utility).
    """
    if not candidates:
        return []

    def _obj(bp: ParetoBlueprint) -> Tuple[float, float, float]:
        utility = bp.quality_score * 0.55 + bp.deal_anomaly_score * 0.45
        return (float(bp.total_core_landed_inr), float(bp.fatigue_score), -utility)

    def _dominates(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> bool:
        return (a[0] <= b[0] and a[1] <= b[1] and a[2] <= b[2]) and (
            a[0] < b[0] or a[1] < b[1] or a[2] < b[2]
        )

    objs = [_obj(c) for c in candidates]
    n = len(candidates)
    dom_counts = [0] * n
    dominated_sets: List[List[int]] = [[] for _ in range(n)]
    fronts: List[List[int]] = [[]]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _dominates(objs[i], objs[j]):
                dominated_sets[i].append(j)
            elif _dominates(objs[j], objs[i]):
                dom_counts[i] += 1
        if dom_counts[i] == 0:
            candidates[i].pareto_front_rank = 1
            fronts[0].append(i)

    f_idx = 0
    while f_idx < len(fronts) and fronts[f_idx]:
        next_front: List[int] = []
        for i in fronts[f_idx]:
            for j in dominated_sets[i]:
                dom_counts[j] -= 1
                if dom_counts[j] == 0:
                    candidates[j].pareto_front_rank = f_idx + 2
                    next_front.append(j)
        if next_front:
            fronts.append(next_front)
        f_idx += 1

    # Compute normalized L1 crowding distance inside each front
    for front in fronts:
        if len(front) <= 2:
            for idx in front:
                candidates[idx].crowding_distance = 10.0
            continue
        crowding = {idx: 0.0 for idx in front}
        for dim in range(3):
            ordered = sorted(front, key=lambda idx: objs[idx][dim])
            crowding[ordered[0]] = 10.0
            crowding[ordered[-1]] = 10.0
            span = max(1e-6, objs[ordered[-1]][dim] - objs[ordered[0]][dim])
            for pos in range(1, len(ordered) - 1):
                crowding[ordered[pos]] += (
                    objs[ordered[pos + 1]][dim] - objs[ordered[pos - 1]][dim]
                ) / span
        for idx in front:
            candidates[idx].crowding_distance = round(min(10.0, crowding[idx]), 3)

    # Select strictly non-dominated Front 1; include Front 2 runner-ups only if Front 1 is singleton
    front1_indices = fronts[0]
    selected_indices = list(front1_indices)
    if len(selected_indices) < 3 and len(fronts) > 1:
        runner_ups = sorted(fronts[1], key=lambda idx: (-candidates[idx].crowding_distance, objs[idx][0]))
        selected_indices.extend(runner_ups[: 3 - len(selected_indices)])
    selected_indices = selected_indices[:3]

    # Identify Utopia Knee on Front 1 (minimum normalized distance to ideal point)
    mins = [min(objs[i][d] for i in selected_indices) for d in range(3)]
    spans = [max(1e-6, max(objs[i][d] for i in selected_indices) - mins[d]) for d in range(3)]

    def _utopia_dist(idx: int) -> float:
        return sum(((objs[idx][d] - mins[d]) / spans[d]) ** 2 for d in range(3)) ** 0.5

    knee_idx = min(front1_indices, key=_utopia_dist)
    min_cost_idx = min(selected_indices, key=lambda idx: objs[idx][0])
    min_fatigue_idx = min(selected_indices, key=lambda idx: (objs[idx][1], objs[idx][2]))

    # Order with Pareto Knee first so blueprints[0] is always the mathematically optimal recommended bundle
    ordered_final = [knee_idx] + [
        idx for idx in sorted(selected_indices, key=lambda i: (candidates[i].pareto_front_rank, objs[i][0]))
        if idx != knee_idx
    ]

    result: List[ParetoBlueprint] = []
    for out_pos, orig_i in enumerate(ordered_final):
        bp = candidates[orig_i]
        bp.id = f"bp-{out_pos + 1}"
        bp.recommended = orig_i == knee_idx

        if bp.pareto_front_rank > 1:
            bp.rank_badge = f"Runner-Up (Front #{bp.pareto_front_rank})"
            bp.strategy_subtitle = "Near-Frontier Alternative · Diversified Micro-Location"
        elif orig_i == knee_idx:
            bp.rank_badge = "Pareto Knee · Optimal Value"
            bp.strategy_subtitle = "Utopia-Closest Trade-Off Across Cost, Fatigue & Utility"
        elif orig_i == min_cost_idx:
            bp.rank_badge = "Pareto Min-Cost · Lowest All-In"
            bp.strategy_subtitle = "Strictly Non-Dominated Minimum Landed Checkout"
        elif orig_i == min_fatigue_idx:
            bp.rank_badge = "Pareto Min-Fatigue · Peak Comfort"
            bp.strategy_subtitle = "Shortest Excursion Detours & Highest Stay Tier"
        else:
            bp.rank_badge = "Pareto Frontier · High Utility"
            bp.strategy_subtitle = "Strictly Non-Dominated Quality & Arbitrage Pick"

        result.append(bp)

    return result
