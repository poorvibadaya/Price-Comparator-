"""Abstract base class for all async scrapers."""

from abc import ABC, abstractmethod


class AsyncScraper(ABC):
    @abstractmethod
    async def scrape(self, query: str, location: dict) -> list[dict]:
        """
        Scrape products for *query* at *location*.

        Returns a list of raw product dicts with at minimum:
            product_name, price, description, delivery_time,
            product_link, image_url, platform
        Returns [] on any error (never raises).
        """
        ...
