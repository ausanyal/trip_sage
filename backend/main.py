from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from catalog import build_goa_hybrid_bluekite_preset, default_wayanad_trip_spec
from models import ChatTurnRequest, ChatTurnResponse, OptimizationResponse, TripSpec
from optimizer import optimize_generic_scenario, optimize_wayanad_scenario, process_chat_turn

app = FastAPI(
    title="TripSage Multi-Modal Arbitrage & Itinerary Engine",
    version="1.0.0",
    description="Joint spatio-temporal travel optimizer across Flights, Self-Drive/Rental Cars, Hotels, Airbnb, and The Blue Kite.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "engine": "TripSage Joint Spatio-Temporal DAG Solver v1.0",
        "channels": [
            "Airbnb",
            "The Blue Kite",
            "StayVista",
            "SaffronStays",
            "Radisson Direct",
            "MakeMyTrip",
            "Agoda",
            "Booking.com",
            "IndiGo / Air India / Akasa Virtual Interline",
        ],
    }


@app.get("/api/presets/wayanad", response_model=OptimizationResponse)
def get_wayanad_preset() -> OptimizationResponse:
    spec = default_wayanad_trip_spec()
    return optimize_wayanad_scenario(spec)


@app.get("/api/presets/goa-hybrid", response_model=OptimizationResponse)
def get_goa_hybrid_preset() -> OptimizationResponse:
    spec, cov, traces, bps = build_goa_hybrid_bluekite_preset()
    return OptimizationResponse(
        trip_spec=spec,
        platform_coverage=cov,
        tool_trace=traces,
        blueprints=bps,
    )


@app.post("/api/optimize", response_model=OptimizationResponse)
def run_optimizer(spec: TripSpec) -> OptimizationResponse:
    return optimize_generic_scenario(spec)


@app.post("/api/chat", response_model=ChatTurnResponse)
def chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    return process_chat_turn(req)
