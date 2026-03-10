# Backend Architecture

## System Flow

```
POST /api/search  (or GET /api/search/stream)
        │
        ▼
[L1 LRU Cache]  ──── hit ──→  return (<1 ms)
        │ miss
        ▼
[L2 Redis Cache] ──── hit ──→  return (<5 ms)
        │ miss
        ▼
asyncio.wait([Tier1Task, Tier2Task], return_when=FIRST_COMPLETED)
        │
        ├─── Tier 1: QuickCompare API (~1–3 s)    ← httpx.AsyncClient
        └─── Tier 2: Parallel async scrapers       ← async_playwright + BrowserPool
                       zepto │ blinkit │ bigbasket │ dmart │ instamart
                             (all launched concurrently via asyncio.create_task)
        │
        ▼
First result with >= min_platforms_required platforms
  → cancel remaining tasks
        │
        ▼
compare_products_in_memory()  via asyncio.to_thread()
  (1 080-line compare.py — unchanged, runs in thread pool)
        │
        ▼
Write to L1 + L2 cache
        │
        ▼
{"products": MatchedProduct[], "source": "tier1|tier2|cache|partial"}
```

## Tier Strategy

| Tier | Mechanism | Typical Latency | Notes |
|------|-----------|-----------------|-------|
| L1 cache | In-process LRU (lru-dict) | < 1 ms | 500 entries, 2 min TTL |
| L2 cache | Redis SETEX | < 5 ms | 10 min TTL; graceful on Redis down |
| Tier 1 | QuickCompare REST API | 1–3 s | Disabled when `QUICKCOMPARE_API_URL` not set |
| Tier 2 | async_playwright scrapers | 8–15 s | All platforms launched in parallel |

## BrowserPool

`scrapers/pool.py` maintains:
- One **Chromium** browser (Zepto, Blinkit, Instamart, DMart)
- One **Firefox** browser (BigBasket — bot-detection avoidance)
- One `asyncio.Semaphore(max_contexts)` shared across both browsers

Each scraper acquires a context via `browser_pool.acquire_chromium()` or
`browser_pool.acquire_firefox()`, which is automatically closed after use.

## Race Strategy

```python
pending = {tier1_task, tier2_task}
while pending:
    done, pending = await asyncio.wait(pending, return_when=FIRST_COMPLETED)
    for task in done:
        result = task.result()
        if result and count_platforms(result) >= min_platforms:
            cancel(pending)
            use(result)
            break
```

## SSE Streaming

`GET /api/search/stream?query=...&lat=...&lon=...`

Events emitted as each scraper completes:
```
event: platform
data: {"platform": "zepto", "count": 24}

event: platform
data: {"platform": "blinkit", "count": 18}

event: done
data: {"products": [...], "source": "tier2"}
```

## File Layout

```
backend/
├── server.py                  # FastAPI app, lifespan, routes
├── config.json                # Runtime configuration
├── compare.py                 # 1 080-line matching engine (unchanged)
├── services/
│   ├── cache.py               # TieredCache (L1 LRU + L2 Redis)
│   └── quickcompare_client.py # Tier 1 httpx client
├── scrapers/
│   ├── pool.py                # BrowserPool (Chromium + Firefox)
│   ├── base.py                # Abstract AsyncScraper
│   ├── zepto.py
│   ├── blinkit.py
│   ├── instamart.py
│   ├── bigbasket.py
│   └── dmart.py               # httpx API first, Playwright fallback
├── orchestrator/
│   └── race.py                # Tier race + matching + cache write
└── ecommerce_platform/        # Legacy sync scrapers (reference only)
```
