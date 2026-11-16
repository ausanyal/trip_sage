from __future__ import annotations

from typing import List

from models import FlightOption, TripSpec
from providers.geo_routing import GeoLocation, haversine_km, nearest_airports
from providers.serpapi_live import has_serpapi_key, search_serpapi_flights


async def discover_gateway_flights(
    origin_geo: GeoLocation,
    dest_geo: GeoLocation,
    spec: TripSpec,
) -> List[FlightOption]:
    """Multi-Airport Gateway & Virtual Interline Flight Arbitrage Engine.

    Uses live Google Flights via SerpApi when `SERPAPI_API_KEY` is set; otherwise computes
    transparent distance-calibrated airfare benchmarks across candidate gateway hubs.
    """
    air_dist_km = haversine_km(origin_geo.lat, origin_geo.lng, dest_geo.lat, dest_geo.lng)
    if spec.transport_mode == "road" and air_dist_km < 850:
        return []

    orig_hubs = nearest_airports(origin_geo.lat, origin_geo.lng, max_km=260.0, limit=1)
    dest_hubs = nearest_airports(dest_geo.lat, dest_geo.lng, max_km=280.0, limit=2)
    if not orig_hubs or not dest_hubs:
        return []

    o_hub, _ = orig_hubs[0]

    # 1. Live Google Flights path when SERPAPI_API_KEY is configured
    if has_serpapi_key():
        live_flights = await search_serpapi_flights(
            o_hub=o_hub,
            dest_hubs=dest_hubs,
            dest_short_name=dest_geo.short_name,
            spec=spec,
        )
        if live_flights:
            return live_flights

    # 2. Transparent parametric airfare benchmark across primary & secondary gateway airports
    best_d_hub, best_d_ground_km = dest_hubs[0]
    alt_note = f"Optimal gateway {best_d_hub.iata} ({best_d_hub.city}) is {best_d_ground_km:.0f} km from {dest_geo.short_name}."
    hub_bonus_inr = 0
    if len(dest_hubs) > 1:
        second_hub, second_km = dest_hubs[1]
        km_saved = max(0.0, second_km - best_d_ground_km)
        hub_bonus_inr = 1800
        alt_note = (
            f"Selected {best_d_hub.iata} ({best_d_ground_km:.0f} km drive to {dest_geo.short_name}) over "
            f"{second_hub.iata} ({second_km:.0f} km), saving {km_saved:.0f} km of airport transfer."
        )

    pax = max(1, spec.party.adults + spec.party.children)
    leg_km = max(220.0, haversine_km(o_hub.lat, o_hub.lng, best_d_hub.lat, best_d_hub.lng))

    is_intl = origin_geo.country_code != dest_geo.country_code
    base_fare = 11500 if is_intl else 4600
    km_rate = 5.4 if is_intl else 4.6
    per_pax_roundtrip = int(round(base_fare + leg_km * km_rate, -2))
    direct_family_total = per_pax_roundtrip * pax
    ota_unoptimized = int(round(direct_family_total * 1.16, -2)) + hub_bonus_inr
    savings = max(1200, ota_unoptimized - direct_family_total)

    flight_mins = max(55, int(round(35 + (leg_km / 760.0) * 60)))
    dur_str = f"{flight_mins // 60}h {flight_mins % 60:02d}m Non-Stop"
    carrier = (
        "Global Carrier / Smart Virtual Interline"
        if is_intl
        else ("IndiGo / Air India Virtual Interline" if o_hub.iata != best_d_hub.iata else "Regional Direct")
    )

    return [
        FlightOption(
            id=f"flt-{o_hub.iata.lower()}-{best_d_hub.iata.lower()}",
            carrier=carrier,
            flight_numbers=f"Outbound {o_hub.iata}->{best_d_hub.iata} · Return {best_d_hub.iata}->{o_hub.iata}",
            route_label=f"{o_hub.iata} -> {best_d_hub.iata} ({best_d_hub.name})",
            gateway_hub_note=alt_note,
            depart_time="09:45 AM",
            arrive_time="11:30 AM",
            duration=dur_str,
            stops_label="Non-Stop / Smart Combo",
            landed_family_total_inr=direct_family_total,
            ota_unoptimized_inr=ota_unoptimized,
            savings_inr=savings,
            booking_channel="Direct Carrier Family Fare + Split Return",
            booking_url=f"https://www.google.com/travel/flights?q=Flights+from+{o_hub.iata}+to+{best_d_hub.iata}+on+{spec.start_date}",
            price_provenance="estimated_benchmark",
            provenance_label="Distance Airfare Benchmark (Set SERPAPI_API_KEY for Live Fares)",
        )
    ]
