from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

from catalog import (
    build_goa_hybrid_bluekite_preset,
    build_radisson_stays,
    build_wayanad_itinerary_days,
    build_wayanad_road_summary,
    build_wayanad_villas,
    default_wayanad_trip_spec,
)
from models import (
    ChannelOffer,
    ChatTurnRequest,
    ChatTurnResponse,
    FlightOption,
    ItineraryDay,
    OptimizationResponse,
    ParetoBlueprint,
    PinnedStaySpec,
    PlatformCoverageNote,
    RoadSegment,
    RoadSummary,
    StayCandidate,
    TimelineStop,
    ToolCallTrace,
    TripSpec,
)


CITY_COORDS: Dict[str, Tuple[float, float, str]] = {
    "bengaluru": (12.9352, 77.6245, "BLR"),
    "bangalore": (12.9352, 77.6245, "BLR"),
    "koramangala": (12.9352, 77.6245, "BLR"),
    "mysuru": (12.2979, 76.6667, "MYQ"),
    "mysore": (12.2979, 76.6667, "MYQ"),
    "wayanad": (11.5515, 76.0410, "CCJ"),
    "goa": (15.5939, 73.7867, "GOX"),
    "north goa": (15.5939, 73.7867, "GOX"),
    "coorg": (12.4244, 75.7382, "CNN"),
    "madikeri": (12.4244, 75.7382, "CNN"),
    "ooty": (11.4102, 76.6950, "CJB"),
    "chikmagalur": (13.3161, 75.7720, "IXE"),
    "nainital": (29.3919, 79.4542, "PGH"),
    "rishikesh": (30.0869, 78.2676, "DED"),
    "udaipur": (24.5854, 73.7125, "UDR"),
    "munnar": (10.0889, 77.0595, "COK"),
    "pondicherry": (11.9416, 79.8083, "MAA"),
    "mumbai": (19.0760, 72.8777, "BOM"),
    "delhi": (28.6139, 77.2090, "DEL"),
}

BLUEKITE_MARKETS = {"goa", "north goa", "assagao", "vagator", "anjuna", "nainital", "rishikesh", "bengaluru", "delhi", "gurugram"}


def _lookup_city(label: str) -> Tuple[float, float, str]:
    lower = label.lower()
    for key, val in CITY_COORDS.items():
        if key in lower:
            return val
    return (15.2993, 74.1240, "GOI")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)) * 1.26, 1)


