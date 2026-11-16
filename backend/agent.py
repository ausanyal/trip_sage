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
    OptimizationResponse,
    PersonaMode,
    PinnedStaySpec,
    ToolCallTrace,
    TripSpec,
    UICommand,
)
from providers.geo_routing import COUNTRY_VISITOR_GATEWAYS, OFFLINE_GAZETTEER, haversine_km
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


_GCP_VERTEX_CACHE: Dict[str, Any] = {
    "project": "",
    "token": "",
    "exp": 0.0,
    "cooldown_until": 0.0,
}


async def _get_gcp_vertex_auth() -> Tuple[str, str]:
    """Fetches project_id and OAuth2 access_token from Google Cloud Run metadata server when available."""
    now = time.time()
    if now < float(_GCP_VERTEX_CACHE.get("cooldown_until", 0.0)):
        return "", ""
    if (
        _GCP_VERTEX_CACHE.get("token")
        and _GCP_VERTEX_CACHE.get("project")
        and now < float(_GCP_VERTEX_CACHE.get("exp", 0.0))
    ):
        return str(_GCP_VERTEX_CACHE["project"]), str(_GCP_VERTEX_CACHE["token"])

    proj = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or ""
    ).strip()
    is_cloud_run = bool(os.getenv("K_SERVICE") or proj)
    timeout_s = 1.6 if is_cloud_run else 0.35

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            if not proj:
                r_proj = await client.get(
                    "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                    headers={"Metadata-Flavor": "Google"},
                )
                if r_proj.status_code != 200:
                    if not is_cloud_run:
                        _GCP_VERTEX_CACHE["cooldown_until"] = now + 90.0
                    return "", ""
                proj = r_proj.text.strip()

            r_tok = await client.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
            )
            if r_tok.status_code != 200:
                if not is_cloud_run:
                    _GCP_VERTEX_CACHE["cooldown_until"] = now + 90.0
                return "", ""
            tok_data = r_tok.json()
            access_token = str(tok_data.get("access_token") or "").strip()
            expires_in = int(tok_data.get("expires_in") or 600)
            if not proj or not access_token:
                return "", ""
            _GCP_VERTEX_CACHE["project"] = proj
            _GCP_VERTEX_CACHE["token"] = access_token
            _GCP_VERTEX_CACHE["exp"] = now + max(60, expires_in - 60)
            return proj, access_token
    except Exception:
        if not is_cloud_run:
            _GCP_VERTEX_CACHE["cooldown_until"] = now + 90.0
        return "", ""


def _extract_non_thought_text(data: Dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    visible = [str(p.get("text") or "") for p in parts if not p.get("thought") and p.get("text")]
    if visible:
        return "".join(visible).strip()
    fallback = [str(p.get("text") or "") for p in parts if p.get("text")]
    return "".join(fallback).strip()


async def _invoke_gemini_or_vertex(
    prompt_text: str,
    *,
    api_key: str = "",
    preferred_model: str = "gemini-2.5-flash",
    json_mode: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 1600,
    thinking_budget: int = 0,
    timeout_s: float = 15.0,
) -> Optional[Tuple[str, str, str]]:
    """Calls Gemini Developer API (if key set) or Cloud Run Vertex AI via service-account metadata."""
    models = [preferred_model]
    for fb in ("gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash"):
        if fb not in models:
            models.append(fb)

    def _build_body(model_id: str) -> Dict[str, Any]:
        gen_cfg: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        if thinking_budget > 0 and model_id.startswith("gemini-2.5"):
            gen_cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
            "generationConfig": gen_cfg,
        }

    # Route A: Explicit or Server-Env Gemini API Key
    clean_key = api_key.strip()
    if clean_key:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                for m in models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
                    resp = await client.post(
                        url,
                        headers={"Content-Type": "application/json", "x-goog-api-key": clean_key},
                        json=_build_body(m),
                    )
                    if resp.status_code == 200:
                        txt = _extract_non_thought_text(resp.json())
                        if txt:
                            return txt, m, "Gemini API"
                    elif resp.status_code in (400, 401, 403) and "API_KEY_INVALID" in resp.text:
                        break
        except Exception:
            pass

    # Route B: Zero-Key Google Cloud Run Vertex AI Metadata Auth
    proj_id, bearer = await _get_gcp_vertex_auth()
    if proj_id and bearer:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                for loc in ("global", "us-central1", "asia-south1"):
                    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
                    abort_vertex = False
                    for m in models:
                        url = f"https://{host}/v1/projects/{proj_id}/locations/{loc}/publishers/google/models/{m}:generateContent"
                        resp = await client.post(
                            url,
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {bearer}",
                            },
                            json=_build_body(m),
                        )
                        if resp.status_code == 200:
                            txt = _extract_non_thought_text(resp.json())
                            if txt:
                                return txt, m, f"Vertex AI · {loc}"
                        elif "SERVICE_DISABLED" in resp.text or (
                            resp.status_code == 403 and "PERMISSION_DENIED" in resp.text
                        ):
                            _GCP_VERTEX_CACHE["cooldown_until"] = time.time() + 300.0
                            abort_vertex = True
                            break
                    if abort_vertex:
                        break
        except Exception:
            pass

    return None


