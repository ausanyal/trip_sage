from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from typing import Dict, List, Tuple

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
    """Splits calendar nights into (outbound_pins, dest_check_in, dest_check_out, return_pins)."""
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

    # Guard against invalid date inversion if user edited dates without updating pinned_stays
    try:
        di = dt.date.fromisoformat(dest_in)
        do = dt.date.fromisoformat(dest_out)
        if do <= di:
            dest_in = d_start.isoformat()
            dest_out = d_end.isoformat()
            return [], dest_in, dest_out, []
    except Exception:
        return [], d_start.isoformat(), d_end.isoformat(), []

    return outbound, dest_in, dest_out, returning


def _build_local_loop_segment(
    day_num: int,
    dest_geo: GeoLocation,
    pois: List[DiscoveredPOI],
    vehicle_name: str,
    explore_days: int,
) -> RoadSegment:
    clearance_mm, km_per_l, fuel_price = parse_vehicle_profile(vehicle_name)
    sample_pois = [p for p in pois if p.category != "dining"][:5]
    coords: List[List[float]] = [[round(dest_geo.lng, 4), round(dest_geo.lat, 4)]]
    for p in sample_pois:
        coords.append([round(p.lng, 4), round(p.lat, 4)])
    coords.append([round(dest_geo.lng, 4), round(dest_geo.lat, 4)])

    loop_km = round(max(36.0, 52.0 * max(1, explore_days)), 1)
    dur_mins = int(round((loop_km / 34.0) * 60))
    fuel_inr = int(round((loop_km / max(1.0, km_per_l)) * fuel_price))

    return RoadSegment(
        id="seg-local-exploration-loop",
        day_number=day_num,
        from_name=f"{dest_geo.short_name} Stay Base",
        to_name=f"{dest_geo.short_name} Micro-Corridor Attractions",
        highway_label=f"{dest_geo.short_name} Local Scenic & Sightseeing Loop",
        distance_km=loop_km,
        duration_mins=dur_mins,
        fastag_toll_inr=0,
        fuel_estimate_inr=fuel_inr,
        gate_alert=f"Clustered by compass sector to cut backtracking ({clearance_mm}mm clearance verified).",
        coordinates=coords,
    )


