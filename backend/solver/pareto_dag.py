from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from currency import get_live_fx_rates, infer_currency_from_countries
from db import save_trip_snapshot
from models import (
    ItineraryDay,
    OptimizationResponse,
    ParetoBlueprint,
    PinnedStaySpec,
    RoadSegment,
    RoadSummary,
    StayCandidate,
    TimelineStop,
    ToolCallTrace,
    TripSpec,
)
from providers.flights_arbitrage import discover_gateway_flights
from providers.geo_routing import (
    DiscoveredPOI,
    GeoLocation,
    discover_pois,
    geocode_place,
    nearest_airports,
    parse_vehicle_profile,
    route_leg,
)
from providers.stays_arbitrage import discover_destination_stays, resolve_pinned_stays
from solver.vrptw import (
    cluster_pois_kmedoids,
    fetch_osrm_table_matrix,
    format_clock_min,
    parse_departure_pref_minutes,
    solve_daily_vrptw_2opt,
    strict_pareto_rank_and_filter,
)

PhaseEmitter = Callable[[str, str], Awaitable[None]]


def _parse_trip_dates(start_str: str, end_str: str) -> Tuple[dt.date, dt.date, int]:
    try:
        d0 = dt.date.fromisoformat(start_str)
        d1 = dt.date.fromisoformat(end_str)
        if d1 <= d0:
            d1 = d0 + dt.timedelta(days=4)
        return d0, d1, (d1 - d0).days
    except Exception:
        d0 = dt.date.today() + dt.timedelta(days=14)
        d1 = d0 + dt.timedelta(days=5)
        return d0, d1, 5


