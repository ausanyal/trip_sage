from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

from models import (
    ChatTurnRequest,
    ChatTurnResponse,
    ToolCallTrace,
    TripSpec,
)
from solver.pareto_dag import solve_trip_pareto

# Load .env from workspace root or backend directory
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_ROOT_ENV)
load_dotenv(_LOCAL_ENV)


GEMINI_SYSTEM_PROMPT = """You are TripSage, an expert multi-modal travel deal arbitrage & itinerary planner.
Given the current structured `TripSpec` JSON, conversation history, and the user's new message, return ONLY a valid JSON object matching this exact structure:
{
  "updated_spec": { ...full valid TripSpec object... },
  "extracted_updates": ["Concise Field -> New Value", ...],
  "needs_clarification": false,
  "follow_up_questions": ["Optional clarifying question 1", ...],
  "assistant_preface": "1-2 concise sentences acknowledging their request or changes."
}

Rules:
1. Preserve all fields from `current_spec` that the user did NOT ask to change.
2. If the user switches to a brand-new `destination`, reset `pinned_stays` to `[]` unless the user explicitly mentions transit stops for the new trip.
3. `transport_mode` MUST be one of: "road", "flight", "hybrid".
4. `stay_strategy` MUST be one of: "hotels", "villas", "hybrid".
5. `activities.dietary` MUST be one of: "veg", "non_veg", "both".
6. `activities.pace` MUST be one of: "relaxed", "balanced", "explorer".
7. Dates (`start_date`, `end_date`, `check_in`, `check_out`) MUST be ISO `YYYY-MM-DD`.
8. Set `needs_clarification` to true (with 2-4 crisp questions) ONLY when the user starts a brand-new trip with underspecified transport mode, stay preference, or party/budget.
"""


async def _call_gemini_spec_extractor(
    req: ChatTurnRequest, api_key: str, model_name: str
) -> Optional[Tuple[TripSpec, List[str], bool, List[str], str, int]]:
    t0 = time.perf_counter()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    history_lines = [f"{m.role.upper()}: {m.content}" for m in req.history[-6:]]
    user_payload = (
        f"CURRENT_TRIP_SPEC_JSON:\n{req.current_spec.model_dump_json(indent=2)}\n\n"
        f"RECENT_CONVERSATION:\n" + ("\n".join(history_lines) if history_lines else "(start)") + "\n\n"
        f"LATEST_USER_MESSAGE:\n{req.message}"
    )

    body: Dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=body,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            if not text:
                return None
            parsed = json.loads(text)
            updated_spec = TripSpec.model_validate(parsed["updated_spec"])
            updates = [str(x) for x in (parsed.get("extracted_updates") or [])]
            needs_clar = bool(parsed.get("needs_clarification", False))
            questions = [str(q) for q in (parsed.get("follow_up_questions") or [])]
            preface = str(parsed.get("assistant_preface") or "").strip()
            elapsed_ms = max(40, int(round((time.perf_counter() - t0) * 1000)))
            return updated_spec, updates, needs_clar, questions, preface, elapsed_ms
    except Exception:
        return None


