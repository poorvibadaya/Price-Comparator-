"""
FastAPI backend — ultra-low latency tiered price comparator.

Run:
    python -m uvicorn server:app --host 0.0.0.0 --port 8080 --reload

Endpoints:
    POST /api/search            — search (cache → Tier1 → Tier2)
    GET  /api/search/stream     — SSE progressive stream
    GET  /api/config            — read runtime config
    PATCH /api/config           — update config at runtime
    GET  /api/health            — health + cache stats
    GET  /api/autocomplete      — Geoapify proxy
    GET  /api/geocode/reverse   — Geoapify reverse proxy
    GET  /api/compare           — compare.json reader
"""

import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.async_api import async_playwright
from pydantic import BaseModel

# ── Path setup (so compare.py / services / scrapers are importable) ──────────
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from services.cache import cache
from services.quickcompare_client import qc_client
from scrapers.pool import browser_pool
from orchestrator import race

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(_BACKEND_DIR, "server.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))
GEOAPIFY_API_KEY = os.environ.get("GEOAPIFY_API_KEY", "")

# ── Config ───────────────────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(_BACKEND_DIR, "config.json")


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("[Config] Failed to load config.json: %s", e)
        return {}


def _save_config(cfg: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


CONFIG: dict = _load_config()


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Server startup ===")

    cfg = CONFIG
    l1 = cfg.get("cache", {}).get("l1_max_size", 500)
    l1_ttl = cfg.get("cache", {}).get("l1_ttl_seconds", 120)
    l2_ttl = cfg.get("cache", {}).get("l2_redis_ttl_seconds", 600)
    redis_url = cfg.get("cache", {}).get("l2_redis_url", "redis://localhost:6379")
    max_ctx = cfg.get("browser_pool", {}).get("max_contexts", 3)

    cache.__init__(l1_max_size=l1, l1_ttl=l1_ttl, l2_ttl=l2_ttl, redis_url=redis_url)
    browser_pool._max_contexts = max_ctx

    await cache.startup()
    await qc_client.startup()

    async with async_playwright() as pw:
        await browser_pool.startup(pw)
        logger.info("=== Server ready on port %d ===", PORT)
        yield
        await browser_pool.shutdown()

    await cache.shutdown()
    await qc_client.shutdown()
    logger.info("=== Server shutdown ===")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Price Comparator API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ───────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    location: dict = {}
    platforms: list[str] = []  # kept for API compatibility; config drives actual platforms


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/api/search")
async def search_all_platforms(body: SearchRequest):
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    t0 = time.perf_counter()
    try:
        result = await race.search_with_race(query, body.location, CONFIG)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error("[API] /api/search FAILED  %.2fs  query='%s'  error=%s", elapsed, query, e)
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = time.perf_counter() - t0
    logger.info(
        "[API] /api/search OK  %.2fs  source=%-8s  products=%d  query='%s'",
        elapsed, result.get("source", "?"), len(result.get("products", [])), query,
    )
    return JSONResponse(content=result)


@app.get("/api/search/stream")
async def search_stream(query: str, lat: float = 0.0, lon: float = 0.0, city: str = ""):
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    location = {"city": city, "coordinates": {"lat": lat, "lng": lon}}

    async def event_generator():
        async for event in race.stream_search(query.strip(), location, CONFIG):
            data = json.dumps(event["data"], default=str)
            yield f"event: {event['type']}\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/config")
async def get_config():
    return JSONResponse(content=CONFIG)


@app.patch("/api/config")
async def update_config(request: Request):
    updates = await request.json()
    _deep_merge(CONFIG, updates)
    try:
        _save_config(CONFIG)
    except Exception as e:
        logger.warning("[Config] Failed to persist config.json: %s", e)
    return JSONResponse(content=CONFIG)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "cache": cache.l1_stats(),
        "redis": cache._redis_available,
    }


@app.get("/api/autocomplete")
async def geoapify_autocomplete(text: str = ""):
    text = text.strip()
    if not text:
        return JSONResponse(content=[])
    if not GEOAPIFY_API_KEY:
        raise HTTPException(status_code=500, detail="GEOAPIFY_API_KEY not set")
    url = (
        f"https://api.geoapify.com/v1/geocode/autocomplete"
        f"?text={quote(text)}&format=json&limit=8&filter=countrycode:in"
        f"&apiKey={GEOAPIFY_API_KEY}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return JSONResponse(content=r.json().get("results", []))
    except Exception as e:
        logger.error("[Geoapify] Autocomplete failed: %s", e)
        raise HTTPException(status_code=502, detail="Autocomplete request failed")


@app.get("/api/geocode/reverse")
async def geoapify_reverse(lat: float | None = None, lon: float | None = None):
    if lat is None or lon is None:
        raise HTTPException(status_code=400, detail="lat and lon required")
    if not GEOAPIFY_API_KEY:
        raise HTTPException(status_code=500, detail="GEOAPIFY_API_KEY not set")
    url = (
        f"https://api.geoapify.com/v1/geocode/reverse"
        f"?lat={lat}&lon={lon}&format=json&apiKey={GEOAPIFY_API_KEY}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            results = r.json().get("results", [])
            return JSONResponse(content=results[0] if results else {})
    except Exception as e:
        logger.error("[Geoapify] Reverse geocode failed: %s", e)
        raise HTTPException(status_code=502, detail="Reverse geocode failed")


@app.get("/api/compare")
async def get_compare_data():
    compare_path = os.path.join(_BACKEND_DIR, "compare.json")
    if not os.path.exists(compare_path):
        raise HTTPException(status_code=404, detail="compare.json not found")
    try:
        with open(compare_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        matched = data.get("products", [])
        return {
            "products": matched,
            "search_query": data.get("search_query", ""),
            "total_products": len(matched),
            "matched_products": data.get("matched_products", 0),
            "location": data.get("location", {}),
        }
    except Exception as e:
        logger.error("[Compare] Failed to load compare.json: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load comparison data")


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Server is running"}


@app.get("/")
async def root():
    return {
        "message": "Price Comparator API (FastAPI v2)",
        "version": "2.0.0",
        "endpoints": {
            "search": "POST /api/search",
            "stream": "GET /api/search/stream",
            "config_read": "GET /api/config",
            "config_update": "PATCH /api/config",
            "health": "GET /api/health",
            "autocomplete": "GET /api/autocomplete",
            "reverse_geocode": "GET /api/geocode/reverse",
            "compare": "GET /api/compare",
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────────
def _deep_merge(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    print(f"\n{'='*60}")
    print(f"Price Comparator API (FastAPI v2)")
    print(f"{'='*60}")
    print(f"Server running on: http://0.0.0.0:{PORT}")
    print(f"{'='*60}\n")

    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
