from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


TransportMode = Literal["road", "flight", "hybrid"]
StayStrategy = Literal["hotels", "villas", "hybrid"]
DietaryPreference = Literal["veg", "non_veg", "both"]
CurrencyCode = Literal["INR", "USD", "EUR", "GBP"]
PriceProvenance = Literal["live_verified", "live_scraped", "estimated_benchmark"]
PersonaMode = Literal["advisor", "eli5", "debate", "devil"]


class TravelParty(BaseModel):
    adults: int = 2
    children: int = 0
    child_ages: List[int] = Field(default_factory=list)
    room_setup: str = "Standard Room / Entire Stay"


class PinnedStaySpec(BaseModel):
    leg_label: str
    city: str
    property_name: str
    check_in: str
    check_out: str
    room_config: str = "Standard Room + Breakfast"


class ActivityPreferences(BaseModel):
    wildlife_safari: bool = False
    adventure_water: bool = False
    moderate_climbs: bool = True
    transit_sightseeing: bool = False
    dietary: DietaryPreference = "both"
    pace: Literal["relaxed", "balanced", "explorer"] = "balanced"


class TripSpec(BaseModel):
    origin: str
    destination: str
    start_date: str
    end_date: str
    departure_time_pref: str = "Morning departure"
    return_timing_pref: str = "Afternoon return"
    transport_mode: TransportMode = "road"
    stay_strategy: StayStrategy = "hybrid"
    vehicle_name: str = "Self-Drive SUV"
    destination_villa_bhk: int = 2
    nightly_budget_min_inr: int = 12000
    nightly_budget_max_inr: int = 20000
    stay_options_limit: int = 3
    stay_pool_offset: int = 0
    currency: Optional[CurrencyCode] = None
    party: TravelParty = Field(default_factory=TravelParty)
    pinned_stays: List[PinnedStaySpec] = Field(default_factory=list)
    activities: ActivityPreferences = Field(default_factory=ActivityPreferences)


class ChannelOffer(BaseModel):
    platform: str
    channel_type: Literal["direct_brand", "villa_portal", "airbnb", "ota"]
    base_total_inr: int
    extra_bed_or_addons_inr: int = 0
    platform_or_cleaning_fee_inr: int = 0
    taxes_gst_inr: int = 0
    promo_discount_inr: int = 0
    landed_total_inr: int
    per_night_landed_inr: int
    inclusions: List[str] = Field(default_factory=list)
    promo_note: Optional[str] = None
    booking_url: str
    is_best_deal: bool = False


class StayCandidate(BaseModel):
    id: str
    name: str
    subtitle: str
    category: Literal["hotel", "villa", "airbnb", "bluekite"]
    city: str
    micro_region: str
    lat: float
    lng: float
    rating: float
    review_count: int
    bedrooms_label: str
    check_in: str
    check_out: str
    nights: int
    image_url: str
    suv_access_note: str
    kid_fit_note: str
    highlights: List[str] = Field(default_factory=list)
    offers: List[ChannelOffer] = Field(default_factory=list)
    best_channel: str
    best_landed_inr: int
    worst_landed_inr: int
    savings_inr: int
    deal_anomaly_score: float = Field(description="0-100 score indicating value vs comp tier")
    anomaly_badge: str
    price_provenance: PriceProvenance = "estimated_benchmark"
    provenance_label: str = "Market Benchmark (Set SERPAPI_API_KEY for Live OTA Checkout)"


class FlightOption(BaseModel):
    id: str
    carrier: str
    flight_numbers: str
    route_label: str
    gateway_hub_note: str
    depart_time: str
    arrive_time: str
    duration: str
    return_depart_time: Optional[str] = None
    return_arrive_time: Optional[str] = None
    return_duration: Optional[str] = None
    stops_label: str
    landed_family_total_inr: int
    ota_unoptimized_inr: int
    savings_inr: int
    booking_channel: str
    booking_url: str = "https://www.google.com/travel/flights"
    skyscanner_url: Optional[str] = None
    inclusions: List[str] = Field(default_factory=list)
    origin_iata: Optional[str] = None
    dest_iata: Optional[str] = None
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    price_provenance: PriceProvenance = "estimated_benchmark"
    provenance_label: str = "Distance Airfare Benchmark (Set SERPAPI_API_KEY for Live Fares)"


class RoadSegment(BaseModel):
    id: str
    day_number: int
    from_name: str
    to_name: str
    highway_label: str
    distance_km: float
    duration_mins: int
    fastag_toll_inr: int
    fuel_estimate_inr: int
    gate_alert: Optional[str] = None
    coordinates: List[List[float]] = Field(
        default_factory=list, description="[lng, lat] polyline coordinates"
    )


