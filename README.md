# TripSage — Multi-Modal Travel Arbitrage & Itinerary Engine

TripSage is a **destination-agnostic**, conversational multi-phase travel planner and joint spatio-temporal optimizer for **Pure Road Trips**, **Fly + Stay**, and **Hybrid (Fly + Drive)** itineraries across **Hotels & Resorts**, **Airbnb**, **The Blue Kite**, **StayVista**, **SaffronStays**, and **Airline / OTA** channels.

## Architecture (v2.0 Generic Engine)

- **Backend (`/backend` — Python FastAPI):**
  - `agent.py` — Multi-phase conversational planner powered by **Gemini API** (`GEMINI_API_KEY` in `.env`, defaulting to `gemini-2.5-flash`) with a zero-key deterministic NLP fallback.
  - `providers/geo_routing.py` — Live **OpenStreetMap Nominatim** geocoding, **Project OSRM** GeoJSON highway geometry & road-number routing, vehicle-specific fuel/toll physics, and **OSM Overpass** POI & regional dining discovery.
  - `providers/stays_arbitrage.py` — Live **The Blue Kite** (`thebluekite.com`) destination & villa scraper, OSM hospitality discovery, Haversine + token-Jaccard **cross-channel entity deduplication**, and statutory GST (`12%/18%`), child/extra-bed, Dec 24/31 resort gala, and platform-fee landed math.
  - `providers/flights_arbitrage.py` — Nearest & secondary **gateway airport arbitrage** (joint airfare + last-mile ground transfer optimization).
  - `solver/pareto_dag.py` — Generic multi-waypoint calendar partitioner, compass-sector daily POI clustering, and **Pareto frontier solver** (`POST /api/optimize`, `POST /api/chat`).
- **Frontend (`/frontend` — Next.js 14 + TypeScript):**
  - Split conversational agent + interactive geo-projected SVG corridor map, bi-directional `TripSpec` drawer, native `<dialog closedby="any">` landed-fee breakdown modal, and declarative initial showcase data (`frontend/src/data/presets.json`).

## Quick Start

```bash
cp .env.example .env   # Optional: add GEMINI_API_KEY=... for LLM conversational planning
./start.sh
```

- **Web App:** http://localhost:3000
- **FastAPI Docs:** http://127.0.0.1:8000/docs
