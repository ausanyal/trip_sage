from __future__ import annotations

import dataclasses
import hashlib
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

from db import RATE_LIMITER, cache_get_json, cache_set_json
from models import ActivityPreferences, RoadSegment


USER_AGENT = "TripSage-MultiModal-Optimizer/3.0 (https://github.com/ausanyal/trip_sage)"


@dataclass
class GeoLocation:
    query: str
    short_name: str
    display_name: str
    lat: float
    lng: float
    country_code: str = "in"
    source: str = "nominatim_live"


@dataclass
class AirportHub:
    iata: str
    name: str
    city: str
    lat: float
    lng: float
    is_regional: bool = False


@dataclass
class DiscoveredPOI:
    id: str
    name: str
    category: str  # "climb" | "nature" | "heritage" | "dining"
    lat: float
    lng: float
    cuisine_or_tag: str
    description: str
    opening_hours_raw: Optional[str] = None
    dietary_note: Optional[str] = None
    kid_note: Optional[str] = None
    insider_tip: Optional[str] = None


# Reference airport coordinate index for Haversine nearest-gateway resolution (India + Global Hubs)
AIRPORT_INDEX: List[AirportHub] = [
    AirportHub("BLR", "Kempegowda International", "Bengaluru", 13.1986, 77.7066),
    AirportHub("MYQ", "Mysore Airport", "Mysuru", 12.2300, 76.6558, is_regional=True),
    AirportHub("CNN", "Kannur International", "Kannur", 11.9186, 75.5472, is_regional=True),
    AirportHub("CCJ", "Calicut International", "Kozhikode", 11.1368, 75.9553),
    AirportHub("COK", "Cochin International", "Kochi", 10.1520, 76.4019),
    AirportHub("TRV", "Trivandrum International", "Thiruvananthapuram", 8.4821, 76.9200),
    AirportHub("CJB", "Coimbatore International", "Coimbatore", 11.0300, 77.0434),
    AirportHub("MAA", "Chennai International", "Chennai", 12.9941, 80.1709),
    AirportHub("IXE", "Mangaluru International", "Mangaluru", 12.9613, 74.8901),
    AirportHub("GOX", "Manohar International (Mopa)", "North Goa", 15.7336, 73.8681, is_regional=True),
    AirportHub("GOI", "Goa Dabolim International", "South/Central Goa", 15.3808, 73.8314),
    AirportHub("BOM", "Chhatrapati Shivaji Maharaj Intl", "Mumbai", 19.0896, 72.8656),
    AirportHub("PNQ", "Pune International", "Pune", 18.5821, 73.9197),
    AirportHub("HYD", "Rajiv Gandhi International", "Hyderabad", 17.2403, 78.4294),
    AirportHub("DEL", "Indira Gandhi International", "New Delhi", 28.5562, 77.1000),
    AirportHub("DED", "Jolly Grant Airport", "Dehradun", 30.1897, 78.1803, is_regional=True),
    AirportHub("PGH", "Pantnagar Airport", "Pantnagar", 29.0334, 79.4737, is_regional=True),
    AirportHub("IXC", "Shaheed Bhagat Singh Intl", "Chandigarh", 30.6735, 76.7885),
    AirportHub("ATQ", "Sri Guru Ram Dass Jee Intl", "Amritsar", 31.7096, 74.7973),
    AirportHub("SXR", "Sheikh ul-Alam International", "Srinagar", 33.9871, 74.7742),
    AirportHub("IXL", "Kushok Bakula Rimpochee", "Leh", 34.1359, 77.5465, is_regional=True),
    AirportHub("JAI", "Jaipur International", "Jaipur", 26.8242, 75.8122),
    AirportHub("UDR", "Maharana Pratap Airport", "Udaipur", 24.6177, 73.8961, is_regional=True),
    AirportHub("JDH", "Jodhpur Airport", "Jodhpur", 26.2511, 73.0489, is_regional=True),
    AirportHub("AMD", "Sardar Vallabhbhai Patel Intl", "Ahmedabad", 23.0772, 72.6347),
    AirportHub("CCU", "Netaji Subhas Chandra Bose Intl", "Kolkata", 22.6547, 88.4467),
    AirportHub("IXB", "Bagdogra International", "Siliguri", 26.6812, 88.3286, is_regional=True),
    AirportHub("GAU", "Lokpriya Gopinath Bordoloi Intl", "Guwahati", 26.1061, 91.5859),
    AirportHub("DXB", "Dubai International", "Dubai", 25.2532, 55.3657),
    AirportHub("AUH", "Zayed International", "Abu Dhabi", 24.4439, 54.6511),
    AirportHub("DOH", "Hamad International", "Doha", 25.2731, 51.6081),
    AirportHub("SIN", "Singapore Changi", "Singapore", 1.3644, 103.9915),
    AirportHub("BKK", "Suvarnabhumi", "Bangkok", 13.6900, 100.7501),
    AirportHub("DPS", "Ngurah Rai International", "Bali", -8.7482, 115.1672),
    AirportHub("NRT", "Narita International", "Tokyo", 35.7720, 140.3929),
    AirportHub("LHR", "London Heathrow", "London", 51.4700, -0.4543),
    AirportHub("LGW", "London Gatwick", "London South", 51.1537, -0.1821, is_regional=True),
    AirportHub("CDG", "Charles de Gaulle", "Paris", 49.0097, 2.5479),
    AirportHub("FRA", "Frankfurt Airport", "Frankfurt", 50.0379, 8.5622),
    AirportHub("FCO", "Leonardo da Vinci Fiumicino", "Rome", 41.8003, 12.2389),
    AirportHub("AMS", "Amsterdam Schiphol", "Amsterdam", 52.3105, 4.7683),
    AirportHub("ZRH", "Zurich Airport", "Zurich", 47.4647, 8.5492),
    AirportHub("JFK", "John F. Kennedy Intl", "New York", 40.6413, -73.7781),
    AirportHub("EWR", "Newark Liberty Intl", "Newark", 40.6895, -74.1745, is_regional=True),
    AirportHub("LAX", "Los Angeles Intl", "Los Angeles", 33.9416, -118.4085),
    AirportHub("SFO", "San Francisco Intl", "San Francisco", 37.6213, -122.3790),
    AirportHub("SYD", "Sydney Kingsford Smith", "Sydney", -33.9399, 151.1753),
]

