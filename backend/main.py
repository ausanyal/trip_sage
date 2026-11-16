from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import process_chat_turn
from currency import get_live_fx_rates
from db import cache_stats, load_trip_snapshot, save_trip_snapshot
from models import (
    ChatTurnRequest,
    ChatTurnResponse,
    OptimizationResponse,
    SavedTripPayload,
    SaveTripRequest,
    TripSpec,
)
from providers.serpapi_live import has_serpapi_key
from solver.pareto_dag import solve_trip_pareto

app = FastAPI(
    title="TripSage World-Class Multi-Modal Arbitrage & VRPTW Engine",
    version="3.0.0",
    description=(
        "Production-grade travel deal arbitrage & spatio-temporal itinerary solver powered by "
        "SerpApi Google Hotels/Vacation Rentals/Flights, Project OSRM N×N matrices, "
        "2-Opt VRPTW scheduling, NSGA-II Strict 3D Pareto Frontier, ECB multi-currency FX, "
        "SSE phase streaming, and SQLite trip persistence."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse_pack(event_name: str, data_obj: object) -> str:
    payload = data_obj if isinstance(data_obj, str) else json.dumps(data_obj, ensure_ascii=False)
    return f"event: {event_name}\ndata: {payload}\n\n"


@app.get("/api/health")
async def health_check() -> dict:
    has_gemini = bool((os.getenv("GEMINI_API_KEY") or "").strip())
    serp_live = has_serpapi_key()
    return {
        "status": "ok",
        "version": "3.0.0",
        "engine": "TripSage NSGA-II 3D Pareto + 2-Opt VRPTW Engine",
        "llm_planner": (
            f"gemini_live ({os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')})"
            if has_gemini
            else "deterministic_nlp_fallback (set GEMINI_API_KEY in .env to enable Gemini LLM)"
        ),
        "pricing_provenance_mode": (
            "live_verified_serpapi"
            if serp_live
            else "transparent_market_benchmark (set SERPAPI_API_KEY in .env for live OTA checkout quotes)"
        ),
        "sqlite_persistence": cache_stats(),
        "live_providers": [
            "SerpApi Google Hotels, Vacation Rentals & Google Flights (when SERPAPI_API_KEY set)",
            "OpenStreetMap Nominatim Geocoder + Wikimedia Commons Real Photo Resolver",
            "Project OSRM GeoJSON Highway Router + /table/v1/driving/ N×N Matrix",
            "OpenStreetMap Overpass POI & Opening-Hours Scanner",
            "The Blue Kite Live Web & JSON-LD Scraper",
            "K-Medoids Clustering + 2-Opt VRPTW Time-Windowed Solver",
            "NSGA-II Non-Dominated 3D Pareto Frontier + Crowding Distance",
            "European Central Bank Live FX (INR / USD / EUR / GBP)",
        ],
    }


@app.get("/api/fx")
async def get_fx_rates() -> Dict[str, object]:
    rates, source = await get_live_fx_rates()
    return {"base": "INR", "rates": rates, "source": source}


@app.post("/api/optimize", response_model=OptimizationResponse)
async def run_optimizer(spec: TripSpec) -> OptimizationResponse:
    return await solve_trip_pareto(spec)


@app.post("/api/optimize/stream")
async def run_optimizer_stream(spec: TripSpec) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def emit_phase(phase: str, detail: str) -> None:
        await queue.put(_sse_pack("phase", {"phase": phase, "detail": detail}))

    async def worker() -> None:
        try:
            result = await solve_trip_pareto(spec, on_phase=emit_phase)
            await queue.put(_sse_pack("complete", result.model_dump()))
        except Exception as exc:
            await queue.put(_sse_pack("error", {"message": str(exc)}))
        finally:
            await queue.put("__EOF__")

    async def event_generator() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(worker())
        try:
            while True:
                chunk = await queue.get()
                if chunk == "__EOF__":
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat", response_model=ChatTurnResponse)
async def chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    return await process_chat_turn(req)


@app.post("/api/chat/stream")
async def chat_turn_stream(req: ChatTurnRequest) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def emit_phase(phase: str, detail: str) -> None:
        await queue.put(_sse_pack("phase", {"phase": phase, "detail": detail}))

    async def worker() -> None:
        try:
            result = await process_chat_turn(req, on_phase=emit_phase)
            await queue.put(_sse_pack("complete", result.model_dump()))
        except Exception as exc:
            await queue.put(_sse_pack("error", {"message": str(exc)}))
        finally:
            await queue.put("__EOF__")

    async def event_generator() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(worker())
        try:
            while True:
                chunk = await queue.get()
                if chunk == "__EOF__":
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/trips")
async def persist_trip(req: SaveTripRequest) -> Dict[str, str]:
    tid = save_trip_snapshot(
        spec_dict=req.spec.model_dump(),
        optimization_dict=req.optimization.model_dump(),
        messages_list=req.messages,
        trip_id=req.trip_id,
    )
    return {"trip_id": tid, "share_path": f"/?trip={tid}"}


@app.get("/api/trips/{trip_id}", response_model=SavedTripPayload)
async def get_persisted_trip(trip_id: str) -> SavedTripPayload:
    loaded = load_trip_snapshot(trip_id)
    if not loaded:
        raise HTTPException(status_code=404, detail=f"Saved trip '{trip_id}' not found.")
    return SavedTripPayload.model_validate(loaded)