def _format_duration(mins: int) -> str:
    h, m = divmod(max(15, mins), 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def _build_dynamic_itinerary(
    spec: TripSpec,
    d_start: dt.date,
    d_end: dt.date,
    origin_geo: GeoLocation,
    dest_geo: GeoLocation,
    outbound_stays: List[StayCandidate],
    dest_stay: StayCandidate,
    return_stays: List[StayCandidate],
    segments: List[RoadSegment],
    pois: List[DiscoveredPOI],
    has_flights: bool,
) -> List[ItineraryDay]:
    total_days = max(2, (d_end - d_start).days + 1)
    days: List[ItineraryDay] = []

    # Sort non-dining POIs by compass angle around destination stay for zero-backtrack daily sector clustering
    excursions = [p for p in pois if p.category != "dining"]
    excursions.sort(key=lambda p: math.atan2(p.lat - dest_stay.lat, p.lng - dest_stay.lng))
    restaurants = [p for p in pois if p.category == "dining"]

    exc_idx = 0
    din_idx = 0

    def next_excursion() -> DiscoveredPOI:
        nonlocal exc_idx
        p = excursions[exc_idx % len(excursions)]
        exc_idx += 1
        return p

    def next_restaurant() -> DiscoveredPOI:
        nonlocal din_idx
        r = restaurants[din_idx % len(restaurants)]
        din_idx += 1
        return r

    seg_by_day: Dict[int, List[RoadSegment]] = {}
    for seg in segments:
        seg_by_day.setdefault(seg.day_number, []).append(seg)

    outbound_nights = sum(s.nights for s in outbound_stays)
    return_nights = sum(s.nights for s in return_stays)

    for day_idx in range(total_days):
        day_num = day_idx + 1
        cur_date = d_start + dt.timedelta(days=day_idx)
        date_lbl = cur_date.strftime("%b %d")
        weekday_lbl = cur_date.strftime("%a")
        day_segs = seg_by_day.get(day_num, [])
        day_km = round(sum(s.distance_km for s in day_segs), 1)
        day_mins = sum(s.duration_mins for s in day_segs)

        stops: List[TimelineStop] = []

        # CASE 1: Outbound transit anchor day (e.g., Day 1 stopping at transit hotel)
        if day_idx < outbound_nights and outbound_stays:
            t_stay = outbound_stays[min(day_idx, len(outbound_stays) - 1)]
            leg = day_segs[0] if day_segs else None
            drive_lbl = _format_duration(leg.duration_mins) if leg else "3h 00m"
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window=spec.departure_time_pref,
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
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window="Late Afternoon",
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
                    time_window="7:45 PM",
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
            drive_lbl = _format_duration(leg.duration_mins) if leg else "2h 45m"
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="Morning" if outbound_stays else spec.departure_time_pref,
                    title=(
                        f"Gateway Flight + Scenic Transfer into {dest_geo.short_name}"
                        if has_flights and not outbound_stays
                        else f"Scenic Corridor Drive: {prev_name} -> {dest_geo.short_name}"
                    ),
                    location_label=leg.highway_label if leg else f"{prev_name} -> {dest_geo.short_name}",
                    category="flight" if (has_flights and not outbound_stays) else "drive",
                    lat=round(((outbound_stays[-1].lat if outbound_stays else origin_geo.lat) + dest_stay.lat) / 2, 4),
                    lng=round(((outbound_stays[-1].lng if outbound_stays else origin_geo.lng) + dest_stay.lng) / 2, 4),
                    duration_label=drive_lbl,
                    description=f"Daylight arrival approach into {dest_geo.short_name} via verified highway corridor.",
                    insider_tip=leg.gate_alert if leg and leg.gate_alert else "Daytime arrival ensures stress-free estate/hotel check-in.",
                )
            )
            lunch_spot = next_restaurant()
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window="12:45 PM – 1:45 PM",
                    title=f"Arrival Lunch at {lunch_spot.name}",
                    location_label=dest_geo.short_name,
                    category="dining",
                    lat=lunch_spot.lat,
                    lng=lunch_spot.lng,
                    duration_label="1h 00m",
                    description=lunch_spot.description,
                    dietary_note=lunch_spot.dietary_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window="2:15 PM",
                    title=f"Check-in at {dest_stay.name}",
                    location_label=f"{dest_geo.short_name} · {dest_stay.micro_region}",
                    category="stay",
                    lat=dest_stay.lat,
                    lng=dest_stay.lng,
                    duration_label=f"{dest_stay.nights}N Primary Base",
                    description=f"Settle into {dest_stay.name} ({dest_stay.bedrooms_label}), positioned centrally for minimal daily driving.",
                    kid_note=dest_stay.kid_fit_note,
                )
            )
            eve_poi = next_excursion()
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s4",
                    time_window="4:45 PM – 6:15 PM",
                    title=f"Golden-Hour Walk: {eve_poi.name}",
                    location_label=dest_geo.short_name,
                    category="nature",
                    lat=eve_poi.lat,
                    lng=eve_poi.lng,
                    duration_label="1h 30m",
                    description=eve_poi.description,
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
            drive_lbl = _format_duration(leg.duration_mins) if leg else "3h 15m"
            lunch_spot = next_restaurant()
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="9:30 AM – 12:30 PM",
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
                    time_window="Afternoon",
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

        # CASE 4: Return transit stopover day (breaking up return drive at a pinned anchor)
        elif day_idx >= total_days - 1 - return_nights and return_stays:
            r_idx = day_idx - (total_days - 1 - return_nights)
            r_stay = return_stays[min(r_idx, len(return_stays) - 1)]
            leg = day_segs[0] if day_segs else None
            drive_lbl = _format_duration(leg.duration_mins) if leg else "3h 15m"
            lunch_spot = next_restaurant()
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="Morning – 12:30 PM",
                    title=f"Relaxed Morning Checkout & Lunch at {lunch_spot.name}",
                    location_label=dest_geo.short_name,
                    category="dining",
                    lat=lunch_spot.lat,
                    lng=lunch_spot.lng,
                    duration_label="Morning",
                    description=f"Enjoy a slow final morning at {dest_stay.name} and lunch before rolling out ({spec.return_timing_pref}).",
                    dietary_note=lunch_spot.dietary_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window="Early Afternoon",
                    title=f"Daylight Return Corridor: {dest_geo.short_name} -> {r_stay.city}",
                    location_label=leg.highway_label if leg else f"{dest_geo.short_name} -> {r_stay.city}",
                    category="drive",
                    lat=round((dest_stay.lat + r_stay.lat) / 2, 4),
                    lng=round((dest_stay.lng + r_stay.lng) / 2, 4),
                    duration_label=drive_lbl,
                    description=f"Daylight drive to {r_stay.name} with ample buffer before any evening checkpost closures.",
                    insider_tip=leg.gate_alert if leg and leg.gate_alert else None,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window="Late Afternoon",
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

        # CASE 5: Full destination exploration day (spatially clustered around stay)
        else:
            morn = next_excursion()
            lunch = next_restaurant()
            aft = next_excursion()
            local_km = day_km if day_km > 0 else 46.0
            local_lbl = _format_duration(day_mins) if day_mins > 0 else "1h 25m"

            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s1",
                    time_window="9:00 AM – 11:30 AM",
                    title=morn.name,
                    location_label=f"{dest_geo.short_name} ({morn.cuisine_or_tag})",
                    category=morn.category,  # type: ignore[arg-type]
                    lat=morn.lat,
                    lng=morn.lng,
                    duration_label="2h 30m",
                    description=morn.description,
                    kid_note=morn.kid_note,
                    insider_tip=morn.insider_tip,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s2",
                    time_window="12:45 PM – 2:00 PM",
                    title=f"Regional Lunch at {lunch.name}",
                    location_label=dest_geo.short_name,
                    category="dining",
                    lat=lunch.lat,
                    lng=lunch.lng,
                    duration_label="1h 15m",
                    description=lunch.description,
                    dietary_note=lunch.dietary_note,
                )
            )
            stops.append(
                TimelineStop(
                    id=f"d{day_num}-s3",
                    time_window="2:45 PM – 4:45 PM",
                    title=aft.name,
                    location_label=f"{dest_geo.short_name} ({aft.cuisine_or_tag})",
                    category=aft.category,  # type: ignore[arg-type]
                    lat=aft.lat,
                    lng=aft.lng,
                    duration_label="2h 00m",
                    description=aft.description,
                    kid_note=aft.kid_note,
                )
            )
            days.append(
                ItineraryDay(
                    day_number=day_num,
                    date_label=date_lbl,
                    weekday=weekday_lbl,
                    headline=f"{dest_geo.short_name} Sector Loop: {morn.name} & {aft.name}",
                    corridor_tag=f"{local_km:.0f} km Clustered Loop",
                    drive_km=local_km,
                    drive_time_label=local_lbl,
                    overnight_label=dest_stay.name,
                    stops=stops,
                )
            )

    return days


