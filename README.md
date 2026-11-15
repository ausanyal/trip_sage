# TripSage — Multi-Modal Travel Arbitrage & Itinerary Engine

TripSage is a conversational multi-phase planner and joint spatio-temporal optimizer for **Road Trips**, **Fly + Stay**, and **Hybrid (Fly + Drive)** itineraries across **Hotels & Resorts**, **Airbnb**, **The Blue Kite**, **StayVista**, **SaffronStays**, and major **Airline / OTA** channels.

## Preloaded Showcase
Out of the box, TripSage boots into the **Koramangala (Bengaluru) → Radisson Blu Plaza Mysore → Wayanad (2 BHK Villa) → Radisson Mysore → Koramangala (Dec 21–26, 2026)** family road trip (`2 Adults + Kids 8 & 10 · Jeep Meridian SUV`), plus a 1-click switcher for **Goa Hybrid Fly + Drive + The Blue Kite Direct Villa Arbitrage**.

## Architecture
- **Backend (`/backend`):** Python FastAPI (`models.py`, `catalog.py`, `optimizer.py`, `main.py`) implementing the 3-Phase Tool-Calling Planner (`POST /api/chat`), Joint Spatio-Temporal Pareto Solver (`POST /api/optimize`), Cross-Channel Entity Deduplication, and Highway/Forest-Gate Telemetry.
- **Frontend (`/frontend`):** Next.js 14 + TypeScript + Modern CSS Design System (`light-dark()`, `@container` size-aware queries, native `<dialog closedby="any">` top-layer discrete animations, IME-safe conversational planner, and Geo-Projected Interactive Corridor Map).

## Quick Start
```bash
./start.sh
```
- **Web App:** http://localhost:3000
- **FastAPI Docs:** http://127.0.0.1:8000/docs
