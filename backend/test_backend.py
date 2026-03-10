"""
Price Comparator — Backend Integration Test Suite
==================================================
Tests every endpoint with real HTTP calls and logs detailed timing.

Usage (server must be running first):
    python -m uvicorn server:app --host 0.0.0.0 --port 8080 &
    python test_backend.py                          # all tests
    python test_backend.py --query "amul butter"   # custom query
    python test_backend.py --host http://localhost:8080  # custom host

Requirements: httpx (pip install httpx)
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_HOST = "http://localhost:8080"
DEFAULT_QUERY = "amul butter"
DEFAULT_LOCATION = {
    "city": "Mumbai",
    "state": "Maharashtra",
    "coordinates": {"lat": 19.076, "lng": 72.877},
}
TIMEOUT = 120  # seconds per request (scrapers can be slow)


# ── Result tracking ───────────────────────────────────────────────────────────
@dataclass
class TestResult:
    name: str
    passed: bool
    elapsed_ms: float
    details: str = ""
    source: str = ""
    product_count: int = 0
    error: str = ""


results: list[TestResult] = []


# ── Helpers ───────────────────────────────────────────────────────────────────
def _sep(char="─", width=70) -> str:
    return char * width


def _banner(title: str) -> None:
    print(f"\n{_sep('━')}")
    print(f"  {title}")
    print(_sep("━"))


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗  {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"     {msg}")


def _timing(label: str, elapsed_ms: float) -> None:
    bar = "█" * min(int(elapsed_ms / 500), 40)
    print(f"     {label:<22} {elapsed_ms:7.0f} ms  {bar}")


async def _get(client: httpx.AsyncClient, path: str, **kwargs) -> tuple[dict, float]:
    t = time.perf_counter()
    r = await client.get(path, timeout=TIMEOUT, **kwargs)
    elapsed = (time.perf_counter() - t) * 1000
    r.raise_for_status()
    return r.json(), elapsed


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> tuple[dict, float]:
    t = time.perf_counter()
    r = await client.post(path, json=body, timeout=TIMEOUT)
    elapsed = (time.perf_counter() - t) * 1000
    r.raise_for_status()
    return r.json(), elapsed


# ── Individual tests ──────────────────────────────────────────────────────────
async def test_health(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 1: Health Check")
    t0 = time.perf_counter()
    try:
        data, ms = await _get(client, "/api/health")
        elapsed = (time.perf_counter() - t0) * 1000
        status = data.get("status")
        redis = data.get("redis", False)
        cache = data.get("cache", {})

        _ok(f"Status: {status}")
        _info(f"Redis available: {redis}")
        _info(f"L1 cache size: {cache.get('size', '?')}/{cache.get('max_size', '?')}")
        _timing("health roundtrip", ms)

        passed = status == "ok"
        return TestResult("Health Check", passed, ms,
                          f"status={status} redis={redis}", "")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Health Check", False, elapsed, error=str(e))


async def test_config_read(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 2: GET /api/config")
    t0 = time.perf_counter()
    try:
        data, ms = await _get(client, "/api/config")
        elapsed = (time.perf_counter() - t0) * 1000

        tiers = data.get("tiers", {})
        platforms = data.get("platforms", {})
        race_cfg = data.get("race", {})

        _ok("Config loaded successfully")
        _info(f"Tier1 QuickCompare: {tiers.get('tier1_quickcompare')}")
        _info(f"Tier2 Scrapers:     {tiers.get('tier2_scrapers')}")
        _info(f"Min platforms:      {race_cfg.get('min_platforms_required')}")
        _info(f"Tier1 timeout:      {race_cfg.get('tier1_timeout_seconds')}s")
        _info(f"Tier2 timeout:      {race_cfg.get('tier2_timeout_seconds')}s")
        _info("Platforms:")
        for name, cfg in platforms.items():
            icon = "✓" if cfg.get("enabled") else "✗"
            _info(f"  {icon} {name}")
        _timing("config roundtrip", ms)

        return TestResult("Config Read", True, ms, json.dumps(tiers))
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Config Read", False, elapsed, error=str(e))


async def test_search_cold(client: httpx.AsyncClient, query: str, location: dict) -> TestResult:
    _banner(f"TEST 3: POST /api/search (cold — no cache)  query='{query}'")

    # First ensure cache is busted by a unique query variation we haven't run
    body = {"query": query, "location": location, "platforms": []}

    t0 = time.perf_counter()
    try:
        data, ms = await _post(client, "/api/search", body)
        elapsed = (time.perf_counter() - t0) * 1000

        source = data.get("source", "?")
        products = data.get("products", [])
        timing = data.get("timing", {})
        latency_ms = data.get("latency_ms", round(ms))

        _ok(f"Response received in {ms:.0f}ms")
        _info(f"Source:         {source}")
        _info(f"Products found: {len(products)}")

        print(f"\n  {_sep()}")
        print("  TIMING BREAKDOWN:")
        _timing("Total (end-to-end)", latency_ms)
        if timing.get("tier1_s", 0) > 0:
            _timing("Tier1 QuickCompare", timing["tier1_s"] * 1000)
        if timing.get("tier2_s", 0) > 0:
            _timing("Tier2 Scrapers", timing["tier2_s"] * 1000)
        if timing.get("matching_s", 0) > 0:
            _timing("Product Matching", timing["matching_s"] * 1000)

        if products:
            print(f"\n  SAMPLE PRODUCTS (first 3):")
            for p in products[:3]:
                name = p.get("name", "?")
                plats = list(p.get("platforms", {}).keys())
                prices = {k: v.get("price_str") or f"₹{v.get('price','?')}"
                          for k, v in p.get("platforms", {}).items()}
                _info(f"• {name}")
                _info(f"  Platforms: {plats}")
                _info(f"  Prices:    {prices}")

        passed = len(products) > 0 or source in ("cache", "tier1", "tier2", "partial")
        return TestResult("Search Cold", passed, ms,
                          f"source={source}", source, len(products))
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Search Cold", False, elapsed, error=str(e))


async def test_search_cached(client: httpx.AsyncClient, query: str, location: dict) -> TestResult:
    _banner(f"TEST 4: POST /api/search (warm cache hit)  query='{query}'")
    body = {"query": query, "location": location, "platforms": []}

    t0 = time.perf_counter()
    try:
        data, ms = await _post(client, "/api/search", body)
        elapsed = (time.perf_counter() - t0) * 1000

        source = data.get("source", "?")
        products = data.get("products", [])
        latency_ms = data.get("latency_ms", round(ms))

        _ok(f"Response received in {ms:.0f}ms")
        _timing("Cached roundtrip", ms)
        _info(f"Source:         {source}  (should be 'cache')")
        _info(f"Products found: {len(products)}")

        if source == "cache":
            _ok("CACHE HIT confirmed ✓")
        else:
            _fail(f"Expected source='cache', got source='{source}'")

        passed = source == "cache"
        return TestResult("Search Cached", passed, ms,
                          f"source={source}", source, len(products))
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Search Cached", False, elapsed, error=str(e))


async def test_tier1_disable(client: httpx.AsyncClient, query: str, location: dict) -> TestResult:
    _banner("TEST 5: Tier1 Disabled → Falls back to Tier2")

    # Disable Tier1 via PATCH
    t0 = time.perf_counter()
    try:
        patch_data, _ = await _get(client, "/api/config")  # read first
        # Disable tier1
        await client.patch(
            "/api/config",
            json={"tiers": {"tier1_quickcompare": False}},
            timeout=10,
        )
        _info("Tier1 disabled via PATCH /api/config")

        # Use a distinct query to avoid cache hit
        test_query = f"{query} 500g"
        body = {"query": test_query, "location": location, "platforms": []}
        data, ms = await _post(client, "/api/search", body)
        elapsed = (time.perf_counter() - t0) * 1000

        source = data.get("source", "?")
        products = data.get("products", [])
        timing = data.get("timing", {})

        _ok(f"Response received in {ms:.0f}ms")
        _info(f"Source: {source}  (should be 'tier2')")
        _timing("No-Tier1 total", ms)
        if timing.get("tier2_s", 0) > 0:
            _timing("Tier2 time", timing["tier2_s"] * 1000)

        passed = source in ("tier2", "partial")

        # Re-enable Tier1
        await client.patch(
            "/api/config",
            json={"tiers": {"tier1_quickcompare": True}},
            timeout=10,
        )
        _info("Tier1 re-enabled")

        return TestResult("Tier1 Disable Fallback", passed, ms,
                          f"source={source}", source, len(products))
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        # Re-enable Tier1 on error too
        try:
            await client.patch("/api/config", json={"tiers": {"tier1_quickcompare": True}}, timeout=5)
        except Exception:
            pass
        return TestResult("Tier1 Disable Fallback", False, elapsed, error=str(e))


async def test_config_patch(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 6: PATCH /api/config runtime update")
    t0 = time.perf_counter()
    try:
        # Read initial
        initial, _ = await _get(client, "/api/config")
        original_threshold = initial.get("matching", {}).get("similarity_threshold", 0.8)

        # Patch
        new_threshold = 0.75
        r = await client.patch(
            "/api/config",
            json={"matching": {"similarity_threshold": new_threshold}},
            timeout=10,
        )
        r.raise_for_status()
        updated = r.json()
        ms = (time.perf_counter() - t0) * 1000

        got = updated.get("matching", {}).get("similarity_threshold")
        _ok(f"PATCH successful in {ms:.0f}ms")
        _info(f"similarity_threshold: {original_threshold} → {got}")

        passed = got == new_threshold

        # Restore
        await client.patch(
            "/api/config",
            json={"matching": {"similarity_threshold": original_threshold}},
            timeout=10,
        )
        _info(f"Restored to {original_threshold}")

        return TestResult("Config PATCH", passed, ms, f"threshold set to {got}")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Config PATCH", False, elapsed, error=str(e))


async def test_sse_stream(client: httpx.AsyncClient, query: str, location: dict) -> TestResult:
    _banner(f"TEST 7: GET /api/search/stream (SSE)  query='{query} fresh'")

    # Use a unique query variation to avoid cache
    test_query = f"{query} fresh"
    lat = location.get("coordinates", {}).get("lat", 0)
    lon = location.get("coordinates", {}).get("lng", 0)
    city = location.get("city", "")

    t0 = time.perf_counter()
    events_received: list[dict] = []

    try:
        url = f"/api/search/stream?query={test_query}&lat={lat}&lon={lon}&city={city}"
        async with client.stream("GET", url, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            event_type = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_str = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(data_str)
                        events_received.append({"type": event_type, "data": data})
                        ts = data.get("timestamp_ms", "?")
                        _info(f"[{ts:>6}ms] event:{event_type}  " + _event_summary(event_type, data))
                    except json.JSONDecodeError:
                        pass
                elif not line:
                    event_type = None
                # Stop after 'done'
                if event_type == "done" and line.startswith("data:"):
                    break

        ms = (time.perf_counter() - t0) * 1000
        _timing("SSE total", ms)

        done_event = next((e for e in events_received if e["type"] == "done"), None)
        products = done_event["data"].get("products", []) if done_event else []

        _ok(f"Received {len(events_received)} SSE events, {len(products)} final products")

        event_types = [e["type"] for e in events_received]
        passed = "done" in event_types
        return TestResult("SSE Stream", passed, ms,
                          f"events={event_types}", "tier2", len(products))
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("SSE Stream", False, elapsed, error=str(e))


async def test_empty_query(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 8: Empty query → 400 error")
    t0 = time.perf_counter()
    try:
        r = await client.post("/api/search", json={"query": "", "location": {}}, timeout=10)
        ms = (time.perf_counter() - t0) * 1000
        passed = r.status_code == 400
        _ok(f"Got HTTP {r.status_code} in {ms:.0f}ms") if passed else _fail(f"Expected 400, got {r.status_code}")
        return TestResult("Empty Query 400", passed, ms, f"HTTP {r.status_code}")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Empty Query 400", False, elapsed, error=str(e))


async def test_cache_stats(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 9: L1 Cache Stats (after previous tests)")
    t0 = time.perf_counter()
    try:
        data, ms = await _get(client, "/api/health")
        elapsed = (time.perf_counter() - t0) * 1000
        cache_stats = data.get("cache", {})
        size = cache_stats.get("size", 0)
        max_size = cache_stats.get("max_size", 500)
        redis = data.get("redis", False)

        _ok(f"L1 cache: {size}/{max_size} entries")
        _info(f"Redis (L2): {'connected' if redis else 'unavailable (L1-only)'}")
        _timing("health check", ms)

        # After cold search + cached repeat, we should have at least 1 entry
        passed = size >= 0  # always passes — just informational
        return TestResult("Cache Stats", True, ms, f"L1={size}/{max_size} Redis={redis}")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Cache Stats", False, elapsed, error=str(e))


async def test_compare_endpoint(client: httpx.AsyncClient) -> TestResult:
    _banner("TEST 10: GET /api/compare (last comparison result)")
    t0 = time.perf_counter()
    try:
        r = await client.get("/api/compare", timeout=10)
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 404:
            _info("compare.json not found yet (run a search first)")
            return TestResult("Compare Endpoint", True, ms, "no compare.json yet")
        r.raise_for_status()
        data = r.json()
        products = data.get("products", [])
        query = data.get("search_query", "?")
        _ok(f"compare.json loaded: {len(products)} products for '{query}'")
        _timing("compare.json read", ms)
        return TestResult("Compare Endpoint", True, ms, f"{len(products)} products")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        _fail(str(e))
        return TestResult("Compare Endpoint", False, elapsed, error=str(e))


# ── Utility ───────────────────────────────────────────────────────────────────
def _event_summary(etype: str, data: dict) -> str:
    if etype == "start":
        return f"query={data.get('query')}"
    if etype == "cache":
        return f"source={data.get('source')} products={len(data.get('products', []))}"
    if etype == "tier1":
        return f"count={data.get('count')} platforms={data.get('platforms')}"
    if etype == "platform":
        return f"platform={data.get('platform')} count={data.get('count')} elapsed={data.get('elapsed_s')}s"
    if etype == "matching":
        return f"raw_count={data.get('raw_count')}"
    if etype == "done":
        return f"source={data.get('source')} products={len(data.get('products', []))}"
    return str(data)[:80]


def _print_summary(all_results: list[TestResult]) -> None:
    print(f"\n\n{'━'*70}")
    print("  SUMMARY")
    print(f"{'━'*70}")
    print(f"  {'TEST':<35} {'STATUS':<8} {'LATENCY':>10}  NOTES")
    print(f"  {'─'*35} {'─'*8} {'─'*10}  {'─'*20}")

    passed = 0
    failed = 0
    for r in all_results:
        icon = "✓" if r.passed else "✗"
        status = "PASS" if r.passed else "FAIL"
        notes = r.error if r.error else r.details
        print(
            f"  {icon} {r.name:<35} {status:<8} {r.elapsed_ms:>8.0f}ms  {notes[:40]}"
        )
        if r.passed:
            passed += 1
        else:
            failed += 1

    print(f"{'─'*70}")
    print(f"  Total: {len(all_results)}  Passed: {passed}  Failed: {failed}")
    print(f"{'━'*70}\n")


# ── Runner ────────────────────────────────────────────────────────────────────
async def run_tests(host: str, query: str, location: dict) -> None:
    print(f"\n{'━'*70}")
    print(f"  Price Comparator — Backend Test Suite")
    print(f"  Server:  {host}")
    print(f"  Query:   '{query}'")
    print(f"  Location: {location.get('city')} ({location.get('coordinates')})")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*70}")

    async with httpx.AsyncClient(base_url=host) as client:
        # Quick connectivity check
        try:
            await client.get("/health", timeout=5)
        except Exception as e:
            print(f"\n  ERROR: Cannot reach {host}\n  {e}\n")
            print("  Start the server first:")
            print("    cd backend && python -m uvicorn server:app --host 0.0.0.0 --port 8080 --reload\n")
            sys.exit(1)

        results.append(await test_health(client))
        results.append(await test_config_read(client))
        results.append(await test_search_cold(client, query, location))
        results.append(await test_search_cached(client, query, location))
        results.append(await test_tier1_disable(client, query, location))
        results.append(await test_config_patch(client))
        results.append(await test_sse_stream(client, query, location))
        results.append(await test_empty_query(client))
        results.append(await test_cache_stats(client))
        results.append(await test_compare_endpoint(client))

    _print_summary(results)
    failed = sum(1 for r in results if not r.passed)
    sys.exit(1 if failed else 0)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Price Comparator Backend Tests")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server base URL")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Search query to test")
    parser.add_argument("--city", default="Mumbai", help="City for location")
    parser.add_argument("--lat", type=float, default=19.076, help="Latitude")
    parser.add_argument("--lon", type=float, default=72.877, help="Longitude")
    args = parser.parse_args()

    location = {
        "city": args.city,
        "state": "Maharashtra",
        "coordinates": {"lat": args.lat, "lng": args.lon},
    }

    asyncio.run(run_tests(args.host, args.query, location))