async def _call_gemini_spec_extractor(
    req: ChatTurnRequest, api_key: str, model_name: str
) -> Optional[Tuple[TripSpec, List[str], bool, List[str], str, int, str, str]]:
    t0 = time.perf_counter()
    history_lines = [f"{m.role.upper()}: {m.content}" for m in req.history[-6:]]
    combined_prompt = (
        f"{GEMINI_SYSTEM_PROMPT}\n\n"
        f"CURRENT_TRIP_SPEC_JSON:\n{req.current_spec.model_dump_json(indent=2)}\n\n"
        f"RECENT_CONVERSATION:\n" + ("\n".join(history_lines) if history_lines else "(start)") + "\n\n"
        f"LATEST_USER_MESSAGE:\n{req.message}"
    )

    llm_out = await _invoke_gemini_or_vertex(
        combined_prompt,
        api_key=api_key,
        preferred_model=model_name,
        json_mode=True,
        temperature=0.15,
        max_tokens=1800,
        thinking_budget=256,
        timeout_s=14.0,
    )
    if not llm_out:
        return None

    text, used_model, provider = llm_out
    try:
        cleaned_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        parsed = json.loads(cleaned_json)
        updated_spec = TripSpec.model_validate(parsed["updated_spec"])
        updates = [str(x) for x in (parsed.get("extracted_updates") or [])]
        needs_clar = bool(parsed.get("needs_clarification", False))
        questions = [str(q) for q in (parsed.get("follow_up_questions") or [])]
        preface = str(parsed.get("assistant_preface") or "").strip()
        elapsed_ms = max(40, int(round((time.perf_counter() - t0) * 1000)))
        return updated_spec, updates, needs_clar, questions, preface, elapsed_ms, used_model, provider
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


