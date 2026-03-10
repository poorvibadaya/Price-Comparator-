"""Async Zepto scraper — Playwright with API response interception."""

import asyncio
import json
import logging

from .pool import browser_pool

logger = logging.getLogger(__name__)
PLATFORM = "zepto"


def _remove_duplicates(products: list) -> list:
    seen = set()
    unique = []
    for p in products:
        key = tuple(sorted(p.items()))
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


def _safe_price(raw) -> str:
    """Convert Zepto price (in paise) to ₹ string."""
    try:
        paise = float(raw)
        if paise > 0:
            rupees = paise / 100  # Zepto returns prices in paise
            return f"₹{int(rupees)}" if rupees == int(rupees) else f"₹{rupees:.2f}"
    except (TypeError, ValueError):
        pass
    return "N/A"


def _parse_api_response(data: dict) -> list[dict]:
    """Extract products from Zepto's /user-search-service/api/v3/search response."""
    products = []
    layout = data.get("layout", [])

    for widget in layout:
        widget_name = widget.get("widgetName", "")
        if not widget_name.startswith("SEARCHED_PRODUCTS"):
            continue

        resolver = widget.get("data", {}).get("resolver", {})
        items = resolver.get("data", {}).get("items", [])

        for item in items:
            pr = item.get("productResponse", {})
            product = pr.get("product", {})
            variant = pr.get("productVariant", {})

            # Name
            name = product.get("name", "N/A")
            if name == "N/A":
                continue

            # Price: prefer discountedSellingPrice > sellingPrice > mrp
            price = (
                _safe_price(pr.get("discountedSellingPrice"))
                if pr.get("discountedSellingPrice")
                else _safe_price(pr.get("sellingPrice"))
                if pr.get("sellingPrice")
                else _safe_price(pr.get("mrp"))
            )

            # Quantity from variant
            description = variant.get("formattedPacksize", "N/A")

            # Image from variant
            images = variant.get("images", [])
            image_url = "N/A"
            if images:
                img = images[0]
                path = img.get("path", "")
                if path:
                    image_url = f"https://cdn.zeptonow.com/production/{path}"
                else:
                    image_url = img.get("url", "N/A")

            # Product link
            product_id = pr.get("id", "")
            product_link = f"https://www.zeptonow.com/product/{product_id}" if product_id else "N/A"

            products.append({
                "product_name": name,
                "price": price,
                "description": description,
                "delivery_time": "N/A",
                "product_link": product_link,
                "image_url": image_url,
            })

    return products


async def scrape(query: str, location: dict) -> list[dict]:
    """
    Scrape Zepto by intercepting the search API response.

    Instead of DOM scraping with heavy scroll + sleep, we intercept
    the JSON response from Zepto's search API endpoint.
    """
    if not query:
        return []

    if isinstance(location, dict):
        location_name = location.get("city") or location.get("address") or "Mumbai"
        coords = location.get("coordinates", {})
        lat = coords.get("lat")
        lng = coords.get("lng")
    else:
        location_name = str(location)
        lat = lng = None

    context_kwargs = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if lat and lng:
        context_kwargs["geolocation"] = {"latitude": lat, "longitude": lng}
        context_kwargs["permissions"] = ["geolocation"]

    try:
        async with browser_pool.acquire_chromium(**context_kwargs) as ctx:
            page = await ctx.new_page()

            # Collect API responses
            api_products: list[dict] = []
            response_received = asyncio.Event()

            async def handle_response(response):
                try:
                    url = response.url
                    if "user-search-service/api/v3/search" in url and "/filters" not in url:
                        body = await response.json()
                        parsed = _parse_api_response(body)
                        if parsed:
                            api_products.extend(parsed)
                            response_received.set()
                except Exception:
                    pass

            page.on("response", handle_response)

            await page.goto("https://www.zepto.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Set location via geolocation
            if lat and lng:
                try:
                    address_header = page.get_by_test_id("user-address")
                    await address_header.wait_for(state="visible", timeout=6000)
                    await address_header.click()
                    await asyncio.sleep(1)
                    saved_container = page.get_by_test_id("saved-address-container")
                    await saved_container.wait_for(state="visible", timeout=6000)
                    enable_btn = saved_container.get_by_role("button", name="Enable")
                    await enable_btn.click()
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.debug("[Zepto] Geolocation failed (%s), trying text search", e)
                    try:
                        await _set_location_text(page, location_name)
                    except Exception:
                        pass
            else:
                try:
                    await _set_location_text(page, location_name)
                except Exception:
                    pass

            # Check serviceability
            if await page.locator("text=We're Coming Soon").count() > 0:
                logger.info("[Zepto] Location not serviceable")
                return []

            # Search — triggers the API call
            try:
                search_icon = page.get_by_test_id("search-bar-icon")
                await search_icon.click()
                await asyncio.sleep(0.5)
                search_input = page.locator('input:not([type="hidden"])').first
                await search_input.click()
                await search_input.fill(query)
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
            except Exception as e:
                logger.warning("[Zepto] Search interaction failed: %s", e)
                return []

            # Wait for API response
            try:
                await asyncio.wait_for(response_received.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("[Zepto] API response timeout for '%s'", query)

            # Small delay for additional pages
            await asyncio.sleep(1.5)

            products = _remove_duplicates(api_products)
            for p in products:
                p["platform"] = PLATFORM

            logger.info("[Zepto] Found %d products for '%s' (API interception)", len(products), query)
            return products

    except Exception as e:
        logger.error("[Zepto] Scrape error: %s", e)
        return []


async def _set_location_text(page, location_name: str) -> None:
    """Set location via text search (fallback when geolocation fails)."""
    address_header = page.get_by_test_id("user-address")
    await address_header.wait_for(state="visible", timeout=8000)
    await address_header.click()
    await asyncio.sleep(0.5)
    search_container = page.get_by_test_id("address-search-input").first
    await search_container.wait_for(state="visible", timeout=8000)
    search_input = search_container.locator("input")
    await search_input.fill(location_name)
    results = page.get_by_test_id("address-search-container")
    first_result = results.get_by_test_id("address-search-item").first
    await first_result.wait_for(state="visible", timeout=8000)
    await first_result.click()
    await asyncio.sleep(1.5)
