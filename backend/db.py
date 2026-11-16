from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_LOCK = threading.Lock()
_SCHEMA_INITIALIZED_FOR: Optional[str] = None


def get_db_path() -> Path:
    env_override = (os.getenv("TRIPSAGE_DB_PATH") or "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "tripsage.db"


def _connect() -> sqlite3.Connection:
    global _SCHEMA_INITIALIZED_FOR
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db_key = str(db_path)
    if _SCHEMA_INITIALIZED_FOR != db_key:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS http_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_http_cache_expires ON http_cache(expires_at);

            CREATE TABLE IF NOT EXISTS saved_trips (
                trip_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                optimization_json TEXT NOT NULL,
                messages_json TEXT NOT NULL
            );
            """
        )
        conn.commit()
        _SCHEMA_INITIALIZED_FOR = db_key
    return conn


def cache_get_json(cache_key: str) -> Optional[Any]:
    now = time.time()
    try:
        with _DB_LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT payload_json, expires_at FROM http_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if not row:
                    return None
                if float(row["expires_at"]) <= now:
                    conn.execute("DELETE FROM http_cache WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None
                return json.loads(row["payload_json"])
            finally:
                conn.close()
    except Exception:
        return None


def cache_set_json(
    cache_key: str,
    provider: str,
    payload: Any,
    ttl_seconds: int = 21600,
) -> None:
    now = time.time()
    expires = now + max(30, ttl_seconds)
    try:
        serialized = json.dumps(payload, ensure_ascii=False)
        with _DB_LOCK:
            conn = _connect()
            try:
                conn.execute(
                    """
                    INSERT INTO http_cache (cache_key, provider, payload_json, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        provider = excluded.provider,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    (cache_key, provider, serialized, now, expires),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


def save_trip_snapshot(
    spec_dict: Dict[str, Any],
    optimization_dict: Dict[str, Any],
    messages_list: Optional[List[Dict[str, Any]]] = None,
    trip_id: Optional[str] = None,
) -> str:
    """Persists an OptimizationResponse + optional chat transcript and returns a shareable `ts-...` slug."""
    if trip_id and re.match(r"^ts-[a-z0-9]{6,16}$", trip_id):
        tid = trip_id
    else:
        canonical = json.dumps(
            {
                "origin": spec_dict.get("origin"),
                "destination": spec_dict.get("destination"),
                "start_date": spec_dict.get("start_date"),
                "end_date": spec_dict.get("end_date"),
                "transport_mode": spec_dict.get("transport_mode"),
                "stay_strategy": spec_dict.get("stay_strategy"),
                "bhk": spec_dict.get("destination_villa_bhk"),
                "budget_max": spec_dict.get("nightly_budget_max_inr"),
                "currency": spec_dict.get("currency", "INR"),
                "msgs_len": len(messages_list or []),
            },
            sort_keys=True,
        )
        tid = "ts-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]

    opt_copy = dict(optimization_dict)
    opt_copy["trip_id"] = tid
    title = f"{spec_dict.get('origin', 'Origin')} -> {spec_dict.get('destination', 'Destination')}"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO saved_trips (trip_id, created_at, title, spec_json, optimization_json, messages_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trip_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    title = excluded.title,
                    spec_json = excluded.spec_json,
                    optimization_json = excluded.optimization_json,
                    messages_json = excluded.messages_json
                """,
                (
                    tid,
                    now_iso,
                    title,
                    json.dumps(spec_dict, ensure_ascii=False),
                    json.dumps(opt_copy, ensure_ascii=False),
                    json.dumps(messages_list or [], ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return tid


def load_trip_snapshot(trip_id: str) -> Optional[Dict[str, Any]]:
    if not trip_id or not re.match(r"^ts-[a-z0-9]{6,16}$", trip_id):
        return None
    try:
        with _DB_LOCK:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT trip_id, created_at, title, spec_json, optimization_json, messages_json FROM saved_trips WHERE trip_id = ?",
                    (trip_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "trip_id": str(row["trip_id"]),
                    "created_at": str(row["created_at"]),
                    "title": str(row["title"]),
                    "spec": json.loads(row["spec_json"]),
                    "optimization": json.loads(row["optimization_json"]),
                    "messages": json.loads(row["messages_json"]),
                }
            finally:
                conn.close()
    except Exception:
        return None


def cache_stats() -> Dict[str, int]:
    now = time.time()
    try:
        with _DB_LOCK:
            conn = _connect()
            try:
                active_cache = conn.execute(
                    "SELECT COUNT(*) AS c FROM http_cache WHERE expires_at > ?",
                    (now,),
                ).fetchone()["c"]
                saved_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM saved_trips"
                ).fetchone()["c"]
                return {
                    "active_http_cache_entries": int(active_cache),
                    "persisted_shareable_trips": int(saved_count),
                }
            finally:
                conn.close()
    except Exception:
        return {"active_http_cache_entries": 0, "persisted_shareable_trips": 0}


class AsyncProviderRateLimiter:
    """Async per-provider minimum-spacing shield preventing upstream 429 bans."""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_call: Dict[str, float] = {}

    async def acquire(self, provider: str, min_interval_sec: float = 0.25) -> None:
        lock = self._locks.get(provider)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[provider] = lock
        async with lock:
            now = time.monotonic()
            prev = self._last_call.get(provider, 0.0)
            wait_for = min_interval_sec - (now - prev)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_call[provider] = time.monotonic()


RATE_LIMITER = AsyncProviderRateLimiter()
