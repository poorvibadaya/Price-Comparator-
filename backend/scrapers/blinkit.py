"""Async Blinkit scraper — Playwright with API response interception."""

import asyncio
import json
import logging

from .pool import browser_pool

logger = logging.getLogger(__name__)
PLATFORM = "blinkit"


def _remove_duplicates(products: list) -> list:
    seen = set()
    unique = []
    for p in products:
        key = tuple(sorted(p.items()))
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


def _parse_api_response(data: dict) -> list[dict]:
    """Extract products from Blinkit's /v1/layout/search API response."""
    products = []
    snippets = data.get("response", {}).get("snippets", [])

    for snippet in snippets:
        widget_type = snippet.get("widget_type", "")
        if "product_card" not in widget_type:
            continue

        sdata = snippet.get("data", {})

        # Product name
        name = sdata.get("name", {}).get("text", "N/A") if isinstance(sdata.get("name"), dict) else "N/A"
        if name == "N/A":
            continue

        # Price: prefer normal_price (selling), fall back to mrp
        price_obj = sdata.get("normal_price") or sdata.get("price") or sdata.get("mrp") or {}
        price_text = price_obj.get("text", "N/A") if isinstance(price_obj, dict) else "N/A"

        # Variant / description (e.g. "79 g")
        variant = sdata.get("variant", {})
        description = variant.get("text", "N/A") if isinstance(variant, dict) else "N/A"

        # Image
        image = sdata.get("image", {})
        image_url = image.get("url", "N/A") if isinstance(image, dict) else "N/A"

        # Product link from identity
        identity = sdata.get("identity", {})
        product_id = identity.get("id", "") if isinstance(identity, dict) else ""
        slug = name.lower().replace(" ", "-").replace("/", "-")
        product_link = f"https://blinkit.com/prn/{slug}/prid/{product_id}" if product_id else "N/A"

        products.append({
            "product_name": name,
            "price": price_text,
            "description": description,
            "delivery_time": "N/A",
            "product_link": product_link,
            "image_url": image_url,
        })

    return products


async def scrape(query: str, location: dict) -> list[dict]:
    """
    Scrape Blinkit by intercepting the search API response.

    Instead of DOM scraping (slow — needs scroll, sleep, evaluate),
    we navigate to the search page and intercept the JSON API response
    that Blinkit's frontend makes. This is ~3-4x faster.
    """
    if not query:
        return []

    location_name = (
        location.get("city", "") if isinstance(location, dict) else str(location)
    )

    context_kwargs = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        async with browser_pool.acquire_chromium(**context_kwargs) as ctx:
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await ctx.new_page()

            # Collect API responses
            api_products: list[dict] = []
            response_received = asyncio.Event()

            async def handle_response(response):
                try:
                    if "layout/search" in response.url and "q=" in response.url:
                        body = await response.json()
                        parsed = _parse_api_response(body)
                        if parsed:
                            api_products.extend(parsed)
                            response_received.set()
                except Exception:
                    pass

            page.on("response", handle_response)

            # Navigate to Blinkit
            await page.goto("https://blinkit.com/", wait_until="domcontentloaded")

            # Handle location popup
            try:
                container = page.locator(".modal-right__input-wrapper")
                await container.wait_for(state="visible", timeout=5000)
                search_input = container.locator("input")
                await search_input.click()
                await search_input.press_sequentially(location_name, delay=60)
                first_result = page.locator(
                    ".address-container-v1 [class*='LocationSearchList__LocationListContainer']"
                ).first
                await first_result.wait_for(state="visible", timeout=8000)
                await first_result.click()
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.debug("[Blinkit] Location setup: %s", e)

            # Close any popups
            try:
                btn = page.locator('[class*="DownloadAppModal__Image"], [class*="modal-close"]')
                if await btn.is_visible():
                    await btn.click()
            except Exception:
                pass

            # Navigate to search — triggers the API call automatically
            search_bar = page.locator('[class^="SearchBar__PlaceholderContainer"]')
            await search_bar.click()
            await asyncio.sleep(0.5)
            await page.keyboard.type(query)
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")

            # Wait for API response (much faster than waiting for DOM)
            try:
                await asyncio.wait_for(response_received.wait(), timeout=8)
            except asyncio.TimeoutError:
                logger.warning("[Blinkit] API response timeout for '%s'", query)

            # Small delay for any pagination responses
            await asyncio.sleep(1)

            products = _remove_duplicates(api_products)
            for p in products:
                p["platform"] = PLATFORM

            logger.info("[Blinkit] Found %d products for '%s' (API interception)", len(products), query)
            return products

    except Exception as e:
        logger.error("[Blinkit] Scrape error: %s", e)
        return []
