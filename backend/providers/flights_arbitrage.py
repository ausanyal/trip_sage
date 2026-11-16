from __future__ import annotations

from typing import List, Tuple
from urllib.parse import quote_plus

from models import FlightOption, TripSpec
from providers.geo_routing import AirportHub, GeoLocation, haversine_km, nearest_airports
from providers.serpapi_live import has_serpapi_key, search_serpapi_flights


def _corridor_carrier_profiles(
    o_hub: AirportHub,
    d_hub: AirportHub,
    orig_cc: str,
    dest_cc: str,
    flight_mins: int,
) -> List[Tuple[str, str, str, str, str, str, float, List[str], str]]:
    """Returns 3 distinct (carrier, flt_nums, dep, arr, dur_str, stops_lbl, mult, inclusions, channel) profiles."""
    is_intl = orig_cc != dest_cc
    se_asia = {"id", "th", "sg", "my", "vn"}
    gulf_io = {"ae", "qa", "lk", "mv"}

    h_nonstop = f"{flight_mins // 60}h {flight_mins % 60:02d}m"
    connect_mins = flight_mins + 115
    h_onestop = f"{connect_mins // 60}h {connect_mins % 60:02d}m"

    if not is_intl and orig_cc == "in":
        return [
            (
                "IndiGo + Akasa Air Split-Return",
                f"6E-614 ({o_hub.iata}->{d_hub.iata}) · QP-1382 ({d_hub.iata}->{o_hub.iata})",
                "08:15 AM",
                "10:10 AM",
                h_nonstop,
                "Non-Stop · Split-Ticket Saver",
                1.00,
                ["15kg Checked + 7kg Cabin", "Split-Carrier Round-Trip Arbitrage"],
                "Direct Airline Combo (IndiGo + Akasa)",
            ),
            (
                "Air India Full-Service Direct",
                f"AI-503 ({o_hub.iata}->{d_hub.iata}) · AI-504 ({d_hub.iata}->{o_hub.iata})",
                "10:45 AM",
                "12:40 PM",
                h_nonstop,
                "Non-Stop · Full-Service",
                1.11,
                ["20kg Checked Baggage", "Hot Meals Included", "Family Seat Grouping"],
                "Air India Direct Family Tariff",
            ),
            (
                "IndiGo Flexi Plus Family Fare",
                f"6E-842 ({o_hub.iata}->{d_hub.iata}) · 6E-849 ({d_hub.iata}->{o_hub.iata})",
                "06:50 AM",
                "08:45 AM",
                h_nonstop,
                "Non-Stop · Free Date Change",
                1.06,
                ["Zero Date-Change Fee", "Free XL/Standard Seats", "Complimentary Snack"],
                "IndiGo Direct Flexi Plus",
            ),
        ]

    if is_intl and (dest_cc in se_asia or orig_cc in se_asia):
        direct_possible = flight_mins <= 275 or d_hub.iata in ("SIN", "KUL", "BKK", "DMK", "HKT")
        return [
            (
                "IndiGo / AirAsia Smart Hub Saver",
                f"6E-1055 / AK-376 ({o_hub.iata}->{d_hub.iata} Round-Trip)",
                "07:15 AM",
                "04:35 PM" if not direct_possible else "01:20 PM",
                h_nonstop if direct_possible else h_onestop,
                "Non-Stop LCC" if direct_possible else "1 Stop (KUL Hub Saver)",
                1.00,
                ["20kg Checked + 7kg Cabin", "Smart Virtual Interline Saver"],
                "Direct Carrier Split-Booking",
            ),
            (
                "Singapore Airlines / Batik Air Full-Service",
                f"SQ-509 / SQ-944 ({o_hub.iata}->{d_hub.iata} Round-Trip)",
                "10:35 AM",
                "06:45 PM" if not direct_possible else "04:15 PM",
                f"{(flight_mins + 65) // 60}h {(flight_mins + 65) % 60:02d}m" if not direct_possible else h_nonstop,
                "Non-Stop Full-Service" if direct_possible else "1 Fast Stop (Changi SIN)",
                1.15,
                ["25kg Checked Baggage", "Hot Meals & Kids Meal", "Complimentary Seat Selection"],
                "Singapore Airlines Direct Family Fare",
            ),
            (
                "Malaysia Airlines / IndiGo Flex Combo",
                f"Outbound 6E + Return MH ({o_hub.iata}<->{d_hub.iata})",
                "06:20 AM",
                "03:50 PM",
                h_onestop if not direct_possible else h_nonstop,
                "Morning Outbound · Evening Return",
                1.08,
                ["20kg–25kg Checked Bag", "1x Free Date Change", "Daytime Kid-Friendly Timing"],
                "Cross-Carrier Split Return",
            ),
        ]

    if is_intl and (dest_cc in gulf_io or orig_cc in gulf_io):
        return [
            (
                "IndiGo / Air India Express Direct",
                f"6E-1415 ({o_hub.iata}->{d_hub.iata}) · IX-814 ({d_hub.iata}->{o_hub.iata})",
                "08:30 AM",
                "11:15 AM",
                h_nonstop,
                "Non-Stop · Smart Value",
                1.00,
                ["20kg–30kg Checked Baggage", "7kg Cabin Bag", "Direct Non-Stop"],
                "Direct Carrier Round-Trip",
            ),
            (
                "Emirates / SriLankan / Qatar Full-Service",
                f"EK-565 / UL-172 ({o_hub.iata}<->{d_hub.iata})",
                "10:15 AM",
                "01:05 PM",
                h_nonstop,
                "Non-Stop · Full-Service",
                1.16,
                ["30kg Checked Baggage", "Gourmet Hot Meal & Kids Pack", "In-Flight Entertainment"],
                "Flagship Carrier Direct",
            ),
            (
                "Air India Flexible Family Return",
                f"AI-971 ({o_hub.iata}->{d_hub.iata}) · AI-972 ({d_hub.iata}->{o_hub.iata})",
                "07:05 AM",
                "09:55 AM",
                h_nonstop,
                "Non-Stop · Flex Tariff",
                1.08,
                ["25kg Checked Baggage", "Hot Meals", "Low-Fee Date Flexibility"],
                "Air India Direct Portal",
            ),
        ]

    return [
        (
            "Smart Hub Saver (Qatar / Etihad / Singapore Air)",
            f"Outbound {o_hub.iata}->{d_hub.iata} · Return {d_hub.iata}->{o_hub.iata}",
            "04:25 AM",
            "02:40 PM",
            h_onestop,
            "1 Stop · Best All-In Value",
            1.00,
            ["23kg Checked + 7kg Cabin", "Through-Checked Baggage", "Hot Meals Included"],
            "Direct Carrier Hub Tariff",
        ),
        (
            "Fastest Flagship Schedule (Air India / Lufthansa / BA)",
            f"Direct/Express {o_hub.iata}<->{d_hub.iata}",
            "09:15 AM",
            "04:50 PM",
            h_nonstop if flight_mins <= 560 else f"{(flight_mins + 55) // 60}h {(flight_mins + 55) % 60:02d}m",
            "Non-Stop / Express" if flight_mins <= 560 else "1 Short Hub Connection",
            1.17,
            ["2x 23kg Checked Baggage", "Full Meal Service & Kids Meal", "Seat Selection"],
            "Flagship Direct Portal",
        ),
        (
            "Alliance Split-Return Flexible Fare",
            f"Split Outbound + Return ({o_hub.iata}<->{d_hub.iata})",
            "07:40 AM",
            "06:10 PM",
            h_onestop,
            "1 Stop · Date-Change Flex",
            1.09,
            ["23kg Checked Baggage", "1x Free Date Change", "Daytime Arrival Window"],
            "Alliance Direct Split-Ticket",
        ),
    ]