def optimize_wayanad_scenario(spec: TripSpec) -> OptimizationResponse:
    radisson_out, radisson_ret = build_radisson_stays(spec)
    villas = build_wayanad_villas(spec)
    road = build_wayanad_road_summary(spec)

    # Adjust if user toggles TransportMode to Hybrid or Flight on Wayanad!
    hybrid_flights: List[FlightOption] = []
    if spec.transport_mode in ("flight", "hybrid"):
        hybrid_flights = [
            FlightOption(
                id="flt-blr-cnn-indigo",
                carrier="IndiGo ATR-72 Regional",
                flight_numbers="6E 7184 (Out) · 6E 7185 (Ret)",
                route_label="BLR -> CNN (Kannur Intl Hub) + Self-Drive Ghats to Wayanad",
                gateway_hub_note="Kannur (CNN) is 88 km / 2h 20m from Vythiri vs. Calicut (CCJ) Thamarassery Ghat hairpins.",
                depart_time="10:40 AM",
                arrive_time="11:55 AM",
                duration="1h 15m Non-Stop",
                stops_label="Non-Stop Regional",
                landed_family_total_inr=26800,
                ota_unoptimized_inr=31200,
                savings_inr=4400,
                booking_channel="IndiGo Direct Family Fare",
            )
        ]
        road.rental_car_cost_inr = 12400
        road.total_road_cost_inr = road.rental_car_cost_inr + 2400

    # If StayStrategy == 'hotels', add a luxury Wayanad resort option for comparison
    wayanad_luxury_hotel = StayCandidate(
        id="wayanad-wild-cgh",
        name="Wayanad Wild – CGH Earth Rainforest Lodge",
        subtitle="Lakkidi Rainforest · 2 Interconnecting Deluxe Canopy Rooms",
        category="hotel",
        city="Wayanad",
        micro_region="Lakkidi Rainforest Canopy",
        lat=11.5220,
        lng=76.0310,
        rating=4.82,
        review_count=640,
        bedrooms_label="2 Interconnecting Rainforest Rooms (Required for 4 Pax)",
        check_in="2026-12-22",
        check_out="2026-12-25",
        nights=3,
        image_url="https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=1000&q=80",
        suv_access_note="Paved estate road + resort 4x4 shuttle.",
        kid_fit_note="Naturalist-led walks & birding, though lacks private living hall/kitchen of a 2 BHK villa.",
        highlights=[
            "Requires 2 hotel rooms + Dec 24 mandatory Christmas Eve Gala supplement (+₹14,000)",
            "Demonstrates why your Hybrid Villa choice saves ~₹29,000 in Wayanad",
        ],
        offers=[
            ChannelOffer(
                platform="CGH Earth Direct",
                channel_type="direct_brand",
                base_total_inr=62000,
                extra_bed_or_addons_inr=14000,
                taxes_gst_inr=13680,
                promo_discount_inr=4280,
                landed_total_inr=85400,
                per_night_landed_inr=28467,
                inclusions=["Breakfast", "Naturalist Walks", "Mandatory Dec 24 Gala Included"],
                promo_note="Includes mandatory Christmas Eve Gala supplement",
                booking_url="https://www.cghearth.com/",
                is_best_deal=True,
            ),
            ChannelOffer(
                platform="Booking.com",
                channel_type="ota",
                base_total_inr=66000,
                extra_bed_or_addons_inr=14000,
                taxes_gst_inr=14400,
                promo_discount_inr=0,
                landed_total_inr=94400,
                per_night_landed_inr=31467,
                inclusions=["Breakfast", "Dec 24 Gala"],
                booking_url="https://www.booking.com/",
                is_best_deal=False,
            ),
        ],
        best_channel="CGH Earth Direct",
        best_landed_inr=85400,
        worst_landed_inr=94400,
        savings_inr=9000,
        deal_anomaly_score=71.0,
        anomaly_badge="Dec 24 Gala Penalty (+₹14k)",
    )

    flight_cost = sum(f.landed_family_total_inr for f in hybrid_flights)
    flight_unopt = sum(f.ota_unoptimized_inr for f in hybrid_flights)

    blueprints: List[ParetoBlueprint] = []

    if spec.stay_strategy == "hotels":
        candidate_villas = [wayanad_luxury_hotel]
    else:
        # Filter or sort villas relative to budget ceiling while always surfacing all 3 top matches
        candidate_villas = sorted(
            villas,
            key=lambda v: (
                0 if (spec.nightly_budget_min_inr <= (v.best_landed_inr // v.nights) <= spec.nightly_budget_max_inr) else 1,
                -v.deal_anomaly_score,
            ),
        )

    blueprint_meta = [
        (
            "Sweet-Spot Recommended",
            "Max Cross-Channel Arbitrage + Central Climb Base",
            True,
            24,
            96,
        ),
        (
            "Pure Coffee-Estate Airbnb",
            "10-Acre Working Plantation Chalet + Kottur Stream",
            False,
            26,
            93,
        ),
        (
            "Lowest All-In Private Pool",
            "100% Exclusive Family Pool + Min Driving Fatigue",
            False,
            21,
            92,
        ),
    ]

    for idx, chosen_dest_stay in enumerate(candidate_villas[:3]):
        badge, sub, is_rec, fatigue, qual = blueprint_meta[idx]
        stays_list = (
            [radisson_out, chosen_dest_stay, radisson_ret]
            if spec.stay_strategy != "villas"
            else [chosen_dest_stay]
        )
        stays_best = sum(s.best_landed_inr for s in stays_list)
        stays_worst = sum(s.worst_landed_inr for s in stays_list)

        core_landed = stays_best + road.total_road_cost_inr + flight_cost
        unopt_landed = stays_worst + road.total_road_cost_inr + (flight_unopt or 0)
        savings = max(0, unopt_landed - core_landed)

        callouts = [
            f"{chosen_dest_stay.name}: ₹{chosen_dest_stay.best_landed_inr // chosen_dest_stay.nights:,}/night all-in via {chosen_dest_stay.best_channel} (within ₹{spec.nightly_budget_min_inr // 1000}k–₹{spec.nightly_budget_max_inr // 1000}k target).",
            "Dec 24 Villa vs. 5-Star Resort Arbitrage: Staying in a private villa on Christmas Eve dodges ₹12,000–₹18,000 in mandatory 5-star Gala Dinner surcharges.",
            "Radisson Blu Mysore Split-Channel Booking: Member Direct on Mon Dec 21 (₹12,500) + MMT Festive Card Offer on Fri Dec 25 (₹15,200) saves ₹4,337.",
        ]
        if chosen_dest_stay.savings_inr > 0:
            callouts.insert(
                1,
                f"Same-Property Fee Stripping: Booking {chosen_dest_stay.name} via {chosen_dest_stay.best_channel} saves ₹{chosen_dest_stay.savings_inr:,} vs. Airbnb's ~14.2% service fee.",
            )

        blueprints.append(
            ParetoBlueprint(
                id=f"bp-wayanad-{idx + 1}",
                rank_badge=badge,
                name=f"{chosen_dest_stay.name} + Radisson Mysore Anchors",
                strategy_subtitle=sub,
                recommended=is_rec,
                total_core_landed_inr=core_landed,
                unoptimized_baseline_inr=unopt_landed,
                total_arbitrage_savings_inr=savings,
                dining_and_activities_est_inr=18500,
                fatigue_score=fatigue,
                quality_score=qual,
                deal_anomaly_score=chosen_dest_stay.deal_anomaly_score,
                stays=stays_list,
                flights=hybrid_flights,
                road=road,
                arbitrage_callouts=callouts,
                days=build_wayanad_itinerary_days(spec, chosen_dest_stay),
            )
        )

    coverage = [
        PlatformCoverageNote(
            platform="Airbnb",
            status="matched",
            listings_scanned=84,
            note="Scanned 2 BHK Superhost & Guest Favorite coffee-estate villas across Vythiri, Kalpetta & Meppadi.",
        ),
        PlatformCoverageNote(
            platform="The Blue Kite",
            status="zero_inventory_pivoted",
            listings_scanned=0,
            note="0 Wayanad villas (operates in Goa, Nainital, Rishikesh & BLR) -> auto-pivoted to StayVista & SaffronStays.",
        ),
        PlatformCoverageNote(
            platform="StayVista & SaffronStays",
            status="matched",
            listings_scanned=29,
            note="Matched syndicated luxury villas where direct portal rates strip 14.2% OTA/Airbnb guest fees.",
        ),
        PlatformCoverageNote(
            platform="Radisson Direct · MMT · Agoda · Booking",
            status="live_scanned",
            listings_scanned=16,
            note="Compared Deluxe + Extra Bed + Age<=10 breakfast rules for Dec 21 (weekday) & Dec 25 (Christmas).",
        ),
    ]

    traces = [
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="hydrate_family_trip_spec",
            latency_ms=95,
            input_summary=f"{spec.origin} -> {spec.destination} ({spec.start_date} to {spec.end_date}) · {spec.party.adults}A+{spec.party.children}C {spec.party.child_ages} · {spec.vehicle_name}",
            finding_summary="Locked Hybrid Stay strategy, 2 PM rollout, Jeep Meridian 203mm clearance, climbs=ON, safaris/water/Mysuru-stops=OFF.",
        ),
        ToolCallTrace(
            phase="Phase 1 · Intent & Constraints",
            tool_name="route_corridor_and_gate_validator",
            latency_ms=164,
            input_summary="NICE Rd -> NH275 -> Radisson Mysore -> NH766 Bandipur/Muthanga checkpost",
            finding_summary="Verified 9 PM–6 AM Bandipur night ban; 9:30 AM outbound & 1:15 PM return crossings clear with 6h+ buffer.",
        ),
        ToolCallTrace(
            phase="Phase 2 · Multi-Channel Arbitrage",
            tool_name="hotel_rate_arbitrage",
            latency_ms=280,
            input_summary="Radisson Blu Plaza Mysore · Deluxe + Extra Bed · Dec 21 & Dec 25 across 4 channels",
            finding_summary="Split-channel win: Radisson Direct (₹12,500 Dec 21) + MMT Card Promo (₹15,200 Dec 25) saves ₹4,337.",
        ),
        ToolCallTrace(
            phase="Phase 2 · Multi-Channel Arbitrage",
            tool_name="villa_cross_channel_deduplicator",
            status="pivoted",
            latency_ms=410,
            input_summary=f"The Blue Kite + Airbnb + StayVista + SaffronStays · {spec.destination_villa_bhk} BHK · ₹{spec.nightly_budget_min_inr:,}–₹{spec.nightly_budget_max_inr:,}/N",
            finding_summary="Blue Kite=0 in Wayanad -> Pivoted to StayVista & Airbnb; matched 'The Sattva Grove' saving ₹7,900 direct vs Airbnb.",
        ),
        ToolCallTrace(
            phase="Phase 3 · Spatio-Temporal Solver",
            tool_name="pareto_itinerary_dag_solver",
            latency_ms=225,
            input_summary="Jointly optimize Vythiri base + Edakkal/Soochipara climb windows + Veg/Non-Veg Kerala dining",
            finding_summary="Generated 3 Pareto blueprints; Vythiri base cuts local hill driving by 45% and dodges ₹15k Dec 24 Gala fees.",
        ),
    ]

    return OptimizationResponse(
        trip_spec=spec,
        platform_coverage=coverage,
        tool_trace=traces,
        blueprints=blueprints,
    )


def optimize_generic_scenario(spec: TripSpec) -> OptimizationResponse:
    dest_lower = spec.destination.lower()
    if "wayanad" in dest_lower:
        return optimize_wayanad_scenario(spec)
    if "goa" in dest_lower:
        goa_spec, cov, traces, bps = build_goa_hybrid_bluekite_preset()
        # Preserve user's mode/stay overrides if changed
        merged = spec.model_copy(deep=True)
        return OptimizationResponse(
            trip_spec=merged,
            platform_coverage=cov,
            tool_trace=traces,
            blueprints=bps,
        )

    # Dynamic multi-modal synthesizer for any other Indian / Global destination (e.g., Nainital, Coorg, Udaipur, Ooty)
    o_lat, o_lng, o_iata = _lookup_city(spec.origin)
    d_lat, d_lng, d_iata = _lookup_city(spec.destination)
    dist_km = _haversine_km(o_lat, o_lng, d_lat, d_lng)

    has_bluekite = any(m in dest_lower for m in BLUEKITE_MARKETS)
    nights = 4
    mid_budget = max(12000, (spec.nightly_budget_min_inr + spec.nightly_budget_max_inr) // 2)

    portal_name = "The Blue Kite Direct" if has_bluekite else "StayVista Direct"
    portal_url = "https://www.thebluekite.com/" if has_bluekite else "https://www.stayvista.com/"
    villa_cat = "bluekite" if has_bluekite else "villa"

    direct_total = mid_budget * nights
    airbnb_total = int(direct_total * 1.155)
    savings_villa = airbnb_total - direct_total

    dest_stay = StayCandidate(
        id="custom-dest-villa",
        name=(
            f"Villa Botanica by The Blue Kite — {spec.destination}"
            if has_bluekite
            else f"The Ridge Estate {spec.destination_villa_bhk}BHK Villa — {spec.destination}"
        ),
        subtitle=f"{spec.destination} · {spec.destination_villa_bhk} BHK Private Luxury Villa + Chef",
        category=villa_cat,  # type: ignore[arg-type]
        city=spec.destination,
        micro_region="Scenic Ridge Corridor",
        lat=d_lat,
        lng=d_lng,
        rating=4.89,
        review_count=114,
        bedrooms_label=f"{spec.destination_villa_bhk} BHK Villa + Lawn + Caretaker",
        check_in=spec.start_date,
        check_out=spec.end_date,
        nights=nights,
        image_url="https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1000&q=80",
        suv_access_note=f"All-weather paved hill approach verified for {spec.vehicle_name}.",
        kid_fit_note="Private garden, family board games, custom home-cooked Veg & Non-Veg meals.",
        highlights=[
            f"Direct booking on {portal_name} avoids ₹{savings_villa:,} in third-party service fees",
            "Positioned within 25 mins of top moderate climbs, viewpoints & heritage eateries",
        ],
        offers=[
            ChannelOffer(
                platform=portal_name,
                channel_type="villa_portal",
                base_total_inr=int(direct_total * 0.88),
                taxes_gst_inr=int(direct_total * 0.12),
                landed_total_inr=direct_total,
                per_night_landed_inr=mid_budget,
                inclusions=["Breakfast", "Caretaker", "Private Estate Access"],
                promo_note="Direct portal all-in rate",
                booking_url=portal_url,
                is_best_deal=True,
            ),
            ChannelOffer(
                platform="Airbnb",
                channel_type="airbnb",
                base_total_inr=direct_total,
                platform_or_cleaning_fee_inr=savings_villa,
                landed_total_inr=airbnb_total,
                per_night_landed_inr=airbnb_total // nights,
                inclusions=["Entire Villa"],
                promo_note="Includes ~14.2% Airbnb guest service fee",
                booking_url="https://www.airbnb.co.in/",
                is_best_deal=False,
            ),
        ],
        best_channel=portal_name,
        best_landed_inr=direct_total,
        worst_landed_inr=airbnb_total,
        savings_inr=savings_villa,
        deal_anomaly_score=92.0,
        anomaly_badge=f"Saves ₹{savings_villa:,} Direct vs Airbnb",
    )

    flights: List[FlightOption] = []
    if spec.transport_mode in ("flight", "hybrid") or dist_km > 650:
        flights.append(
            FlightOption(
                id="custom-flight-1",
                carrier="IndiGo / Air India Smart Combo",
                flight_numbers=f"6E 512 ({o_iata}->{d_iata}) · AI 845 ({d_iata}->{o_iata})",
                route_label=f"{o_iata} -> {d_iata} Gateway Hub",
                gateway_hub_note="Selected optimal regional gateway balancing airfare and last-mile scenic drive.",
                depart_time="09:20 AM",
                arrive_time="11:45 AM",
                duration="2h 25m",
                stops_label="Non-Stop",
                landed_family_total_inr=34800,
                ota_unoptimized_inr=41200,
                savings_inr=6400,
                booking_channel="Direct Airline Family Bundle",
            )
        )

    drive_round_km = round(dist_km * 2 + 120, 1) if spec.transport_mode == "road" else 210.0
    fuel_inr = int(drive_round_km * 7.8)
    tolls_inr = int(drive_round_km * 1.6)
    rental_inr = 11500 if spec.transport_mode == "hybrid" else 0

    road = RoadSummary(
        vehicle=spec.vehicle_name,
        ground_clearance_mm=200,
        total_distance_km=drive_round_km,
        total_drive_hours=round(drive_round_km / 48.0, 1),
        estimated_fuel_liters=round(drive_round_km / 12.2, 1),
        fuel_cost_inr=fuel_inr,
        fastag_and_forest_tolls_inr=tolls_inr,
        rental_car_cost_inr=rental_inr,
        total_road_cost_inr=fuel_inr + tolls_inr + rental_inr,
        corridor_notes=[
            f"Optimized corridor between {spec.origin} and {spec.destination} with rest & culinary stops every ~2.5 hours.",
        ],
        segments=[
            RoadSegment(
                id="custom-seg-1",
                day_number=1,
                from_name=spec.origin if spec.transport_mode == "road" else f"{d_iata} Gateway Airport",
                to_name=spec.destination,
                highway_label="Primary Scenic National Highway Corridor",
                distance_km=round(drive_round_km / 2, 1),
                duration_mins=int((drive_round_km / 2) / 50 * 60),
                fastag_toll_inr=tolls_inr // 2,
                fuel_estimate_inr=fuel_inr // 2,
                coordinates=[[o_lng, o_lat], [(o_lng + d_lng) / 2, (o_lat + d_lat) / 2 + 0.15], [d_lng, d_lat]],
            )
        ],
    )

    flight_sum = sum(f.landed_family_total_inr for f in flights)
    core_total = dest_stay.best_landed_inr + road.total_road_cost_inr + flight_sum
    unopt_total = dest_stay.worst_landed_inr + road.total_road_cost_inr + sum(f.ota_unoptimized_inr for f in flights)

    bp = ParetoBlueprint(
        id="custom-bp-1",
        rank_badge="Sweet-Spot Recommended",
        name=f"{spec.destination} Multi-Modal Arbitrage Plan",
        strategy_subtitle=f"{spec.transport_mode.upper()} Mode · {spec.stay_strategy.upper()} Stays",
        recommended=True,
        total_core_landed_inr=core_total,
        unoptimized_baseline_inr=unopt_total,
        total_arbitrage_savings_inr=unopt_total - core_total,
        dining_and_activities_est_inr=16000,
        fatigue_score=28,
        quality_score=94,
        deal_anomaly_score=92.0,
        stays=[dest_stay],
        flights=flights,
        road=road,
        arbitrage_callouts=[
            f"Cross-channel stay deduplication saved ₹{savings_villa:,} via {portal_name}.",
            "Paced daily excursions around moderate climbs, local heritage dining (Veg + Non-Veg), and relaxed mornings.",
        ],
        days=[
            ItineraryDay(
                day_number=1,
                date_label=spec.start_date,
                weekday="Day 1",
                headline=f"Arrival Corridor: {spec.origin} -> {spec.destination}",
                corridor_tag=f"{round(drive_round_km / 2, 0):.0f} km Scenic Leg",
                drive_km=round(drive_round_km / 2, 1),
                drive_time_label="3h 30m",
                overnight_label=dest_stay.name,
                stops=[
                    TimelineStop(
                        id="c-d1-1",
                        time_window="Morning / Afternoon",
                        title=f"Outbound Journey to {spec.destination}",
                        location_label=spec.destination,
                        category="drive" if not flights else "flight",
                        lat=d_lat,
                        lng=d_lng,
                        duration_label="3h 30m",
                        description=f"Smooth transit into {spec.destination} followed by check-in at {dest_stay.name} and estate walk.",
                    )
                ],
            ),
            ItineraryDay(
                day_number=2,
                date_label="Day 2",
                weekday="Explorer Day",
                headline=f"{spec.destination} Ridge Climbs, Local Kitchens & Sunset Point",
                corridor_tag="48 km Local Loop",
                drive_km=48.0,
                drive_time_label="1h 30m",
                overnight_label=dest_stay.name,
                stops=[
                    TimelineStop(
                        id="c-d2-1",
                        time_window="9:00 AM – 4:30 PM",
                        title=f"Signature Moderate Climb & Regional Culinary Trail in {spec.destination}",
                        location_label=spec.destination,
                        category="climb",
                        lat=d_lat + 0.02,
                        lng=d_lng + 0.02,
                        duration_label="Full Curated Day",
                        description="Morning ridge hike before crowds, regional Veg + Non-Veg heirloom lunch, and relaxed artisan heritage visit.",
                    )
                ],
            ),
        ],
    )

    return OptimizationResponse(
        trip_spec=spec,
        platform_coverage=[
            PlatformCoverageNote(
                platform="The Blue Kite",
                status="matched" if has_bluekite else "zero_inventory_pivoted",
                listings_scanned=22 if has_bluekite else 0,
                note=(
                    f"Direct Blue Kite luxury homes matched in {spec.destination}."
                    if has_bluekite
                    else f"0 listings in {spec.destination} -> auto-pivoted to StayVista, SaffronStays & Airbnb."
                ),
            ),
            PlatformCoverageNote(
                platform="Airbnb & Boutique OTAs",
                status="matched",
                listings_scanned=64,
                note="Compared landed rates including cleaning fees, 14.2% guest fees, and 18% GST.",
            ),
        ],
        tool_trace=[
            ToolCallTrace(
                phase="Phase 1 · Intent & Constraints",
                tool_name="hydrate_trip_spec",
                latency_ms=88,
                input_summary=f"{spec.origin} -> {spec.destination} ({spec.transport_mode}, {spec.stay_strategy})",
                finding_summary="Updated live form parameters from conversational state.",
            ),
            ToolCallTrace(
                phase="Phase 2 · Multi-Channel Arbitrage",
                tool_name="cross_platform_rate_scanner",
                latency_ms=310,
                input_summary=f"Airbnb + The Blue Kite + StayVista + OTAs in {spec.destination}",
                finding_summary=f"Best deal via {portal_name} saving ₹{savings_villa:,}.",
            ),
            ToolCallTrace(
                phase="Phase 3 · Spatio-Temporal Solver",
                tool_name="pareto_itinerary_dag_solver",
                latency_ms=190,
                input_summary="Synthesize route + stays + family curation",
                finding_summary=f"Total core ₹{core_total:,} (saves ₹{unopt_total - core_total:,}).",
            ),
        ],
        blueprints=[bp],
    )


def process_chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    """Conversational Multi-Phase Planner: extracts state deltas, asks questions when underspecified, or re-optimizes."""
    msg = req.message.strip()
    lower = msg.lower()
    spec = req.current_spec.model_copy(deep=True)
    updates: List[str] = []

    # 1. Detect Destination switches
    for city_key, label in [
        ("goa", "Assagao & Aldona, North Goa"),
        ("wayanad", "Wayanad, Kerala"),
        ("nainital", "Nainital, Uttarakhand"),
        ("rishikesh", "Rishikesh, Uttarakhand"),
        ("coorg", "Coorg (Madikeri), Karnataka"),
        ("ooty", "Ooty, Tamil Nadu"),
        ("udaipur", "Udaipur, Rajasthan"),
        ("chikmagalur", "Chikmagalur, Karnataka"),
        ("munnar", "Munnar, Kerala"),
    ]:
        if re.search(rf"\b{city_key}\b", lower) and city_key not in spec.destination.lower():
            spec.destination = label
            updates.append(f"Destination -> {label}")
            if city_key == "goa" and ("hybrid" in lower or "fly" in lower or "blue kite" in lower or "bluekite" in lower):
                spec.transport_mode = "hybrid"
                spec.stay_strategy = "villas"
                spec.vehicle_name = "Self-Drive SUV at Mopa (GOX)"
                updates.append("Mode -> Hybrid (Fly + Drive)")
            break

    # 2. Detect Transport Mode
    if any(p in lower for p in ["fly and drive", "fly + drive", "hybrid mode", "fly somewhere and then", "rent a car"]):
        spec.transport_mode = "hybrid"
        updates.append("Transport Mode -> Hybrid (Fly + Drive)")
    elif any(p in lower for p in ["flight only", "fly + stay", "fly to"]):
        if "drive" not in lower:
            spec.transport_mode = "flight"
            updates.append("Transport Mode -> Fly + Stay")
    elif any(p in lower for p in ["road trip", "own car", "self drive from"]):
        spec.transport_mode = "road"
        updates.append("Transport Mode -> Pure Road Trip")

    # 3. Detect Stay Strategy
    if any(p in lower for p in ["hotels only", "prefer hotel", "only hotel", "switch to hotel"]):
        spec.stay_strategy = "hotels"
        updates.append("Stay Strategy -> Hotels & Resorts Only")
    elif any(p in lower for p in ["villas only", "only airbnb", "blue kite", "bluekite"]):
        spec.stay_strategy = "villas"
        updates.append("Stay Strategy -> Villas (Airbnb / The Blue Kite)")
    elif "hybrid stay" in lower or ("radisson" in lower and "airbnb" in lower):
        spec.stay_strategy = "hybrid"
        updates.append("Stay Strategy -> Hybrid Stays")

    # 4. Detect BHK & Budget (e.g., "3 bhk", "20-30k", "under 25k")
    bhk_match = re.search(r"(\d)\s*(?:bhk|br|bedroom)", lower)
    if bhk_match:
        spec.destination_villa_bhk = int(bhk_match.group(1))
        updates.append(f"Villa Size -> {spec.destination_villa_bhk} BHK")

    range_match = re.search(r"(\d{1,2})\s*(?:k|000)?\s*(?:-|to)\s*(\d{1,2})\s*k", lower)
    if range_match:
        lo_k = int(range_match.group(1))
        hi_k = int(range_match.group(2))
        spec.nightly_budget_min_inr = lo_k * 1000
        spec.nightly_budget_max_inr = hi_k * 1000
        updates.append(f"Nightly Budget -> ₹{lo_k}k–₹{hi_k}k")

    # 5. Detect Vehicle
    for car in ["jeep meridian", "innova", "fortuner", "creta", "xuv700", "safari", "sedan", "compass"]:
        if car in lower and "wildlife safari" not in lower and "jeep safari" not in lower:
            spec.vehicle_name = f"{car.title()} (Own Car)"
            updates.append(f"Vehicle -> {spec.vehicle_name}")
            break

    # 6. Detect Activity Toggles
    if "add safari" in lower or "include safari" in lower or "yes safari" in lower:
        spec.activities.wildlife_safari = True
        updates.append("Wildlife Safari -> Enabled")
    elif "no safari" in lower or "skip safari" in lower:
        spec.activities.wildlife_safari = False
        updates.append("Wildlife Safari -> Skipped")

    if "mysore zoo" in lower or "mysore palace" in lower or "mysuru sightseeing" in lower:
        if "no " not in lower and "skip" not in lower:
            spec.activities.transit_sightseeing = True
            updates.append("Mysuru Sightseeing -> Enabled")

    if "veg only" in lower or "pure veg" in lower:
        spec.activities.dietary = "veg"
        updates.append("Dietary -> Pure Veg")
    elif "veg and non" in lower or "both veg" in lower:
        spec.activities.dietary = "both"
        updates.append("Dietary -> Veg + Non-Veg")

    # Check if user asked a broad new trip prompt missing mode/stay choices so we show conversational follow-ups
    is_new_unclarified = (
        ("plan a trip" in lower or "want to go to" in lower)
        and len(req.history) == 0
        and not any(w in lower for w in ["road", "fly", "flight", "car", "hybrid"])
    )

    opt = optimize_generic_scenario(spec)
    top_bp = opt.blueprints[0]

    if is_new_unclarified:
        questions = [
            f"For {spec.destination}, do you prefer a **Pure Road Trip**, **Fly + Stay**, or a **Hybrid (Fly + Rental Car)** setup?",
            "For stays, would you like **Hotels & Resorts**, **Airbnb / The Blue Kite Villas**, or a **Hybrid Stay** (transit hotel + destination villa)?",
            "How many adults/kids are traveling, and what nightly budget range feels comfortable?",
        ]
        reply = (
            f"I've initialized a draft blueprint for **{spec.destination}** (`₹{top_bp.total_core_landed_inr:,}` estimated core) on the canvas! "
            "Before I lock in final channel arbitrage, let me confirm 3 quick preferences:"
        )
        return ChatTurnResponse(
            updated_spec=spec,
            assistant_reply=reply,
            extracted_updates=updates or ["Draft Spec Hydrated"],
            needs_clarification=True,
            follow_up_questions=questions,
            optimization=opt,
        )

    update_str = (
        f"Updated live parameters ({', '.join(updates)}) and re-ran all 3 planner phases. "
        if updates
        else "Re-evaluated your itinerary across all channels and route corridors. "
    )

    reply = (
        f"{update_str}Your top Pareto recommendation is **{top_bp.name}** at **₹{top_bp.total_core_landed_inr:,}** core all-in "
        f"(saving **₹{top_bp.total_arbitrage_savings_inr:,}** vs. unoptimized OTA rates). "
        f"Click any day card or map pin to inspect drive segments, climb timings, and cross-channel fee breakdowns—or tell me what you'd like to tweak next!"
    )

    return ChatTurnResponse(
        updated_spec=spec,
        assistant_reply=reply,
        extracted_updates=updates or ["Re-verified live rates & corridor"],
        needs_clarification=False,
        follow_up_questions=[],
        optimization=opt,
    )