_MONTH_MAP: Dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _parse_date_token(token: str, default_year: int) -> Optional[dt.date]:
    token = token.strip(" .,;-")
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
    m_mon1 = re.match(
        r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?$",
        token,
        flags=re.IGNORECASE,
    )
    if m_mon1 and m_mon1.group(1).lower() in _MONTH_MAP:
        yr = int(m_mon1.group(3)) if m_mon1.group(3) else default_year
        try:
            return dt.date(yr, _MONTH_MAP[m_mon1.group(1).lower()], int(m_mon1.group(2)))
        except ValueError:
            return None
    m_mon2 = re.match(
        r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})(?:\s*,?\s*(20\d{2}))?$",
        token,
        flags=re.IGNORECASE,
    )
    if m_mon2 and m_mon2.group(2).lower() in _MONTH_MAP:
        yr = int(m_mon2.group(3)) if m_mon2.group(3) else default_year
        try:
            return dt.date(yr, _MONTH_MAP[m_mon2.group(2).lower()], int(m_mon2.group(1)))
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

    # 2. Destination Villa BHK & nightly budget ceiling — ask ONLY what wasn't already specified
    has_explicit_budget = bool(re.search(r"(?:\d+\s*(?:k|000)\b|[$€£]\s*\d{2,4})", lower))
    has_explicit_bhk = bool(re.search(r"\b\d\s*(?:bhk|br|bedroom)\b", lower))
    cur_hint = (spec.currency or "").upper()
    budget_examples = (
        "$180–$260 or $260–$400/night"
        if cur_hint == "USD"
        else (
            "€165–€240 or €240–€360/night"
            if cur_hint == "EUR"
            else (
                "£140–£210 or £210–£320/night"
                if cur_hint == "GBP"
                else "₹15k–₹20k or ₹20k–₹30k/night"
            )
        )
    )
    if spec.stay_strategy in ("villas", "hybrid"):
        if not has_explicit_bhk and not has_explicit_budget:
            questions.append(
                f"**{dest_short} Villa Size & Budget:** Would you prefer a **2 BHK** or **3 BHK** private stay in {dest_short}, and what nightly budget range should I target (e.g., {budget_examples})?"
            )
        elif has_explicit_bhk and not has_explicit_budget:
            questions.append(
                f"**{dest_short} Nightly Budget:** For your **{spec.destination_villa_bhk} BHK/BR** private stay in {dest_short}, what nightly budget range should I target (e.g., {budget_examples})?"
            )
        elif has_explicit_budget and not has_explicit_bhk:
            questions.append(
                f"**{dest_short} Villa Size:** Within your nightly budget, would you prefer a **2 BHK** or **3 BHK** private stay in {dest_short}?"
            )

    # 3. Specific Car / SUV Model if road trip and still generic
    known_car_named = any(
        k in lower
        for k in [
            "meridian", "fortuner", "innova", "hycross", "crysta", "xuv", "safari",
            "compass", "creta", "seltos", "scorpio", "thar", "nexon", "virtus", "city", "tesla",
        ]
    )
    if spec.transport_mode == "road" and not known_car_named:
        questions.append(
            "**Which Car Are You Driving?** Sharing your car/SUV model lets me calibrate exact highway fuel burn, tolls, and steep estate-road ground clearance."
        )

    # 4. Activity preferences if not specified
    if not any(w in lower for w in ["safari", "climb", "trek", "zipline", "water sport"]):
        stop_city_q = f" or sightseeing detours in **{spec.pinned_stays[0].city}**" if spec.pinned_stays else ""
        questions.append(
            f"**Activity Pacing & Interests:** Should I include or skip **(a) Wildlife Safaris**, **(b) Adventure / Water Activities**, **(c) Moderate Scenic Climbs**{stop_city_q}?"
        )

    # 5. Departure / Flight timing preference if not specified
    if not re.search(r"\b\d{1,2}\s*(?:am|pm)\b", lower) and "after lunch" not in lower and "morning" not in lower:
        if spec.transport_mode in ("flight", "hybrid"):
            questions.append(
                f"**Flight Schedule & Cabin Preference:** For **{orig_short} -> {dest_short}**, do you prefer **morning non-stop / full-service flights** (with 25kg baggage & meals) or the **lowest-fare smart hub saver**?"
            )
        else:
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

    # 2. Generic Date Range ("from MM/DD to MM/DD", "Dec 21 to Dec 26", "YYYY-MM-DD to YYYY-MM-DD", or "for 5 days / 4 nights")
    yr = dt.date.today().year
    dates_explicitly_set = False
    explicit_range = re.search(
        r"\b(?:from|between)\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*20\d{2})?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}(?:\s*,?\s*20\d{2})?)"
        r"\s+(?:to|and|-|through)\s+(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/20\d{2})?|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*20\d{2})?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}(?:\s*,?\s*20\d{2})?)\b",
        msg,
        flags=re.IGNORECASE,
    )
    if explicit_range:
        d1 = _parse_date_token(explicit_range.group(1), yr)
        d2 = _parse_date_token(explicit_range.group(2), yr)
        if d1 and d2 and d2 > d1:
            spec.start_date, spec.end_date = d1.isoformat(), d2.isoformat()
            dates_explicitly_set = True
            updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
    if not dates_explicitly_set:
        iso_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", msg)
        if len(iso_dates) >= 2:
            spec.start_date, spec.end_date = min(iso_dates), max(iso_dates)
            dates_explicitly_set = True
            updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
        else:
            slash_tokens = re.findall(r"\b(\d{1,2}/\d{1,2}(?:/20\d{2})?)\b", msg)
            parsed_slash = [d for tok in slash_tokens if (d := _parse_date_token(tok, yr)) is not None]
            if len(parsed_slash) >= 2:
                d_lo, d_hi = min(parsed_slash), max(parsed_slash)
                if d_hi > d_lo:
                    spec.start_date, spec.end_date = d_lo.isoformat(), d_hi.isoformat()
                    dates_explicitly_set = True
                    updates.append(f"Dates -> {spec.start_date} to {spec.end_date}")
    if not dates_explicitly_set:
        dur_m = re.search(r"\b(?:for\s+)?(\d{1,2})\s*[-\s]?(nights?|days?)\b", lower)
        if dur_m:
            num_val = max(1, min(14, int(dur_m.group(1))))
            nights_val = num_val if "night" in dur_m.group(2) else max(1, num_val - 1)
            try:
                d0 = dt.date.fromisoformat(spec.start_date)
            except ValueError:
                d0 = dt.date.today() + dt.timedelta(days=14)
                spec.start_date = d0.isoformat()
            spec.end_date = (d0 + dt.timedelta(days=nights_val)).isoformat()
            updates.append(f"Duration -> {nights_val} Nights ({spec.start_date} to {spec.end_date})")

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
    elif any(
        p in lower
        for p in [
            "flight only",
            "fly + stay",
            "fly and stay",
            "flights only",
            "by flight",
            "with flights",
            "fly to ",
            "fly from ",
            "flying to ",
            "flying from ",
        ]
    ):
        spec.transport_mode = "flight"
        if spec.vehicle_name in ("Family SUV (Own Car)", "Self-Drive SUV"):
            spec.vehicle_name = "Airport Private Transfer SUV"
        updates.append("Transport Mode -> Fly + Stay")
    elif any(p in lower for p in ["road trip", "own car", "pure road", "drive from", "driving from"]):
        spec.transport_mode = "road"
        updates.append("Transport Mode -> Pure Road Trip")
    elif dest_switched:
        # Auto-infer Fly + Stay when switching to an international, island, or >1,100 km destination without "road trip"
        o_key = spec.origin.lower().split(",")[0].strip()
        d_key = spec.destination.lower().split(",")[0].strip()
        d_full = spec.destination.lower().strip()
        o_cc = (
            COUNTRY_VISITOR_GATEWAYS[o_key][4]
            if o_key in COUNTRY_VISITOR_GATEWAYS
            else (OFFLINE_GAZETTEER[o_key][2] if o_key in OFFLINE_GAZETTEER else "in")
        )
        d_cc = (
            COUNTRY_VISITOR_GATEWAYS[d_full][4]
            if d_full in COUNTRY_VISITOR_GATEWAYS
            else (
                COUNTRY_VISITOR_GATEWAYS[d_key][4]
                if d_key in COUNTRY_VISITOR_GATEWAYS
                else (OFFLINE_GAZETTEER[d_key][2] if d_key in OFFLINE_GAZETTEER else o_cc)
            )
        )
        island_hit = any(tok in d_full for tok in ("andaman", "port blair", "havelock", "lakshadweep", "agatti", "bali", "maldives"))
        long_haul = False
        if o_key in OFFLINE_GAZETTEER and d_key in OFFLINE_GAZETTEER:
            olat, olng, _ = OFFLINE_GAZETTEER[o_key]
            dlat, dlng, _ = OFFLINE_GAZETTEER[d_key]
            long_haul = haversine_km(olat, olng, dlat, dlng) > 1100.0
        if o_cc != d_cc or island_hit or long_haul:
            spec.transport_mode = "flight"
            spec.vehicle_name = "Airport Private Transfer SUV"
            updates.append("Transport Mode -> Fly + Stay")

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
            "br villa",
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
        updates.append("Stay Strategy -> Private Villas & Homes")

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