async def discover_gateway_flights(
    origin_geo: GeoLocation,
    dest_geo: GeoLocation,
    spec: TripSpec,
) -> List[FlightOption]:
    """Multi-Airport Gateway & Virtual Interline Flight Arbitrage Engine.

    Uses live Google Flights via SerpApi when `SERPAPI_API_KEY` is set; otherwise computes
    transparent multi-carrier and multi-gateway round-trip options with Google Flights & Skyscanner deep-links.
    """
    air_dist_km = haversine_km(origin_geo.lat, origin_geo.lng, dest_geo.lat, dest_geo.lng)
    if spec.transport_mode == "road" and air_dist_km < 850:
        return []

    orig_hubs = nearest_airports(origin_geo.lat, origin_geo.lng, max_km=380.0, limit=1)
    if not orig_hubs and spec.transport_mode in ("flight", "hybrid"):
        orig_hubs = nearest_airports(origin_geo.lat, origin_geo.lng, max_km=2500.0, limit=1)

    dest_hubs = nearest_airports(dest_geo.lat, dest_geo.lng, max_km=380.0, limit=2)
    if not dest_hubs and spec.transport_mode in ("flight", "hybrid"):
        dest_hubs = nearest_airports(dest_geo.lat, dest_geo.lng, max_km=2500.0, limit=2)

    if not orig_hubs or not dest_hubs:
        return []

    o_hub, _ = orig_hubs[0]
    dest_hubs = [(dh, dkm) for dh, dkm in dest_hubs if dh.iata != o_hub.iata]
    if not dest_hubs:
        return []

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

    # 2. Transparent parametric multi-carrier & multi-gateway benchmark options
    best_d_hub, best_d_ground_km = dest_hubs[0]
    alt_note = (
        f"Primary gateway {best_d_hub.iata} ({best_d_hub.city}) is {best_d_ground_km:.0f} km from {dest_geo.short_name}."
    )
    hub_bonus_inr = 0
    if len(dest_hubs) > 1:
        second_hub, second_km = dest_hubs[1]
        km_saved = max(0.0, second_km - best_d_ground_km)
        hub_bonus_inr = 1800
        alt_note = (
            f"Selected {best_d_hub.iata} ({best_d_ground_km:.0f} km transfer to {dest_geo.short_name}) over "
            f"{second_hub.iata} ({second_km:.0f} km), saving {km_saved:.0f} km of ground drive."
        )

    pax = max(1, spec.party.adults + spec.party.children)
    leg_km = max(220.0, haversine_km(o_hub.lat, o_hub.lng, best_d_hub.lat, best_d_hub.lng))

    is_intl = origin_geo.country_code != dest_geo.country_code
    base_fare = 11500 if is_intl else 4600
    km_rate = 5.4 if is_intl else 4.6
    per_pax_roundtrip = int(round(base_fare + leg_km * km_rate, -2))
    base_family_total = per_pax_roundtrip * pax

    flight_mins = max(55, int(round(35 + (leg_km / 760.0) * 60)))
    profiles = _corridor_carrier_profiles(
        o_hub=o_hub,
        d_hub=best_d_hub,
        orig_cc=origin_geo.country_code,
        dest_cc=dest_geo.country_code,
        flight_mins=flight_mins,
    )

    gflights_primary = (
        f"https://www.google.com/travel/flights?q=Flights+from+{o_hub.iata}+to+{best_d_hub.iata}"
        f"+on+{spec.start_date}+return+{spec.end_date}"
    )
    skyscanner_primary = (
        f"https://www.skyscanner.co.in/transport/flights/{o_hub.iata.lower()}/{best_d_hub.iata.lower()}/"
    )

    options: List[FlightOption] = []
    for idx, (
        carrier,
        flt_nums,
        dep_t,
        arr_t,
        dur_s,
        stops_s,
        mult,
        incl,
        channel_lbl,
    ) in enumerate(profiles, start=1):
        landed = int(round(base_family_total * mult, -2))
        ota_unopt = int(round(landed * 1.15, -2)) + (hub_bonus_inr if idx == 1 else 900)
        sav = max(1100, ota_unopt - landed)
        note = (
            alt_note
            if idx == 1
            else (
                f"Shortest total travel window into {best_d_hub.iata} with full family baggage & meals."
                if idx == 2
                else f"Morning departure + flexible return protection into {best_d_hub.iata} ({best_d_ground_km:.0f} km to {dest_geo.short_name})."
            )
        )
        carrier_hint = quote_plus(carrier.split("/")[0].split("+")[0].strip())
        carrier_gflights_url = f"{gflights_primary}+{carrier_hint}"
        options.append(
            FlightOption(
                id=f"flt-{o_hub.iata.lower()}-{best_d_hub.iata.lower()}-{idx}",
                carrier=carrier,
                flight_numbers=flt_nums,
                route_label=f"{o_hub.iata} -> {best_d_hub.iata} ({best_d_hub.name})",
                gateway_hub_note=note,
                depart_time=dep_t,
                arrive_time=arr_t,
                duration=dur_s,
                stops_label=stops_s,
                landed_family_total_inr=landed,
                ota_unoptimized_inr=ota_unopt,
                savings_inr=sav,
                booking_channel=channel_lbl,
                booking_url=carrier_gflights_url,
                skyscanner_url=skyscanner_primary,
                inclusions=incl,
                origin_iata=o_hub.iata,
                dest_iata=best_d_hub.iata,
                origin_lat=o_hub.lat,
                origin_lng=o_hub.lng,
                dest_lat=best_d_hub.lat,
                dest_lng=best_d_hub.lng,
                price_provenance="estimated_benchmark",
                provenance_label="Distance Airfare Benchmark (Set SERPAPI_API_KEY for Live Fares)",
            )
        )

    # 4th Option: Alternate Gateway Airport Comparison when a secondary hub exists within reach
    if len(dest_hubs) > 1:
        second_hub, second_km = dest_hubs[1]
        alt_leg_km = max(220.0, haversine_km(o_hub.lat, o_hub.lng, second_hub.lat, second_hub.lng))
        alt_per_pax = int(round(base_fare + alt_leg_km * km_rate, -2))
        alt_family_total = max(int(round(base_family_total * 0.96, -2)), alt_per_pax * pax)
        alt_unopt = int(round(alt_family_total * 1.13, -2))
        alt_mins = max(55, int(round(35 + (alt_leg_km / 760.0) * 60)))
        extra_drive_km = max(0.0, second_km - best_d_ground_km)

        options.append(
            FlightOption(
                id=f"flt-{o_hub.iata.lower()}-{second_hub.iata.lower()}-alt",
                carrier=f"Alternate Gateway via {second_hub.iata} ({second_hub.city})",
                flight_numbers=f"Outbound {o_hub.iata}->{second_hub.iata} · Return {second_hub.iata}->{o_hub.iata}",
                route_label=f"{o_hub.iata} -> {second_hub.iata} ({second_hub.name})",
                gateway_hub_note=(
                    f"Secondary gateway comparison: {second_hub.iata} is {second_km:.0f} km from {dest_geo.short_name} "
                    f"(+{extra_drive_km:.0f} km ground transfer vs. {best_d_hub.iata})."
                ),
                depart_time="11:20 AM",
                arrive_time="05:10 PM" if is_intl else "01:15 PM",
                duration=f"{alt_mins // 60}h {alt_mins % 60:02d}m",
                stops_label=f"Alt Hub ({second_hub.iata})",
                landed_family_total_inr=alt_family_total,
                ota_unoptimized_inr=alt_unopt,
                savings_inr=max(900, alt_unopt - alt_family_total),
                booking_channel=f"Secondary Airport Check ({second_hub.iata})",
                booking_url=(
                    f"https://www.google.com/travel/flights?q=Flights+from+{o_hub.iata}+to+{second_hub.iata}"
                    f"+on+{spec.start_date}+return+{spec.end_date}"
                ),
                skyscanner_url=(
                    f"https://www.skyscanner.co.in/transport/flights/{o_hub.iata.lower()}/{second_hub.iata.lower()}/"
                ),
                inclusions=["20kg Checked Bag", f"{second_km:.0f} km Ground Transfer"],
                origin_iata=o_hub.iata,
                dest_iata=second_hub.iata,
                origin_lat=o_hub.lat,
                origin_lng=o_hub.lng,
                dest_lat=second_hub.lat,
                dest_lng=second_hub.lng,
                price_provenance="estimated_benchmark",
                provenance_label="Distance Airfare Benchmark (Set SERPAPI_API_KEY for Live Fares)",
            )
        )

    return options

