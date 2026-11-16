# TripSage v3.0 — Multi-Modal Travel Arbitrage & Operations-Research Engine

TripSage is a **public-launch-ready, destination-agnostic** conversational travel planner, cross-channel stay & flight arbitrage scanner, and operations-research itinerary optimizer for **Pure Road Trips**, **Fly + Stay**, and **Hybrid (Fly + Drive)** journeys worldwide (with India-first statutory GST, highway toll/fuel physics, and boutique villa connectors).

## Key Capabilities (v3.0)

### 1. Live Multi-Channel Arbitrage & Radical Price Provenance
- **Live OTA & Flight Quotes (`backend/providers/serpapi_live.py`):** Queries **SerpApi** (`SERPAPI_API_KEY`) for real-time **Google Hotels**, **Vacation Rentals** (`vacation_rentals=true`), and **Google Flights** multi-gateway quotes with actual property photos and booking deep links.
- **Live Boutique Villa & Direct Scrapers (`backend/providers/stays_arbitrage.py`):** Scrapes `thebluekite.com` (`JSON-LD` + tariff DOM extraction + gallery imagery), queries **OSM Overpass** hospitality properties, fetches real property/landmark photography via **Wikimedia Commons**, deduplicates properties across channels via Haversine + token-Jaccard entity resolution, and computes **true landed cost** (statutory `12%/18%` GST slabs, platform service/cleaning fees, extra-bed/child supplements, and Dec 24/31 resort gala surcharges).
- **Explicit Price Provenance Badges:** Every stay and flight option carries an explicit provenance classification (`live_serpapi` -> **Live Verified Quote**, `live_scraped` -> **Live Scraped Tariff**, or `calibrated_benchmark` -> **Benchmark Estimate** when `SERPAPI_API_KEY` is unset) — never disguising estimated rates as live quotes.

### 2. True Operations-Research Solver (`backend/solver/`)
- **Asymmetric `N×N` OSRM Matrix (`vrptw.py`):** Queries Project OSRM `/table/v1/driving/` for real road travel-time and distance matrices across anchors, POIs, and dining stops.
- **PAM K-Medoids + 2-Opt VRPTW Daily Tour Optimizer (`vrptw.py`):** Partitions POIs across active sightseeing days via K-Medoids clustering and solves **Time-Windowed Vehicle Routing (`VRPTW`)** with 2-Opt local search respecting OSM `opening_hours`, `[12:15, 14:45]` regional lunch windows, `21:00–06:00` forest checkpost curfews, and `<= 210 min` continuous family driving caps.
- **Strict NSGA-II 3D Pareto Frontier (`vrptw.py` & `pareto_dag.py`):** Evaluates candidate itinerary combinations across `(Total Landed Cost, Drive-Minute Fatigue, Experience Utility)`, computes non-dominated Pareto Front 1 ranks + Crowding Distance, and selects the mathematically optimal **Utopia Knee** alongside Budget/Pace/Signature alternatives.

### 3. Interactive `EPSG:3857` Slippy Map & Modern Web UI (`frontend/src/`)
- **Web Mercator (`EPSG:3857`) Slippy Map (`RouteCorridorMap.tsx`):** Retina `@2x` street/terrain tiles (`CARTO Dark Matter` in dark mode, `CARTO Voyager` in light mode, plus offline vector grid fallback), pointer drag-to-pan, wheel zoom, `+` / `-` / `Fit Bounds` / `Layers` controls, automatic day-corridor zoom (`D1`–`D6`), OSRM highway polylines, and currency-aware stay & POI pins.
- **SSE Live Phase Streaming (`POST /api/optimize/stream`, `POST /api/chat/stream`):** Streams real-time solver phase telemetry (`Phase 1` Geocoding & Highway Physics -> `Phase 2` Multi-Channel Stay/Flight Arbitrage -> `Phase 3` OSRM `N×N` VRPTW & NSGA-II Frontier) directly into the conversational copilot.
- **Global + India-First Multi-Currency (`backend/currency.py`):** Live ECB exchange rates (`api.frankfurter.app`, SQLite-cached) with instant `₹ INR`, `$ USD`, `€ EUR`, and `£ GBP` switching (`Intl.NumberFormat`) and automatic origin/destination currency detection.
- **SQLite Trip Persistence & Shareable Permalinks (`backend/db.py`):** Persists solved itineraries in WAL-mode SQLite (`POST /api/trips`, `GET /api/trips/{trip_id}`) with instant `/?trip=ts-<id>` URL hydration, upstream HTTP TTL caching, async provider rate-limiting, and accessible Top-Layer `popover="manual"` share notifications.

## Quick Start

```bash
cp .env.example .env
# Optional in .env:
#   GEMINI_API_KEY=...    # Enables Gemini 2.5 Flash conversational tool-calling planner
#   SERPAPI_API_KEY=...   # Enables live Google Hotels, Vacation Rentals & Google Flights quotes
./start.sh
```

- **Web App:** http://localhost:3000
- **FastAPI OpenAPI Docs:** http://127.0.0.1:8000/docs
- **Health & Cache Telemetry:** http://127.0.0.1:8000/api/health

## Running Automated Tests & Production Build

```bash
# Backend unit + async SSE integration suite
./backend/.venv/bin/python -m unittest discover -s backend/tests -v

# Frontend TypeScript & Next.js production build
./frontend/node_modules/.bin/next build frontend
```