_RE_FOLLOW_UPS = re.compile(r"(?im)^FOLLOW_UPS:\s*(.+)$")
_RE_UI_CMDS = re.compile(r"(?im)^UI_COMMANDS_JSON:\s*(\[.*\])\s*$")


def _extract_ui_commands(message: str, max_days: int) -> List[UICommand]:
    cmds: List[UICommand] = []
    low = message.lower()

    m_day = re.search(r"\b(?:focus|zoom|show|open|inspect|jump\s+to)\s+day\s*(\d{1,2})\b", low)
    if m_day:
        d_num = int(m_day.group(1))
        if 1 <= d_num <= max(1, max_days):
            cmds.append(
                UICommand(
                    cmd="SELECT_DAY",
                    day=d_num,
                    reason=f"Focused map & companion snapshot on Day {d_num}",
                )
            )

    if re.search(r"\b(?:open|show|switch\s+to|inspect)\s+(?:channel|stay|fee|ota)?\s*arbitrage\b", low):
        cmds.append(
            UICommand(
                cmd="SET_TAB",
                tab="arbitrage",
                reason="Switched workspace tab to Cross-Channel Arbitrage",
            )
        )
    elif re.search(r"\b(?:open|show|switch\s+to|inspect)\s+(?:road|toll|fastag|fuel|transfer|telemetry)\b", low):
        cmds.append(
            UICommand(
                cmd="SET_TAB",
                tab="telemetry",
                reason="Switched workspace tab to Road, Tolls & Logistics",
            )
        )
    elif re.search(r"\b(?:open|show|switch\s+to)\s+(?:daily\s+)?itinerary\b", low):
        cmds.append(
            UICommand(
                cmd="SET_TAB",
                tab="itinerary",
                reason="Switched workspace tab to VRPTW Itinerary",
            )
        )

    m_bp = re.search(r"\b(?:select|switch\s+to|choose|activate)\s+(?:blueprint|option|runner[- ]up)\s*#?(\d)\b", low)
    if m_bp:
        bp_idx = max(0, int(m_bp.group(1)) - 1)
        cmds.append(
            UICommand(
                cmd="SELECT_BLUEPRINT",
                blueprint_idx=bp_idx,
                reason=f"Selected Pareto Blueprint #{bp_idx + 1}",
            )
        )

    if re.search(r"\b(?:open|edit|tune|show)\s+(?:trip\s+)?(?:inputs|parameters|spec\s+drawer)\b", low):
        cmds.append(UICommand(cmd="OPEN_PARAMS", reason="Opened Bi-Directional Trip Spec Drawer"))

    return cmds


