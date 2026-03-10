"""Async BigBasket scraper — httpx API first, Playwright fallback."""

import asyncio
import logging
from urllib.parse import quote

import httpx

from .pool import browser_pool

logger = logging.getLogger(__name__)
PLATFORM = "bigbasket"

# ── Static cookies/headers that BigBasket's listing API accepts ──────────────
_BB_HEADERS = {
    "x-channel": "BB-WEB",
    "x-entry-context": "bb-b2c",
    "x-entry-context-id": "100",
    "content-type": "application/json",
    "Accept": "*/*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
}

_BB_COOKIES = (
    '_bb_locSrc=default; x-channel=web; _bb_aid="MzAwNTUzOTIyMA=="; '
    "_bb_cid=4; _bb_vid=MTE1OTMwNTc0MzcwODgyNzM3NA==; "
    "_bb_nhid=7427; _bb_dsid=7427; _bb_dsevid=7427"
)


def _safe_price(raw) -> str:
    try:
        f = float(raw)
        if f > 0:
            return f"₹{int(f)}" if f == int(f) else f"₹{f:.2f}"
    except (TypeError, ValueError):
        pass
    return "N/A"


# ── API scraper ──────────────────────────────────────────────────────────────
async def _search_via_api(query: str) -> list[dict] | None:
    """
    Call BigBasket's listing-svc API directly.
    Returns list of product dicts on success, None on failure.
    """
    url = "https://www.bigbasket.com/listing-svc/v2/products"
    params = {"type": "ps", "slug": query, "page": "1", "bucket_id": "56"}
    headers = {**_BB_HEADERS, "Cookie": _BB_COOKIES}

    try:
        logger.info("[BigBasket] Calling API for '%s'", query)
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        tabs = data.get("tabs", [])
        if not tabs:
            logger.warning("[BigBasket] API: no tabs in response for '%s'", query)
            return None

        raw_products = tabs[0].get("product_info", {}).get("products", [])
        if not raw_products:
            logger.warning("[BigBasket] API: 0 products for '%s'", query)
            return None

        products = []
        for p in raw_products:
            brand = p.get("brand", {}).get("name", "")
            desc_text = p.get("desc", "N/A")
            full_name = f"{brand} {desc_text}".strip() if brand else desc_text

            # Price: discount.prim_price.sp or discount.mrp
            pricing = p.get("pricing", {})
            discount = pricing.get("discount", {})
            prim = discount.get("prim_price", {})
            price_str = _safe_price(prim.get("sp")) if prim.get("sp") else _safe_price(discount.get("mrp"))

            # Image
            images = p.get("images", [])
            image_url = images[0].get("m", "N/A") if images else "N/A"

            # Link
            abs_url = p.get("absolute_url", "")
            product_link = f"https://www.bigbasket.com{abs_url}" if abs_url else "N/A"

            # Quantity description
            weight = p.get("w", "N/A")

            products.append({
                "product_name": full_name,
                "price": price_str,
                "description": weight,
                "delivery_time": "N/A",
                "product_link": product_link,
                "image_url": image_url,
            })

        logger.info(
            "[BigBasket] API: %d products for '%s' — sample: name=%r price=%s",
            len(products), query,
            products[0]["product_name"] if products else "?",
            products[0]["price"] if products else "?",
        )
        return products

    except Exception as e:
        logger.warning("[BigBasket] API failed for '%s': %s", query, e)
        return None


