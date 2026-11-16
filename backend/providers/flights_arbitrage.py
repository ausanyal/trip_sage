from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

from models import FlightOption, TravelParty, TripSpec
from providers.geo_routing import AirportHub, GeoLocation, haversine_km, nearest_airports
from providers.serpapi_live import has_serpapi_key, search_serpapi_flights


def _fmt_clock(mins_of_day: int) -> str:
    wrapped = mins_of_day % 1440
    h24, m = divmod(wrapped, 60)
    suffix = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return f"{h12:02d}:{m:02d} {suffix}"


def _fmt_duration(total_mins: int) -> str:
    safe = max(45, int(total_mins))
    return f"{safe // 60}h {safe % 60:02d}m"


def compute_local_arrival_clock(
    dep_mins: int,
    block_mins: int,
    orig_tz_mins: int,
    dest_tz_mins: int,
) -> str:
    """Computes exact local destination clock time including timezone offset and day rollover."""
    local_arr = dep_mins + block_mins + (dest_tz_mins - orig_tz_mins)
    day_shift = local_arr // 1440
    clock = _fmt_clock(local_arr)
    if day_shift > 0:
        return f"{clock} (+{day_shift}d)"
    if day_shift < 0:
        return f"{clock} ({day_shift}d)"
    return clock


def build_skyscanner_deep_link(
    orig_iata: str,
    dest_iata: str,
    start_date: str,
    end_date: str,
    party: TravelParty,
    country_code: str = "in",
) -> str:
    """Builds a pre-populated Skyscanner round-trip flight URL with YYMMDD dates and passenger counts."""
    domain = "www.skyscanner.co.in" if country_code == "in" else "www.skyscanner.com"
    try:
        d1 = dt.date.fromisoformat(start_date).strftime("%y%m%d")
        d2 = dt.date.fromisoformat(end_date).strftime("%y%m%d")
        date_path = f"{d1}/{d2}/"
    except Exception:
        date_path = ""

    adults = max(1, party.adults)
    q_parts = [f"adultsv2={adults}", "cabinclass=economy", "rtn=1"]
    if party.children > 0:
        ages = (party.child_ages + [8] * party.children)[: party.children]
        age_pipe = "%7C".join(str(max(2, min(15, a))) for a in ages)
        q_parts.append(f"childrenv2={age_pipe}")

    return f"https://{domain}/transport/flights/{orig_iata.lower()}/{dest_iata.lower()}/{date_path}?{'&'.join(q_parts)}"


def build_google_flights_deep_link(
    orig_iata: str,
    dest_iata: str,
    start_date: str,
    end_date: str,
    party: TravelParty,
    carrier_hint: str = "",
) -> str:
    """Builds a pre-populated Google Flights round-trip query URL."""
    pax_str = f"{max(1, party.adults)} adults" + (
        f" {party.children} children" if party.children > 0 else ""
    )
    q = f"Flights from {orig_iata} to {dest_iata} on {start_date} through {end_date} for {pax_str}"
    if carrier_hint:
        q = f"{q} {carrier_hint}"
    return f"https://www.google.com/travel/flights?q={quote_plus(q)}"


@dataclass
class _CarrierScheduleTemplate:
    carrier: str
    flight_numbers: str
    carrier_search_hint: str
    out_dep_mins: int
    out_block_mins: int
    ret_dep_mins: int
    ret_block_mins: int
    stops_label: str
    fare_multiplier: float
    inclusions: List[str]
    booking_channel: str


def _estimate_per_pax_roundtrip_inr(leg_km: float, is_intl: bool) -> int:
    if not is_intl:
        return int(round(4800 + leg_km * 4.4, -2))
    if leg_km <= 2600:
        return int(round(11500 + leg_km * 4.8, -2))
    if leg_km <= 5000:
        return int(round(12500 + leg_km * 5.2, -2))
    return int(round(24000 + leg_km * 5.6, -2))