def _build_evidence_snapshot(opt: OptimizationResponse) -> str:
    ccy = opt.active_currency
    fx = opt.fx_rates
    spec = opt.trip_spec
    lines = [
        f"Route: {spec.origin} -> {spec.destination} ({spec.start_date} to {spec.end_date})",
        f"Mode: {spec.transport_mode} | Stay Strategy: {spec.stay_strategy} | Vehicle: {spec.vehicle_name}",
        f"Party: {spec.party.adults} Adults + {spec.party.children} Kids (Ages: {spec.party.child_ages}) | Dietary: {spec.activities.dietary}",
        f"Active Currency: {ccy}",
        "",
        "=== PARETO FRONTIER BLUEPRINTS ===",
    ]
    for idx, bp in enumerate(opt.blueprints[:5], start=1):
        tot = format_amount_from_inr(bp.total_core_landed_inr, ccy, fx)
        unopt = format_amount_from_inr(bp.unoptimized_baseline_inr, ccy, fx)
        sav = format_amount_from_inr(bp.total_arbitrage_savings_inr, ccy, fx)
        stay_desc = "; ".join(
            f"{s.name} ({s.nights}N via {s.best_channel}: {format_amount_from_inr(s.best_landed_inr, ccy, fx)} vs worst {format_amount_from_inr(s.worst_landed_inr, ccy, fx)}, rating {s.rating})"
            for s in bp.stays
        )
        lines.append(
            f"#{idx} [{bp.rank_badge}] {bp.name}: Core All-In={tot} (Unoptimized={unopt}, Saves={sav}) | "
            f"Fatigue={bp.fatigue_score}/100 | Utility={bp.quality_score}/100 | Stays: {stay_desc}"
        )

    top = opt.blueprints[0]
    if top.flights:
        lines.append("\n=== GATEWAY FLIGHT OPTIONS ===")
        for f in top.flights[:4]:
            f_tot = format_amount_from_inr(f.landed_family_total_inr, ccy, fx)
            f_sav = format_amount_from_inr(f.savings_inr, ccy, fx)
            lines.append(
                f"- {f.carrier} ({f.route_label}): Out {f.depart_time}-{f.arrive_time} ({f.duration}), "
                f"Ret {f.return_depart_time or 'N/A'}-{f.return_arrive_time or 'N/A'} | Party Total={f_tot} (Saves {f_sav})"
            )

    lines.append(
        f"\n=== ROAD / GROUND LOGISTICS ===\n"
        f"Distance={top.road.total_distance_km} km | Drive Hours={top.road.total_drive_hours}h | "
        f"Ground Total={format_amount_from_inr(top.road.total_road_cost_inr, ccy, fx)} "
        f"(Fuel={format_amount_from_inr(top.road.fuel_cost_inr, ccy, fx)}, Tolls={format_amount_from_inr(top.road.fastag_and_forest_tolls_inr, ccy, fx)})"
    )
    if top.arbitrage_callouts:
        lines.append("Callouts: " + " | ".join(top.arbitrage_callouts[:4]))

    lines.append("\n=== DAILY VRPTW SCHEDULE HIGHLIGHTS ===")
    for d in top.days[:6]:
        stop_titles = ", ".join(f"{s.time_window} {s.title}" for s in d.stops[:4])
        lines.append(
            f"Day {d.day_number} ({d.date_label}): {d.headline} [{d.drive_km} km, {d.drive_time_label}, Stay: {d.overnight_label}] -> {stop_titles}"
        )
    return "\n".join(lines)


def _stage3_system_prompt(mode: PersonaMode, had_updates: bool) -> str:
    persona_map: Dict[str, str] = {
        "advisor": (
            "PERSONA: Articulate, executive Luxury & Quantitative Travel Strategist. "
            "Speak warmly in first person, explaining trade-offs across landed channel fees, driving fatigue, checkpost windows, and kid-friendly pacing."
        ),
        "eli5": (
            "PERSONA: Friendly Plain-English Family Travel Coach (ELI5). "
            "Use vivid everyday analogies (like comparing hidden OTA cleaning fees to airport baggage surcharges, and VRPTW routing to beating school-run traffic) while keeping every rupee/dollar figure exact."
        ),
        "debate": (
            "PERSONA: Travel Investment Committee Debate. "
            "Structure your reasoning into '### 🟢 Case for the Pareto Knee (#1)', '### 🔵 Case for the Runner-Up Alternative', and '### ⚖️ Final Verdict' using exact figures."
        ),
        "devil": (
            "PERSONA: Candid Chief Risk Officer & Pre-Mortem Travel Auditor. "
            "Stress-test this itinerary for hidden traps: checkpost/curfew cutoffs, kid car-sickness/ghat fatigue, non-refundable villa policies, weather/peak-season bottlenecks, and concrete mitigations."
        ),
    }
    persona = persona_map.get(mode, persona_map["advisor"])
    update_rule = (
        "Open by briefly confirming the route/spec updates you just locked in, then reason over the solved Pareto blueprints and answer the user's intent."
        if had_updates
        else "Directly answer the user's question or reasoning request using the exact numbers in [SOLVED PARETO & ARBITRAGE EVIDENCE]."
    )
    return (
        "You are TripSage Copilot — a 3-stage multi-modal travel arbitrage, Pareto, and VRPTW reasoning agent.\n"
        f"{persona}\n"
        "RULES:\n"
        f"1. {update_rule}\n"
        "2. Ground every price, hotel/villa name, flight carrier, distance, and savings number STRICTLY in [SOLVED PARETO & ARBITRAGE EVIDENCE]. Never invent properties or numbers.\n"
        "3. Keep your response crisp, high-signal, and well-structured (110–250 words).\n"
        "4. On the very final line, append `FOLLOW_UPS: Question 1? | Question 2? | Question 3?` with 3 smart, clickable follow-up prompts tailored to this trip."
    )