# ── Playwright fallback ──────────────────────────────────────────────────────
_EXTRACTION_SCRIPT = """
() => {
    const items = document.querySelectorAll('.SKUDeck___StyledDiv-sc-1e5d9gk-0.bFjDCO');
    const products = Array.from(items).map(item => {
        const brandEl = item.querySelector('span.BrandName___StyledLabel2-sc-hssfrl-0');
        const brand = brandEl ? brandEl.innerText.trim() : "";
        const nameEl = item.querySelector('h3.line-clamp-2');
        const productNameOnly = nameEl ? nameEl.innerText.trim() : "N/A";
        const fullProductName = brand ? `${brand} ${productNameOnly}` : productNameOnly;
        const priceBlock = item.querySelector('div.flex.flex-col.gap-0\\\\.5');
        let price = "N/A";
        if (priceBlock) {
            const spans = priceBlock.querySelectorAll('span');
            if (spans[0]) price = spans[0].innerText.trim();
        }
        const deliveryEl = item.querySelector('div.text-sunglow-800');
        const deliveryTime = deliveryEl ? deliveryEl.innerText.trim() : "N/A";
        const linkEl = item.querySelector('div.relative.border-solid a');
        let productLink = "N/A", imageUrl = "N/A";
        if (linkEl) {
            const href = linkEl.getAttribute('href');
            productLink = href ? `https://www.bigbasket.com${href}` : "N/A";
            const imgEl = linkEl.querySelector('img');
            if (imgEl) {
                const src = imgEl.getAttribute('data-src') || imgEl.getAttribute('src');
                if (src && !src.startsWith('data:')) imageUrl = src;
            }
        }
        const qtyEl = item.querySelector('h3 span.truncate');
        const description = qtyEl ? qtyEl.innerText.trim() : "N/A";
        return { "product_name": fullProductName, "price": price, "description": description,
                 "delivery_time": deliveryTime, "product_link": productLink, "image_url": imageUrl };
    });
    return products.filter(p => p.product_name !== "N/A");
}
"""


def _remove_duplicates(products: list) -> list:
    seen = set()
    unique = []
    for p in products:
        key = tuple(sorted(p.items()))
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


async def _scrape_via_playwright(query: str, location_name: str) -> list[dict]:
    logger.info("[BigBasket] Playwright fallback for '%s' @ %s", query, location_name)
    context_kwargs = {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
        "locale": "en-US",
        "timezone_id": "Asia/Kolkata",
    }
    async with browser_pool.acquire_firefox(**context_kwargs) as ctx:
        page = await ctx.new_page()
        await page.goto("https://www.bigbasket.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Set location
        loc_btn = page.locator(
            'xpath=//button[contains(., "Delivery in 10 min") and contains(., "Select Location")]'
        ).first
        await loc_btn.wait_for(state="visible", timeout=10000)
        await loc_btn.evaluate("e => e.click()")
        loc_input = page.locator('input[placeholder="Search for area or street name"]').first
        await loc_input.wait_for(state="visible", timeout=5000)
        await loc_input.click(force=True)
        await page.keyboard.type(location_name, delay=80)
        await asyncio.sleep(1.5)
        first_item = page.locator("ul li.sc-jdkBTo.cnPYAb").first
        box = await first_item.bounding_box()
        if box:
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            await first_item.click(force=True)
        await asyncio.sleep(2)

        # Search
        search_input = page.locator('input[placeholder="Search for Products..."]').first
        await search_input.wait_for(state="visible", timeout=10000)
        await search_input.click(force=True)
        await page.keyboard.type(query, delay=80)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)
        await page.evaluate("document.body.style.zoom = '20%'")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        products = await page.evaluate(_EXTRACTION_SCRIPT)
        products = _remove_duplicates(products)
        logger.info("[BigBasket] Playwright: %d products for '%s'", len(products), query)
        return products


# ── Public entry point ───────────────────────────────────────────────────────
async def scrape(query: str, location: dict) -> list[dict]:
    if not query:
        return []

    location_name = (
        location.get("city", "") if isinstance(location, dict) else str(location)
    )

    # Method 1: API (fast, ~1s)
    products = await _search_via_api(query)

    # Method 2: Playwright fallback
    if not products:
        logger.info("[BigBasket] API gave no results — falling back to Playwright")
        try:
            products = await _scrape_via_playwright(query, location_name)
        except Exception as e:
            logger.error("[BigBasket] Playwright fallback failed: %s", e)
            return []

    products = _remove_duplicates(products)
    for p in products:
        p["platform"] = PLATFORM

    logger.info("[BigBasket] Total: %d products for '%s'", len(products), query)
    return products
