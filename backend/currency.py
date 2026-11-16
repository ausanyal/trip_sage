from __future__ import annotations

from typing import Dict, Literal, Optional, Tuple

import httpx

from db import RATE_LIMITER, cache_get_json, cache_set_json

CurrencyCode = Literal["INR", "USD", "EUR", "GBP"]

SUPPORTED_CURRENCIES = ("INR", "USD", "EUR", "GBP")

# Resilient reference conversion rates from 1 INR when offline
DEFAULT_FX_FROM_INR: Dict[str, float] = {
    "INR": 1.0,
    "USD": 0.0118,
    "EUR": 0.0109,
    "GBP": 0.0093,
}

CURRENCY_SYMBOLS: Dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}

EUROZONE_COUNTRIES = {
    "at", "be", "cy", "de", "ee", "es", "fi", "fr", "gr", "hr",
    "ie", "it", "lt", "lu", "lv", "mt", "nl", "pt", "si", "sk",
}


def infer_currency_from_countries(
    origin_cc: str,
    dest_cc: str,
    explicit_currency: Optional[str] = None,
) -> CurrencyCode:
    """India-first + global auto-detection of display currency."""
    if explicit_currency and explicit_currency.upper() in SUPPORTED_CURRENCIES:
        return explicit_currency.upper()  # type: ignore[return-value]

    ccs = {(origin_cc or "").lower(), (dest_cc or "").lower()}
    if "in" in ccs:
        return "INR"
    if "gb" in ccs or "uk" in ccs:
        return "GBP"
    if ccs & EUROZONE_COUNTRIES:
        return "EUR"
    return "USD"


async def get_live_fx_rates() -> Tuple[Dict[str, float], str]:
    """Fetches daily European Central Bank FX rates from Frankfurter API (cached 12h in SQLite)."""
    cache_key = "fx:inr_to_global:v1"
    cached = cache_get_json(cache_key)
    if isinstance(cached, dict) and "USD" in cached and "INR" in cached:
        return {k: float(v) for k, v in cached.items()}, "ecb_frankfurter_cached"

    try:
        await RATE_LIMITER.acquire("frankfurter_fx", min_interval_sec=0.2)
        async with httpx.AsyncClient(timeout=3.2) as client:
            resp = await client.get(
                "https://api.frankfurter.app/latest",
                params={"from": "INR", "to": "USD,EUR,GBP"},
            )
            if resp.status_code == 200:
                data = resp.json() or {}
                raw_rates = data.get("rates") or {}
                if raw_rates:
                    rates: Dict[str, float] = {
                        "INR": 1.0,
                        "USD": float(raw_rates.get("USD", DEFAULT_FX_FROM_INR["USD"])),
                        "EUR": float(raw_rates.get("EUR", DEFAULT_FX_FROM_INR["EUR"])),
                        "GBP": float(raw_rates.get("GBP", DEFAULT_FX_FROM_INR["GBP"])),
                    }
                    cache_set_json(cache_key, "frankfurter_fx", rates, ttl_seconds=43200)
                    return rates, "ecb_frankfurter_live"
    except Exception:
        pass

    return dict(DEFAULT_FX_FROM_INR), "reference_fx_fallback"


def format_amount_from_inr(
    amount_inr: int,
    currency: str = "INR",
    fx_rates: Optional[Dict[str, float]] = None,
) -> str:
    cur = currency.upper() if currency and currency.upper() in SUPPORTED_CURRENCIES else "INR"
    rates = fx_rates or DEFAULT_FX_FROM_INR
    rate = float(rates.get(cur, 1.0))
    converted = int(round(amount_inr * rate))
    sym = CURRENCY_SYMBOLS.get(cur, "₹")
    if cur == "INR":
        return f"₹{amount_inr:,}"
    return f"{sym}{converted:,}"