async def _run_stage3_reasoning(
    req: ChatTurnRequest,
    opt: OptimizationResponse,
    updates: List[str],
    api_key: str,
    model_name: str,
) -> Optional[Tuple[str, List[str], str, str, int]]:
    t0 = time.perf_counter()
    evidence = _build_evidence_snapshot(opt)
    hist_lines = [f"{m.role.upper()}: {m.content[:360]}" for m in req.history[-5:]]
    prompt = (
        f"{_stage3_system_prompt(req.mode, bool(updates))}\n\n"
        f"=== RECENT CONVERSATION ===\n" + ("\n".join(hist_lines) if hist_lines else "(Start)") + "\n\n"
        f"=== EXTRACTED SPEC UPDATES THIS TURN ===\n{', '.join(updates) if updates else 'None (Analytical / Advisory Turn)'}\n\n"
        f"=== [SOLVED PARETO & ARBITRAGE EVIDENCE] ===\n{evidence}\n\n"
        f"=== USER MESSAGE ===\n{req.message}"
    )
    llm_res = await _invoke_gemini_or_vertex(
        prompt,
        api_key=api_key,
        preferred_model=model_name,
        json_mode=False,
        temperature=0.3,
        max_tokens=1400,
        thinking_budget=512,
        timeout_s=16.0,
    )
    if not llm_res:
        return None
    raw_text, used_model, provider = llm_res
    follow_ups: List[str] = []
    clean_lines: List[str] = []
    for line in raw_text.splitlines():
        m_fu = _RE_FOLLOW_UPS.match(line.strip())
        if m_fu:
            follow_ups = [
                p.strip(" `\"'*-•")
                for p in m_fu.group(1).split("|")
                if p.strip(" `\"'*-•")
            ][:3]
        elif not _RE_UI_CMDS.match(line.strip()):
            clean_lines.append(line)
    elapsed_ms = max(45, int(round((time.perf_counter() - t0) * 1000)))
    clean_md = "\n".join(clean_lines).strip()
    if not clean_md:
        return None
    return clean_md, follow_ups, used_model, provider, elapsed_ms


def _default_follow_up_prompts(opt: OptimizationResponse) -> List[str]:
    dest = opt.trip_spec.destination.split(",")[0].strip()
    prompts = [
        f"Why does {opt.blueprints[0].name} win on landed fee math?",
        f"Stress-test this {dest} itinerary for hidden risks & fatigue",
        f"Search more similar places to stay in {dest}",
    ]
    return prompts[:3]


