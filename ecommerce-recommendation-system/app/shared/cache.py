import aioredis
import json
from typing import Any, Optional
import os

class CacheService:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = None

    async def get_redis(self):
        if not self._redis:
            self._redis = await aioredis.from_url(self.redis_url)
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        redis = await self.get_redis()
        value = await redis.get(key)
        if value:
            return json.loads(value)
        return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        redis = await self.get_redis()
        await redis.setex(key, ttl, json.dumps(value, default=str))

    async def delete(self, key: str):
        redis = await self.get_redis()
        await redis.delete(key)

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        redis = await self.get_redis()
        values = await redis.mget(keys)
        result = {}
        for key, value in zip(keys, values):
            if value:
                result[key] = json.loads(value)
        return result

    async def set_many(self, data: dict[str, Any], ttl: int = 3600):
        redis = await self.get_redis()
        pipe = redis.pipeline()
        for key, value in data.items():
            pipe.setex(key, ttl, json.dumps(value, default=str))
        await pipe.execute()

cache_service = CacheService()