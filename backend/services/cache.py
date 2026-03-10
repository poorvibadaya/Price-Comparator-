"""
Two-level cache: L1 LRU (in-process) + L2 Redis (shared).
L1: lru-dict with manual TTL via time.monotonic()
L2: redis.asyncio with SETEX; gracefully disabled if Redis unreachable.
Cache key format: search:{query}:{lat:.3f}:{lon:.3f}
"""

import json
import logging
import time

from lru import LRU

logger = logging.getLogger(__name__)


class TieredCache:
    def __init__(
        self,
        l1_max_size: int = 500,
        l1_ttl: int = 120,
        l2_ttl: int = 600,
        redis_url: str = "redis://localhost:6379",
    ):
        self._l1 = LRU(l1_max_size)
        self._l1_max_size = l1_max_size
        self._l1_ttl = l1_ttl
        self._l2_ttl = l2_ttl
        self._redis_url = redis_url
        self._redis = None
        self._redis_available = False

    async def startup(self):
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("[Cache] Redis connection established at %s", self._redis_url)
        except Exception as e:
            logger.warning("[Cache] Redis unavailable, operating L1-only: %s", e)
            self._redis_available = False

    async def get(self, key: str):
        # L1 check
        entry = self._l1.get(key)
        if entry is not None:
            value, expiry = entry
            if time.monotonic() < expiry:
                return value
            del self._l1[key]

        # L2 check
        if self._redis_available:
            try:
                raw = await self._redis.get(key)
                if raw:
                    value = json.loads(raw)
                    # Warm L1
                    self._l1[key] = (value, time.monotonic() + self._l1_ttl)
                    return value
            except Exception as e:
                logger.warning("[Cache] Redis get error: %s", e)

        return None

    async def set(self, key: str, value) -> None:
        self._l1[key] = (value, time.monotonic() + self._l1_ttl)
        if self._redis_available:
            try:
                await self._redis.setex(
                    key, self._l2_ttl, json.dumps(value, default=str)
                )
            except Exception as e:
                logger.warning("[Cache] Redis set error: %s", e)

    def l1_stats(self) -> dict:
        return {"size": len(self._l1), "max_size": self._l1_max_size}

    async def shutdown(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass


def build_cache_key(query: str, location: dict) -> str:
    lat = 0.0
    lon = 0.0
    if isinstance(location, dict):
        coords = location.get("coordinates", {})
        lat = coords.get("lat", 0.0)
        lon = coords.get("lng", 0.0)
    return f"search:{query.strip().lower()}:{lat:.3f}:{lon:.3f}"


# Singleton used by the rest of the app
cache = TieredCache()