def _synthesize_builtin_reasoning_reply(
    req: ChatTurnRequest,
    opt: OptimizationResponse,
    updates: List[str],
    questions: List[str],
    expanded_pool: bool,
) -> str:
    """Deterministic multi-mode reasoning synthesizer when neither Gemini API key nor Cloud Run Vertex AI is reachable."""
    ccy = opt.active_currency
    fx = opt.fx_rates
    top_bp = opt.blueprints[0]
    alt_bp = opt.blueprints[1] if len(opt.blueprints) > 1 else None
    fmt_core = format_amount_from_inr(top_bp.total_core_landed_inr, ccy, fx)
    fmt_save = format_amount_from_inr(top_bp.total_arbitrage_savings_inr, ccy, fx)
    low_msg = req.message.lower()

    if expanded_pool:
        dest_short = opt.trip_spec.destination.split(",")[0].strip()
        shortlist = _format_stay_comparison_shortlist(opt)
        return (
            f"Expanded your **{dest_short}** stay search to **{len(opt.blueprints)} non-dominated options** "
            f"(each solved end-to-end with your route & party):\n\n"
            f"{shortlist}\n\n"
            f"Click any Pareto card on the right (or open **Cross-Channel Stay Arbitrage**) to switch your itinerary & map!"
        )

    if req.mode == "eli5" or "like i'm 5" in low_msg or "eli5" in low_msg:
        primary_stay = top_bp.stays[-1] if top_bp.stays else None
        stay_analogy = (
            f"For **{primary_stay.name}**, booking via **{primary_stay.best_channel}** is like buying concert tickets at the box office instead of paying markup + service fees—saving **{format_amount_from_inr(primary_stay.savings_inr, ccy, fx)}** on the exact same bedrooms."
            if primary_stay
            else ""
        )
        return (
            f"Here is the plain-English picture for **{opt.trip_spec.origin} -> {opt.trip_spec.destination}**:\n\n"
            f"- **Think of our Pareto solver like picking the sweet-spot family car:** **{top_bp.name}** lands at **{fmt_core}** all-in (saving **{fmt_save}**) without exhausting everyone on the road (`Fatigue {top_bp.fatigue_score}/100`).\n"
            f"- **Zero Backtracking Schedule:** We grouped stops by neighborhood and morning/lunch clocks across **{len(top_bp.days)} days** (`{top_bp.road.total_distance_km} km` total) so climbs happen while it's cool and meals hit right on time.\n"
            + (f"- **Hidden Fee Win:** {stay_analogy}" if stay_analogy else "")
        )

    if req.mode == "debate" or ("compare" in low_msg and alt_bp is not None) or "vs" in low_msg:
        alt_core = format_amount_from_inr(alt_bp.total_core_landed_inr, ccy, fx) if alt_bp else fmt_core
        alt_name = alt_bp.name if alt_bp else "Runner-Up Option"
        return (
            f"Comparing your top non-dominated blueprints for **{opt.trip_spec.origin} -> {opt.trip_spec.destination}**:\n\n"
            f"### 🟢 Case for Pareto Knee: **{top_bp.name}** (**{fmt_core}**)\n"
            f"- Best multi-objective balance (`Fatigue {top_bp.fatigue_score}` · `Score {top_bp.quality_score}`), saving **{fmt_save}** via {top_bp.stays[-1].best_channel if top_bp.stays else 'direct channel'} fee arbitrage.\n\n"
            f"### 🔵 Case for Runner-Up: **{alt_name}** (**{alt_core}**)\n"
            + (
                f"- Trades `{format_amount_from_inr(abs(alt_bp.total_core_landed_inr - top_bp.total_core_landed_inr), ccy, fx)}` price delta for a diversified micro-location (`Fatigue {alt_bp.fatigue_score}` · `Score {alt_bp.quality_score}`).\n\n"
                if alt_bp
                else "- Provides backup availability across alternate portals.\n\n"
            )
            + f"### ⚖️ Verdict\nLock **{top_bp.name}** first for optimal landed value, and keep **{alt_name}** as your instant backup."
        )

    if req.mode == "devil" or re.search(r"\b(risk|stress|trap|catch|warn|safe|problem|audit)\b", low_msg):
        callouts = "\n".join(f"- {c}" for c in top_bp.arbitrage_callouts[:3])
        return (
            f"Pre-mortem risk & logistics audit for **{opt.trip_spec.origin} -> {opt.trip_spec.destination}** (**{fmt_core}**):\n\n"
            f"- **Pacing & Corridor Fatigue (`{top_bp.fatigue_score}/100`):** Total ground distance is **{top_bp.road.total_distance_km} km** (`{top_bp.road.total_drive_hours}h`). Stick to your **{opt.trip_spec.departure_time_pref}** rollout so forest checkposts, ghat curves, or airport transfers never slip into late-evening bottlenecks.\n"
            f"- **Channel Cancellation Guardrail:** Before paying the lowest landed rate (**{fmt_save}** saved), verify free-cancellation cutoff dates when traveling with kids.\n"
            f"{callouts}"
        )

    if re.search(r"\b(why|explain|how\s+did|fee|cheaper|arbitrage)\b", low_msg) and not updates:
        callouts = "\n".join(f"- {c}" for c in top_bp.arbitrage_callouts[:3])
        return (
            f"Here is why **{top_bp.name}** wins as the Pareto Knee at **{fmt_core}** (saving **{fmt_save}**):\n\n"
            f"{callouts}\n\n"
            f"Across cost, road fatigue (`{top_bp.fatigue_score}/100`), and property quality (`{top_bp.quality_score}/100`), it sits closest to the Utopia point of all feasible combinations."
        )

    transit_summary = ""
    if opt.trip_spec.pinned_stays:
        uniq_stops = list(dict.fromkeys(f"{p.property_name} ({p.check_in})" for p in opt.trip_spec.pinned_stays))
        transit_summary = f" Anchored transit stopovers at **{', '.join(uniq_stops)}**."

    flight_summary = ""
    if top_bp.flights:
        f0 = top_bp.flights[0]
        fmt_flt = format_amount_from_inr(f0.landed_family_total_inr, ccy, fx)
        flight_summary = (
            f" Shortlisted **{len(top_bp.flights)} round-trip flight options** led by **{f0.carrier}** "
            f"({f0.origin_iata or opt.trip_spec.origin} -> {f0.dest_iata or opt.trip_spec.destination}, **{fmt_flt}** for your party)."
        )

    if questions:
        return (
            f"Mapped an initial **{len(opt.blueprints)}-blueprint Pareto & VRPTW plan** for "
            f"**{opt.trip_spec.origin} -> {opt.trip_spec.destination}** (**{fmt_core}** core all-in, saving **{fmt_save}** across channels)."
            f"{transit_summary}{flight_summary}\n\nTo tailor the final rooms, villa budget, and daily kid-friendly pacing, let me know:"
        )

    change_note = (
        f"Locked updates ({', '.join(updates)}) and re-solved the N×N VRPTW matrix & Pareto frontier.{transit_summary}{flight_summary} "
        if updates
        else f"Re-verified live routing, 2-Opt VRPTW time windows, and cross-channel checkout math.{transit_summary}{flight_summary} "
    )
    return (
        f"{change_note}Pareto Knee: **{top_bp.name}** at **{fmt_core}** core all-in "
        f"(saving **{fmt_save}** across channels)."
    )


