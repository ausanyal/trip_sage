from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from currency import format_amount_from_inr, infer_currency_from_countries
from db import cache_get_json, cache_set_json, load_trip_snapshot, save_trip_snapshot
from main import chat_turn_stream, get_persisted_trip, health_check, persist_trip, run_optimizer_stream
from models import (
    ChatTurnRequest,
    ParetoBlueprint,
    RoadSummary,
    SaveTripRequest,
    TravelParty,
    TripSpec,
)
from providers.geo_routing import DiscoveredPOI, GeoLocation
from providers.serpapi_live import search_serpapi_stays
from solver.pareto_dag import solve_trip_pareto
from solver.vrptw import (
    cluster_pois_kmedoids,
    solve_daily_vrptw_2opt,
    strict_pareto_rank_and_filter,
)


def _dummy_road() -> RoadSummary:
    return RoadSummary(
        vehicle="SUV",
        ground_clearance_mm=200,
        total_distance_km=320.0,
        total_drive_hours=6.5,
        estimated_fuel_liters=25.0,
        fuel_cost_inr=2400,
        fastag_and_forest_tolls_inr=450,
        total_road_cost_inr=2850,
    )


class TestTripSageV3Engine(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        os.environ["TRIPSAGE_DB_PATH"] = str(Path(self._tmp_dir.name) / "test_tripsage.db")

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()
        os.environ.pop("TRIPSAGE_DB_PATH", None)
        os.environ.pop("SERPAPI_API_KEY", None)

    def test_strict_nsga2_pareto_dominance_and_knee(self) -> None:
        # 3 Front-1 points + 1 strictly dominated point
        b_knee = ParetoBlueprint(
            id="c1",
            rank_badge="",
            name="Balanced Knee Villa",
            strategy_subtitle="",
            total_core_landed_inr=82000,
            unoptimized_baseline_inr=94000,
            total_arbitrage_savings_inr=12000,
            dining_and_activities_est_inr=12000,
            fatigue_score=24,
            quality_score=95,
            deal_anomaly_score=94.0,
            road=_dummy_road(),
        )
        b_cheap = ParetoBlueprint(
            id="c2",
            rank_badge="",
            name="Min-Cost Chalet",
            strategy_subtitle="",
            total_core_landed_inr=69000,
            unoptimized_baseline_inr=76000,
            total_arbitrage_savings_inr=7000,
            dining_and_activities_est_inr=12000,
            fatigue_score=34,
            quality_score=87,
            deal_anomaly_score=88.0,
            road=_dummy_road(),
        )
        b_luxury = ParetoBlueprint(
            id="c3",
            rank_badge="",
            name="Peak-Comfort Estate",
            strategy_subtitle="",
            total_core_landed_inr=99000,
            unoptimized_baseline_inr=116000,
            total_arbitrage_savings_inr=17000,
            dining_and_activities_est_inr=12000,
            fatigue_score=18,
            quality_score=98,
            deal_anomaly_score=96.0,
            road=_dummy_road(),
        )
        b_dominated = ParetoBlueprint(
            id="c4",
            rank_badge="",
            name="Strictly Dominated Tourist Trap",
            strategy_subtitle="",
            total_core_landed_inr=108000,  # worse than b_knee & b_luxury
            unoptimized_baseline_inr=110000,
            total_arbitrage_savings_inr=2000,
            dining_and_activities_est_inr=12000,
            fatigue_score=48,  # worse
            quality_score=82,  # worse
            deal_anomaly_score=79.0,  # worse
            road=_dummy_road(),
        )

        ranked = strict_pareto_rank_and_filter([b_dominated, b_cheap, b_luxury, b_knee])
        self.assertEqual(len(ranked), 3)
        names = [b.name for b in ranked]
        self.assertNotIn("Strictly Dominated Tourist Trap", names)
        self.assertTrue(all(b.pareto_front_rank == 1 for b in ranked))
        self.assertTrue(ranked[0].recommended)
        self.assertIn("Pareto Knee", ranked[0].rank_badge)

    def test_2opt_vrptw_respects_meal_and_climb_time_windows(self) -> None:
        pois = [
            DiscoveredPOI(
                id="p-climb",
                name="Chembra Ridge Trail",
                category="climb",
                lat=11.54,
                lng=76.08,
                cuisine_or_tag="Peak",
                description="Morning climb",
                opening_hours_raw="08:00-16:00",
            ),
            DiscoveredPOI(
                id="p-her",
                name="Wayanad Heritage Museum",
                category="heritage",
                lat=11.61,
                lng=76.19,
                cuisine_or_tag="Museum",
                description="Afternoon museum",
                opening_hours_raw="10:00-17:30",
            ),
            DiscoveredPOI(
                id="p-din",
                name="1980s Nostalgic Kitchen",
                category="dining",
                lat=11.57,
                lng=76.12,
                cuisine_or_tag="Kerala Sadya",
                description="Lunch stop",
                opening_hours_raw="12:00-22:00",
            ),
        ]
        node_map = {"p-climb": 1, "p-her": 2, "p-din": 3}
        dur_m = [
            [0.0, 22.0, 38.0, 26.0],
            [22.0, 0.0, 34.0, 18.0],
            [38.0, 34.0, 0.0, 19.0],
            [26.0, 18.0, 19.0, 0.0],
        ]
        dist_m = [
            [0.0, 12.0, 24.0, 15.0],
            [12.0, 0.0, 21.0, 10.0],
            [24.0, 21.0, 0.0, 11.0],
            [15.0, 10.0, 11.0, 0.0],
        ]
        clusters = cluster_pois_kmedoids(pois[:2], k_days=1, dist_lookup=lambda a, b: 10.0)
        self.assertEqual(len(clusters), 1)

        used_rests: set[str] = set()
        stops, loop_km, loop_mins, coords = solve_daily_vrptw_2opt(
            day_num=3,
            city_short="Wayanad",
            depot_lat=11.55,
            depot_lng=76.05,
            day_excursions=pois[:2],
            restaurants=[pois[2]],
            pace="balanced",
            node_index_map=node_map,
            dur_matrix=dur_m,
            dist_matrix=dist_m,
            used_restaurant_ids=used_rests,
        )
        self.assertEqual(len(stops), 3)
        # Climb should run first in the morning, followed by lunch around midday, then afternoon museum
        self.assertEqual(stops[0].category, "climb")
        self.assertIn("AM", stops[0].time_window)
        dining_stop = next(s for s in stops if s.category == "dining")
        self.assertIn("PM", dining_stop.time_window)
        self.assertGreater(loop_km, 30.0)
        self.assertGreaterEqual(len(coords), 5)

    def test_sqlite_cache_and_trip_permalink_roundtrip(self) -> None:
        cache_set_json("unit:key:1", "unittest", {"hello": "world"}, ttl_seconds=120)
        self.assertEqual(cache_get_json("unit:key:1"), {"hello": "world"})

        spec = TripSpec(
            origin="Bengaluru",
            destination="Coorg",
            start_date="2026-12-20",
            end_date="2026-12-23",
        )
        tid = save_trip_snapshot(
            spec_dict=spec.model_dump(),
            optimization_dict={"blueprints": [], "trip_spec": spec.model_dump()},
            messages_list=[{"role": "user", "content": "Test trip"}],
        )
        self.assertTrue(tid.startswith("ts-"))
        loaded = load_trip_snapshot(tid)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["spec"]["destination"], "Coorg")
        self.assertEqual(len(loaded["messages"]), 1)

    def test_currency_inference_and_formatting(self) -> None:
        self.assertEqual(infer_currency_from_countries("in", "in"), "INR")
        self.assertEqual(infer_currency_from_countries("in", "ae"), "INR")
        self.assertEqual(infer_currency_from_countries("us", "gb"), "GBP")
        self.assertEqual(infer_currency_from_countries("us", "fr"), "EUR")
        self.assertEqual(infer_currency_from_countries("us", "jp"), "USD")
        self.assertEqual(infer_currency_from_countries("in", "in", "USD"), "USD")

        fx = {"INR": 1.0, "USD": 0.012, "EUR": 0.011, "GBP": 0.0095}
        self.assertEqual(format_amount_from_inr(100000, "INR", fx), "₹100,000")
        self.assertEqual(format_amount_from_inr(100000, "USD", fx), "$1,200")

    async def test_serpapi_live_hotel_adapter_parsing(self) -> None:
        os.environ["SERPAPI_API_KEY"] = "mock-serp-key"
        fake_serp_payload = {
            "properties": [
                {
                    "name": "Radisson Blu Plaza Hotel Mysore",
                    "gps_coordinates": {"latitude": 12.2971, "longitude": 76.6644},
                    "overall_rating": 4.6,
                    "reviews": 4120,
                    "images": [{"original_image": "https://example.com/radisson-real.jpg"}],
                    "prices": [
                        {
                            "source": "Booking.com",
                            "link": "https://booking.com/radisson-mysore",
                            "total_rate": {"extracted_lowest": 14800, "extracted_before_taxes_fees": 12540},
                        },
                        {
                            "source": "Radisson Official Site",
                            "link": "https://radissonhotels.com/mysore",
                            "total_rate": {"extracted_lowest": 12900, "extracted_before_taxes_fees": 10930},
                        },
                    ],
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_serp_payload

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)

        with patch("providers.serpapi_live.httpx.AsyncClient", return_value=mock_client):
            stays = await search_serpapi_stays(
                loc=GeoLocation("Mysuru", "Mysuru", "Mysuru, India", 12.2958, 76.6394, "in"),
                check_in="2026-12-21",
                check_out="2026-12-22",
                party=TravelParty(adults=2, children=2, child_ages=[8, 10]),
                bhk=1,
                vacation_rentals=False,
                vehicle_name="Jeep Meridian SUV",
                property_query="Radisson Mysore",
            )

        self.assertEqual(len(stays), 1)
        st = stays[0]
        self.assertEqual(st.price_provenance, "live_verified")
        self.assertEqual(st.best_channel, "Radisson Official Site")
        self.assertEqual(st.best_landed_inr, 12900)
        self.assertEqual(st.savings_inr, 1900)
        self.assertEqual(st.image_url, "https://example.com/radisson-real.jpg")

    async def test_sse_streaming_and_trip_persistence_endpoints(self) -> None:
        health = await health_check()
        self.assertEqual(health["version"], "3.0.0")

        spec = TripSpec(
            origin="Mumbai",
            destination="Lonavala",
            start_date="2026-12-18",
            end_date="2026-12-21",
            transport_mode="road",
            stay_strategy="villas",
            destination_villa_bhk=3,
        )
        sse_resp = await run_optimizer_stream(spec)
        chunks: list[str] = []
        async for ch in sse_resp.body_iterator:
            chunks.append(ch if isinstance(ch, str) else ch.decode("utf-8"))

        joined = "".join(chunks)
        self.assertIn("event: phase", joined)
        self.assertIn("event: complete", joined)

        complete_line = [
            line[len("data: ") :]
            for block in joined.split("\n\n")
            if "event: complete" in block
            for line in block.splitlines()
            if line.startswith("data: ")
        ][0]
        opt_json = json.loads(complete_line)
        self.assertTrue(opt_json["trip_id"].startswith("ts-"))
        self.assertGreaterEqual(len(opt_json["blueprints"]), 2)

        # Verify persisted trip retrieval endpoint
        restored = await get_persisted_trip(opt_json["trip_id"])
        self.assertEqual(restored.spec.destination, "Lonavala")

        # Verify SSE chat stream endpoint
        chat_sse = await chat_turn_stream(
            ChatTurnRequest(
                message="Switch to USD currency and pure veg dietary",
                current_spec=spec,
                history=[],
            )
        )
        chat_chunks: list[str] = []
        async for ch in chat_sse.body_iterator:
            chat_chunks.append(ch if isinstance(ch, str) else ch.decode("utf-8"))
        chat_joined = "".join(chat_chunks)
        self.assertIn("event: phase", chat_joined)
        self.assertIn("event: complete", chat_joined)
        self.assertIn("Pure Veg", chat_joined)


if __name__ == "__main__":
    unittest.main()
