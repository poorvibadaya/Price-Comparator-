# Backend Engine (Python, FastAPI, Playwright + httpx)

This folder contains the core backend engine for the Price-Comparator application. It serves as a centralized API that both the **React Web App** (root folder) and the **Expo Mobile App** (`groease-mobile/`) communicate with.

## Project Context
- **`/` (Root Folder)**: React Web Application (Vite + React).
- **`/groease-mobile/`**: React Native Expo Mobile App.
- **`/backend/`** (This folder): Python API handling all business logic and scraping.

## Architecture

### Tiered Search (< 5s target)
```
Request → L1 cache (<1ms) → L2 Redis (<5ms) → Tier1 QuickCompare (1-3s) → Tier2 Scrapers
```

**Tier2 Scrapers** run in parallel with early-return:
| Platform | Method | Speed |
|----------|--------|-------|
| DMart | httpx API (`digital.dmart.in`) | ~0.7s |
| BigBasket | httpx API (`listing-svc/v2/products`) | ~0.8s |
| Blinkit | Playwright + API response interception | ~7s |
| Zepto | Playwright + API response interception | ~10s |

Once **2 platforms** respond (default), remaining scrapers get a 2s grace period before cancellation. Typical cold search: **3-4 seconds**.

### Key Files
| File | Role |
|------|------|
| `server.py` | FastAPI app entry point |
| `config.json` | Runtime config (tiers, cache, platforms, race) |
| `orchestrator/race.py` | Tiered search with early-return + SSE streaming |
| `services/cache.py` | L1 LRU + L2 Redis two-level cache |
| `services/quickcompare_client.py` | Tier 1 httpx client |
| `scrapers/pool.py` | BrowserPool: Chromium + Firefox, Semaphore(5) |
| `scrapers/{zepto,blinkit,bigbasket,dmart}.py` | Async scrapers |
| `compare.py` | Product matching engine (1080 lines) |
| `test_backend.py` | 10-test integration suite |

## Environment Variables
Create a `.env` file in this `backend/` directory:
```env
GEOAPIFY_API_KEY=your_api_key_here
# Optional: enables Tier 1 fast path
QUICKCOMPARE_API_URL=https://your-quickcompare-instance.com
```

## How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers (required for Blinkit/Zepto scrapers)
playwright install chromium firefox

# 3. Start Redis (required for L2 cache)
redis-server &

# 4. Start the FastAPI server
python -m uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```

The server runs on `http://0.0.0.0:8080/`.

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/search` | Search products (cache → Tier1 → Tier2) |
| GET | `/api/search/stream` | SSE progressive search stream |
| GET | `/api/config` | Read runtime config |
| PATCH | `/api/config` | Update config at runtime |
| GET | `/api/health` | Health + cache stats |
| GET | `/api/autocomplete` | Geoapify location proxy |
| GET | `/api/geocode/reverse` | Geoapify reverse geocode proxy |
| GET | `/api/compare` | Last comparison result (compare.json) |

## Running Tests
```bash
# Flush Redis first to avoid stale cache hits
redis-cli FLUSHALL

# Run the test suite (server must be running)
python test_backend.py
```