async def process_chat_turn(
    req: ChatTurnRequest,
    on_phase: Optional[PhaseEmitter] = None,
) -> ChatTurnResponse:
    """3-Stage Conversational Reasoning Planner:
    Stage 1 (Gemini/Vertex JSON Spec Extractor + Deterministic NLP Fallback + UI Page-Driver) ->
    Stage 2 (NSGA-II 3D Pareto + OSRM 2-Opt VRPTW Solver) ->
    Stage 3 (Grounded Gemini 2.5 Thinking Synthesis + Built-In Multi-Persona Fallback).
    """
    api_key = (req.api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    if on_phase:
        await on_phase(
            "Phase 1 · Intent & Constraints",
            "Extracting structured trip intent, transit anchors, party constraints & UI actions...",
        )

    gemini_result = await _call_gemini_spec_extractor(req, api_key, model_name)

    used_llm = False
    engine_label = "⚡ TripSage 3-Stage Reasoning Engine"

    if gemini_result is not None:
        updated_spec, updates, needs_clar, questions, preface, llm_ms, s1_model, s1_prov = gemini_result
        used_llm = True
        engine_label = f"🧠 {s1_model} ({s1_prov})"
        if updated_spec.destination.strip().lower() != req.current_spec.destination.strip().lower():
            if not re.search(r"\b(inr|usd|eur|gbp|rupees?|dollars?|euros?|pounds?)\b|[₹$€£]", req.message, re.I):
                updated_spec.currency = None
        if updated_spec.pinned_stays and updated_spec.stay_strategy == "villas":
            updated_spec.stay_strategy = "hybrid"
    else:
        updated_spec, updates, questions = _deterministic_nlp_extract(req)
        needs_clar = bool(questions)
        preface = ""
        llm_ms = 0

    opt = await solve_trip_pareto(updated_spec, on_phase=on_phase, persist_snapshot=False)
    if gemini_result is not None:
        opt.tool_trace.insert(
            0,
            ToolCallTrace(
                phase="Phase 1 · Intent & Constraints",
                tool_name=f"llm_spec_extract ({engine_label.replace('🧠 ', '')})",
                latency_ms=llm_ms,
                input_summary=req.message[:90],
                finding_summary=", ".join(updates) if updates else "Confirmed conversational intent & constraints.",
            ),
        )

    ui_cmds = _extract_ui_commands(req.message, len(opt.blueprints[0].days))
    expanded_pool = (
        updated_spec.stay_options_limit > req.current_spec.stay_options_limit
        or updated_spec.stay_pool_offset != req.current_spec.stay_pool_offset
    )

    if on_phase:
        await on_phase(
            "Phase 4 · Grounded Advisory Reasoning",
            f"Synthesizing {req.mode.upper()} reasoning over solved Pareto blueprints & channel fee math...",
        )

    stage3 = None
    if not expanded_pool:
        stage3 = await _run_stage3_reasoning(req, opt, updates, api_key, model_name)

    if stage3 is not None:
        s3_md, s3_fups, s3_model, s3_prov, s3_ms = stage3
        used_llm = True
        engine_label = f"🧠 {s3_model} ({s3_prov} · {req.mode.capitalize()})"
        reply = s3_md
        suggested_prompts = s3_fups or _default_follow_up_prompts(opt)
        opt.tool_trace.append(
            ToolCallTrace(
                phase="Phase 4 · Grounded Advisory Reasoning",
                tool_name=f"gemini_grounded_reasoner ({s3_model})",
                latency_ms=s3_ms,
                input_summary=f"mode={req.mode} · {len(opt.blueprints)} Pareto blueprints",
                finding_summary="Synthesized citation-grounded trade-offs & follow-up prompts.",
            )
        )
    else:
        reply = _synthesize_builtin_reasoning_reply(req, opt, updates, questions, expanded_pool)
        if preface and not reply.startswith(preface):
            reply = f"{preface}\n\n{reply}"
        suggested_prompts = _default_follow_up_prompts(opt)

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
        extracted_updates=updates or (["Gemini Spec Synced"] if used_llm else ["Live VRPTW & Pareto Re-Scan"]),
        needs_clarification=needs_clar or bool(questions),
        follow_up_questions=questions,
        suggested_prompts=suggested_prompts,
        ui_commands=ui_cmds,
        engine_label=engine_label,
        used_llm=used_llm,
        optimization=opt,
    )
