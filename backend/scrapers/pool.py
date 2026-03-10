"""
BrowserPool: shared async Playwright browsers with a concurrency semaphore.
Chromium is used for Zepto, Blinkit, Instamart, DMart.
Firefox is used for BigBasket (bot-detection avoidance).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)


class BrowserPool:
    def __init__(self, max_contexts: int = 3):
        self._max_contexts = max_contexts
        self._semaphore: asyncio.Semaphore | None = None
        self._chromium: Browser | None = None
        self._firefox: Browser | None = None

    async def startup(self, playwright: Playwright) -> None:
        self._semaphore = asyncio.Semaphore(self._max_contexts)

        logger.info("[BrowserPool] Launching Chromium (headless)…")
        self._chromium = await playwright.chromium.launch(headless=True)

        logger.info("[BrowserPool] Launching Firefox (headless)…")
        self._firefox = await playwright.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
                "useAutomationExtension": False,
                "general.useragent.override": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
                    "Gecko/20100101 Firefox/121.0"
                ),
            },
        )

        logger.info("[BrowserPool] Ready — max_contexts=%d", self._max_contexts)

    async def shutdown(self) -> None:
        logger.info("[BrowserPool] Shutting down…")
        for browser in (self._chromium, self._firefox):
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    @asynccontextmanager
    async def acquire_chromium(self, **context_kwargs) -> BrowserContext:
        """Borrow a Chromium BrowserContext; automatically closed on exit."""
        if self._chromium is None or self._semaphore is None:
            raise RuntimeError("BrowserPool not started")
        async with self._semaphore:
            ctx = await self._chromium.new_context(**context_kwargs)
            try:
                yield ctx
            finally:
                await ctx.close()

    @asynccontextmanager
    async def acquire_firefox(self, **context_kwargs) -> BrowserContext:
        """Borrow a Firefox BrowserContext; automatically closed on exit."""
        if self._firefox is None or self._semaphore is None:
            raise RuntimeError("BrowserPool not started")
        async with self._semaphore:
            ctx = await self._firefox.new_context(**context_kwargs)
            try:
                yield ctx
            finally:
                await ctx.close()


# Singleton — imported by all scrapers
browser_pool = BrowserPool()
