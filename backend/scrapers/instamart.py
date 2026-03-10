"""Async Swiggy Instamart scraper — converted from ecommerce_platform/instamart.py."""

import asyncio
import logging

from .pool import browser_pool

logger = logging.getLogger(__name__)
PLATFORM = "swiggy-instamart"

_EXTRACTION_SCRIPT = """
() => {
    const items = document.querySelectorAll('div._3Rr1X');
    return Array.from(items).map(item => {
        const timeEl = item.querySelector('.sc-gEvEer.ePxHTM.GOJ8s._1y_Uf');
        const deliveryTime = timeEl ? timeEl.innerText.trim() : "N/A";
        const nameEl = item.querySelector('.sc-gEvEer.iPErou._1lbNR');
        const productName = nameEl ? nameEl.innerText.trim() : "N/A";
        const imgEl = item.querySelector('img._16I1D') || item.querySelector('img');
        let imageUrl = "N/A";
        if (imgEl) {
            const dataSrc = imgEl.getAttribute('data-src');
            if (dataSrc && !dataSrc.startsWith('data:')) {
                imageUrl = dataSrc;
            } else {
                const srcset = imgEl.getAttribute('srcset') || imgEl.getAttribute('data-srcset');
                if (srcset) {
                    const firstUrl = srcset.split(',')[0].trim().split(' ')[0];
                    if (firstUrl && !firstUrl.startsWith('data:')) imageUrl = firstUrl;
                }
                if (imageUrl === "N/A") {
                    const src = imgEl.getAttribute('src');
                    if (src && !src.startsWith('data:')) imageUrl = src;
                }
            }
        }
        const descEl = item.querySelector('.sc-gEvEer.bCqPoH._3wq_F');
        let description = "N/A";
        if (descEl) {
            description = Array.from(descEl.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => node.textContent.trim())
                .join(' ') || descEl.firstChild?.textContent?.trim() || "N/A";
        }
        const priceEl = item.querySelector('.sc-gEvEer.iQcBUp._2jn41');
        const price = priceEl ? priceEl.innerText.trim() : "N/A";
        const linkEl = item.closest('a') || item.querySelector('a');
        let productLink = "N/A";
        if (linkEl) {
            const href = linkEl.getAttribute('href');
            productLink = href
                ? (href.startsWith('http') ? href : `https://www.swiggy.com${href}`)
                : "N/A";
        }
        return {
            "product_name": productName,
            "price": price,
            "description": description,
            "delivery_time": deliveryTime,
            "product_link": productLink,
            "image_url": imageUrl
        };
    }).filter(p => p.product_name !== "N/A");
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


async def _setup_automatic_handlers(page) -> None:
    try_again_button = page.locator("button.sc-iGgWBj.gVfwdV.hIVl0").filter(
        has=page.locator(
            'span.sc-gEvEer.jvMXGN div.sc-gEvEer.eMfGmB', has_text="Try Again"
        )
    )

    async def recover_from_error():
        try:
            await try_again_button.wait_for(state="visible", timeout=5000)
            await try_again_button.click()
            await page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            logger.debug("[Instamart] Handler failed: %s", e)

    await page.add_locator_handler(try_again_button, recover_from_error)


async def _set_location(page, location_name: str) -> None:
    search_container = page.get_by_test_id("search-location")
    await page.wait_for_timeout(2000)
    await search_container.click()
    await page.locator("input[placeholder*='Search']").fill(location_name)
    first_result = page.locator("._11n32").first
    await first_result.wait_for(state="visible")
    await page.wait_for_timeout(2000)
    await first_result.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.locator(".sc-gEvEer.jvMXGN").click()


async def _search_and_scroll(page, query: str) -> None:
    await page.wait_for_timeout(2000)
    await page.get_by_test_id("search-container").click()
    await page.locator("input._18fRo").click()
    await page.wait_for_timeout(2000)
    await page.locator("input._18fRo").fill(query)
    await page.wait_for_timeout(3000)
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(5000)
    await page.evaluate("document.body.style.zoom = '10%'")

    for i in range(5):
        logger.debug("[Instamart] Scroll %d/5", i + 1)
        await page.evaluate(
            """(selector) => {
                const container = document.querySelector(selector);
                if (container) container.scrollTop = container.scrollHeight;
            }""",
            "._2_95H",
        )
        await page.wait_for_timeout(5000)


async def scrape(query: str, location: dict) -> list[dict]:
    if not query:
        return []

    location_name = (
        location.get("city", "") if isinstance(location, dict) else str(location)
    )

    context_kwargs = {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with browser_pool.acquire_chromium(**context_kwargs) as ctx:
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await ctx.new_page()
            await _setup_automatic_handlers(page)
            await page.goto(
                "https://www.swiggy.com/instamart/",
                wait_until="domcontentloaded",
                timeout=10000,
            )
            await _set_location(page, location_name)
            await _search_and_scroll(page, query)

            products = await page.evaluate(_EXTRACTION_SCRIPT)
            products = _remove_duplicates(products)
            for p in products:
                p["platform"] = PLATFORM

            logger.info("[Instamart] Found %d products for '%s'", len(products), query)
            return products

    except Exception as e:
        logger.error("[Instamart] Scrape error: %s", e)
        return []