class RoadSummary(BaseModel):
    vehicle: str
    ground_clearance_mm: int
    total_distance_km: float
    total_drive_hours: float
    estimated_fuel_liters: float
    fuel_cost_inr: int
    fastag_and_forest_tolls_inr: int
    rental_car_cost_inr: int = 0
    total_road_cost_inr: int
    corridor_notes: List[str] = Field(default_factory=list)
    segments: List[RoadSegment] = Field(default_factory=list)


class TimelineStop(BaseModel):
    id: str
    time_window: str
    title: str
    location_label: str
    category: Literal["drive", "stay", "climb", "dining", "heritage", "nature", "flight"]
    lat: float
    lng: float
    duration_label: str
    description: str
    dietary_note: Optional[str] = None
    kid_note: Optional[str] = None
    insider_tip: Optional[str] = None
    drive_from_prev_mins: Optional[int] = None


class ItineraryDay(BaseModel):
    day_number: int
    date_label: str
    weekday: str
    headline: str
    corridor_tag: str
    drive_km: float
    drive_time_label: str
    overnight_label: str
    stops: List[TimelineStop] = Field(default_factory=list)


class PlatformCoverageNote(BaseModel):
    platform: str
    status: Literal["matched", "zero_inventory_pivoted", "live_scanned"]
    listings_scanned: int
    note: str


class ParetoBlueprint(BaseModel):
    id: str
    rank_badge: str
    name: str
    strategy_subtitle: str
    recommended: bool = False
    pareto_front_rank: int = 1
    crowding_distance: float = 1.0
    total_core_landed_inr: int
    unoptimized_baseline_inr: int
    total_arbitrage_savings_inr: int
    dining_and_activities_est_inr: int
    fatigue_score: int = Field(description="Lower means more relaxed driving/pacing (0-100)")
    quality_score: int = Field(description="Overall stay + experience quality (0-100)")
    deal_anomaly_score: float
    stays: List[StayCandidate] = Field(default_factory=list)
    flights: List[FlightOption] = Field(default_factory=list)
    road: RoadSummary
    arbitrage_callouts: List[str] = Field(default_factory=list)
    days: List[ItineraryDay] = Field(default_factory=list)


class ToolCallTrace(BaseModel):
    phase: Literal[
        "Phase 1 · Intent & Constraints",
        "Phase 2 · Multi-Channel Arbitrage",
        "Phase 3 · Spatio-Temporal Solver",
        "Phase 4 · Grounded Advisory Reasoning",
    ]
    tool_name: str
    status: Literal["completed", "pivoted"] = "completed"
    latency_ms: int
    input_summary: str
    finding_summary: str


class OptimizationResponse(BaseModel):
    trip_id: Optional[str] = None
    active_currency: CurrencyCode = "INR"
    fx_rates: Dict[str, float] = Field(
        default_factory=lambda: {"INR": 1.0, "USD": 0.0118, "EUR": 0.0109, "GBP": 0.0093}
    )
    pareto_frontier_note: str = (
        "Strict Non-Dominated 3D Pareto Frontier (Cost × Fatigue × Utility) + 2-Opt VRPTW Schedule"
    )
    trip_spec: TripSpec
    platform_coverage: List[PlatformCoverageNote]
    tool_trace: List[ToolCallTrace]
    blueprints: List[ParetoBlueprint]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: Optional[str] = None
    extracted_updates: List[str] = Field(default_factory=list)
    tool_trace: List[ToolCallTrace] = Field(default_factory=list)


class UICommand(BaseModel):
    cmd: Literal["SET_TAB", "SELECT_DAY", "SET_CURRENCY", "OPEN_PARAMS", "SELECT_BLUEPRINT"]
    tab: Optional[Literal["itinerary", "arbitrage", "telemetry"]] = None
    day: Optional[int] = None
    currency: Optional[CurrencyCode] = None
    blueprint_idx: Optional[int] = None
    reason: Optional[str] = None


class ChatTurnRequest(BaseModel):
    message: str
    current_spec: TripSpec
    history: List[ChatMessage] = Field(default_factory=list)
    mode: PersonaMode = "advisor"
    api_key: Optional[str] = None


class ChatTurnResponse(BaseModel):
    updated_spec: TripSpec
    assistant_reply: str
    extracted_updates: List[str]
    needs_clarification: bool = False
    follow_up_questions: List[str] = Field(default_factory=list)
    suggested_prompts: List[str] = Field(default_factory=list)
    ui_commands: List[UICommand] = Field(default_factory=list)
    engine_label: str = "TripSage 3-Phase Engine"
    used_llm: bool = False
    optimization: Optional[OptimizationResponse] = None


class SaveTripRequest(BaseModel):
    spec: TripSpec
    optimization: OptimizationResponse
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    trip_id: Optional[str] = None


class SavedTripPayload(BaseModel):
    trip_id: str
    created_at: str
    title: str
    spec: TripSpec
    optimization: OptimizationResponse
    messages: List[Dict[str, Any]] = Field(default_factory=list)