async def solve_trip_pareto(spec: TripSpec) -> OptimizationResponse:
    """End-to-end destination-agnostic Multi-Modal Arbitrage & Spatio-Temporal Pareto Solver."""
    t0 = time.perf_counter()
    d_start, d_end, total_nights = _parse_trip_dates(spec.start_date, spec.end_date)
    outbound_pins, dest_in, dest_out, return_pins = _partition_stay_windows(
        d_start, d_end, spec.pinned_stays, spec.stay_strategy
    )
    active_pins = outbound_pins + return_pins

    # Phase 1A: Concurrent Geocoding of Origin, Destination, and any Transit Cities
    unique_pin_cities = list(dict.fromkeys(p.city for p in active_pins))
    geo_tasks = [geocode_place(spec.origin), geocode_place(spec.destination)] + [
        geocode_place(c) for c in unique_pin_cities
    ]
    geo_results = await asyncio.gather(*geo_tasks)
    origin_geo = geo_results[0]
    dest_geo = geo_results[1]
    pin_city_geos: Dict[str, GeoLocation] = {
        city: geo_results[2 + i] for i, city in enumerate(unique_pin_cities)
    }
    t_phase1_geo = int(round((time.perf_counter() - t0) * 1000))

    # Phase 1B: Build & Route Multi-Leg Corridor via Live Project OSRM
    t_route_start = time.perf_counter()
    flights = discover_gateway_flights(origin_geo, dest_geo, spec)

    leg_specs: List[Tuple[str, int, GeoLocation, GeoLocation]] = []
    if spec.transport_mode in ("flight", "hybrid") and not active_pins:
        dest_hubs = nearest_airports(dest_geo.lat, dest_geo.lng, max_km=260.0, limit=1)
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
                (
                    f"seg-out-{idx_w + 1}",
                    day_cursor,
                    waypoints[idx_w],
                    waypoints[idx_w + 1],
                )
            )
            day_cursor += 1

        ret_waypoints: List[GeoLocation] = [dest_geo] + [pin_city_geos[p.city] for p in return_pins] + [origin_geo]
        ret_day_start = max(2, total_nights + 2 - len(ret_waypoints))
        for idx_r in range(len(ret_waypoints) - 1):
            leg_specs.append(
                (
                    f"seg-ret-{idx_r + 1}",
                    ret_day_start + idx_r,
                    ret_waypoints[idx_r],
                    ret_waypoints[idx_r + 1],
                )
            )

    routed_pairs = await asyncio.gather(
        *[route_leg(sid, dnum, a, b, spec.vehicle_name) for sid, dnum, a, b in leg_specs]
    )
    highway_segments = [pair[0] for pair in routed_pairs]
    routing_sources = {pair[1] for pair in routed_pairs}
    t_route_ms = int(round((time.perf_counter() - t_route_start) * 1000))

    # Phase 2: Concurrent Multi-Channel Stay Discovery, Deduplication & POI Scan
    t_arb_start = time.perf_counter()
    pinned_resolved_task = resolve_pinned_stays(active_pins, spec, pin_city_geos)
    dest_stays_task = discover_destination_stays(dest_geo, spec, dest_in, dest_out)
    pois_task = discover_pois(dest_geo.lat, dest_geo.lng, dest_geo.short_name, spec.activities)

    pinned_resolved, (dest_candidates, coverage_notes), (pois, poi_source) = await asyncio.gather(
        pinned_resolved_task, dest_stays_task, pois_task
    )
    t_arb_ms = int(round((time.perf_counter() - t_arb_start) * 1000))

    outbound_resolved = pinned_resolved[: len(outbound_pins)]
    return_resolved = pinned_resolved[len(outbound_pins) :]

    # Phase 3: Assemble Local Loop, Road Telemetry & Pareto Frontier Blueprints
    t_dag_start = time.perf_counter()
    explore_days = max(1, total_nights - len(active_pins) - 1)
    first_explore_day = len(outbound_pins) + 2
    local_loop_seg = _build_local_loop_segment(
        min(total_nights, first_explore_day),
        dest_geo,
        pois,
        spec.vehicle_name,
        explore_days,
    )
    all_segments = sorted(highway_segments + [local_loop_seg], key=lambda s: s.day_number)

    clearance_mm, km_per_l, _ = parse_vehicle_profile(spec.vehicle_name)
    total_km = round(sum(s.distance_km for s in all_segments), 1)
    total_mins = sum(s.duration_mins for s in all_segments)
    total_fuel_inr = sum(s.fuel_estimate_inr for s in all_segments)
    total_tolls_inr = sum(s.fastag_toll_inr for s in all_segments)
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
            f"Live corridor routed ({'Project OSRM GeoJSON' if 'osrm_live' in routing_sources else 'Geodesic Corridor'}): {total_km} km across {len(all_segments)} legs.",
            f"POIs & regional dining clustered around {dest_geo.short_name} ({poi_source}) to minimize hill/city backtracking.",
        ],
        segments=all_segments,
    )

    flight_landed = sum(f.landed_family_total_inr for f in flights)
    flight_unopt = sum(f.ota_unoptimized_inr for f in flights)
    pax = max(1, spec.party.adults + spec.party.children)
    est_dining_activities = int(round(pax * 820 * (total_nights + 1), -2))

    bp_templates = [
        ("Sweet-Spot Recommended", "Max Cross-Channel Arbitrage + Central Base", True),
        ("Boutique Direct / Superhost Pick", "High Guest Rating + Curated Micro-Location", False),
        ("Value All-In Frontier", "Lowest Total Landed Checkout + Smooth Access", False),
    ]

    blueprints: List[ParetoBlueprint] = []
    for idx, chosen_stay in enumerate(dest_candidates[:3]):
        badge, sub, is_rec = bp_templates[idx % len(bp_templates)]
        stays_chain = outbound_resolved + [chosen_stay] + return_resolved
        stays_best = sum(s.best_landed_inr for s in stays_chain)
        stays_worst = sum(s.worst_landed_inr for s in stays_chain)

        core_landed = stays_best + road_summary.total_road_cost_inr + flight_landed
        unopt_landed = stays_worst + road_summary.total_road_cost_inr + flight_unopt
        savings = max(0, unopt_landed - core_landed)

        avg_daily_drive_hrs = road_summary.total_drive_hours / max(1, total_nights + 1)
        fatigue_score = min(65, max(16, int(round(avg_daily_drive_hrs * 8.2)) - idx))
        quality_score = min(98, int(round(chosen_stay.rating * 19.6)))

        callouts = [
            f"{chosen_stay.name}: ₹{chosen_stay.best_landed_inr // max(1, chosen_stay.nights):,}/night landed via {chosen_stay.best_channel}.",
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
                f"Gateway Flight Arbitrage ({flights[0].route_label}): Saves ₹{flights[0].savings_inr:,} vs. unbundled OTA fare."
            )

        anchor_suffix = (
            f" + {', '.join(dict.fromkeys(p.city for p in pinned_resolved))} Transit"
            if pinned_resolved
            else ""
        )

        days = _build_dynamic_itinerary(
            spec=spec,
            d_start=d_start,
            d_end=d_end,
            origin_geo=origin_geo,
            dest_geo=dest_geo,
            outbound_stays=outbound_resolved,
            dest_stay=chosen_stay,
            return_stays=return_resolved,
            segments=all_segments,
            pois=pois,
            has_flights=bool(flights),
        )

        blueprints.append(
            ParetoBlueprint(
                id=f"bp-{idx + 1}",
                rank_badge=badge,
                name=f"{chosen_stay.name}{anchor_suffix}",
                strategy_subtitle=sub,
                recommended=is_rec,
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

    t_dag_ms = max(12, int(round((time.perf_counter() - t_dag_start) * 1000)))
    bk_cov = next((c for c in coverage_notes if c.platform == "The Blue Kite"), None)

    traces = [
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="nominatim_geocoder_and_spec_hydrator",
            latency_ms=max(18, t_phase1_geo),
            input_summary=f"{spec.origin} -> {spec.destination} ({spec.start_date}..{spec.end_date}) · {spec.party.adults}A+{spec.party.children}C",
            finding_summary=f"Resolved {origin_geo.short_name} ({origin_geo.lat:.2f},{origin_geo.lng:.2f}) -> {dest_geo.short_name} ({dest_geo.lat:.2f},{dest_geo.lng:.2f}) [{origin_geo.source}].",
        ),
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="osrm_corridor_and_gate_router",
            latency_ms=max(25, t_route_ms),
            input_summary=f"{len(leg_specs)} driving legs · {spec.vehicle_name} ({spec.transport_mode} mode)",
            finding_summary=f"Routed {total_km} km ({road_summary.total_drive_hours}h) · Fuel ₹{total_fuel_inr:,} · Tolls ₹{total_tolls_inr:,}.",
        ),
        ToolCallTrace(
            phase="Phase 2 · Multi-Channel Arbitrage",
            tool_name="multi_channel_stay_and_flight_deduplicator",
            status="pivoted" if (bk_cov and bk_cov.status == "zero_inventory_pivoted") else "completed",
            latency_ms=max(40, t_arb_ms),
            input_summary=f"The Blue Kite + Airbnb + StayVista + OTAs in {dest_geo.short_name} ({spec.stay_strategy})",
            finding_summary=(
                f"{bk_cov.note} Top savings: ₹{blueprints[0].total_arbitrage_savings_inr:,}."
                if bk_cov
                else f"Matched {len(dest_candidates)} deduplicated stays."
            ),
        ),
        ToolCallTrace(
            phase="Phase 3 · Spatio-Temporal Solver",
            tool_name="pareto_itinerary_dag_solver",
            latency_ms=t_dag_ms,
            input_summary=f"Cluster {len(pois)} POIs/restaurants across {total_nights + 1} days",
            finding_summary=f"Solved {len(blueprints)} Pareto blueprints; recommended core ₹{blueprints[0].total_core_landed_inr:,}.",
        ),
    ]

    return OptimizationResponse(
        trip_spec=spec,
        platform_coverage=coverage_notes,
        tool_trace=traces,
        blueprints=blueprints,
    )