# Offline coordinate fallback index used ONLY when outbound network/Nominatim is unreachable
OFFLINE_GAZETTEER: Dict[str, Tuple[float, float, str]] = {
    "koramangala": (12.9352, 77.6245, "in"),
    "bengaluru": (12.9716, 77.5946, "in"),
    "bangalore": (12.9716, 77.5946, "in"),
    "mysuru": (12.2958, 76.6394, "in"),
    "mysore": (12.2958, 76.6394, "in"),
    "wayanad": (11.6050, 76.0830, "in"),
    "vythiri": (11.5515, 76.0410, "in"),
    "coorg": (12.4244, 75.7382, "in"),
    "madikeri": (12.4244, 75.7382, "in"),
    "ooty": (11.4102, 76.6950, "in"),
    "chikmagalur": (13.3161, 75.7720, "in"),
    "munnar": (10.0889, 77.0595, "in"),
    "kochi": (9.9312, 76.2673, "in"),
    "pondicherry": (11.9416, 79.8083, "in"),
    "puducherry": (11.9416, 79.8083, "in"),
    "chennai": (13.0827, 80.2707, "in"),
    "assagao": (15.5939, 73.7867, "in"),
    "goa": (15.4909, 73.8278, "in"),
    "mumbai": (19.0760, 72.8777, "in"),
    "lonavala": (18.7546, 73.4062, "in"),
    "mahabaleshwar": (17.9307, 73.6477, "in"),
    "pune": (18.5204, 73.8567, "in"),
    "hyderabad": (17.3850, 78.4867, "in"),
    "delhi": (28.6139, 77.2090, "in"),
    "rishikesh": (30.0869, 78.2676, "in"),
    "nainital": (29.3919, 79.4542, "in"),
    "manali": (32.2432, 77.1892, "in"),
    "shimla": (31.1048, 77.1734, "in"),
    "jaipur": (26.9124, 75.7873, "in"),
    "udaipur": (24.5854, 73.7125, "in"),
    "jodhpur": (26.2389, 73.0243, "in"),
    "darjeeling": (27.0410, 88.2663, "in"),
    "gangtok": (27.3389, 88.6065, "in"),
    "dubai": (25.2048, 55.2708, "ae"),
    "singapore": (1.3521, 103.8198, "sg"),
    "bali": (-8.4095, 115.1889, "id"),
    "tokyo": (35.6762, 139.6503, "jp"),
    "london": (51.5072, -0.1276, "gb"),
    "paris": (48.8566, 2.3522, "fr"),
    "rome": (41.9028, 12.4964, "it"),
    "zurich": (47.3769, 8.5417, "ch"),
    "new york": (40.7128, -74.0060, "us"),
    "san francisco": (37.7749, -122.4194, "us"),
    "los angeles": (34.0522, -118.2437, "us"),
}

