# API Reference

## Base URL
`http://localhost:8080`

---

## POST /api/search

Search for products across all enabled platforms.

**Request body:**
```json
{
  "query": "amul butter",
  "location": {
    "city": "Mumbai",
    "state": "Maharashtra",
    "coordinates": { "lat": 19.0760, "lng": 72.8777 }
  },
  "platforms": []
}
```

**Response:**
```json
{
  "products": [
    {
      "name": "Amul Butter",
      "image": "https://...",
      "original_names": {
        "zepto": "Amul Butter Pasteurised",
        "blinkit": "Amul Butter 500g"
      },
      "platforms": {
        "zepto":    { "price": 275, "price_str": "₹275", "url": "...", "image": "..." },
        "blinkit":  { "price": 270, "price_str": "₹270", "url": "...", "image": "..." },
        "bigbasket":{ "price": 278, "price_str": "₹278", "url": "...", "image": "..." }
      }
    }
  ],
  "source": "tier1"
}
```

`source` values: `cache`, `tier1`, `tier2`, `partial`

---

## GET /api/search/stream

SSE stream for progressive results.

**Query params:** `query`, `lat`, `lon`, `city` (optional)

**SSE events:**
```
event: platform
data: {"platform": "zepto", "count": 24}

event: platform
data: {"platform": "blinkit", "count": 18}

event: done
data: {"products": [...], "source": "tier2"}
```

---

## GET /api/config

Returns current configuration JSON.

---

## PATCH /api/config

Update configuration at runtime (persisted to config.json).

**Examples:**
```json
{ "tiers": { "tier1_quickcompare": false } }
{ "platforms": { "bigbasket": { "enabled": false } } }
{ "race": { "min_platforms_required": 3 } }
```

---

## GET /api/health

```json
{
  "status": "ok",
  "cache": { "size": 42, "max_size": 500 },
  "redis": true
}
```

---

## GET /api/autocomplete?text=mumbai

Proxies Geoapify autocomplete. Requires `GEOAPIFY_API_KEY` in `.env`.

---

## GET /api/geocode/reverse?lat=19.07&lon=72.87

Proxies Geoapify reverse geocode.

---

## GET /api/compare

Returns the last comparison result from `compare.json`.

---

## GET /api/health  (legacy)
## GET /health

Simple health check.

---

## Error responses

All errors return:
```json
{ "detail": "error message" }
```

HTTP codes: `400` bad request, `500` server error, `502` upstream failed.