def _clean_place_phrase(raw: str) -> str:
    cleaned = re.split(
        r"\b(?:from|on|between|for|with|in\s+dec|in\s+jan|staying|via|prefer|driving|and\s+we)\b",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = cleaned.strip(" .,;:-")
    return " ".join(w.capitalize() if w.islower() else w for w in cleaned.split())


def _deterministic_nlp_extract(req: ChatTurnRequest) -> Tuple[TripSpec, List[str], bool]:
    """Destination-agnostic fallback extractor used when GEMINI_API_KEY is not configured."""
    msg = req.message.strip()
    lower = msg.lower()
    spec = req.current_spec.model_copy(deep=True)
    updates: List[str] = []
    dest_switched = False

    # 1. Generic "from <Origin> to <Destination>" or "trip to / go to / visit <Destination>"
    from_to = re.search(
        r"\bfrom\s+([A-Za-z][A-Za-z\s,]{1,35}?)\s+to\s+([A-Za-z][A-Za-z\s,]{2,35})",
        msg,
        flags=re.IGNORECASE,
    )
    if from_to:
        cand_orig = _clean_place_phrase(from_to.group(1))
        cand_dest = _clean_place_phrase(from_to.group(2))
        if len(cand_orig) >= 3 and len(cand_dest) >= 3 and not cand_orig.isdigit():
            if cand_orig.lower() != spec.origin.lower():
                spec.origin = cand_orig
                updates.append(f"Origin -> {cand_orig}")
            if cand_dest.lower() not in spec.destination.lower():
                spec.destination = cand_dest
                spec.pinned_stays = []
                dest_switched = True
                updates.append(f"Destination -> {cand_dest}")
    else:
        to_match = re.search(
            r"\b(?:trip\s+to|go\s+to|visit|travel\s+to|plan\s+for|switch\s+destination\s+to)\s+([A-Za-z][A-Za-z\s,]{2,32})",
            msg,
            flags=re.IGNORECASE,
        )
        if to_match:
            cand_dest = _clean_place_phrase(to_match.group(1))
            if len(cand_dest) >= 3 and cand_dest.lower() not in spec.destination.lower():
                spec.destination = cand_dest
                spec.pinned_stays = []
                dest_switched = True
                updates.append(f"Destination -> {cand_dest}")

    # 2. Generic Date Range ("YYYY-MM-DD to YYYY-MM-DD" or "MM/DD to MM/DD")
    iso_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", msg)
    if len(iso_dates) >= 2:
        spec.start_date, spec.end_date = iso_dates[0], iso_dates[1]
        updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
    else:
        slash_dates = re.findall(r"\b(\d{1,2})/(\d{1,2})\b", msg)
        if len(slash_dates) >= 2:
            yr = dt.date.today().year
            try:
                d1 = dt.date(yr, int(slash_dates[0][0]), int(slash_dates[0][1]))
                d2 = dt.date(yr, int(slash_dates[1][0]), int(slash_dates[1][1]))
                spec.start_date, spec.end_date = d1.isoformat(), d2.isoformat()
                updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
            except ValueError:
                pass

    # 3. Transport Mode
    if any(p in lower for p in ["fly + drive", "fly and drive", "hybrid", "rent a car", "fly somewhere and"]):
        if "hybrid stay" not in lower:
            spec.transport_mode = "hybrid"
            updates.append("Transport Mode -> Hybrid (Fly + Drive)")
    elif any(p in lower for p in ["flight only", "fly + stay", "flights only"]):
        spec.transport_mode = "flight"
        updates.append("Transport Mode -> Fly + Stay")
    elif any(p in lower for p in ["road trip", "own car", "pure road", "drive from"]):
        spec.transport_mode = "road"
        updates.append("Transport Mode -> Pure Road Trip")

    # 4. Stay Strategy
    if any(p in lower for p in ["hotels only", "only hotel", "switch to hotel", "resorts only"]):
        spec.stay_strategy = "hotels"
        updates.append("Stay Strategy -> Hotels & Resorts Only")
    elif any(p in lower for p in ["villas only", "only airbnb", "blue kite", "bluekite", "prefer villa"]):
        spec.stay_strategy = "villas"
        updates.append("Stay Strategy -> Villas (Airbnb / The Blue Kite)")
    elif "hybrid stay" in lower:
        spec.stay_strategy = "hybrid"
        updates.append("Stay Strategy -> Hybrid Stays")

    # 5. Party composition ("2 adults", "2 kids", "ages 8 and 10")
    ad_m = re.search(r"(\d+)\s*adults?", lower)
    if ad_m:
        spec.party.adults = max(1, int(ad_m.group(1)))
        updates.append(f"Adults -> {spec.party.adults}")
    ch_m = re.search(r"(\d+)\s*(?:kids?|children)", lower)
    if ch_m:
        spec.party.children = max(0, int(ch_m.group(1)))
        updates.append(f"Children -> {spec.party.children}")
    ages_m = re.search(r"ages?\s*(?:of\s*)?(\d{1,2})(?:\s*(?:,|and|&)\s*(\d{1,2}))?", lower)
    if ages_m:
        ages = [int(ages_m.group(1))]
        if ages_m.group(2):
            ages.append(int(ages_m.group(2)))
        spec.party.child_ages = ages

    # 6. Villa BHK & Nightly Budget
    bhk_m = re.search(r"(\d)\s*(?:bhk|br|bedroom)", lower)
    if bhk_m:
        spec.destination_villa_bhk = max(1, min(6, int(bhk_m.group(1))))
        updates.append(f"Villa Size -> {spec.destination_villa_bhk} BHK")

    rng_m = re.search(r"(\d{1,3})\s*(?:k|000)?\s*(?:-|to)\s*(\d{1,3})\s*k", lower)
    if rng_m:
        lo_k, hi_k = int(rng_m.group(1)), int(rng_m.group(2))
        spec.nightly_budget_min_inr = lo_k * 1000
        spec.nightly_budget_max_inr = hi_k * 1000
        updates.append(f"Nightly Budget -> ₹{lo_k}k–₹{hi_k}k")
    else:
        cap_m = re.search(r"(?:under|within|below|max)\s*₹?\s*(\d{1,3})\s*k", lower)
        if cap_m:
            hi_k = int(cap_m.group(1))
            spec.nightly_budget_min_inr = max(5000, int(hi_k * 700))
            spec.nightly_budget_max_inr = hi_k * 1000
            updates.append(f"Nightly Budget -> up to ₹{hi_k}k")

    # 7. Vehicle
    veh_m = re.search(
        r"(?:driving\s+(?:a|an|our)?|vehicle\s+is|car\s+is)\s+([A-Za-z0-9][A-Za-z0-9\s-]{2,26})",
        msg,
        flags=re.IGNORECASE,
    )
    if veh_m:
        v_clean = veh_m.group(1).strip(" .,;")
        spec.vehicle_name = v_clean
        updates.append(f"Vehicle -> {v_clean}")

    # 8. Activity & Dietary Toggles
    if any(p in lower for p in ["turn on wildlife", "add safari", "include safari", "enable safari", "with safari"]):
        spec.activities.wildlife_safari = True
        updates.append("Wildlife Safari -> ON")
    elif any(p in lower for p in ["no safari", "skip safari", "without safari", "turn off safari"]):
        spec.activities.wildlife_safari = False
        updates.append("Wildlife Safari -> OFF")

    if any(p in lower for p in ["add water", "enable adventure", "include zipline", "water sports"]):
        spec.activities.adventure_water = True
        updates.append("Adventure & Water -> ON")
    elif any(p in lower for p in ["no water", "no adventure", "skip water"]):
        spec.activities.adventure_water = False
        updates.append("Adventure & Water -> OFF")

    if any(p in lower for p in ["no climb", "skip climb", "no trek", "avoid climb"]):
        spec.activities.moderate_climbs = False
        updates.append("Moderate Climbs -> OFF")
    elif any(p in lower for p in ["add climb", "moderate climb", "include hike", "include trek"]):
        spec.activities.moderate_climbs = True
        updates.append("Moderate Climbs -> ON")

    if "pure veg" in lower or "veg only" in lower or "vegetarian only" in lower:
        spec.activities.dietary = "veg"
        updates.append("Dietary -> Pure Veg")
    elif "veg and non" in lower or "both veg" in lower or "non-veg" in lower:
        spec.activities.dietary = "both"
        updates.append("Dietary -> Veg + Non-Veg")

    needs_clar = dest_switched and not any(
        w in lower for w in ["road", "fly", "flight", "hybrid", "hotel", "villa", "airbnb", "bhk"]
    )
    return spec, updates, needs_clar


async def process_chat_turn(req: ChatTurnRequest) -> ChatTurnResponse:
    """Multi-Phase Conversational Planner: Gemini API primary + deterministic NLP fallback."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    gemini_result = None
    if api_key:
        gemini_result = await _call_gemini_spec_extractor(req, api_key, model_name)

    if gemini_result is not None:
        updated_spec, updates, needs_clar, questions, preface, llm_ms = gemini_result
        opt = await solve_trip_pareto(updated_spec)
        opt.tool_trace.insert(
            0,
            ToolCallTrace(
                phase="Phase 1 · Intent & Constraints",
                tool_name=f"gemini_planner_extract ({model_name})",
                latency_ms=llm_ms,
                input_summary=req.message[:90],
                finding_summary=", ".join(updates) if updates else "Confirmed conversational intent & constraints.",
            ),
        )
        top_bp = opt.blueprints[0]
        reply = (
            f"{preface + ' ' if preface else ''}"
            f"Solved **{len(opt.blueprints)} Pareto blueprints** for **{updated_spec.origin} -> {updated_spec.destination}** — "
            f"top pick **{top_bp.name}** lands at **₹{top_bp.total_core_landed_inr:,}** core all-in "
            f"(saving **₹{top_bp.total_arbitrage_savings_inr:,}** via cross-channel arbitrage)."
        )
        return ChatTurnResponse(
            updated_spec=updated_spec,
            assistant_reply=reply,
            extracted_updates=updates or ["Gemini Spec Synced"],
            needs_clarification=needs_clar,
            follow_up_questions=questions,
            optimization=opt,
        )

    # Zero-key fallback: deterministic destination-agnostic NLP + live OSRM/OSM/BlueKite Pareto solver
    updated_spec, updates, needs_clar = _deterministic_nlp_extract(req)
    opt = await solve_trip_pareto(updated_spec)
    top_bp = opt.blueprints[0]

    if needs_clar:
        questions = [
            f"For **{updated_spec.destination}**, do you prefer a **Pure Road Trip**, **Fly + Stay**, or **Hybrid (Fly + Rental Car)**?",
            "Should we focus on **Hotels & Resorts**, **Villas (Airbnb / The Blue Kite)**, or **Hybrid Stays**?",
            "What dates, party size, and nightly budget band should we lock in?",
        ]
        reply = (
            f"Initialized a live route & arbitrage blueprint for **{updated_spec.origin} -> {updated_spec.destination}** "
            f"(currently **₹{top_bp.total_core_landed_inr:,}** core all-in). Confirm any of these to refine:"
        )
        return ChatTurnResponse(
            updated_spec=updated_spec,
            assistant_reply=reply,
            extracted_updates=updates or ["Draft Route Initialized"],
            needs_clarification=True,
            follow_up_questions=questions,
            optimization=opt,
        )

    change_note = (
        f"Applied updates ({', '.join(updates)}) and re-solved the live corridor & channel rates. "
        if updates
        else "Re-verified live routing, POIs, and cross-channel checkout math. "
    )
    reply = (
        f"{change_note}Top recommendation: **{top_bp.name}** at **₹{top_bp.total_core_landed_inr:,}** core all-in "
        f"(saving **₹{top_bp.total_arbitrage_savings_inr:,}** across channels)."
    )
    return ChatTurnResponse(
        updated_spec=updated_spec,
        assistant_reply=reply,
        extracted_updates=updates or ["Live Corridor & Channel Re-Scan"],
        needs_clarification=False,
        follow_up_questions=[],
        optimization=opt,
    )
