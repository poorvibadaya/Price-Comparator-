"""
Tier 1 QuickCompare API client.
Uses XOR-encrypted X-Request-ID header.
Returns None on any failure so the race falls through to Tier 2.
"""

import asyncio
import base64
import logging
import os
import uuid

import httpx

logger = logging.getLogger(__name__)

# XOR key for X-Request-ID encryption
XOR_KEY = bytes.fromhex(
    "04026aadf583caa59cbbf8599d15889274c2fff741b3a8a19229861aa25c6290"
)

# Set QUICKCOMPARE_API_URL in .env to enable Tier 1.
# If empty, tier1_search always returns None (Tier 2 handles everything).
QUICKCOMPARE_API_URL = os.environ.get("QUICKCOMPARE_API_URL", "")


def encrypt_request_id(uid: str) -> str:
    b = uid.encode("utf-8")
    xored = bytes(byte ^ XOR_KEY[i % len(XOR_KEY)] for i, byte in enumerate(b))
    return base64.b64encode(xored).decode("ascii")


class QuickCompareClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def search(
        self, query: str, location: dict, timeout: float = 5.0
    ) -> list | None:
        """
        Call QuickCompare API.  Returns list of raw product dicts or None.
        """
        if not QUICKCOMPARE_API_URL:
            return None
        if not self._client:
            return None

        request_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        clean_user_id = user_id.replace("-", "").lower()

        headers = {
            "X-Request-ID": encrypt_request_id(request_id),
            "X-User-ID": user_id,
            "X-Clean-User-ID": clean_user_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {"query": query, "location": location}

        try:
            response = await asyncio.wait_for(
                self._client.post(QUICKCOMPARE_API_URL, headers=headers, json=payload),
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            products = data.get("products", [])
            logger.info("[QuickCompare] %d products for '%s'", len(products), query)
            return products if products else None
        except Exception as e:
            logger.warning("[QuickCompare] Request failed: %s", e)
            return None


# Singleton
qc_client = QuickCompareClient()