def _corridor_carrier_templates(
    o_hub: AirportHub,
    d_hub: AirportHub,
    orig_cc: str,
    dest_cc: str,
    leg_km: float,
) -> List[_CarrierScheduleTemplate]:
    """Generates 3 corridor-authentic round-trip carrier & timing templates."""
    is_intl = orig_cc != dest_cc
    se_asia = {"id", "th", "sg", "my", "vn", "kh", "ph"}
    gulf_io = {"ae", "qa", "lk", "mv", "mu", "sc"}
    subcont_near = {"np", "bt"}

    nonstop_mins = max(55, int(round(36 + (leg_km / 735.0) * 60)))
    short_hub_mins = nonstop_mins + 95
    std_hub_mins = nonstop_mins + 125

    # 1. Domestic India
    if not is_intl and orig_cc == "in":
        return [
            _CarrierScheduleTemplate(
                carrier="IndiGo + Akasa Air Split-Return",
                flight_numbers=f"6E-614 ({o_hub.iata}->{d_hub.iata}) · QP-1382 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="IndiGo",
                out_dep_mins=8 * 60 + 15,
                out_block_mins=nonstop_mins,
                ret_dep_mins=16 * 60 + 25,
                ret_block_mins=nonstop_mins + 5,
                stops_label="Non-Stop · Split-Ticket Saver",
                fare_multiplier=1.00,
                inclusions=["15kg Checked + 7kg Cabin", "Split-Carrier Round-Trip Arbitrage"],
                booking_channel="Direct Airline Combo (IndiGo + Akasa)",
            ),
            _CarrierScheduleTemplate(
                carrier="Air India Full-Service Direct",
                flight_numbers=f"AI-503 ({o_hub.iata}->{d_hub.iata}) · AI-504 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="Air India",
                out_dep_mins=10 * 60 + 45,
                out_block_mins=nonstop_mins,
                ret_dep_mins=14 * 60 + 50,
                ret_block_mins=nonstop_mins + 5,
                stops_label="Non-Stop · Full-Service",
                fare_multiplier=1.12,
                inclusions=["20kg Checked Baggage", "Hot Meals Included", "Family Seat Grouping"],
                booking_channel="Air India Direct Family Tariff",
            ),
            _CarrierScheduleTemplate(
                carrier="IndiGo Flexi Plus Family Fare",
                flight_numbers=f"6E-842 ({o_hub.iata}->{d_hub.iata}) · 6E-849 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="IndiGo Flexi",
                out_dep_mins=6 * 60 + 50,
                out_block_mins=nonstop_mins,
                ret_dep_mins=18 * 60 + 10,
                ret_block_mins=nonstop_mins + 5,
                stops_label="Non-Stop · Free Date Change",
                fare_multiplier=1.06,
                inclusions=["Zero Date-Change Fee", "Free Standard Seats", "Complimentary Snack"],
                booking_channel="IndiGo Direct Flexi Plus",
            ),
        ]

    # 2. Nepal / Bhutan short regional international
    if is_intl and (dest_cc in subcont_near or orig_cc in subcont_near):
        direct_ok = leg_km <= 2100
        blk = nonstop_mins if direct_ok else short_hub_mins
        return [
            _CarrierScheduleTemplate(
                carrier="IndiGo Regional Direct" if direct_ok else "IndiGo via DEL Hub",
                flight_numbers=f"6E-1155 ({o_hub.iata}->{d_hub.iata}) · 6E-1156 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="IndiGo",
                out_dep_mins=7 * 60 + 40,
                out_block_mins=blk,
                ret_dep_mins=15 * 60 + 15,
                ret_block_mins=blk + 10,
                stops_label="Non-Stop Regional" if direct_ok else "1 Stop (DEL Hub)",
                fare_multiplier=1.00,
                inclusions=["20kg Checked + 7kg Cabin", "Direct Carrier Fare"],
                booking_channel="IndiGo Direct Portal",
            ),
            _CarrierScheduleTemplate(
                carrier="Air India / Drukair Full-Service",
                flight_numbers=f"AI-215 ({o_hub.iata}->{d_hub.iata}) · AI-216 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="Air India",
                out_dep_mins=10 * 60 + 20,
                out_block_mins=blk,
                ret_dep_mins=13 * 60 + 50,
                ret_block_mins=blk + 10,
                stops_label="Non-Stop Full-Service" if direct_ok else "1 Fast Hub Stop",
                fare_multiplier=1.14,
                inclusions=["25kg Checked Baggage", "Hot Meals", "Window Mountain Views"],
                booking_channel="Flagship Carrier Direct",
            ),
            _CarrierScheduleTemplate(
                carrier="Nepal Airlines / IndiGo Split-Return",
                flight_numbers=f"Outbound 6E + Return RA ({o_hub.iata}<->{d_hub.iata})",
                carrier_search_hint="Nepal Airlines",
                out_dep_mins=8 * 60 + 55,
                out_block_mins=blk,
                ret_dep_mins=16 * 60 + 30,
                ret_block_mins=blk + 10,
                stops_label="Flexible Split-Ticket",
                fare_multiplier=1.07,
                inclusions=["20kg–25kg Baggage", "1x Date Change Flex"],
                booking_channel="Split-Ticket Direct",
            ),
        ]

    # 3. Southeast Asia (Bali / Thailand / Singapore / Malaysia / Vietnam)
    if is_intl and (dest_cc in se_asia or orig_cc in se_asia):
        has_lcc_nonstop = (
            (o_hub.iata == "BLR" and d_hub.iata == "DPS")
            or d_hub.iata in ("SIN", "KUL", "BKK", "DMK", "HKT")
            or leg_km <= 3250
        )
        lcc_blk = nonstop_mins if has_lcc_nonstop else std_hub_mins
        sq_nonstop = d_hub.iata == "SIN" or o_hub.iata == "SIN"
        sq_blk = nonstop_mins if sq_nonstop else short_hub_mins
        return [
            _CarrierScheduleTemplate(
                carrier="IndiGo Non-Stop Saver" if has_lcc_nonstop else "IndiGo / AirAsia Smart Hub Saver",
                flight_numbers=(
                    f"6E-1605 ({o_hub.iata}->{d_hub.iata}) · 6E-1606 ({d_hub.iata}->{o_hub.iata})"
                    if (o_hub.iata == "BLR" and d_hub.iata == "DPS")
                    else f"6E-1055 / AK-376 ({o_hub.iata}<->{d_hub.iata})"
                ),
                carrier_search_hint="IndiGo",
                out_dep_mins=7 * 60 + 15,
                out_block_mins=lcc_blk,
                ret_dep_mins=16 * 60 + 45,
                ret_block_mins=lcc_blk + 10,
                stops_label="Non-Stop Direct" if has_lcc_nonstop else "1 Stop (KUL Hub Saver)",
                fare_multiplier=1.00,
                inclusions=["20kg Checked + 7kg Cabin", "Direct Carrier Family Saver"],
                booking_channel="Direct Carrier Round-Trip",
            ),
            _CarrierScheduleTemplate(
                carrier="Singapore Airlines Full-Service",
                flight_numbers=f"SQ-509 ({o_hub.iata}->{d_hub.iata}) · SQ-944 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="Singapore Airlines",
                out_dep_mins=10 * 60 + 35,
                out_block_mins=sq_blk,
                ret_dep_mins=14 * 60 + 20,
                ret_block_mins=sq_blk + 10,
                stops_label="Non-Stop Full-Service" if sq_nonstop else "1 Fast Stop (Changi SIN)",
                fare_multiplier=1.16,
                inclusions=["25kg Checked Baggage", "Hot Meals & Kids Meal", "Complimentary Seat Selection"],
                booking_channel="Singapore Airlines Direct",
            ),
            _CarrierScheduleTemplate(
                carrier="Malaysia Airlines / IndiGo Flex Combo",
                flight_numbers=f"Outbound 6E + Return MH ({o_hub.iata}<->{d_hub.iata})",
                carrier_search_hint="Malaysia Airlines",
                out_dep_mins=6 * 60 + 20,
                out_block_mins=std_hub_mins if not has_lcc_nonstop else short_hub_mins,
                ret_dep_mins=17 * 60 + 40,
                ret_block_mins=std_hub_mins if not has_lcc_nonstop else short_hub_mins,
                stops_label="Morning Outbound · Flexible Return",
                fare_multiplier=1.08,
                inclusions=["20kg–25kg Checked Bag", "1x Free Date Change", "Daytime Kid-Friendly Timing"],
                booking_channel="Cross-Carrier Split Return",
            ),
        ]

    # 4. Middle East & Indian Ocean (UAE, Qatar, Sri Lanka, Maldives, Mauritius, Seychelles)
    if is_intl and (dest_cc in gulf_io or orig_cc in gulf_io):
        direct_ok = leg_km <= 4200
        blk = nonstop_mins if direct_ok else short_hub_mins
        flagship_name = (
            "SriLankan Airlines Direct"
            if d_hub.iata == "CMB"
            else ("Emirates Full-Service Direct" if d_hub.iata in ("DXB", "MRU", "SEZ") else "Qatar / Emirates Full-Service")
        )
        return [
            _CarrierScheduleTemplate(
                carrier="IndiGo / Air India Express Direct",
                flight_numbers=f"6E-1415 ({o_hub.iata}->{d_hub.iata}) · IX-814 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="IndiGo",
                out_dep_mins=8 * 60 + 30,
                out_block_mins=blk,
                ret_dep_mins=16 * 60 + 15,
                ret_block_mins=blk + 10,
                stops_label="Non-Stop · Smart Value" if direct_ok else "1 Stop · Smart Value",
                fare_multiplier=1.00,
                inclusions=["20kg–30kg Checked Baggage", "7kg Cabin Bag", "Direct Carrier Fare"],
                booking_channel="Direct Carrier Round-Trip",
            ),
            _CarrierScheduleTemplate(
                carrier=flagship_name,
                flight_numbers=f"EK-565 / UL-172 ({o_hub.iata}<->{d_hub.iata})",
                carrier_search_hint=flagship_name.split()[0],
                out_dep_mins=10 * 60 + 15,
                out_block_mins=blk,
                ret_dep_mins=14 * 60 + 40,
                ret_block_mins=blk + 10,
                stops_label="Non-Stop · Full-Service" if direct_ok else "1 Stop (DXB Hub)",
                fare_multiplier=1.16,
                inclusions=["30kg Checked Baggage", "Hot Meal & Kids Pack", "In-Flight Entertainment"],
                booking_channel="Flagship Carrier Direct",
            ),
            _CarrierScheduleTemplate(
                carrier="Air India Flexible Family Return",
                flight_numbers=f"AI-971 ({o_hub.iata}->{d_hub.iata}) · AI-972 ({d_hub.iata}->{o_hub.iata})",
                carrier_search_hint="Air India",
                out_dep_mins=7 * 60 + 5,
                out_block_mins=blk,
                ret_dep_mins=18 * 60 + 20,
                ret_block_mins=blk + 10,
                stops_label="Non-Stop · Flex Tariff" if direct_ok else "1 Stop · Flex Tariff",
                fare_multiplier=1.08,
                inclusions=["25kg Checked Baggage", "Hot Meals", "Low-Fee Date Flexibility"],
                booking_channel="Air India Direct Portal",
            ),
        ]

    # 5. Global Long-Haul / Intra-Continental (Europe, East Asia, Americas, Oceania)
    direct_possible = leg_km <= 7800
    fast_blk = nonstop_mins if direct_possible else short_hub_mins
    return [
        _CarrierScheduleTemplate(
            carrier="Smart Hub Saver (Qatar / Emirates / Singapore Air)",
            flight_numbers=f"QR-573 / EK-569 ({o_hub.iata}<->{d_hub.iata})",
            carrier_search_hint="Qatar Airways",
            out_dep_mins=4 * 60 + 25,
            out_block_mins=std_hub_mins,
            ret_dep_mins=15 * 60 + 10,
            ret_block_mins=std_hub_mins + 15,
            stops_label="1 Stop · Best All-In Value",
            fare_multiplier=1.00,
            inclusions=["23kg Checked + 7kg Cabin", "Through-Checked Baggage", "Hot Meals Included"],
            booking_channel="Direct Carrier Hub Tariff",
        ),
        _CarrierScheduleTemplate(
            carrier="Fastest Flagship Schedule (Air India / Lufthansa / BA)",
            flight_numbers=f"AI-127 / LH-755 ({o_hub.iata}<->{d_hub.iata})",
            carrier_search_hint="Lufthansa",
            out_dep_mins=9 * 60 + 15,
            out_block_mins=fast_blk,
            ret_dep_mins=13 * 60 + 35,
            ret_block_mins=fast_blk + 20,
            stops_label="Non-Stop Express" if direct_possible else "1 Short Hub Connection",
            fare_multiplier=1.17,
            inclusions=["2x 23kg Checked Baggage", "Full Meal Service & Kids Meal", "Seat Selection"],
            booking_channel="Flagship Direct Portal",
        ),
        _CarrierScheduleTemplate(
            carrier="Alliance Split-Return Flexible Fare",
            flight_numbers=f"Split Outbound + Return ({o_hub.iata}<->{d_hub.iata})",
            carrier_search_hint="Star Alliance",
            out_dep_mins=7 * 60 + 40,
            out_block_mins=std_hub_mins,
            ret_dep_mins=17 * 60 + 25,
            ret_block_mins=std_hub_mins + 15,
            stops_label="1 Stop · Date-Change Flex",
            fare_multiplier=1.09,
            inclusions=["23kg Checked Baggage", "1x Free Date Change", "Daytime Arrival Window"],
            booking_channel="Alliance Direct Split-Ticket",
        ),
    ]


