"""
Tiered search orchestrator with proper prioritization and timing.

Priority order (strict cascade with Tier2 pre-warming):
  1. L1 LRU cache         → hit returns in  <1 ms
  2. L2 Redis cache       → hit returns in  <5 ms
  3. Tier 1 QuickCompare  → returns in  1–3 s  (if QUICKCOMPARE_API_URL set)
  4. Tier 2 Scrapers      → returns in  8–15 s (parallel, all enabled platforms)

Tier2 pre-warms (starts scrapers) simultaneously with Tier1 so that if Tier1
fails/times-out, scrapers are already running — no extra latency penalty.

Every stage logs its own timing so you can see exactly which path was taken
and how long each step took.
"""

import asyncio
import logging
import sys
import os
import time
from typing import AsyncIterator

# ── Import path ──────────────────────────────────────────────────────────────
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from compare import compare_products_in_memory, normalize_product_data, save_comparison_to_json
from services.cache import cache, build_cache_key
from services.quickcompare_client import qc_client
from scrapers import zepto, blinkit, instamart, bigbasket, dmart

logger = logging.getLogger(__name__)

# ── Platform registry ─────────────────────────────────────────────────────────
_PLATFORM_SCRAPERS: dict = {
    "zepto":            zepto.scrape,
    "blinkit":          blinkit.scrape,
    "swiggy-instamart": instamart.scrape,
    "bigbasket":        bigbasket.scrape,
    "dmart":            dmart.scrape,
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _count_platforms(products: list) -> int:
    """Count distinct non-empty platform names in a product list."""
    return len({p.get("platform", "").strip() for p in products if p.get("platform")})


def _enabled_scrapers(config: dict) -> dict:
    """Return {platform_name: scrape_fn} for all enabled platforms."""
    return {
        name: _PLATFORM_SCRAPERS[name]
        for name, cfg in config.get("platforms", {}).items()
        if cfg.get("enabled", False) and name in _PLATFORM_SCRAPERS
    }


# ── Tier 1: QuickCompare ──────────────────────────────────────────────────────
async def _tier1_search(query: str, location: dict, config: dict) -> list | None:
    """
    Call QuickCompare API.
    Returns list of raw products on success, None on any failure/timeout.
    """
    timeout = config.get("race", {}).get("tier1_timeout_seconds", 5)
    try:
        result = await asyncio.wait_for(
            qc_client.search(query, location, timeout=timeout),
            timeout=timeout + 1,  # outer safety margin
        )
        return result  # None if API not configured or failed
    except asyncio.TimeoutError:
        logger.warning("[Tier1] Timed out after %ds for '%s'", timeout, query)
        return None
    except asyncio.CancelledError:
        raise  # propagate cancellation
    except Exception as e:
        logger.warning("[Tier1] Error for '%s': %s", query, e)
        return None


# ── Tier 2: Parallel scrapers ─────────────────────────────────────────────────
async def _timed_scrape(
    platform_name: str, fn, query: str, location: dict
) -> tuple[str, list, float]:
    """Run one scraper and return (platform_name, products, elapsed_seconds)."""
    t = time.perf_counter()
    try:
        products = await fn(query, location)
        elapsed = time.perf_counter() - t
        return platform_name, products or [], elapsed
    except asyncio.CancelledError:
        raise
    except Exception as e:
        elapsed = time.perf_counter() - t
        logger.error("[Tier2] [ERR] %s failed in %.2fs: %s", platform_name, elapsed, e)
        return platform_name, [], elapsed


async def _tier2_search(query: str, location: dict, config: dict) -> list:
    """
    Launch all enabled scrapers in parallel with early-return.

    Returns merged product list when:
      a) min_platforms_required have responded (early-return: gives remaining
         scrapers a short grace period before cancelling), OR
      b) all scrapers complete, OR
      c) tier2_timeout is hit.

    Early-return means we don't wait for the slowest scraper if enough
    platforms have already delivered results.
    """
    scrapers = _enabled_scrapers(config)
    tier2_timeout = config.get("race", {}).get("tier2_timeout_seconds", 10)
    min_platforms = config.get("race", {}).get("min_platforms_required", 2)
    early_return_grace = config.get("race", {}).get("early_return_grace_seconds", 2)

    if not scrapers:
        logger.warning("[Tier2] No scrapers enabled for '%s'", query)
        return []

    t_start = time.perf_counter()
    logger.info(
        "[Tier2] Launching %d scrapers in parallel: %s (timeout=%ds, early-return after %d platforms + %ds grace)",
        len(scrapers),
        list(scrapers.keys()),
        tier2_timeout,
        min_platforms,
        early_return_grace,
    )

    tasks: dict[asyncio.Task, str] = {}
    for name, fn in scrapers.items():
        t = asyncio.create_task(_timed_scrape(name, fn, query, location))
        tasks[t] = name

    all_products: list = []
    pending = set(tasks.keys())
    responded_platforms: set[str] = set()
    early_return_deadline: float | None = None  # set when min_platforms reached

    try:
        deadline = asyncio.get_event_loop().time() + tier2_timeout
        while pending:
            now = asyncio.get_event_loop().time()
            # Use the earlier of: overall deadline or early-return deadline
            effective_deadline = deadline
            if early_return_deadline is not None:
                effective_deadline = min(deadline, early_return_deadline)

            remaining = effective_deadline - now
            if remaining <= 0:
                if early_return_deadline is not None and now >= early_return_deadline:
                    logger.info(
                        "[Tier2] Early-return: %d platforms responded, grace period expired — cancelling %d remaining",
                        len(responded_platforms), len(pending),
                    )
                else:
                    logger.warning(
                        "[Tier2] Timeout (%ds) for '%s' — cancelling %d scrapers",
                        tier2_timeout, query, len(pending),
                    )
                for t in pending:
                    t.cancel()
                break

            try:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                for t in pending:
                    t.cancel()
                raise

            if not done:
                for t in pending:
                    t.cancel()
                break

            for task in done:
                platform_name = tasks[task]
                try:
                    _, products, elapsed = task.result()
                    count = len(products)
                    all_products.extend(products)
                    if count:
                        responded_platforms.add(platform_name)
                        logger.info(
                            "[Tier2] [OK] %-20s  %3d products  %.2fs",
                            platform_name, count, elapsed,
                        )
                    else:
                        logger.info(
                            "[Tier2] [ 0] %-20s    0 products  %.2fs",
                            platform_name, elapsed,
                        )
                except asyncio.CancelledError:
                    logger.info("[Tier2] [--] %s cancelled", platform_name)
                except Exception as e:
                    logger.error("[Tier2] [ERR] %s result error: %s", platform_name, e)

            # Check early-return condition
            if (
                early_return_deadline is None
                and len(responded_platforms) >= min_platforms
            ):
                early_return_deadline = asyncio.get_event_loop().time() + early_return_grace
                logger.info(
                    "[Tier2] Early-return triggered: %d/%d platforms responded, "
                    "giving remaining %d scrapers %ds grace",
                    len(responded_platforms), min_platforms,
                    len(pending), early_return_grace,
                )

    except asyncio.CancelledError:
        for t in pending:
            t.cancel()
        raise

    elapsed_total = time.perf_counter() - t_start
    n_platforms = _count_platforms(all_products)
    logger.info(
        "[Tier2] Completed in %.2fs — %d products from %d platforms%s",
        elapsed_total,
        len(all_products),
        n_platforms,
        " (early-return)" if early_return_deadline is not None else "",
    )
    return all_products


# ── Matching ──────────────────────────────────────────────────────────────────
async def _run_matching(
    raw_products: list, query: str, location: dict, config: dict
) -> list:
    """Normalize then run compare.py matching in a thread pool."""
    matching_config = config.get("matching", {})

    # Normalize platform/price fields (sync, fast)
    normalized = []
    for p in raw_products:
        try:
            normalized.append(normalize_product_data(p, p.get("platform", "unknown")))
        except Exception:
            normalized.append(p)

    try:
        matched = await asyncio.to_thread(
            compare_products_in_memory, normalized, query, location, matching_config
        )
    except Exception as e:
        logger.error("[Matching] compare_products_in_memory failed: %s", e)
        matched = []

    # Persist to compare.json for debugging (best-effort)
    try:
        await asyncio.to_thread(save_comparison_to_json, matched or [], query, location)
    except Exception:
        pass

    return matched or []


# ── Main search entry point ───────────────────────────────────────────────────
async def search_with_race(query: str, location: dict, config: dict) -> dict:
    """
    Full tiered search with detailed timing output.

    Cascade order:
      cache → Tier1 (QuickCompare) → Tier2 (scrapers)

    Tier2 is pre-warmed immediately so its scrapers are running while
    Tier1 is being awaited — no latency penalty on Tier1 failure.
    """
    t_request = time.perf_counter()
    cache_key = build_cache_key(query, location)
    tiers = config.get("tiers", {})
    race_cfg = config.get("race", {})
    min_platforms = race_cfg.get("min_platforms_required", 2)
    t1_timeout = race_cfg.get("tier1_timeout_seconds", 5)
    t2_timeout = race_cfg.get("tier2_timeout_seconds", 20)
    tier1_on = tiers.get("tier1_quickcompare", True)
    tier2_on = tiers.get("tier2_scrapers", True)
    enabled_platforms = list(_enabled_scrapers(config).keys()) if tier2_on else []

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("[Search] START  query='%s'  location=%s", query, _loc_str(location))

    # ── 0. Log execution plan ─────────────────────────────────────────────────
    cache_stats = cache.l1_stats()
    logger.info("[Search] PLAN:")
    logger.info("[Search]   step 1 → L1 cache    (entries=%d/%d)",
                cache_stats["size"], cache_stats["max_size"])
    logger.info("[Search]   step 2 → L2 Redis    (%s)",
                "connected" if cache._redis_available else "unavailable — skipped")
    logger.info("[Search]   step 3 → Tier1 QuickCompare  %s  timeout=%ds",
                "ENABLED" if tier1_on else "DISABLED — skipped", t1_timeout)
    logger.info("[Search]   step 4 → Tier2 Scrapers      %s  [%s]  timeout=%ds",
                "ENABLED" if tier2_on else "DISABLED — skipped",
                ", ".join(enabled_platforms) if enabled_platforms else "none",
                t2_timeout)
    logger.info("[Search]   min platforms for success: %d", min_platforms)

    # ── 1. Cache check ────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    cached = await cache.get(cache_key)
    if cached:
        t_cache = (time.perf_counter() - t0) * 1000
        logger.info("[Search] → CACHE HIT  %.1fms  (original source=%s)",
                    t_cache, cached.get("source", "?"))
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return {**cached, "source": "cache"}

    logger.info("[Search] → Cache MISS (L1+L2)  %.1fms — continuing to live fetch",
                (time.perf_counter() - t0) * 1000)

    raw_products: list = []
    source = "partial"
    tier2_task: asyncio.Task | None = None
    t_tier1: float = 0.0
    t_tier2: float = 0.0

    # ── 2. Pre-warm Tier2 scrapers immediately (runs in background) ───────────
    if tier2_on:
        tier2_task = asyncio.create_task(_tier2_search(query, location, config))
        logger.info("[Search] → Tier2 scrapers pre-warmed (running in background)")

    # ── 3. Try Tier1 (QuickCompare) ───────────────────────────────────────────
    if tier1_on:
        t_t1 = time.perf_counter()
        logger.info("[Search] Trying Tier1 QuickCompare…")
        tier1_result = await _tier1_search(query, location, config)
        t_tier1 = time.perf_counter() - t_t1

        if tier1_result and _count_platforms(tier1_result) >= min_platforms:
            n_plat = _count_platforms(tier1_result)
            logger.info(
                "[Search] TIER1 SUCCESS  %.2fs  %d products  %d platforms",
                t_tier1, len(tier1_result), n_plat,
            )
            # Cancel Tier2 — we don't need it
            if tier2_task and not tier2_task.done():
                tier2_task.cancel()
                logger.info("[Search] Tier2 cancelled (Tier1 won)")
            raw_products = tier1_result
            source = "tier1"
        else:
            n_plat = _count_platforms(tier1_result) if tier1_result else 0
            logger.warning(
                "[Search] TIER1 FAIL  %.2fs  %d products  %d/%d platforms — falling back to Tier2",
                t_tier1,
                len(tier1_result) if tier1_result else 0,
                n_plat,
                min_platforms,
            )

    # ── 4. Tier2 (scrapers) fallback ──────────────────────────────────────────
    if not raw_products and tier2_task is not None:
        t_t2 = time.perf_counter()
        logger.info("[Search] Awaiting Tier2 scrapers…")
        try:
            raw_products = await tier2_task
        except asyncio.CancelledError:
            raw_products = []
        except Exception as e:
            logger.error("[Search] Tier2 task error: %s", e)
            raw_products = []
        t_tier2 = time.perf_counter() - t_t2
        source = "tier2"
        logger.info(
            "[Search] TIER2 DONE  +%.2fs  %d products  %d platforms",
            t_tier2,
            len(raw_products),
            _count_platforms(raw_products),
        )
    elif not raw_products and tier2_task is None:
        logger.warning("[Search] Both tiers disabled — no results")

    if not raw_products:
        t_total = time.perf_counter() - t_request
        logger.warning("[Search] NO RESULTS for '%s'  total=%.2fs", query, t_total)
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return {
            "products": [],
            "source": "partial",
            "latency_ms": round(t_total * 1000),
            "timing": {"tier1_s": round(t_tier1, 3), "tier2_s": round(t_tier2, 3)},
        }

    # ── 5. Product matching ────────────────────────────────────────────────────
    t_m = time.perf_counter()
    logger.info("[Search] Running product matching on %d raw products…", len(raw_products))
    matched = await _run_matching(raw_products, query, location, config)
    t_match = time.perf_counter() - t_m
    logger.info("[Search] Matching done  %.2fs  → %d matched groups", t_match, len(matched))

    # ── 6. Cache write + response ─────────────────────────────────────────────
    t_total = time.perf_counter() - t_request
    response = {
        "products": matched,
        "source": source,
        "latency_ms": round(t_total * 1000),
        "timing": {
            "tier1_s": round(t_tier1, 3),
            "tier2_s": round(t_tier2, 3),
            "matching_s": round(t_match, 3),
            "total_s": round(t_total, 3),
        },
    }
    await cache.set(cache_key, response)

    logger.info(
        "[Search] COMPLETE  query='%s'  source=%-8s  products=%d  "
        "total=%.2fs  (tier1=%.2fs  tier2=%.2fs  match=%.2fs)",
        query, source, len(matched),
        t_total, t_tier1, t_tier2, t_match,
    )
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return response


# ── SSE streaming ─────────────────────────────────────────────────────────────
async def stream_search(
    query: str, location: dict, config: dict
) -> AsyncIterator[dict]:
    """
    Async generator for the SSE endpoint.

    Emits:
      - start:    search begun
      - cache:    result served from cache
      - tier1:    QuickCompare result available
      - platform: individual scraper result (Tier2)
      - matching: matching started
      - done:     final products ready

    All events include a timestamp_ms field.
    """
    t_start = time.perf_counter()
    cache_key = build_cache_key(query, location)
    tiers = config.get("tiers", {})
    min_platforms = config.get("race", {}).get("min_platforms_required", 2)

    def ms() -> int:
        return round((time.perf_counter() - t_start) * 1000)

    yield {"type": "start", "data": {"query": query, "timestamp_ms": 0}}

    # Cache check
    cached = await cache.get(cache_key)
    if cached:
        yield {"type": "cache", "data": {**cached, "timestamp_ms": ms()}}
        return

    all_products: list = []

    # Tier 1: QuickCompare
    if tiers.get("tier1_quickcompare", True):
        tier1_result = await _tier1_search(query, location, config)
        if tier1_result and _count_platforms(tier1_result) >= min_platforms:
            yield {
                "type": "tier1",
                "data": {
                    "count": len(tier1_result),
                    "platforms": _count_platforms(tier1_result),
                    "timestamp_ms": ms(),
                },
            }
            all_products = tier1_result

    # Tier 2: Scrapers (if Tier1 insufficient or disabled)
    if not all_products and tiers.get("tier2_scrapers", True):
        scrapers = _enabled_scrapers(config)
        tasks: dict[asyncio.Task, str] = {}
        for name, fn in scrapers.items():
            t = asyncio.create_task(_timed_scrape(name, fn, query, location))
            tasks[t] = name

        pending = set(tasks.keys())
        tier2_timeout = config.get("race", {}).get("tier2_timeout_seconds", 20)
        deadline = asyncio.get_event_loop().time() + tier2_timeout

        while pending:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                for t in pending:
                    t.cancel()
                break
            done, pending = await asyncio.wait(
                pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                for t in pending:
                    t.cancel()
                break
            for task in done:
                platform_name = tasks[task]
                try:
                    _, products, elapsed = task.result()
                    all_products.extend(products)
                    yield {
                        "type": "platform",
                        "data": {
                            "platform": platform_name,
                            "count": len(products),
                            "elapsed_s": round(elapsed, 2),
                            "timestamp_ms": ms(),
                        },
                    }
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    yield {
                        "type": "error",
                        "data": {"platform": platform_name, "error": str(e), "timestamp_ms": ms()},
                    }

    # Matching
    yield {"type": "matching", "data": {"raw_count": len(all_products), "timestamp_ms": ms()}}
    matched = await _run_matching(all_products, query, location, config)

    t_total = time.perf_counter() - t_start
    response = {
        "products": matched,
        "source": "tier2" if all_products else "partial",
        "latency_ms": round(t_total * 1000),
    }
    await cache.set(cache_key, response)

    yield {"type": "done", "data": {**response, "timestamp_ms": ms()}}


# ── Utility ───────────────────────────────────────────────────────────────────
def _loc_str(location: dict) -> str:
    city = location.get("city", "")
    coords = location.get("coordinates", {})
    lat = coords.get("lat", "")
    lon = coords.get("lng", "")
    parts = [x for x in [city, f"{lat},{lon}" if lat and lon else ""] if x]
    return " / ".join(parts) or str(location)
