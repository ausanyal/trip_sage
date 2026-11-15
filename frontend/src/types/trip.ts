export type TransportMode = "road" | "flight" | "hybrid";
export type StayStrategy = "hotels" | "villas" | "hybrid";
export type DietaryPreference = "veg" | "non_veg" | "both";

export interface TravelParty {
  adults: number;
  children: number;
  child_ages: number[];
  room_setup: string;
}

export interface PinnedStaySpec {
  leg_label: string;
  city: string;
  property_name: string;
  check_in: string;
  check_out: string;
  room_config: string;
}

export interface ActivityPreferences {
  wildlife_safari: boolean;
  adventure_water: boolean;
  moderate_climbs: boolean;
  transit_sightseeing: boolean;
  dietary: DietaryPreference;
  pace: "relaxed" | "balanced" | "explorer";
}

export interface TripSpec {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  departure_time_pref: string;
  return_timing_pref: string;
  transport_mode: TransportMode;
  stay_strategy: StayStrategy;
  vehicle_name: string;
  destination_villa_bhk: number;
  nightly_budget_min_inr: number;
  nightly_budget_max_inr: number;
  party: TravelParty;
  pinned_stays: PinnedStaySpec[];
  activities: ActivityPreferences;
}

export interface ChannelOffer {
  platform: string;
  channel_type: "direct_brand" | "villa_portal" | "airbnb" | "ota";
  base_total_inr: number;
  extra_bed_or_addons_inr: number;
  platform_or_cleaning_fee_inr: number;
  taxes_gst_inr: number;
  promo_discount_inr: number;
  landed_total_inr: number;
  per_night_landed_inr: number;
  inclusions: string[];
  promo_note?: string | null;
  booking_url: string;
  is_best_deal: boolean;
}

export interface StayCandidate {
  id: string;
  name: string;
  subtitle: string;
  category: "hotel" | "villa" | "airbnb" | "bluekite";
  city: string;
  micro_region: string;
  lat: number;
  lng: number;
  rating: number;
  review_count: number;
  bedrooms_label: string;
  check_in: string;
  check_out: string;
  nights: number;
  image_url: string;
  suv_access_note: string;
  kid_fit_note: string;
  highlights: string[];
  offers: ChannelOffer[];
  best_channel: string;
  best_landed_inr: number;
  worst_landed_inr: number;
  savings_inr: number;
  deal_anomaly_score: number;
  anomaly_badge: string;
}

export interface FlightOption {
  id: string;
  carrier: string;
  flight_numbers: string;
  route_label: string;
  gateway_hub_note: string;
  depart_time: string;
  arrive_time: string;
  duration: string;
  stops_label: string;
  landed_family_total_inr: number;
  ota_unoptimized_inr: number;
  savings_inr: number;
  booking_channel: string;
}

export interface RoadSegment {
  id: string;
  day_number: number;
  from_name: string;
  to_name: string;
  highway_label: string;
  distance_km: number;
  duration_mins: number;
  fastag_toll_inr: number;
  fuel_estimate_inr: number;
  gate_alert?: string | null;
  coordinates: number[][];
}

export interface RoadSummary {
  vehicle: string;
  ground_clearance_mm: number;
  total_distance_km: number;
  total_drive_hours: number;
  estimated_fuel_liters: number;
  fuel_cost_inr: number;
  fastag_and_forest_tolls_inr: number;
  rental_car_cost_inr: number;
  total_road_cost_inr: number;
  corridor_notes: string[];
  segments: RoadSegment[];
}

export interface TimelineStop {
  id: string;
  time_window: string;
  title: string;
  location_label: string;
  category: "drive" | "stay" | "climb" | "dining" | "heritage" | "nature" | "flight";
  lat: number;
  lng: number;
  duration_label: string;
  description: string;
  dietary_note?: string | null;
  kid_note?: string | null;
  insider_tip?: string | null;
}

export interface ItineraryDay {
  day_number: number;
  date_label: string;
  weekday: string;
  headline: string;
  corridor_tag: string;
  drive_km: number;
  drive_time_label: string;
  overnight_label: string;
  stops: TimelineStop[];
}

export interface PlatformCoverageNote {
  platform: string;
  status: "matched" | "zero_inventory_pivoted" | "live_scanned";
  listings_scanned: number;
  note: string;
}

export interface ParetoBlueprint {
  id: string;
  rank_badge: string;
  name: string;
  strategy_subtitle: string;
  recommended: boolean;
  total_core_landed_inr: number;
  unoptimized_baseline_inr: number;
  total_arbitrage_savings_inr: number;
  dining_and_activities_est_inr: number;
  fatigue_score: number;
  quality_score: number;
  deal_anomaly_score: number;
  stays: StayCandidate[];
  flights: FlightOption[];
  road: RoadSummary;
  arbitrage_callouts: string[];
  days: ItineraryDay[];
}

export interface ToolCallTrace {
  phase:
    | "Phase 1 · Intent & Constraints"
    | "Phase 2 · Multi-Channel Arbitrage"
    | "Phase 3 · Spatio-Temporal Solver";
  tool_name: string;
  status: "completed" | "pivoted";
  latency_ms: number;
  input_summary: string;
  finding_summary: string;
}

export interface OptimizationResponse {
  trip_spec: TripSpec;
  platform_coverage: PlatformCoverageNote[];
  tool_trace: ToolCallTrace[];
  blueprints: ParetoBlueprint[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  extracted_updates?: string[];
  tool_trace?: ToolCallTrace[];
  follow_up_questions?: string[];
}
