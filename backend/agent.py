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

from currency import format_amount_from_inr
from db import save_trip_snapshot
from models import (
    ChatTurnRequest,
    ChatTurnResponse,
    PinnedStaySpec,
    ToolCallTrace,
    TripSpec,
)
from solver.pareto_dag import PhaseEmitter, solve_trip_pareto

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
2. If the user switches to a brand-new `destination`, reset `pinned_stays` to `[]` BEFORE extracting any new transit/stopover stays mentioned in the new message, and set `currency` to `null` unless explicitly specified.
3. Whenever the user mentions an en-route / transit hotel or stopover city (e.g., "stay at Radisson, Mysore on 12/21 and again on 12/25"), populate `updated_spec.pinned_stays` with `PinnedStaySpec` entries (`leg_label`, `city`, `property_name`, `check_in`, `check_out` = check_in + 1 day, `room_config`).
4. If `pinned_stays` has transit hotels AND the destination prefers Airbnb/villas, `stay_strategy` MUST be `"hybrid"`. Otherwise `"hotels"`, `"villas"`, or `"hybrid"`.
5. `transport_mode` MUST be one of: `"road"`, `"flight"`, `"hybrid"`.
6. `activities.dietary` MUST be one of: `"veg"`, `"non_veg"`, `"both"`.
7. `activities.pace` MUST be one of: `"relaxed"`, `"balanced"`, `"explorer"`.
8. `currency` MUST be one of: `"INR"`, `"USD"`, `"EUR"`, `"GBP"`, or `null`.
9. Dates (`start_date`, `end_date`, `check_in`, `check_out`) MUST be ISO `YYYY-MM-DD`.
10. If the user explicitly asks you to ask clarifying questions OR starts a new trip with missing specifics (e.g., car model, exact room setup, BHK/budget ceiling, kid activity preferences, departure time), set `needs_clarification` to `true` and return 3-5 tailored travel-agent questions in `follow_up_questions`.
11. If the user asks to see MORE, SIMILAR, OTHER, or ALTERNATIVE places/villas/hotels to stay (so they have more options to choose from), increase `stay_options_limit` from `3` to `6` (or if already `>= 6`, increment `stay_pool_offset` by `3` to load a fresh batch of properties) without resetting `pinned_stays`.
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
    # Strip leading verbal connectors (e.g. "intend to go to Wayanad" -> "Wayanad")
    stripped = re.sub(
        r"^(?:and\s+)?(?:we\s+)?(?:also\s+)?(?:intend\s+to\s+|want\s+to\s+|would\s+like\s+to\s+|"
        r"plan\s+to\s+|planning\s+to\s+|going\s+to\s+)?(?:go\s+to|visit|travel\s+to|head\s+to|reach|explore)\s+",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.split(
        r"\b(?:from|on|between|for|with|within|under|around|staying|via|prefer|driving|flying|using|leaving|starting|"
        r"in\s+(?:a|an|the|my|our|\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        r"hotel|hotels|villa|villas|airbnb|resort|resorts|boutique|private|luxury|budget|usd|inr|eur|gbp)|"
        r"and\s+(?:we|one|on|our|stay|return|fly|drive|prefer|intend|want|would))\b",
        stripped,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(
        r"\s+\b(?:in|on|at|for|with|by|a|an|the|to)$",
        "",
        cleaned.strip(" .,;:-"),
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip(" .,;:-")
    return " ".join(w.capitalize() if w.islower() else w for w in cleaned.split())


def _parse_date_token(token: str, default_year: int) -> Optional[dt.date]:
    token = token.strip()
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", token):
        try:
            return dt.date.fromisoformat(token)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?$", token)
    if m:
        yr = int(m.group(3)) if m.group(3) else default_year
        try:
            return dt.date(yr, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _extract_pinned_stays_from_text(
    msg: str, spec: TripSpec, updates: List[str]
) -> None:
    """Extracts outbound & return en-route transit hotel anchors or conversational stopover requests."""
    try:
        d_start = dt.date.fromisoformat(spec.start_date)
        d_end = dt.date.fromisoformat(spec.end_date)
    except ValueError:
        d_start = dt.date.today() + dt.timedelta(days=14)
        d_end = d_start + dt.timedelta(days=5)

    ref_year = d_start.year
    mid_date = d_start + dt.timedelta(days=max(1, (d_end - d_start).days // 2))

    # Pattern 1: Explicit "stay at/in <Property>, <City> on <Date>" (supports multiple occurrences)
    stay_pattern = re.compile(
        r"\bstay\s+(?:at|in)\s+([A-Za-z0-9'&.\s-]{2,36}?)(?:\s*,\s*|\s+in\s+)([A-Za-z][A-Za-z\s.-]{2,24}?)\s+on\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?)\b",
        flags=re.IGNORECASE,
    )
    found_explicit: List[PinnedStaySpec] = []
    for m in stay_pattern.finditer(msg):
        raw_prop = " ".join(w.capitalize() if w.islower() else w for w in m.group(1).strip(" .,;-").split())
        raw_city = _clean_place_phrase(m.group(2))
        d_in = _parse_date_token(m.group(3), ref_year)
        if not raw_city or not d_in:
            continue
        # Avoid treating primary destination itself as a transit stopover
        if raw_city.lower() in spec.destination.lower():
            continue
        prop_display = raw_prop if raw_city.lower() in raw_prop.lower() else f"{raw_prop} {raw_city}"
        is_outbound = d_in < mid_date
        found_explicit.append(
            PinnedStaySpec(
                leg_label="Outbound Transit Anchor" if is_outbound else "Return Transit Anchor",
                city=raw_city,
                property_name=prop_display,
                check_in=d_in.isoformat(),
                check_out=(d_in + dt.timedelta(days=1)).isoformat(),
                room_config=spec.party.room_setup
                if "Room" in spec.party.room_setup
                else ("Deluxe Room + Extra Bed" if spec.party.children > 0 else "Deluxe Double Room"),
            )
        )

    # Check if user also says "on our way back ... again stay in this/same hotel on <Date>"
    if len(found_explicit) == 1:
        repeat_m = re.search(
            r"\b(?:on(?:e)?\s+our\s+way\s+back|way\s+back|return(?:ing)?\s+leg|again\s+stay|stay\s+again)\b[^.\n]{0,95}?\bon\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?)\b",
            msg,
            flags=re.IGNORECASE,
        )
        if repeat_m:
            d_ret = _parse_date_token(repeat_m.group(1), ref_year)
            first_pin = found_explicit[0]
            if d_ret and d_ret.isoformat() != first_pin.check_in:
                found_explicit.append(
                    PinnedStaySpec(
                        leg_label="Return Transit Anchor",
                        city=first_pin.city,
                        property_name=first_pin.property_name,
                        check_in=d_ret.isoformat(),
                        check_out=(d_ret + dt.timedelta(days=1)).isoformat(),
                        room_config=first_pin.room_config,
                    )
                )

    if found_explicit:
        spec.pinned_stays = found_explicit
        summary_dates = " & ".join(p.check_in for p in found_explicit)
        updates.append(f"Transit Stays -> {found_explicit[0].property_name} ({summary_dates})")
        return

    # Pattern 2: Conversational stopover follow-up ("i dont see mysore as a stop", "add mysore stop", "stop in pune on the way")
    stop_followup = re.search(
        r"(?:don'?t\s+see|missing|include|add|stop\s+(?:at|in)|overnight\s+(?:at|in))\s+([A-Za-z][A-Za-z\s]{2,22}?)\s+(?:as\s+a\s+stop|stop|on\s+the\s+way|in\s+the\s+plan|en\s*route)",
        msg,
        flags=re.IGNORECASE,
    )
    if stop_followup:
        stop_city = _clean_place_phrase(stop_followup.group(1))
        if (
            len(stop_city) >= 3
            and stop_city.lower() not in spec.destination.lower()
            and not any(stop_city.lower() == p.city.lower() for p in spec.pinned_stays)
        ):
            room_cfg = "Deluxe Room + Extra Bed" if spec.party.children > 0 else "Deluxe Double Room"
            new_pins = [
                PinnedStaySpec(
                    leg_label="Outbound Transit Anchor",
                    city=stop_city,
                    property_name=f"Upscale Highway Hotel {stop_city}",
                    check_in=d_start.isoformat(),
                    check_out=(d_start + dt.timedelta(days=1)).isoformat(),
                    room_config=room_cfg,
                )
            ]
            if (d_end - d_start).days >= 4:
                ret_in = d_end - dt.timedelta(days=1)
                new_pins.append(
                    PinnedStaySpec(
                        leg_label="Return Transit Anchor",
                        city=stop_city,
                        property_name=f"Upscale Highway Hotel {stop_city}",
                        check_in=ret_in.isoformat(),
                        check_out=d_end.isoformat(),
                        room_config=room_cfg,
                    )
                )
            spec.pinned_stays = new_pins
            if spec.stay_strategy == "villas":
                spec.stay_strategy = "hybrid"
            updates.append(f"Added Stopover -> {stop_city} ({'Outbound & Return' if len(new_pins) > 1 else 'Outbound'})")


def _build_contextual_questions(
    msg: str, spec: TripSpec, dest_switched: bool
) -> List[str]:
    """Generates dynamic, travel-agent-grade clarifying questions for missing trip specifics."""
    lower = msg.lower()
    user_asked_for_questions = any(
        p in lower
        for p in [
            "ask questions",
            "ask any question",
            "questions if any",
            "let me know what you need",
            "anything else you need",
        ]
    )

    if not dest_switched and not user_asked_for_questions:
        return []

    questions: List[str] = []
    dest_short = spec.destination.split(",")[0].strip()
    orig_short = spec.origin.split(",")[0].strip()

    # 1. Transit hotel room setup if pinned stays exist and room config wasn't explicitly specified
    if spec.pinned_stays and not any(
        w in lower for w in ["deluxe", "extra bed", "rollaway", "interconnecting", "2 rooms", "two rooms", "suite"]
    ):
        pin0 = spec.pinned_stays[0]
        pin_dates = " & ".join(p.check_in[5:] for p in spec.pinned_stays)
        questions.append(
            f"**{pin0.property_name} Room Setup ({pin_dates}):** With {spec.party.adults} adults"
            + (f" + {spec.party.children} kids" if spec.party.children else "")
            + ", do you prefer **1 Deluxe Room + Extra Bed** (best value) or **2 Interconnecting Rooms**?"
        )

    # 2. Destination Villa BHK & nightly budget ceiling if not explicitly given
    has_explicit_budget = bool(re.search(r"\d+\s*(?:k|000)\b", lower))
    has_explicit_bhk = bool(re.search(r"\b\d\s*(?:bhk|br|bedroom)\b", lower))
    if spec.stay_strategy in ("villas", "hybrid") and (not has_explicit_bhk or not has_explicit_budget):
        questions.append(
            f"**{dest_short} Villa Size & Budget:** Would you prefer a **2 BHK** or **3 BHK** private villa/Airbnb in {dest_short}, and what nightly budget range should I target (e.g., ₹15k–₹20k or ₹20k–₹30k/night)?"
        )

    # 3. Specific Car / SUV Model if road/hybrid and still generic
    known_car_named = any(
        k in lower
        for k in [
            "meridian", "fortuner", "innova", "hycross", "crysta", "xuv", "safari",
            "compass", "creta", "seltos", "scorpio", "thar", "nexon", "virtus", "city", "tesla",
        ]
    )
    if spec.transport_mode == "road" and not known_car_named:
        questions.append(
            "**Which Car Are You Driving?** Sharing your car/SUV model lets me calibrate exact highway fuel burn, FASTag tolls, and steep estate-road ground clearance."
        )

    # 4. Activity preferences if not specified
    if not any(w in lower for w in ["safari", "climb", "trek", "zipline", "water sport"]):
        stop_city_q = f" or sightseeing detours in **{spec.pinned_stays[0].city}**" if spec.pinned_stays else ""
        questions.append(
            f"**Activity Pacing & Interests:** Should I include or skip **(a) Wildlife Safaris**, **(b) Adventure / Water Activities**, **(c) Moderate Scenic Climbs**{stop_city_q}?"
        )

    # 5. Rollout & return timing if not specified
    if not re.search(r"\b\d{1,2}\s*(?:am|pm)\b", lower) and "after lunch" not in lower and "morning" not in lower:
        questions.append(
            f"**Departure & Return Windows:** What time do you like rolling out from **{orig_short}** on {spec.start_date}, and when do you prefer starting your return legs?"
        )

    # Fallback core mode/stay questions if a terse 1-line destination prompt was given
    if not questions and not any(w in lower for w in ["road", "fly", "flight", "hybrid", "hotel", "villa", "airbnb"]):
        questions = [
            f"For **{dest_short}**, do you prefer a **Pure Road Trip**, **Fly + Stay**, or **Hybrid (Fly + Rental Car)**?",
            "Should we focus on **Hotels & Resorts**, **Villas (Airbnb / The Blue Kite)**, or **Hybrid Stays**?",
            "What dates, party size, and nightly budget band should we lock in?",
        ]

    return questions[:5]


def _deterministic_nlp_extract(
    req: ChatTurnRequest,
) -> Tuple[TripSpec, List[str], List[str]]:
    """Destination-agnostic multi-clause & multi-turn extractor used when GEMINI_API_KEY is not configured."""
    msg = req.message.strip()
    lower = msg.lower()
    spec = req.current_spec.model_copy(deep=True)
    updates: List[str] = []
    dest_switched = False

    # 1. Multi-clause "traveling/driving from <Origin> ... go to / visit / to <Destination>"
    multi_from_to = re.search(
        r"\b(?:travel(?:l)?ing|driving|flying|going|starting|leaving|trip|journey)\s+from\s+([A-Za-z][A-Za-z\s,.-]{1,42}?)\s+"
        r"(?:and\s+(?:[A-Za-z']+\s+){0,6}?(?:go\s+to|visit|travel\s+to|head\s+to|reach)|to)\s+([A-Za-z][A-Za-z0-9\s,.-]{2,48})",
        msg,
        flags=re.IGNORECASE,
    )
    simple_from_to = (
        None
        if multi_from_to
        else re.search(
            r"(?<!back\s)(?<!return\s)(?<!returning\s)\bfrom\s+([A-Za-z][A-Za-z\s,.-]{1,38}?)\s+to\s+([A-Za-z][A-Za-z0-9\s,.-]{2,48})",
            msg,
            flags=re.IGNORECASE,
        )
    )
    chosen_ft = multi_from_to or simple_from_to

    if chosen_ft:
        cand_orig = _clean_place_phrase(chosen_ft.group(1))
        cand_dest = _clean_place_phrase(chosen_ft.group(2))
        is_return_leg_mention = (
            cand_dest.lower() in spec.origin.lower()
            and cand_orig.lower() != spec.origin.lower()
        )
        if (
            not is_return_leg_mention
            and len(cand_orig) >= 3
            and len(cand_dest) >= 3
            and not cand_orig.isdigit()
        ):
            if cand_orig.lower() != spec.origin.lower():
                spec.origin = cand_orig
                updates.append(f"Origin -> {cand_orig}")
            if cand_dest.lower().split(",")[0].strip() != spec.destination.lower().split(",")[0].strip():
                spec.destination = cand_dest
                spec.pinned_stays = []
                spec.stay_options_limit = 3
                spec.stay_pool_offset = 0
                spec.currency = None
                dest_switched = True
                updates.append(f"Destination -> {cand_dest}")
    else:
        to_match = re.search(
            r"\b(?:trip\s+to|intend\s+to\s+go\s+to|go\s+to|visit|travel\s+to|plan\s+for|switch\s+destination\s+to)\s+([A-Za-z][A-Za-z0-9\s,.-]{2,44})",
            msg,
            flags=re.IGNORECASE,
        )
        if to_match:
            cand_dest = _clean_place_phrase(to_match.group(1))
            if (
                len(cand_dest) >= 3
                and cand_dest.lower().split(",")[0].strip() != spec.destination.lower().split(",")[0].strip()
            ):
                spec.destination = cand_dest
                spec.pinned_stays = []
                spec.stay_options_limit = 3
                spec.stay_pool_offset = 0
                spec.currency = None
                dest_switched = True
                updates.append(f"Destination -> {cand_dest}")

    # 2. Generic Date Range ("from MM/DD to MM/DD" or "YYYY-MM-DD to YYYY-MM-DD")
    yr = dt.date.today().year
    explicit_range = re.search(
        r"\bfrom\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?)\s+to\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?)\b",
        msg,
        flags=re.IGNORECASE,
    )
    if explicit_range:
        d1 = _parse_date_token(explicit_range.group(1), yr)
        d2 = _parse_date_token(explicit_range.group(2), yr)
        if d1 and d2 and d2 > d1:
            spec.start_date, spec.end_date = d1.isoformat(), d2.isoformat()
            updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
    else:
        iso_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", msg)
        if len(iso_dates) >= 2:
            spec.start_date, spec.end_date = min(iso_dates), max(iso_dates)
            updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
        else:
            slash_tokens = re.findall(r"\b(\d{1,2}/\d{1,2}(?:/20\d{2})?)\b", msg)
            parsed_slash = [d for tok in slash_tokens if (d := _parse_date_token(tok, yr)) is not None]
            if len(parsed_slash) >= 2:
                d_lo, d_hi = min(parsed_slash), max(parsed_slash)
                if d_hi > d_lo:
                    spec.start_date, spec.end_date = d_lo.isoformat(), d_hi.isoformat()
                    updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")

    # 3. Party composition & Room setup (run BEFORE pinned stays so child count informs transit room config)
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

    if "deluxe room" in lower and "extra bed" in lower:
        spec.party.room_setup = "Deluxe Room + Extra Bed"
        for p in spec.pinned_stays:
            p.room_config = "Deluxe Room + Extra Bed"
        updates.append("Transit Room -> Deluxe Room + Extra Bed")
    elif "interconnecting" in lower or "2 rooms" in lower or "two rooms" in lower:
        spec.party.room_setup = "2 Interconnecting Rooms"
        for p in spec.pinned_stays:
            p.room_config = "2 Interconnecting Rooms"
        updates.append("Transit Room -> 2 Interconnecting Rooms")

    # 4. Extract Pinned Transit Stays & En-Route Stopovers ("stay at Radisson, Mysore on 12/21 ... again on 12/25")
    _extract_pinned_stays_from_text(msg, spec, updates)

    # 5. Currency preference
    if any(w in lower for w in ["in usd", "to usd", "us dollars"]):
        spec.currency = "USD"
        updates.append("Currency -> USD")
    elif any(w in lower for w in ["in eur", "to eur", "in euros"]):
        spec.currency = "EUR"
        updates.append("Currency -> EUR")
    elif any(w in lower for w in ["in gbp", "to gbp", "in pounds"]):
        spec.currency = "GBP"
        updates.append("Currency -> GBP")
    elif any(w in lower for w in ["in inr", "to inr", "in rupees"]):
        spec.currency = "INR"
        updates.append("Currency -> INR")

    # 6. Transport Mode
    if any(p in lower for p in ["fly + drive", "fly and drive", "rent a car", "fly somewhere and"]):
        spec.transport_mode = "hybrid"
        updates.append("Transport Mode -> Hybrid (Fly + Drive)")
    elif "hybrid" in lower and "hybrid stay" not in lower and "road trip" not in lower:
        spec.transport_mode = "hybrid"
        updates.append("Transport Mode -> Hybrid (Fly + Drive)")
    elif any(p in lower for p in ["flight only", "fly + stay", "flights only"]):
        spec.transport_mode = "flight"
        updates.append("Transport Mode -> Fly + Stay")
    elif any(p in lower for p in ["road trip", "own car", "pure road", "drive from"]):
        spec.transport_mode = "road"
        updates.append("Transport Mode -> Pure Road Trip")

    # 7. Stay Strategy (couples transit hotel anchors + destination villa/Airbnb into `"hybrid"`)
    wants_dest_villa = any(
        p in lower
        for p in [
            "prefer airbnb",
            "airbnb vs hotel",
            "airbnb over hotel",
            "villas only",
            "only airbnb",
            "blue kite",
            "bluekite",
            "prefer villa",
            "bhk",
        ]
    )
    if any(p in lower for p in ["hotels only", "only hotel", "switch to hotel", "resorts only"]):
        spec.stay_strategy = "hotels"
        updates.append("Stay Strategy -> Hotels & Resorts Only")
    elif "hybrid stay" in lower or (spec.pinned_stays and wants_dest_villa):
        spec.stay_strategy = "hybrid"
        updates.append("Stay Strategy -> Hybrid (Transit Hotel + Destination Villa)")
    elif wants_dest_villa and not spec.pinned_stays:
        spec.stay_strategy = "villas"
        updates.append("Stay Strategy -> Villas (Airbnb / The Blue Kite)")

    # 8. Villa BHK & Nightly Budget
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
        elif any(p in lower for p in ["high end", "high-end", "luxury", "premium stay"]):
            spec.nightly_budget_min_inr = 15000
            spec.nightly_budget_max_inr = 22000
            updates.append("Stay Tier -> High-End (₹15k–₹22k/N)")

    # 9. Vehicle Model (supports both "driving a <Car>" and numbered answers like "3. Jeep Meridian SUV")
    known_car_m = re.search(
        r"\b((?:jeep\s+meridian|toyota\s+fortuner|fortuner|innova\s+hycross|innova\s+crysta|innova|"
        r"mahindra\s+xuv\d*|xuv\s*700|tata\s+safari|safari|jeep\s+compass|hyundai\s+creta|creta|"
        r"kia\s+seltos|seltos|mahindra\s+scorpio|scorpio\s*n?|mahindra\s+thar|thar|nexon\s*ev|tesla\s+model\s*[3ysx])"
        r"(?:\s+suv|\s+4x4|\s+awd)?)\b",
        msg,
        flags=re.IGNORECASE,
    )
    veh_m = re.search(
        r"(?:driving\s+(?:a|an|our)?|vehicle\s+is|car\s+is)\s+([A-Za-z0-9][A-Za-z0-9\s-]{2,26})",
        msg,
        flags=re.IGNORECASE,
    )
    if known_car_m:
        v_clean = " ".join(w.upper() if w.lower() in ("suv", "ev", "awd", "4x4") else w.capitalize() for w in known_car_m.group(1).split())
        spec.vehicle_name = v_clean
        updates.append(f"Vehicle -> {v_clean}")
    elif veh_m:
        v_clean = veh_m.group(1).strip(" .,;")
        spec.vehicle_name = v_clean
        updates.append(f"Vehicle -> {v_clean}")
    elif "own car" in lower and spec.vehicle_name in ("Self-Drive SUV", "Airport Private Transfer SUV"):
        spec.vehicle_name = "Family SUV (Own Car)"

    # 10. Departure & Return Timing Preferences
    dep_time_m = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", lower)
    if dep_time_m:
        t_lbl = dep_time_m.group(1).upper().replace("AM", " AM").replace("PM", " PM")
        t_lbl = " ".join(t_lbl.split())
        spec.departure_time_pref = f"{t_lbl} Rollout"
        updates.append(f"Departure -> {t_lbl}")

    if "early afternoon" in lower and "after lunch" in lower:
        spec.return_timing_pref = "Early Afternoon / Post-Lunch"
        updates.append("Return Legs -> Early Afternoon & Post-Lunch")
    elif "after lunch" in lower or "post-lunch" in lower:
        spec.return_timing_pref = "Post-Lunch Return"
        updates.append("Return Timing -> Post-Lunch")
    elif "early afternoon" in lower:
        spec.return_timing_pref = "Early Afternoon Return"
        updates.append("Return Timing -> Early Afternoon")

    # 11. Activity & Dietary Toggles (supports both prose and structured "Safari: No / Climbs: Yes")
    safari_yn = re.search(r"safari[a-z\s]*[:=-]\s*(yes|no)\b", lower)
    if safari_yn:
        spec.activities.wildlife_safari = safari_yn.group(1) == "yes"
        updates.append(f"Wildlife Safari -> {'ON' if spec.activities.wildlife_safari else 'OFF'}")
    elif any(p in lower for p in ["turn on wildlife", "add safari", "include safari", "enable safari", "with safari"]):
        spec.activities.wildlife_safari = True
        updates.append("Wildlife Safari -> ON")
    elif any(p in lower for p in ["no safari", "skip safari", "without safari", "turn off safari"]):
        spec.activities.wildlife_safari = False
        updates.append("Wildlife Safari -> OFF")

    water_yn = re.search(r"(?:adventure|water)[a-z\s&]*[:=-]\s*(yes|no)\b", lower)
    if water_yn:
        spec.activities.adventure_water = water_yn.group(1) == "yes"
        updates.append(f"Adventure & Water -> {'ON' if spec.activities.adventure_water else 'OFF'}")
    elif any(p in lower for p in ["add water", "enable adventure", "include zipline", "water sports"]):
        spec.activities.adventure_water = True
        updates.append("Adventure & Water -> ON")
    elif any(p in lower for p in ["no water", "no adventure", "skip water"]):
        spec.activities.adventure_water = False
        updates.append("Adventure & Water -> OFF")

    climb_yn = re.search(r"climbs?[a-z\s]*[:=-]\s*(yes|no)\b", lower)
    if climb_yn:
        spec.activities.moderate_climbs = climb_yn.group(1) == "yes"
        updates.append(f"Moderate Climbs -> {'ON' if spec.activities.moderate_climbs else 'OFF'}")
    elif any(p in lower for p in ["no climb", "skip climb", "no trek", "avoid climb"]):
        spec.activities.moderate_climbs = False
        updates.append("Moderate Climbs -> OFF")
    elif any(p in lower for p in ["add climb", "moderate climb", "include hike", "include trek"]):
        spec.activities.moderate_climbs = True
        updates.append("Moderate Climbs -> ON")

    transit_stop_yn = re.search(r"(?:stops?|stopovers?)\s*[:=-]\s*(yes|no)\b", lower)
    if transit_stop_yn:
        spec.activities.transit_sightseeing = transit_stop_yn.group(1) == "yes"
        updates.append(f"Transit Detours -> {'ON' if spec.activities.transit_sightseeing else 'OFF'}")

    if "pure veg" in lower or "veg only" in lower or "vegetarian only" in lower:
        spec.activities.dietary = "veg"
        updates.append("Dietary -> Pure Veg")
    elif "veg and non" in lower or "both veg" in lower or "non-veg" in lower:
        spec.activities.dietary = "both"
        updates.append("Dietary -> Veg + Non-Veg")

    # 12. Expand or Rotate Destination Stay Options ("search more similar places to stay", "more options to choose from")
    wants_more_stays = bool(
        re.search(
            r"\b(?:more\s+(?:similar\s+)?(?:places|stays|options|villas|hotels|resorts|airbnbs|properties|homes)|"
            r"similar\s+(?:places|stays|villas|hotels|resorts|options|properties)|"
            r"(?:other|another|different|additional|extra|alternative)\s+(?:places|stays|options|villas|hotels|resorts|airbnbs|choices|batch)|"
            r"more\s+options\s+to\s+choose)\b",
            lower,
        )
    )
    if wants_more_stays:
        if (spec.stay_options_limit or 3) < 6:
            spec.stay_options_limit = 6
            updates.append("Stay Pool -> Expanded to 6 Comparable Stays")
        else:
            spec.stay_pool_offset = (spec.stay_pool_offset or 0) + 3
            spec.stay_options_limit = 6
            updates.append(f"Stay Pool -> Next Comparable Batch (Offset +{spec.stay_pool_offset})")

    questions = _build_contextual_questions(msg, spec, dest_switched)
    return spec, updates, questions


def _format_stay_comparison_shortlist(opt: Any) -> str:
    dest_short = opt.trip_spec.destination.split(",")[0].strip()
    outbound_cnt = sum(
        1
        for p in opt.trip_spec.pinned_stays
        if p.check_in < opt.trip_spec.end_date and "Outbound" in p.leg_label
    )
    lines: List[str] = []
    for idx_bp, bp in enumerate(opt.blueprints, start=1):
        d_stay = next(
            (s for s in bp.stays if s.city.lower() == dest_short.lower()),
            bp.stays[min(outbound_cnt, max(0, len(bp.stays) - 1))],
        )
        per_night = format_amount_from_inr(
            d_stay.best_landed_inr // max(1, d_stay.nights),
            opt.active_currency,
            opt.fx_rates,
        )
        trip_tot = format_amount_from_inr(
            bp.total_core_landed_inr, opt.active_currency, opt.fx_rates
        )
        sav_str = (
            f" · Saves {format_amount_from_inr(d_stay.savings_inr, opt.active_currency, opt.fx_rates)}"
            if d_stay.savings_inr > 0
            else ""
        )
        lines.append(
            f"{idx_bp}. **{d_stay.name}** ({d_stay.best_channel}) — **{per_night}/night** landed · Full trip **{trip_tot}**{sav_str}"
        )
    return "\n".join(lines)


async def process_chat_turn(
    req: ChatTurnRequest,
    on_phase: Optional[PhaseEmitter] = None,
) -> ChatTurnResponse:
    """Multi-Phase Conversational Planner: Gemini API primary + deterministic NLP fallback + SSE hooks."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    if on_phase:
        await on_phase(
            "Phase 1 · Intent & Constraints",
            "Extracting structured trip intent, transit anchors, party constraints & currency...",
        )

    gemini_result = None
    if api_key:
        gemini_result = await _call_gemini_spec_extractor(req, api_key, model_name)

    if gemini_result is not None:
        updated_spec, updates, needs_clar, questions, preface, llm_ms = gemini_result
        if updated_spec.destination.strip().lower() != req.current_spec.destination.strip().lower():
            if not re.search(r"\b(inr|usd|eur|gbp|rupees?|dollars?|euros?|pounds?)\b|[₹$€£]", req.message, re.I):
                updated_spec.currency = None
        if updated_spec.pinned_stays and updated_spec.stay_strategy == "villas":
            updated_spec.stay_strategy = "hybrid"
        opt = await solve_trip_pareto(updated_spec, on_phase=on_phase, persist_snapshot=False)
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
        fmt_core = format_amount_from_inr(top_bp.total_core_landed_inr, opt.active_currency, opt.fx_rates)
        fmt_save = format_amount_from_inr(top_bp.total_arbitrage_savings_inr, opt.active_currency, opt.fx_rates)
        expanded_pool = (
            updated_spec.stay_options_limit > req.current_spec.stay_options_limit
            or updated_spec.stay_pool_offset != req.current_spec.stay_pool_offset
        )
        if expanded_pool:
            shortlist = _format_stay_comparison_shortlist(opt)
            dest_short = opt.trip_spec.destination.split(",")[0].strip()
            reply = (
                f"{preface + ' ' if preface else ''}"
                f"Expanded your **{dest_short}** stay search to **{len(opt.blueprints)} comparable options** "
                f"(all priced all-in and solved with your route):\n\n{shortlist}\n\n"
                f"All **{len(opt.blueprints)} Pareto cards** are now live on the right — click any card to switch your itinerary & map, "
                f"or ask *\"show another batch of stays\"* to scan deeper!"
            )
        else:
            reply = (
                f"{preface + ' ' if preface else ''}"
                f"Solved **{len(opt.blueprints)} non-dominated Pareto blueprints** for **{opt.trip_spec.origin} -> {opt.trip_spec.destination}** — "
                f"Pareto Knee **{top_bp.name}** lands at **{fmt_core}** core all-in "
                f"(saving **{fmt_save}** via cross-channel arbitrage)."
            )
        if questions:
            reply += "\n\nTo fine-tune this draft itinerary, let me know your preferences on:"
        transcript = [m.model_dump() for m in req.history] + [
            {"role": "user", "content": req.message},
            {
                "role": "assistant",
                "content": reply,
                "extracted_updates": updates,
                "follow_up_questions": questions,
            },
        ]
        opt.trip_id = save_trip_snapshot(opt.trip_spec.model_dump(), opt.model_dump(), transcript)
        return ChatTurnResponse(
            updated_spec=opt.trip_spec,
            assistant_reply=reply,
            extracted_updates=updates or ["Gemini Spec Synced"],
            needs_clarification=needs_clar or bool(questions),
            follow_up_questions=questions,
            optimization=opt,
        )

    # Zero-key fallback: deterministic multi-clause NLP + live OSRM/OSM/BlueKite/VRPTW Pareto solver
    updated_spec, updates, questions = _deterministic_nlp_extract(req)
    opt = await solve_trip_pareto(updated_spec, on_phase=on_phase, persist_snapshot=False)
    top_bp = opt.blueprints[0]
    fmt_core = format_amount_from_inr(top_bp.total_core_landed_inr, opt.active_currency, opt.fx_rates)
    fmt_save = format_amount_from_inr(top_bp.total_arbitrage_savings_inr, opt.active_currency, opt.fx_rates)

    transit_summary = ""
    if opt.trip_spec.pinned_stays:
        uniq_stops = list(dict.fromkeys(f"{p.property_name} ({p.check_in})" for p in opt.trip_spec.pinned_stays))
        transit_summary = f" Anchored transit stopovers at **{', '.join(uniq_stops)}**."

    expanded_pool = (
        updated_spec.stay_options_limit > req.current_spec.stay_options_limit
        or updated_spec.stay_pool_offset != req.current_spec.stay_pool_offset
    )

    if expanded_pool:
        dest_short = opt.trip_spec.destination.split(",")[0].strip()
        shortlist = _format_stay_comparison_shortlist(opt)
        reply = (
            f"Expanded your **{dest_short}** stay search to **{len(opt.blueprints)} comparable options** "
            f"(each solved end-to-end with your route{',' + transit_summary.rstrip('.') if transit_summary else ''}):\n\n"
            f"{shortlist}\n\n"
            f"All **{len(opt.blueprints)} Pareto cards** are now live on the right — click any card (or open **Cross-Channel Stay Arbitrage**) "
            f"to switch your itinerary & map to that stay, or ask *\"show more stay options\"* again to load another fresh batch!"
        )
    elif questions:
        reply = (
            f"Mapped an initial **{len(opt.blueprints)}-blueprint Pareto & VRPTW plan** for "
            f"**{opt.trip_spec.origin} -> {opt.trip_spec.destination}** (**{fmt_core}** core all-in, saving **{fmt_save}** across channels)."
            f"{transit_summary}\n\nTo tailor the final rooms, villa budget, and daily kid-friendly pacing, let me know:"
        )
    else:
        change_note = (
            f"Locked updates ({', '.join(updates)}) and re-solved the N×N VRPTW matrix & Pareto frontier.{transit_summary} "
            if updates
            else f"Re-verified live routing, 2-Opt VRPTW time windows, and cross-channel checkout math.{transit_summary} "
        )
        reply = (
            f"{change_note}Pareto Knee: **{top_bp.name}** at **{fmt_core}** core all-in "
            f"(saving **{fmt_save}** across channels)."
        )

    transcript = [m.model_dump() for m in req.history] + [
        {"role": "user", "content": req.message},
        {
            "role": "assistant",
            "content": reply,
            "extracted_updates": updates,
            "follow_up_questions": questions,
        },
    ]
    opt.trip_id = save_trip_snapshot(opt.trip_spec.model_dump(), opt.model_dump(), transcript)

    return ChatTurnResponse(
        updated_spec=opt.trip_spec,
        assistant_reply=reply,
        extracted_updates=updates or ["Live VRPTW & Pareto Re-Scan"],
        needs_clarification=bool(questions),
        follow_up_questions=questions,
        optimization=opt,
    )
