from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent import process_chat_turn
from models import ChatTurnRequest, ChatTurnResponse, OptimizationResponse, TripSpec
from solver.pareto_dag import solve_trip_pareto

app = FastAPI(
    title="TripSage Multi-Modal Arbitrage & Itinerary Engine",
    version="2.0.0",
    description=(
        "Destination-agnostic multi-phase planner and joint spatio-temporal optimizer "
        "powered by Gemini API, Project OSRM highway routing, OpenStreetMap Overpass POIs, "
        "live Blue Kite / hospitality discovery, and cross-channel landed-fee arbitrage."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check() -> dict:
    has_gemini = bool((os.getenv("GEMINI_API_KEY") or "").strip())
    return {
        "status": "ok",
        "version": "2.0.0",
        "engine": "TripSage Generic Spatio-Temporal DAG Solver",
        "llm_planner": (
            f"gemini_live ({os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')})"
            if has_gemini
            else "deterministic_nlp_fallback (set GEMINI_API_KEY in .env to enable Gemini LLM)"
        ),
        "live_providers": [
            "OpenStreetMap Nominatim Geocoder",
            "Project OSRM GeoJSON Highway Router",
            "OpenStreetMap Overpass POI & Hospitality Scanner",
            "The Blue Kite Live Web Scraper",
            "Cross-Channel GST, Extra-Bed & Service-Fee Deduplicator",
            "Multi-Airport Gateway & Virtual-Interline Flight Scorer",
        ],
    }


@app.post("/api/optimize", response_model=OptimizationResponse)
async def run_optimizer(spec: TripSpec) -> OptimizationResponse:
    return await solve_trip_pareto(spec)


@app.post("/api/chat", response_model=ChatTurnResponse)
async def chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    return await process_chat_turn(req)