async def discover_gateway_flights(
    origin_geo: GeoLocation,
    dest_geo: GeoLocation,
    spec: TripSpec,
) -> List[FlightOption]:
    """Multi-Airport Gateway & Virtual Interline Flight Arbitrage Engine.

    Uses live Google Flights via SerpApi when `SERPAPI_API_KEY` is set; otherwise computes
    timezone-exact multi-carrier & multi-gateway round-trip options with pre-filled deep-links.
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

    # 2. Timezone-exact parametric multi-carrier & multi-gateway benchmark options
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
            f"{second_hub.iata} ({second_km:.0f} km), saving {km_saved:.0f} km of ground transfer."
        )

    pax = max(1, spec.party.adults + spec.party.children)
    leg_km = max(220.0, haversine_km(o_hub.lat, o_hub.lng, best_d_hub.lat, best_d_hub.lng))
    is_intl = origin_geo.country_code != dest_geo.country_code

    per_pax_roundtrip = _estimate_per_pax_roundtrip_inr(leg_km, is_intl)
    base_family_total = per_pax_roundtrip * pax

    templates = _corridor_carrier_templates(
        o_hub=o_hub,
        d_hub=best_d_hub,
        orig_cc=origin_geo.country_code,
        dest_cc=dest_geo.country_code,
        leg_km=leg_km,
    )

    skyscanner_primary = build_skyscanner_deep_link(
        orig_iata=o_hub.iata,
        dest_iata=best_d_hub.iata,
        start_date=spec.start_date,
        end_date=spec.end_date,
        party=spec.party,
        country_code=origin_geo.country_code,
    )

    options: List[FlightOption] = []
    for idx, tpl in enumerate(templates, start=1):
        landed = int(round(base_family_total * tpl.fare_multiplier, -2))
        ota_unopt = int(round(landed * 1.15, -2)) + (hub_bonus_inr if idx == 1 else 900)
        sav = max(1100, ota_unopt - landed)

        out_dep_str = _fmt_clock(tpl.out_dep_mins)
        out_arr_str = compute_local_arrival_clock(
            tpl.out_dep_mins, tpl.out_block_mins, o_hub.tz_offset_mins, best_d_hub.tz_offset_mins
        )
        out_dur_str = _fmt_duration(tpl.out_block_mins)

        ret_dep_str = _fmt_clock(tpl.ret_dep_mins)
        ret_arr_str = compute_local_arrival_clock(
            tpl.ret_dep_mins, tpl.ret_block_mins, best_d_hub.tz_offset_mins, o_hub.tz_offset_mins
        )
        ret_dur_str = _fmt_duration(tpl.ret_block_mins)

        note = (
            alt_note
            if idx == 1
            else (
                f"Full-service schedule into {best_d_hub.iata} with checked baggage, hot meals & family seating."
                if idx == 2
                else f"Daytime outbound + date-change flexible return via {best_d_hub.iata} ({best_d_ground_km:.0f} km to {dest_geo.short_name})."
            )
        )

        gflights_url = build_google_flights_deep_link(
            orig_iata=o_hub.iata,
            dest_iata=best_d_hub.iata,
            start_date=spec.start_date,
            end_date=spec.end_date,
            party=spec.party,
            carrier_hint=tpl.carrier_search_hint,
        )

        options.append(
            FlightOption(
                id=f"flt-{o_hub.iata.lower()}-{best_d_hub.iata.lower()}-{idx}",
                carrier=tpl.carrier,
                flight_numbers=tpl.flight_numbers,
                route_label=f"{o_hub.iata} -> {best_d_hub.iata} ({best_d_hub.name})",
                gateway_hub_note=note,
                depart_time=out_dep_str,
                arrive_time=out_arr_str,
                duration=out_dur_str,
                return_depart_time=ret_dep_str,
                return_arrive_time=ret_arr_str,
                return_duration=ret_dur_str,
                stops_label=tpl.stops_label,
                landed_family_total_inr=landed,
                ota_unoptimized_inr=ota_unopt,
                savings_inr=sav,
                booking_channel=tpl.booking_channel,
                booking_url=gflights_url,
                skyscanner_url=skyscanner_primary,
                inclusions=tpl.inclusions,
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

    # 4th Option: Alternate Gateway Airport Comparison when a realistic secondary hub exists (< 320 km transfer)
    if len(dest_hubs) > 1 and dest_hubs[1][1] <= 320.0:
        second_hub, second_km = dest_hubs[1]
        alt_leg_km = max(220.0, haversine_km(o_hub.lat, o_hub.lng, second_hub.lat, second_hub.lng))
        alt_per_pax = _estimate_per_pax_roundtrip_inr(alt_leg_km, is_intl)
        alt_family_total = max(int(round(base_family_total * 0.95, -2)), alt_per_pax * pax)
        alt_unopt = int(round(alt_family_total * 1.13, -2))
        alt_block_mins = max(55, int(round(36 + (alt_leg_km / 735.0) * 60))) + (95 if is_intl and alt_leg_km > 3200 else 0)
        extra_drive_km = max(0.0, second_km - best_d_ground_km)

        alt_dep_mins = 11 * 60 + 20
        alt_ret_dep_mins = 15 * 60 + 30
        alt_arr_str = compute_local_arrival_clock(
            alt_dep_mins, alt_block_mins, o_hub.tz_offset_mins, second_hub.tz_offset_mins
        )
        alt_ret_arr_str = compute_local_arrival_clock(
            alt_ret_dep_mins, alt_block_mins + 10, second_hub.tz_offset_mins, o_hub.tz_offset_mins
        )

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
                depart_time=_fmt_clock(alt_dep_mins),
                arrive_time=alt_arr_str,
                duration=_fmt_duration(alt_block_mins),
                return_depart_time=_fmt_clock(alt_ret_dep_mins),
                return_arrive_time=alt_ret_arr_str,
                return_duration=_fmt_duration(alt_block_mins + 10),
                stops_label=f"Alt Hub ({second_hub.iata})",
                landed_family_total_inr=alt_family_total,
                ota_unoptimized_inr=alt_unopt,
                savings_inr=max(900, alt_unopt - alt_family_total),
                booking_channel=f"Secondary Airport Check ({second_hub.iata})",
                booking_url=build_google_flights_deep_link(
                    orig_iata=o_hub.iata,
                    dest_iata=second_hub.iata,
                    start_date=spec.start_date,
                    end_date=spec.end_date,
                    party=spec.party,
                ),
                skyscanner_url=build_skyscanner_deep_link(
                    orig_iata=o_hub.iata,
                    dest_iata=second_hub.iata,
                    start_date=spec.start_date,
                    end_date=spec.end_date,
                    party=spec.party,
                    country_code=origin_geo.country_code,
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
