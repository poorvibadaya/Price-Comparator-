# QuickCompare API — Tier 1 Integration

## Overview

QuickCompare is an optional Tier 1 data source that can return price data from
multiple platforms in ~1–3 seconds, significantly faster than direct scraping.

When enabled it races against the Playwright scrapers (Tier 2).  The first
result with ≥ `min_platforms_required` platforms wins and cancels the other.

## Enabling

Set `QUICKCOMPARE_API_URL` in `backend/.env`:

```env
QUICKCOMPARE_API_URL=https://api.quickcompare.example.com/v1/search
```

If the variable is unset, Tier 1 is silently disabled and all requests fall
through to Tier 2 scrapers.

## Request

```
POST {QUICKCOMPARE_API_URL}
Content-Type: application/json
X-Request-ID: <encrypted UUID — see below>
X-User-ID: <raw UUID v4>
X-Clean-User-ID: <UUID with dashes removed, lowercased>
```

Body:
```json
{ "query": "amul butter", "location": { "city": "Mumbai", ... } }
```

## Response

Expected shape (products list):
```json
{ "products": [ { "product_name": "...", "price": "₹275", "platform": "zepto", ... } ] }
```

Any HTTP error or parse failure returns `None` → race falls back to Tier 2.

## X-Request-ID Encryption

```python
XOR_KEY = bytes.fromhex(
    "04026aadf583caa59cbbf8599d15889274c2fff741b3a8a19229861aa25c6290"
)

def encrypt_request_id(uid: str) -> str:
    b = uid.encode("utf-8")
    xored = bytes(byte ^ XOR_KEY[i % len(XOR_KEY)] for i, byte in enumerate(b))
    return base64.b64encode(xored).decode("ascii")

# Usage
uid = str(uuid.uuid4())           # e.g. "550e8400-e29b-41d4-a716-446655440000"
header_value = encrypt_request_id(uid)
```

The XOR key cycles (modulo `len(XOR_KEY)`) over the UTF-8 bytes of the UUID
string, then Base64-encodes the result.

## Timeout

`tier1_timeout_seconds` in `config.json` (default: 5 s).  If the API does not
respond within this window the task is treated as failed and Tier 2 continues.

## Disabling at runtime

```http
PATCH /api/config
{ "tiers": { "tier1_quickcompare": false } }
```

Takes effect immediately for subsequent requests.