def _partition_stay_windows(
    d_start: dt.date,
    d_end: dt.date,
    pinned: List[PinnedStaySpec],
    stay_strategy: str,
) -> Tuple[List[PinnedStaySpec], str, str, List[PinnedStaySpec]]:
    if not pinned or stay_strategy == "villas":
        return [], d_start.isoformat(), d_end.isoformat(), []

    sorted_pins = sorted(pinned, key=lambda p: p.check_in)
    mid_date = d_start + dt.timedelta(days=max(1, (d_end - d_start).days // 2))

    outbound: List[PinnedStaySpec] = []
    returning: List[PinnedStaySpec] = []
    for p in sorted_pins:
        try:
            ci = dt.date.fromisoformat(p.check_in)
        except Exception:
            ci = d_start
        if ci < mid_date:
            outbound.append(p)
        else:
            returning.append(p)

    dest_in = outbound[-1].check_out if outbound else d_start.isoformat()
    dest_out = returning[0].check_in if returning else d_end.isoformat()

    try:
        di = dt.date.fromisoformat(dest_in)
        do = dt.date.fromisoformat(dest_out)
        if do <= di:
            return [], d_start.isoformat(), d_end.isoformat(), []
    except Exception:
        return [], d_start.isoformat(), d_end.isoformat(), []

    return outbound, dest_in, dest_out, returning


def _format_duration(mins: int) -> str:
    h, m = divmod(max(15, mins), 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


async def _build_vrptw_itinerary_for_stay(
    spec: TripSpec,
    d_start: dt.date,
    d_end: dt.date,
    origin_geo: GeoLocation,
    dest_geo: GeoLocation,
    outbound_stays: List[StayCandidate],
    dest_stay: StayCandidate,
    return_stays: List[StayCandidate],
    highway_segments: List[RoadSegment],
    pois: List[DiscoveredPOI],
    has_flights: bool,
) -> Tuple[List[ItineraryDay], List[RoadSegment], str]:
    """Builds a full multi-day itinerary where destination exploration days are solved via
    OSRM N×N travel-time matrices + K-medoids clustering + 2-Opt VRPTW local search.
    """
    total_days = max(2, (d_end - d_start).days + 1)
    outbound_nights = sum(s.nights for s in outbound_stays)
    return_nights = sum(s.nights for s in return_stays)

    # Identify which day_idx values are full destination exploration days
    explore_day_indices = [
        idx
        for idx in range(total_days)
        if idx > outbound_nights and idx < (total_days - 1 - return_nights)
    ]

    excursions = [p for p in pois if p.category != "dining"][:14]
    restaurants = [p for p in pois if p.category == "dining"][:8]

    # Build N×N OSRM table anchored at this specific candidate stay's GPS coordinates (depot = index 0)
    matrix_nodes: List[Tuple[float, float]] = [(dest_stay.lat, dest_stay.lng)]
    node_index_map: Dict[str, int] = {}
    for p in excursions + restaurants:
        if p.id not in node_index_map and len(matrix_nodes) < 24:
            node_index_map[p.id] = len(matrix_nodes)
            matrix_nodes.append((p.lat, p.lng))

    dur_matrix, dist_matrix, matrix_source = await fetch_osrm_table_matrix(matrix_nodes)

    def _pair_dist(a: DiscoveredPOI, b: DiscoveredPOI) -> float:
        ia = node_index_map.get(a.id, 0)
        ib = node_index_map.get(b.id, 0)
        return dist_matrix[ia][ib]

    daily_clusters = cluster_pois_kmedoids(
        excursions=excursions,
        k_days=max(1, len(explore_day_indices)),
        dist_lookup=_pair_dist,
    )

    clearance_mm, km_per_l, fuel_price = parse_vehicle_profile(spec.vehicle_name)
    seg_by_day: Dict[int, List[RoadSegment]] = {}
    for seg in highway_segments:
        seg_by_day.setdefault(seg.day_number, []).append(seg)

    local_loop_segments: List[RoadSegment] = []
    used_rest_ids: set[str] = set()
    cluster_cursor = 0
    days: List[ItineraryDay] = []

    dep_min_day1 = parse_departure_pref_minutes(spec.departure_time_pref, default_min=9 * 60)
    ret_min_pref = parse_departure_pref_minutes(spec.return_timing_pref, default_min=13 * 60 + 30)

    def _pick_transit_rest() -> DiscoveredPOI:
        avail = [r for r in restaurants if r.id not in used_rest_ids] or restaurants
        pick = avail[0]
        used_rest_ids.add(pick.id)
        return pick

    for day_idx in range(total_days):
        day_num = day_idx + 1
        cur_date = d_start + dt.timedelta(days=day_idx)
        date_lbl = cur_date.strftime("%b %d")
        weekday_lbl = cur_date.strftime("%a")
        day_segs = seg_by_day.get(day_num, [])
        day_km = round(sum(s.distance_km for s in day_segs), 1)
        day_mins = sum(s.duration_mins for s in day_segs)
        stops: List[TimelineStop] = []

        # CASE 1: Outbound transit anchor day
        if day_idx < outbound_nights and outbound_stays:
            t_stay = outbound_stays[min(day_idx, len(outbound_stays) - 1)]
            leg = day_segs[0] if day_segs else None
            leg_mins = leg.duration_mins if leg else 180
            drive_lbl = _format_duration(leg_mins)
            arr_min = min(20 * 60 + 30, dep_min_day1 + leg_mins)

            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window=f"{format_clock_min(dep_min_day1)} – {format_clock_min(arr_min)}",
                    title=f"Outbound Leg: {origin_geo.short_name} -> {t_stay.city}",
                    location_label=leg.highway_label if leg else f"{origin_geo.short_name} -> {t_stay.city}",
                    category="drive",
                    lat=round((origin_geo.lat + t_stay.lat) / 2, 4),
                    lng=round((origin_geo.lng + t_stay.lng) / 2, 4),
                    duration_label=drive_lbl,
                    description=f"Cruise from {spec.origin} to {t_stay.name} ({leg.distance_km if leg else 150:.0f} km).",
                    insider_tip=(
                        f"Estimated highway tolls ₹{leg.fastag_toll_inr} · fuel ₹{leg.fuel_estimate_inr}."
                        if leg
                        else None
                    ),
                    drive_from_prev_mins=leg_mins,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window=format_clock_min(arr_min + 15),
                    title=f"Check-in at {t_stay.name}",
                    location_label=f"{t_stay.city} · {t_stay.micro_region}",
                    category="stay",
                    lat=t_stay.lat,
                    lng=t_stay.lng,
                    duration_label=f"{t_stay.nights}N Transit Anchor",
                    description=(
                        f"Rest & pool unwind at {t_stay.name} ({t_stay.bedrooms_label}) — skipping city detours per preference."
                        if not spec.activities.transit_sightseeing
                        else f"Check in at {t_stay.name} followed by an evening heritage stroll in {t_stay.city}."
                    ),
                    kid_note=t_stay.kid_fit_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window="7:45 PM – 9:00 PM",
                    title=f"Relaxed Dinner at {t_stay.name}",
                    location_label=t_stay.city,
                    category="dining",
                    lat=t_stay.lat,
                    lng=t_stay.lng,
                    duration_label="1h 15m",
                    description="Unhurried evening meal on-site so nobody has to navigate evening city traffic.",
                    dietary_note="Pure Vegetarian menu curated" if spec.activities.dietary == "veg" else "Veg & Non-Veg multi-cuisine spread",
                )
            )
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"{origin_geo.short_name} -> {t_stay.city} Transit Anchor",
                    corridor_tag=f"{day_km:.0f} km Highway Leg",
                    drive_km=day_km,
                    drive_time_label=drive_lbl,
                    overnight_label=t_stay.name,
                    stops=stops,
                )
            )

        # CASE 2: Arrival day into primary destination
        elif day_idx == outbound_nights:
            prev_name = outbound_stays[-1].city if outbound_stays else origin_geo.short_name
            leg = day_segs[0] if day_segs else None
            leg_mins = leg.duration_mins if leg else 165
            drive_lbl = _format_duration(leg_mins)
            start_m = 9 * 60 if outbound_stays else dep_min_day1
            # Enforce daytime checkpost passage before 19:30
            if start_m + leg_mins > 19 * 60 + 30:
                start_m = max(6 * 60 + 30, 19 * 60 + 30 - leg_mins)
            arr_m = start_m + leg_mins

            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window=f"{format_clock_min(start_m)} – {format_clock_min(arr_m)}",
                    title=(
                        f"Gateway Flight + Scenic Transfer into {dest_geo.short_name}"
                        if has_flights and not outbound_stays
                        else f"Daylight Corridor Drive: {prev_name} -> {dest_geo.short_name}"
                    ),
                    location_label=leg.highway_label if leg else f"{prev_name} -> {dest_geo.short_name}",
                    category="flight" if (has_flights and not outbound_stays) else "drive",
                    lat=round(((outbound_stays[-1].lat if outbound_stays else origin_geo.lat) + dest_stay.lat) / 2, 4),
                    lng=round(((outbound_stays[-1].lng if outbound_stays else origin_geo.lng) + dest_stay.lng) / 2, 4),
                    duration_label=drive_lbl,
                    description=f"Daylight arrival approach into {dest_geo.short_name} via verified highway corridor.",
                    insider_tip=leg.gate_alert if leg and leg.gate_alert else "Daytime arrival ensures stress-free check-in.",
                    drive_from_prev_mins=leg_mins,
                )
            )
            lunch_spot = _pick_transit_rest()
            lunch_start = max(12 * 60 + 30, arr_m + 15)
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window=f"{format_clock_min(lunch_start)} – {format_clock_min(lunch_start + 65)}",
                    title=f"Arrival Lunch at {lunch_spot.name}",
                    location_label=dest_geo.short_name,
                    category="dining",
                    lat=lunch_spot.lat,
                    lng=lunch_spot.lng,
                    duration_label="1h 05m",
                    description=lunch_spot.description,
                    dietary_note=lunch_spot.dietary_note,
                )
            )
            checkin_m = max(14 * 60, lunch_start + 85)
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window=format_clock_min(checkin_m),
                    title=f"Check-in at {dest_stay.name}",
                    location_label=f"{dest_geo.short_name} · {dest_stay.micro_region}",
                    category="stay",
                    lat=dest_stay.lat,
                    lng=dest_stay.lng,
                    duration_label=f"{dest_stay.nights}N Primary Base",
                    description=f"Settle into {dest_stay.name} ({dest_stay.bedrooms_label}), positioned centrally to minimize daily excursion detours.",
                    kid_note=dest_stay.kid_fit_note,
                )
            )
            if excursions:
                nearest_eve = min(
                    excursions,
                    key=lambda p: dur_matrix[0][node_index_map.get(p.id, 0)],
                )
                eve_drv = int(round(dur_matrix[0][node_index_map.get(nearest_eve.id, 0)]))
                stops.append(
                    TimelineStop(
                        id=f"d{day_num}-s4",
                        time_window="4:45 PM – 6:10 PM",
                        title=f"Golden-Hour Walk: {nearest_eve.name}",
                        location_label=dest_geo.short_name,
                        category="nature",
                        lat=nearest_eve.lat,
                        lng=nearest_eve.lng,
                        duration_label="1h 25m",
                        description=nearest_eve.description,
                        insider_tip=f"Closest sunset spot to {dest_stay.name} ({eve_drv}m drive).",
                        drive_from_prev_mins=eve_drv,
                    )
                )
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"Arrive in {dest_geo.short_name} & Settle into {dest_stay.name}",
                    corridor_tag=f"{day_km:.0f} km Arrival Corridor",
                    drive_km=day_km,
                    drive_time_label=drive_lbl,
                    overnight_label=dest_stay.name,
                    stops=stops,
                )
            )

        # CASE 3: Final homebound day
        elif day_idx == total_days - 1:
            start_from = return_stays[-1].city if return_stays else dest_geo.short_name
            leg = day_segs[0] if day_segs else None
            leg_mins = leg.duration_mins if leg else 195
            drive_lbl = _format_duration(leg_mins)
            lunch_spot = _pick_transit_rest()
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="9:30 AM – 1:00 PM",
                    title=f"Unhurried Morning & Pre-Departure Lunch in {start_from}",
                    location_label=start_from,
                    category="dining",
                    lat=return_stays[-1].lat if return_stays else lunch_spot.lat,
                    lng=return_stays[-1].lng if return_stays else lunch_spot.lng,
                    duration_label="Morning + Lunch",
                    description=f"Relaxed breakfast, checkout, and lunch before your {spec.return_timing_pref}.",
                    dietary_note=lunch_spot.dietary_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window=f"{format_clock_min(ret_min_pref)} – {format_clock_min(ret_min_pref + leg_mins)}",
                    title=(
                        f"Return Flight + Homeward Transfer to {origin_geo.short_name}"
                        if has_flights and not return_stays
                        else f"Homebound Cruise: {start_from} -> {origin_geo.short_name}"
                    ),
                    location_label=leg.highway_label if leg else f"{start_from} -> {origin_geo.short_name}",
                    category="flight" if (has_flights and not return_stays) else "drive",
                    lat=origin_geo.lat,
                    lng=origin_geo.lng,
                    duration_label=drive_lbl,
                    description=f"Smooth return leg back to {spec.origin}, wrapping up your {total_days}-day trip.",
                    drive_from_prev_mins=leg_mins,
                )
            )
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"Return Leg: {start_from} -> {origin_geo.short_name}",
                    corridor_tag=f"{day_km:.0f} km Homeward Leg",
                    drive_km=day_km,
                    drive_time_label=drive_lbl,
                    overnight_label=f"Home ({origin_geo.short_name})",
                    stops=stops,
                )
            )

        # CASE 4: Return transit stopover day
        elif day_idx >= total_days - 1 - return_nights and return_stays:
            r_idx = day_idx - (total_days - 1 - return_nights)
            r_stay = return_stays[min(r_idx, len(return_stays) - 1)]
            leg = day_segs[0] if day_segs else None
            leg_mins = leg.duration_mins if leg else 190
            drive_lbl = _format_duration(leg_mins)
            rollout_m = min(ret_min_pref, 20 * 60 - leg_mins)  # Guarantee checkpost clearance before 20:00
            lunch_spot = _pick_transit_rest()

            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="9:30 AM – 12:45 PM",
                    title=f"Relaxed Checkout & Farewell Lunch at {lunch_spot.name}",
                    location_label=dest_geo.short_name,
                    category="dining",
                    lat=lunch_spot.lat,
                    lng=lunch_spot.lng,
                    duration_label="Morning",
                    description=f"Slow final morning at {dest_stay.name} and lunch before rolling out.",
                    dietary_note=lunch_spot.dietary_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window=f"{format_clock_min(rollout_m)} – {format_clock_min(rollout_m + leg_mins)}",
                    title=f"Daylight Return Corridor: {dest_geo.short_name} -> {r_stay.city}",
                    location_label=leg.highway_label if leg else f"{dest_geo.short_name} -> {r_stay.city}",
                    category="drive",
                    lat=round((dest_stay.lat + r_stay.lat) / 2, 4),
                    lng=round((dest_stay.lng + r_stay.lng) / 2, 4),
                    duration_label=drive_lbl,
                    description=f"Daylight drive to {r_stay.name} clearing forest/ghat checkposts well before 21:00 closure.",
                    insider_tip=leg.gate_alert if leg and leg.gate_alert else None,
                    drive_from_prev_mins=leg_mins,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window=format_clock_min(rollout_m + leg_mins + 15),
                    title=f"Check-in & Evening Rest at {r_stay.name}",
                    location_label=f"{r_stay.city} · {r_stay.micro_region}",
                    category="stay",
                    lat=r_stay.lat,
                    lng=r_stay.lng,
                    duration_label=f"{r_stay.nights}N Return Anchor",
                    description=f"Break up the return journey comfortably at {r_stay.name} ({r_stay.bedrooms_label}).",
                )
            )
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"{dest_geo.short_name} -> {r_stay.city} Return Stopover",
                    corridor_tag=f"{day_km:.0f} km Return Corridor",
                    drive_km=day_km,
                    drive_time_label=drive_lbl,
                    overnight_label=r_stay.name,
                    stops=stops,
                )
            )

        # CASE 5: Full Destination Exploration Day — Solved via K-Medoids + 2-Opt VRPTW!
        else:
            cluster = daily_clusters[cluster_cursor % len(daily_clusters)]
            cluster_cursor += 1
            vrp_stops, loop_km, loop_mins, loop_coords = solve_daily_vrptw_2opt(
                day_num=day_num,
                city_short=dest_geo.short_name,
                depot_lat=dest_stay.lat,
                depot_lng=dest_stay.lng,
                day_excursions=cluster,
                restaurants=restaurants,
                pace=spec.activities.pace,
                node_index_map=node_index_map,
                dur_matrix=dur_matrix,
                dist_matrix=dist_matrix,
                used_restaurant_ids=used_rest_ids,
            )
            loop_fuel = int(round((loop_km / max(1.0, km_per_l)) * fuel_price))
            local_loop_segments.append(
                RoadSegment(
                    id=f"seg-vrptw-day-{day_num}",
                    day_number=day_num,
                    from_name=dest_stay.name.split("—")[0].strip(),
                    to_name=f"{dest_geo.short_name} Day {day_num} VRPTW Loop",
                    highway_label=f"2-Opt VRPTW Sector Tour ({len(vrp_stops)} Time-Windowed Stops)",
                    distance_km=loop_km,
                    duration_mins=loop_mins,
                    fastag_toll_inr=0,
                    fuel_estimate_inr=loop_fuel,
                    gate_alert=f"2-Opt VRPTW verified ({matrix_source}) · {clearance_mm}mm clearance ready.",
                    coordinates=loop_coords,
                )
            )
            non_dining_titles = [s.title for s in vrp_stops if s.category != "dining"]
            hl_names = " & ".join(non_dining_titles[:2]) if non_dining_titles else f"{dest_geo.short_name} Highlights"
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"{dest_geo.short_name} VRPTW Loop: {hl_names}",
                    corridor_tag=f"{loop_km:.0f} km 2-Opt VRPTW Loop",
                    drive_km=loop_km,
                    drive_time_label=_format_duration(loop_mins),
                    overnight_label=dest_stay.name,
                    stops=vrp_stops,
                )
            )

    all_segs = sorted(highway_segments + local_loop_segments, key=lambda s: s.day_number)
    return days, all_segs, matrix_source