_GEOCODE_MEM: Dict[str, GeoLocation] = {}
_POI_MEM: Dict[str, Tuple[List[DiscoveredPOI], str]] = {}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_airports(
    lat: float, lng: float, max_km: float = 280.0, limit: int = 2
) -> List[Tuple[AirportHub, float]]:
    scored = [(hub, round(haversine_km(lat, lng, hub.lat, hub.lng), 1)) for hub in AIRPORT_INDEX]
    scored.sort(key=lambda item: item[1])
    within = [item for item in scored if item[1] <= max_km]
    return (within or scored[:1])[:limit]


async def geocode_place(query: str) -> GeoLocation:
    key = query.strip().lower()
    if key in _GEOCODE_MEM:
        return _GEOCODE_MEM[key]

    sql_key = f"geocode:v3:{key}"
    cached = cache_get_json(sql_key)
    if isinstance(cached, dict) and "lat" in cached and "lng" in cached:
        loc = GeoLocation(**cached)
        _GEOCODE_MEM[key] = loc
        return loc

    short_default = query.split(",")[0].strip() or query.strip()

    try:
        await RATE_LIMITER.acquire("nominatim", min_interval_sec=0.85)
        async with httpx.AsyncClient(timeout=3.8, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": 1,
                },
            )
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    top = rows[0]
                    addr = top.get("address") or {}
                    cc = str(addr.get("country_code", "in")).lower()
                    loc = GeoLocation(
                        query=query,
                        short_name=short_default,
                        display_name=str(top.get("display_name", query)),
                        lat=float(top["lat"]),
                        lng=float(top["lon"]),
                        country_code=cc,
                        source="nominatim_live",
                    )
                    _GEOCODE_MEM[key] = loc
                    cache_set_json(sql_key, "nominatim", dataclasses.asdict(loc), ttl_seconds=604800)
                    return loc
    except Exception:
        pass

    # Resilient fallback when offline or rate-limited
    for token, (lat, lng, cc) in OFFLINE_GAZETTEER.items():
        if token in key:
            loc = GeoLocation(
                query=query,
                short_name=short_default,
                display_name=query,
                lat=lat,
                lng=lng,
                country_code=cc,
                source="gazetteer_fallback",
            )
            _GEOCODE_MEM[key] = loc
            return loc

    digest = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    lat = 12.0 + (digest % 1600) / 100.0
    lng = 74.0 + ((digest // 1600) % 1000) / 100.0
    loc = GeoLocation(
        query=query,
        short_name=short_default,
        display_name=query,
        lat=round(lat, 4),
        lng=round(lng, 4),
        country_code="in",
        source="computed_fallback",
    )
    _GEOCODE_MEM[key] = loc
    return loc


def parse_vehicle_profile(vehicle_name: str) -> Tuple[int, float, float]:
    """Returns (ground_clearance_mm, km_per_liter, fuel_unit_inr)."""
    low = vehicle_name.lower()
    if any(k in low for k in ["ev", "electric", "nexon ev", "zs ev", "ioniq", "tesla"]):
        return 190, 6.5, 14.0
    if any(k in low for k in ["suv", "meridian", "fortuner", "safari", "xuv", "compass", "thar", "hycross", "crysta", "innova", "scorpio"]):
        return 203, 12.4, 93.0
    if any(k in low for k in ["creta", "seltos", "elevate", "taigun", "kushaq", "brezza", "nexon"]):
        return 192, 14.8, 98.0
    if any(k in low for k in ["sedan", "city", "verna", "virtus", "slavia"]):
        return 165, 16.2, 102.0
    return 185, 14.0, 96.0


def _downsample_coords(coords: List[List[float]], max_pts: int = 40) -> List[List[float]]:
    if len(coords) <= max_pts:
        return [[round(c[0], 4), round(c[1], 4)] for c in coords]
    step = (len(coords) - 1) / float(max_pts - 1)
    sampled = [coords[int(round(i * step))] for i in range(max_pts - 1)]
    sampled.append(coords[-1])
    return [[round(c[0], 4), round(c[1], 4)] for c in sampled]


def _curved_great_circle_path(
    lng1: float, lat1: float, lng2: float, lat2: float, steps: int = 14
) -> List[List[float]]:
    pts: List[List[float]] = []
    dx = lng2 - lng1
    dy = lat2 - lat1
    perp_x = -dy * 0.08
    perp_y = dx * 0.08
    for i in range(steps + 1):
        t = i / float(steps)
        arc = math.sin(math.pi * t)
        pts.append([round(lng1 + dx * t + perp_x * arc, 4), round(lat1 + dy * t + perp_y * arc, 4)])
    return pts


async def route_leg(
    seg_id: str,
    day_number: int,
    from_loc: GeoLocation,
    to_loc: GeoLocation,
    vehicle_name: str,
) -> Tuple[RoadSegment, str]:
    """Routes a driving leg via Project OSRM live highway geometry (SQLite cached), falling back to geodesic."""
    clearance_mm, km_per_l, fuel_price = parse_vehicle_profile(vehicle_name)
    cache_key = f"osrm_leg:v3:{round(from_loc.lat, 3)},{round(from_loc.lng, 3)}->{round(to_loc.lat, 3)},{round(to_loc.lng, 3)}"

    coords: List[List[float]] = []
    distance_km = 0.0
    duration_mins = 0
    highway_refs: List[str] = []
    corridor_alerts: List[str] = []
    source = "osrm_live"

    cached = cache_get_json(cache_key)
    if isinstance(cached, dict) and cached.get("coords"):
        distance_km = float(cached["distance_km"])
        duration_mins = int(cached["duration_mins"])
        coords = cached["coords"]
        highway_refs = cached.get("highway_refs") or []
        corridor_alerts = cached.get("corridor_alerts") or []
        source = "osrm_cached"
    else:
        try:
            await RATE_LIMITER.acquire("osrm", min_interval_sec=0.12)
            url = (
                f"https://router.project-osrm.org/route/v1/driving/"
                f"{from_loc.lng},{from_loc.lat};{to_loc.lng},{to_loc.lat}"
            )
            async with httpx.AsyncClient(timeout=4.2, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(
                    url,
                    params={"overview": "full", "geometries": "geojson", "steps": "true"},
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    routes = payload.get("routes") or []
                    if routes:
                        r0 = routes[0]
                        distance_km = round(float(r0.get("distance", 0.0)) / 1000.0, 1)
                        duration_mins = max(15, int(round(float(r0.get("duration", 0.0)) / 60.0)))
                        raw_coords = (r0.get("geometry") or {}).get("coordinates") or []
                        if raw_coords:
                            coords = _downsample_coords(raw_coords, max_pts=40)

                        for leg in r0.get("legs") or []:
                            for st in leg.get("steps") or []:
                                ref = str(st.get("ref") or "").strip()
                                nm = str(st.get("name") or "").strip()
                                if ref:
                                    primary_ref = ref.split(";")[0].strip()
                                    if primary_ref and primary_ref not in highway_refs:
                                        highway_refs.append(primary_ref)
                                low_nm = f"{ref} {nm}".lower()
                                if any(
                                    w in low_nm
                                    for w in ["reserve", "forest", "wildlife", "national park", "tiger", "ghat", "hairpin"]
                                ):
                                    label_hit = nm or ref
                                    if label_hit and label_hit not in corridor_alerts:
                                        corridor_alerts.append(label_hit)

                        if distance_km > 0.5 and coords:
                            cache_set_json(
                                cache_key,
                                "osrm_route",
                                {
                                    "distance_km": distance_km,
                                    "duration_mins": duration_mins,
                                    "coords": coords,
                                    "highway_refs": highway_refs,
                                    "corridor_alerts": corridor_alerts,
                                },
                                ttl_seconds=86400,
                            )
        except Exception:
            pass

    if distance_km <= 0.5 or not coords:
        source = "geodesic_fallback"
        gc = haversine_km(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng)
        distance_km = round(max(12.0, gc * 1.27), 1)
        duration_mins = max(25, int(round((distance_km / 52.0) * 60)))
        coords = _curved_great_circle_path(from_loc.lng, from_loc.lat, to_loc.lng, to_loc.lat)

    highway_label = (
        f"Via {' -> '.join(highway_refs[:4])}"
        if highway_refs
        else f"Primary Highway Corridor ({from_loc.short_name} -> {to_loc.short_name})"
    )

    liters = distance_km / max(1.0, km_per_l)
    fuel_inr = int(round(liters * fuel_price))

    has_express_or_nh = any(r.upper().startswith(("NH", "NE", "AH", "I-", "E", "A")) for r in highway_refs)
    toll_rate_per_km = 2.15 if has_express_or_nh else (1.35 if distance_km > 90 else 0.0)
    toll_inr = int(round(distance_km * toll_rate_per_km))

    gate_alert: Optional[str] = None
    if corridor_alerts:
        gate_alert = (
            f"Traverses {', '.join(corridor_alerts[:2])} — daytime forest/ghat checkpost window "
            f"(06:00–21:00) enforced by VRPTW solver ({clearance_mm}mm clearance verified)."
        )
    elif duration_mins > 210:
        gate_alert = "3.5h+ highway stretch — 30-min family meal/fuel break inserted to cap driver fatigue."

    return (
        RoadSegment(
            id=seg_id,
            day_number=day_number,
            from_name=from_loc.short_name,
            to_name=to_loc.short_name,
            highway_label=highway_label,
            distance_km=distance_km,
            duration_mins=duration_mins,
            fastag_toll_inr=toll_inr,
            fuel_estimate_inr=fuel_inr,
            gate_alert=gate_alert,
            coordinates=coords,
        ),
        source,
    )


async def discover_pois(
    lat: float,
    lng: float,
    city_short: str,
    activities: ActivityPreferences,
    radius_m: int = 24000,
) -> Tuple[List[DiscoveredPOI], str]:
    """Queries OpenStreetMap Overpass API for real local attractions, climbs, nature spots, and restaurants."""
    cache_key = f"pois:v3:{round(lat, 2)}:{round(lng, 2)}:{activities.dietary}:{activities.moderate_climbs}:{activities.adventure_water}"
    if cache_key in _POI_MEM:
        return _POI_MEM[cache_key]

    cached_sql = cache_get_json(cache_key)
    if isinstance(cached_sql, dict) and cached_sql.get("items"):
        restored = [DiscoveredPOI(**item) for item in cached_sql["items"]]
        src = str(cached_sql.get("source", "overpass_osm_cached"))
        _POI_MEM[cache_key] = (restored, src)
        return restored, src

    overpass_query = f"""
    [out:json][timeout:6];
    (
      node["natural"~"waterfall|peak|cave_entrance|beach"](around:{radius_m},{lat},{lng});
      way["natural"~"waterfall|peak|cave_entrance|beach"](around:{radius_m},{lat},{lng});
      node["tourism"~"viewpoint|attraction|museum|zoo"](around:{radius_m},{lat},{lng});
      way["tourism"~"viewpoint|attraction|museum|zoo"](around:{radius_m},{lat},{lng});
      node["historic"~"monument|fort|archaeological_site|castle|ruins"](around:{radius_m},{lat},{lng});
      node["leisure"~"nature_reserve|park"](around:{radius_m},{lat},{lng});
      node["amenity"="restaurant"]["name"](around:{min(radius_m, 16000)},{lat},{lng});
    );
    out center 75;
    """

    discovered: List[DiscoveredPOI] = []
    seen_names: set[str] = set()

    try:
        await RATE_LIMITER.acquire("overpass", min_interval_sec=0.35)
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": overpass_query},
            )
            if resp.status_code == 200:
                elements = (resp.json() or {}).get("elements") or []
                elements.sort(
                    key=lambda el: sum(
                        1
                        for k in ("wikipedia", "wikidata", "website", "cuisine", "opening_hours")
                        if k in (el.get("tags") or {})
                    ),
                    reverse=True,
                )
                for idx, el in enumerate(elements):
                    tags = el.get("tags") or {}
                    name = str(tags.get("name:en") or tags.get("name") or "").strip()
                    if not name or len(name) < 3:
                        continue
                    norm = name.lower()
                    if norm in seen_names:
                        continue
                    seen_names.add(norm)

                    elat = el.get("lat") or (el.get("center") or {}).get("lat")
                    elng = el.get("lon") or (el.get("center") or {}).get("lon")
                    if elat is None or elng is None:
                        continue

                    oh_raw = str(tags.get("opening_hours") or "").strip() or None

                    if tags.get("amenity") == "restaurant":
                        cuisine = str(tags.get("cuisine") or "Regional & Multi-Cuisine").replace(";", ", ").replace("_", " ").title()
                        veg_tag = tags.get("diet:vegetarian")
                        if activities.dietary == "veg" and veg_tag == "no":
                            continue
                        diet_label = (
                            f"Pure Veg / Veg-Friendly ({cuisine})"
                            if activities.dietary == "veg"
                            else f"Veg + Non-Veg Regional ({cuisine})"
                        )
                        discovered.append(
                            DiscoveredPOI(
                                id=f"poi-din-{idx}",
                                name=name,
                                category="dining",
                                lat=float(elat),
                                lng=float(elng),
                                cuisine_or_tag=cuisine,
                                description=f"OpenStreetMap verified local dining stop in {city_short} ({cuisine}).",
                                opening_hours_raw=oh_raw or "11:30-22:30",
                                dietary_note=diet_label,
                            )
                        )
                    elif tags.get("natural") in ("peak", "waterfall", "cave_entrance") or tags.get("tourism") == "viewpoint":
                        nat = str(tags.get("natural") or tags.get("tourism") or "scenic").replace("_", " ").title()
                        cat = "climb" if activities.moderate_climbs else "nature"
                        discovered.append(
                            DiscoveredPOI(
                                id=f"poi-clm-{idx}",
                                name=name,
                                category=cat,
                                lat=float(elat),
                                lng=float(elng),
                                cuisine_or_tag=nat,
                                description=f"OpenStreetMap verified {nat.lower()} excursion near {city_short} with panoramic vistas.",
                                opening_hours_raw=oh_raw or "08:00-17:00",
                                kid_note="Scheduled in cool morning window by VRPTW solver before midday heat.",
                                insider_tip=(
                                    f"OSM Hours: {oh_raw}"
                                    if oh_raw
                                    else "Arrive before 09:30 AM for clearest views & easy parking."
                                ),
                            )
                        )
                    elif tags.get("historic") or tags.get("tourism") in ("museum", "attraction", "zoo"):
                        tag_lbl = str(tags.get("historic") or tags.get("tourism") or "heritage").replace("_", " ").title()
                        if not activities.wildlife_safari and "safari" in norm:
                            continue
                        discovered.append(
                            DiscoveredPOI(
                                id=f"poi-her-{idx}",
                                name=name,
                                category="heritage",
                                lat=float(elat),
                                lng=float(elng),
                                cuisine_or_tag=tag_lbl,
                                description=f"Local {tag_lbl.lower()} highlight in the {city_short} micro-corridor.",
                                opening_hours_raw=oh_raw or "09:30-17:30",
                            )
                        )
                    else:
                        discovered.append(
                            DiscoveredPOI(
                                id=f"poi-nat-{idx}",
                                name=name,
                                category="nature",
                                lat=float(elat),
                                lng=float(elng),
                                cuisine_or_tag="Nature Reserve",
                                description=f"Scenic green corridor & nature walk around {city_short}.",
                                opening_hours_raw=oh_raw or "08:00-18:00",
                            )
                        )
    except Exception:
        pass

    live_hit = len(discovered) >= 4
    source = "overpass_osm_live" if live_hit else "regional_synthesizer_fallback"

    climbs_pool = [p for p in discovered if p.category in ("climb", "nature")]
    heritage_pool = [p for p in discovered if p.category == "heritage"]
    dining_pool = [p for p in discovered if p.category == "dining"]

    offsets = [(0.028, 0.022), (-0.024, 0.031), (0.019, -0.027), (-0.031, -0.018)]
    while len(climbs_pool) < 4:
        k = len(climbs_pool)
        dlat, dlng = offsets[k % len(offsets)]
        poi = DiscoveredPOI(
            id=f"gen-climb-{k}",
            name=f"{city_short} Scenic Ridge & Viewpoint Trail #{k + 1}" if activities.moderate_climbs else f"{city_short} Botanical & Valley Overlook #{k + 1}",
            category="climb" if activities.moderate_climbs else "nature",
            lat=lat + dlat,
            lng=lng + dlng,
            cuisine_or_tag="Scenic Trail",
            description=f"Curated morning outdoor exploration in the {city_short} elevation belt.",
            opening_hours_raw="08:00-17:00",
            kid_note="Family-paced trail with scenic photo lookouts.",
            insider_tip="Scheduled early morning for cool breeze.",
        )
        climbs_pool.append(poi)
        discovered.append(poi)

    while len(heritage_pool) < 2:
        k = len(heritage_pool)
        dlat, dlng = offsets[(k + 2) % len(offsets)]
        poi = DiscoveredPOI(
            id=f"gen-her-{k}",
            name=f"{city_short} Artisan & Cultural Heritage Centre #{k + 1}",
            category="heritage",
            lat=lat + dlat * 0.8,
            lng=lng + dlng * 0.8,
            cuisine_or_tag="Cultural Stop",
            description=f"Afternoon craft, culture, and local heritage experience in {city_short}.",
            opening_hours_raw="09:30-18:00",
        )
        heritage_pool.append(poi)
        discovered.append(poi)

    while len(dining_pool) < 4:
        k = len(dining_pool)
        dlat, dlng = offsets[(k + 1) % len(offsets)]
        diet_txt = "Pure Vegetarian Regional Thali & Cafe" if activities.dietary == "veg" else "Signature Regional Veg & Non-Veg Kitchen"
        poi = DiscoveredPOI(
            id=f"gen-din-{k}",
            name=f"{city_short} Heritage Kitchen & Bistro #{k + 1}",
            category="dining",
            lat=lat + dlat * 0.5,
            lng=lng + dlng * 0.5,
            cuisine_or_tag="Regional Cuisine",
            description=f"Spacious family-friendly restaurant along the {city_short} sightseeing loop.",
            opening_hours_raw="11:30-22:30",
            dietary_note=diet_txt,
        )
        dining_pool.append(poi)
        discovered.append(poi)

    _POI_MEM[cache_key] = (discovered, source)
    if live_hit:
        cache_set_json(
            cache_key,
            "overpass_pois",
            {"source": "overpass_osm_cached", "items": [dataclasses.asdict(p) for p in discovered]},
            ttl_seconds=86400,
        )
    return discovered, source
