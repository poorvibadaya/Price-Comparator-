"""
Async DMart scraper — httpx API first, Playwright fallback.

API structure (confirmed 2026-03):
  GET digital.dmart.in/api/v3/search/{query}?...
  Response:
    data["products"][i]
      .name            — product name
      .productId       — product ID
      .targetUrl       — "/pdp/694006" (relative to dmart.in)
      .sKUs[0]
        .name          — full SKU name with size
        .priceSALE     — DMart special price, e.g. "71.00"
        .priceMRP      — MRP, e.g. "75.00"
        .imageKey      — CDN path, e.g. "J/U/L/JUL130000789xx28JUL25"
        .skuUniqueID   — SKU id

  Image URL:
    https://cdnprod.mafretailproxy.com/sys-master-hybris-media/{imageKey}.jpg
"""

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

from .pool import browser_pool

logger = logging.getLogger(__name__)
PLATFORM = "dmart"

_IMAGE_BASE = "https://cdnprod.mafretailproxy.com/sys-master-hybris-media"
_SITE_BASE = "https://www.dmart.in"


# ── Playwright extraction script ──────────────────────────────────────────────
# Handles both CSS background-image (old) and <img> tags (new).
# Filters out ₹0 prices so the cheapest non-zero price is always shown.
_PLAYWRIGHT_EXTRACTION_SCRIPT = r"""
() => {
    const items = document.querySelectorAll(
        'div.w-\\[265px\\].h-\\[390px\\].bg-appWhite'
    );
    return Array.from(items).map(item => {
        // Product name
        const nameEl = item.querySelector("div.text-primaryColor.min-h-10");
        const productName = nameEl ? nameEl.innerText.trim() : "N/A";

        // Price — filter out ₹0 entries, take last (= special price)
        const validPrices = Array.from(item.querySelectorAll('p'))
            .map(p => p.innerText.trim())
            .filter(t => /^\u20b9[1-9]/.test(t));
        const dmartPrice = validPrices.length > 0
            ? validPrices[validPrices.length - 1]
            : "N/A";

        // Image — try CSS background-image first, fall back to <img> tag
        let image = "N/A";
        const imgDiv = item.querySelector('div[style*="background-image"]');
        if (imgDiv) {
            const bg = imgDiv.style.backgroundImage;
            const m = bg.match(/url\(["']?(.*?)["']?\)/);
            if (m && m[1]) image = m[1];
        }
        if (image === "N/A") {
            const imgEl = item.querySelector('img');
            if (imgEl && imgEl.src && !imgEl.src.startsWith('data:')) {
                image = imgEl.src;
            }
        }

        return {
            "product_name": productName,
            "price": dmartPrice,
            "description": "N/A",
            "delivery_time": "N/A",
            "product_link": "N/A",
            "image_url": image
        };
    }).filter(p => p.product_name !== "N/A");
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────
def _remove_duplicates(products: list) -> list:
    seen = set()
    unique = []
    for p in products:
        key = tuple(sorted(p.items()))
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


def _split_product_name(full_name: str) -> tuple[str, str]:
    if not full_name or full_name == "N/A":
        return full_name, "N/A"
    for pattern in [r"\s*\(.*?\)\s*:\s*", r"\s*:\s*", r"\s*-\s*\d+"]:
        match = re.search(pattern, full_name)
        if match:
            name = full_name[: match.start()].strip()
            desc = re.sub(r"^[:\-\s]+", "", full_name[match.start():].strip())
            return name, desc
    return full_name, "N/A"


def _safe_price(raw) -> str:
    """Convert a raw price value to '₹N' string, or 'N/A' if zero/missing."""
    try:
        f = float(raw)
        if f > 0:
            # Format: no decimals if whole number
            return f"₹{int(f)}" if f == int(f) else f"₹{f:.2f}"
    except (TypeError, ValueError):
        pass
    return "N/A"


def _build_image_url(image_key: str) -> str:
    """Build the CDN image URL from the DMart imageKey."""
    if not image_key:
        return "N/A"
    return f"{_IMAGE_BASE}/{image_key}.jpg"


# ── DMart API scraper ─────────────────────────────────────────────────────────
async def _search_via_api(query: str, store_id: int = 10706) -> list[dict] | None:
    """
    Call DMart's internal search API.

    Products live at data["products"][i].sKUs[0] for price/image.
    Returns list of product dicts on success, None on failure/no results.
    """
    url = (
        f"https://digital.dmart.in/api/v3/search/{quote(query)}"
        f"?page=1&size=40&channel=web&searchTerm={quote(query)}&storeId={store_id}"
    )
    headers = {
        "X-REQUEST-ID": (
            "ODdkN2I4MDAtMzU0Ni00Mjk0LThhZjgtODA0YjE2NWE2NjI4"
            "fHxTLTIwMjYwMTA2XzE1NDgyMnx8LTEwMDI="
        ),
        "storeId": str(store_id),
        "d_info": "w-20260106_154822",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
    }

    try:
        logger.info("[DMart] Calling API for '%s' (store=%d)", query, store_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Products are at the top level: data["products"]
        raw_items = data.get("products") or []
        if not raw_items:
            logger.warning("[DMart] API returned 0 products for '%s'", query)
            return None

        products = []
        for item in raw_items:
            # Use SKU-level name (includes size) if available
            skus = item.get("sKUs") or []
            sku = skus[0] if skus else {}

            name = sku.get("name") or item.get("name") or "N/A"

            # Price: prefer priceSALE, fall back to priceMRP
            price_sale = _safe_price(sku.get("priceSALE"))
            price_mrp  = _safe_price(sku.get("priceMRP"))
            price_str  = price_sale if price_sale != "N/A" else price_mrp

            # Image: construct CDN URL from imageKey
            image_url = _build_image_url(sku.get("imageKey", ""))

            # Product link
            target = item.get("targetUrl", "")
            product_link = f"{_SITE_BASE}{target}" if target else "N/A"

            # Description from SKU name split
            _, description = _split_product_name(name)

            products.append({
                "product_name": name,
                "price": price_str,
                "description": description,
                "delivery_time": "N/A",
                "product_link": product_link,
                "image_url": image_url,
            })

        logger.info(
            "[DMart] API: %d products for '%s' — sample: name=%r price=%s img=%s",
            len(products), query,
            products[0]["product_name"] if products else "?",
            products[0]["price"] if products else "?",
            products[0]["image_url"][:60] if products else "?",
        )
        return products if products else None

    except Exception as e:
        logger.warning("[DMart] API failed for '%s': %s", query, e)
        return None


# ── DMart Playwright scraper (fallback) ───────────────────────────────────────
async def _set_location(page, location_name: str) -> None:
    search_input = page.locator("#pincodeInput")
    await search_input.wait_for(state="visible", timeout=15000)
    await search_input.click()
    await search_input.fill("")
    await search_input.press_sequentially(location_name, delay=120)

    suggestions_container = page.locator(".pinCodeScrollBar")
    await suggestions_container.wait_for(state="visible", timeout=15000)
    first_result = suggestions_container.locator("li button").first
    await first_result.wait_for(state="visible", timeout=15000)
    await first_result.click()

    await page.wait_for_timeout(1500)
    confirm_btn = page.locator('button:has-text("CONFIRM LOCATION")')
    reject_btn = page.locator('button:has-text("SELECT DIFFERENT LOCATION")')

    if await reject_btn.is_visible():
        raise Exception("Pincode not serviceable by DMart")
    elif await confirm_btn.is_visible():
        await confirm_btn.click()
        await asyncio.sleep(3)
    else:
        raise Exception("No location confirmation button appeared")


async def _search_products(page, query: str) -> None:
    search_input = page.locator("#scrInput")
    await search_input.wait_for(state="visible", timeout=15000)
    await search_input.click()
    await search_input.fill("")
    await search_input.press_sequentially(query, delay=100)
    await page.wait_for_timeout(500)
    search_button = page.locator('button:has-text("SEARCH")')
    await search_button.wait_for(state="visible", timeout=15000)
    await search_button.click()
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(3)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(3)


async def _scrape_via_playwright(query: str, location_name: str) -> list[dict]:
    logger.info("[DMart] Using Playwright fallback for '%s' @ %s", query, location_name)
    context_kwargs = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        )
    }
    async with browser_pool.acquire_chromium(**context_kwargs) as ctx:
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await ctx.new_page()
        await page.goto("https://www.dmart.in/", wait_until="domcontentloaded")
        await _set_location(page, location_name)
        await _search_products(page, query)

        raw_list = await page.evaluate(_PLAYWRIGHT_EXTRACTION_SCRIPT)
        products = []
        for item in raw_list:
            name, description = _split_product_name(item["product_name"])
            products.append({**item, "product_name": name, "description": description})

        logger.info(
            "[DMart] Playwright: %d products for '%s' — sample price=%s img=%s",
            len(products), query,
            products[0]["price"] if products else "?",
            (products[0]["image_url"] or "")[:60] if products else "?",
        )
        return products


# ── Public scrape entry point ─────────────────────────────────────────────────
async def scrape(query: str, location: dict) -> list[dict]:
    if not query:
        return []

    if isinstance(location, dict):
        location_name = location.get("city") or location.get("state") or str(location)
    else:
        location_name = str(location)

    # Method 1: API
    products = await _search_via_api(query)

    # Method 2: Playwright fallback
    if not products:
        logger.info("[DMart] API gave no results — falling back to Playwright")
        try:
            products = await _scrape_via_playwright(query, location_name)
        except Exception as e:
            logger.error("[DMart] Playwright fallback failed: %s", e)
            return []

    products = _remove_duplicates(products)
    for p in products:
        p["platform"] = PLATFORM

    logger.info("[DMart] Total: %d products for '%s'", len(products), query)
    return products