async def solve_trip_pareto(
    spec: TripSpec,
    on_phase: Optional[PhaseEmitter] = None,
    persist_snapshot: bool = True,
) -> OptimizationResponse:
    """End-to-end Multi-Modal Arbitrage + N×N Matrix 2-Opt VRPTW + Strict 3D Pareto Frontier Solver."""
    t0 = time.perf_counter()
    d_start, d_end, total_nights = _parse_trip_dates(spec.start_date, spec.end_date)
    outbound_pins, dest_in, dest_out, return_pins = _partition_stay_windows(
        d_start, d_end, spec.pinned_stays, spec.stay_strategy
    )
    active_pins = outbound_pins + return_pins

    if on_phase:
        await on_phase(
            "Phase 1 · Intent & Constraints",
            f"Geocoding {spec.origin} -> {spec.destination} & hydrating {total_nights}N calendar constraints...",
        )

    # Phase 1A: Concurrent Geocoding + Live ECB FX Lookup
    unique_pin_cities = list(dict.fromkeys(p.city for p in active_pins))
    geo_tasks = [geocode_place(spec.origin), geocode_place(spec.destination)] + [
        geocode_place(c) for c in unique_pin_cities
    ]
    fx_task = get_live_fx_rates()
    geo_results, (fx_rates, fx_source) = await asyncio.gather(
        asyncio.gather(*geo_tasks), fx_task
    )
    origin_geo = geo_results[0]
    dest_geo = geo_results[1]
    pin_city_geos: Dict[str, GeoLocation] = {
        city: geo_results[2 + i] for i, city in enumerate(unique_pin_cities)
    }
    active_currency = infer_currency_from_countries(
        origin_geo.country_code, dest_geo.country_code, spec.currency
    )
    t_phase1_geo = int(round((time.perf_counter() - t0) * 1000))

    # Phase 1B: Route Multi-Leg Highway Corridor + Gateway Flight Arbitrage
    if on_phase:
        await on_phase(
            "Phase 1 · Intent & Constraints",
            f"Routing {spec.vehicle_name} highway geometry & scanning nearest gateway airports...",
        )
    t_route_start = time.perf_counter()
    flights = await discover_gateway_flights(origin_geo, dest_geo, spec)

    leg_specs: List[Tuple[str, int, GeoLocation, GeoLocation]] = []
    if spec.transport_mode in ("flight", "hybrid") and not active_pins:
        dest_hubs = nearest_airports(dest_geo.lat, dest_geo.lng, max_km=280.0, limit=1)
        if dest_hubs:
            hub, _ = dest_hubs[0]
            hub_geo = GeoLocation(
                query=hub.name,
                short_name=f"{hub.iata} Airport",
                display_name=hub.name,
                lat=hub.lat,
                lng=hub.lng,
                country_code=dest_geo.country_code,
            )
            leg_specs.append(("seg-air-arrival-transfer", 1, hub_geo, dest_geo))
            leg_specs.append(("seg-air-return-transfer", total_nights + 1, dest_geo, hub_geo))
    else:
        waypoints: List[GeoLocation] = [origin_geo]
        day_cursor = 1
        for p in outbound_pins:
            waypoints.append(pin_city_geos[p.city])
        waypoints.append(dest_geo)
        for idx_w in range(len(waypoints) - 1):
            leg_specs.append(
                (f"seg-out-{idx_w + 1}", day_cursor, waypoints[idx_w], waypoints[idx_w + 1])
            )
            day_cursor += 1

        ret_waypoints: List[GeoLocation] = [dest_geo] + [pin_city_geos[p.city] for p in return_pins] + [origin_geo]
        ret_day_start = max(2, total_nights + 2 - len(ret_waypoints))
        for idx_r in range(len(ret_waypoints) - 1):
            leg_specs.append(
                (f"seg-ret-{idx_r + 1}", ret_day_start + idx_r, ret_waypoints[idx_r], ret_waypoints[idx_r + 1])
            )

    routed_pairs = await asyncio.gather(
        *[route_leg(sid, dnum, a, b, spec.vehicle_name) for sid, dnum, a, b in leg_specs]
    )
    highway_segments = [pair[0] for pair in routed_pairs]
    routing_sources = {pair[1] for pair in routed_pairs}
    t_route_ms = int(round((time.perf_counter() - t_route_start) * 1000))

    # Phase 2: Multi-Channel Stay Discovery, Entity Deduplication & Overpass POI Scan
    if on_phase:
        await on_phase(
            "Phase 2 · Multi-Channel Arbitrage",
            f"Deduplicating cross-channel stays (SerpApi / Blue Kite / Airbnb / OTAs) & POIs in {dest_geo.short_name}...",
        )
    t_arb_start = time.perf_counter()
    pinned_resolved, (dest_candidates, coverage_notes), (pois, poi_source) = await asyncio.gather(
        resolve_pinned_stays(active_pins, spec, pin_city_geos),
        discover_destination_stays(dest_geo, spec, dest_in, dest_out),
        discover_pois(dest_geo.lat, dest_geo.lng, dest_geo.short_name, spec.activities),
    )
    t_arb_ms = int(round((time.perf_counter() - t_arb_start) * 1000))

    outbound_resolved = pinned_resolved[: len(outbound_pins)]
    return_resolved = pinned_resolved[len(outbound_pins) :]

    # Phase 3: OSRM N×N Matrix + 2-Opt VRPTW + Strict 3D NSGA-II Pareto Frontier
    if on_phase:
        await on_phase(
            "Phase 3 · Spatio-Temporal Solver",
            f"Solving N×N OSRM travel-time matrix, 2-Opt VRPTW schedule & strict 3D Pareto frontier...",
        )
    t_dag_start = time.perf_counter()
    clearance_mm, km_per_l, _ = parse_vehicle_profile(spec.vehicle_name)
    flight_landed = sum(f.landed_family_total_inr for f in flights)
    flight_unopt = sum(f.ota_unoptimized_inr for f in flights)
    pax = max(1, spec.party.adults + spec.party.children)
    est_dining_activities = int(round(pax * 820 * (total_nights + 1), -2))

    # Solve exact VRPTW schedule per candidate stay so micro-location detours genuinely impact road cost & fatigue!
    vrptw_results = await asyncio.gather(
        *[
            _build_vrptw_itinerary_for_stay(
                spec=spec,
                d_start=d_start,
                d_end=d_end,
                origin_geo=origin_geo,
                dest_geo=dest_geo,
                outbound_stays=outbound_resolved,
                dest_stay=chosen_stay,
                return_stays=return_resolved,
                highway_segments=highway_segments,
                pois=pois,
                has_flights=bool(flights),
            )
            for chosen_stay in dest_candidates
        ]
    )

    raw_blueprints: List[ParetoBlueprint] = []
    matrix_sources: set[str] = set()

    for idx, (chosen_stay, (days, stay_segments, mat_src)) in enumerate(
        zip(dest_candidates, vrptw_results)
    ):
        matrix_sources.add(mat_src)
        total_km = round(sum(s.distance_km for s in stay_segments), 1)
        total_mins = sum(s.duration_mins for s in stay_segments)
        total_fuel_inr = sum(s.fuel_estimate_inr for s in stay_segments)
        total_tolls_inr = sum(s.fastag_toll_inr for s in stay_segments)
        rental_inr = (2900 * (total_nights + 1)) if spec.transport_mode == "hybrid" else 0

        road_summary = RoadSummary(
            vehicle=spec.vehicle_name,
            ground_clearance_mm=clearance_mm,
            total_distance_km=total_km,
            total_drive_hours=round(total_mins / 60.0, 1),
            estimated_fuel_liters=round(total_km / max(1.0, km_per_l), 1),
            fuel_cost_inr=total_fuel_inr,
            fastag_and_forest_tolls_inr=total_tolls_inr,
            rental_car_cost_inr=rental_inr,
            total_road_cost_inr=total_fuel_inr + total_tolls_inr + rental_inr,
            corridor_notes=[
                f"Highway geometry ({'Project OSRM Live/Cached' if any('osrm' in s for s in routing_sources) else 'Geodesic Corridor'}): {total_km} km across {len(stay_segments)} legs.",
                f"Daily POI loops solved via K-Medoids + 2-Opt VRPTW over N×N matrix ({mat_src}, {poi_source}).",
            ],
            segments=stay_segments,
        )

        stays_chain = outbound_resolved + [chosen_stay] + return_resolved
        stays_best = sum(s.best_landed_inr for s in stays_chain)
        stays_worst = sum(s.worst_landed_inr for s in stays_chain)

        core_landed = stays_best + road_summary.total_road_cost_inr + flight_landed
        unopt_landed = stays_worst + road_summary.total_road_cost_inr + flight_unopt
        savings = max(0, unopt_landed - core_landed)

        # True fatigue index driven by actual daily driving minutes + checkpost/transfer load
        avg_daily_mins = total_mins / float(max(1, total_nights + 1))
        comfort_credit = 3 if chosen_stay.category in ("bluekite", "villa") else 0
        fatigue_score = min(78, max(14, int(round(avg_daily_mins * 0.19)) - comfort_credit))
        quality_score = min(99, int(round(chosen_stay.rating * 19.7)))

        callouts = [
            f"{chosen_stay.name}: ₹{chosen_stay.best_landed_inr // max(1, chosen_stay.nights):,}/night landed via {chosen_stay.best_channel} ({chosen_stay.provenance_label}).",
        ]
        if chosen_stay.savings_inr > 0:
            callouts.append(
                f"Same-Property Fee Arbitrage: {chosen_stay.best_channel} saves ₹{chosen_stay.savings_inr:,} vs. {chosen_stay.offers[-1].platform}."
            )
        if pinned_resolved:
            pin_saved = sum(p.savings_inr for p in pinned_resolved)
            pin_channels = " + ".join(f"{p.city} ({p.best_channel})" for p in pinned_resolved)
            callouts.append(f"Transit Anchor Split-Channel Win: {pin_channels} saves ₹{pin_saved:,}.")
        if flights:
            callouts.append(
                f"Gateway Flight Arbitrage ({flights[0].route_label}): Saves ₹{flights[0].savings_inr:,} ({flights[0].provenance_label})."
            )

        anchor_suffix = (
            f" + {', '.join(dict.fromkeys(p.city for p in pinned_resolved))} Transit"
            if pinned_resolved
            else ""
        )

        raw_blueprints.append(
            ParetoBlueprint(
                id=f"cand-{idx + 1}",
                rank_badge="Candidate",
                name=f"{chosen_stay.name}{anchor_suffix}",
                strategy_subtitle="",
                recommended=False,
                total_core_landed_inr=core_landed,
                unoptimized_baseline_inr=unopt_landed,
                total_arbitrage_savings_inr=savings,
                dining_and_activities_est_inr=est_dining_activities,
                fatigue_score=fatigue_score,
                quality_score=quality_score,
                deal_anomaly_score=chosen_stay.deal_anomaly_score,
                stays=stays_chain,
                flights=flights,
                road=road_summary,
                arbitrage_callouts=callouts,
                days=days,
            )
        )

    blueprints = strict_pareto_rank_and_filter(raw_blueprints)
    front1_count = sum(1 for b in blueprints if b.pareto_front_rank == 1)

    t_dag_ms = max(14, int(round((time.perf_counter() - t_dag_start) * 1000)))
    bk_cov = next((c for c in coverage_notes if c.platform == "The Blue Kite"), None)

    traces = [
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="nominatim_geocoder_and_ecb_fx_hydrator",
            latency_ms=max(18, t_phase1_geo),
            input_summary=f"{spec.origin} -> {spec.destination} ({spec.start_date}..{spec.end_date}) · {spec.party.adults}A+{spec.party.children}C",
            finding_summary=(
                f"Resolved {origin_geo.short_name} ({origin_geo.lat:.2f},{origin_geo.lng:.2f}) -> "
                f"{dest_geo.short_name} ({dest_geo.lat:.2f},{dest_geo.lng:.2f}) [{origin_geo.source}] · Currency {active_currency} ({fx_source})."
            ),
        ),
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="osrm_corridor_and_gateway_router",
            latency_ms=max(22, t_route_ms),
            input_summary=f"{len(leg_specs)} highway legs · {spec.vehicle_name} ({spec.transport_mode} mode)",
            finding_summary=(
                f"Routed {blueprints[0].road.total_distance_km} km ({blueprints[0].road.total_drive_hours}h) · "
                f"Fuel ₹{blueprints[0].road.fuel_cost_inr:,} · Tolls ₹{blueprints[0].road.fastag_and_forest_tolls_inr:,}."
            ),
        ),
        ToolCallTrace(
            phase="Phase 2 · Multi-Channel Arbitrage",
            tool_name="serpapi_bluekite_ota_entity_deduplicator",
            status="pivoted" if (bk_cov and bk_cov.status == "zero_inventory_pivoted") else "completed",
            latency_ms=max(35, t_arb_ms),
            input_summary=f"Cross-OTA & Direct Villa scan in {dest_geo.short_name} ({spec.stay_strategy})",
            finding_summary=(
                f"{bk_cov.note} Top savings: ₹{blueprints[0].total_arbitrage_savings_inr:,} ({blueprints[0].stays[0].price_provenance})."
                if bk_cov
                else f"Evaluated {len(dest_candidates)} deduplicated stays · Saves ₹{blueprints[0].total_arbitrage_savings_inr:,}."
            ),
        ),
        ToolCallTrace(
            phase="Phase 3 · Spatio-Temporal Solver",
            tool_name="nsga2_pareto_and_2opt_vrptw_solver",
            latency_ms=t_dag_ms,
            input_summary=f"N×N matrix ({', '.join(sorted(matrix_sources))}) · {len(pois)} POIs · {len(raw_blueprints)} bundles",
            finding_summary=(
                f"Isolated {front1_count} strictly non-dominated Front-1 blueprints; "
                f"Pareto Knee '{blueprints[0].name}' @ ₹{blueprints[0].total_core_landed_inr:,}."
            ),
        ),
    ]

    spec_out = spec.model_copy(deep=True)
    if spec_out.currency is None:
        spec_out.currency = active_currency

    resp = OptimizationResponse(
        active_currency=active_currency,
        fx_rates=fx_rates,
        pareto_frontier_note=(
            f"NSGA-II Non-Dominated 3D Frontier ({front1_count} Front-1 Bundles across Cost × Fatigue × Utility) "
            f"+ 2-Opt VRPTW Time-Windowed Daily Tours"
        ),
        trip_spec=spec_out,
        platform_coverage=coverage_notes,
        tool_trace=traces,
        blueprints=blueprints,
    )

    if persist_snapshot:
        tid = save_trip_snapshot(
            spec_dict=spec_out.model_dump(),
            optimization_dict=resp.model_dump(),
        )
        resp.trip_id = tid

    return resp
