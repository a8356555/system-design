import aioredis
import json
import pickle
from typing import Any, Optional, List
from datetime import timedelta
import os

class RedisCacheService:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = None

    async def get_redis(self):
        if not self._redis:
            self._redis = await aioredis.from_url(self.redis_url)
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        redis = await self.get_redis()
        value = await redis.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Fallback to pickle for complex objects
                return pickle.loads(value)
        return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set value in cache with TTL in seconds"""
        redis = await self.get_redis()
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError):
            # Fallback to pickle for complex objects
            serialized = pickle.dumps(value)
        
        await redis.setex(key, ttl, serialized)

    async def delete(self, key: str):
        """Delete key from cache"""
        redis = await self.get_redis()
        await redis.delete(key)

    async def get_many(self, keys: List[str]) -> dict[str, Any]:
        """Get multiple values from cache"""
        redis = await self.get_redis()
        values = await redis.mget(keys)
        result = {}
        
        for key, value in zip(keys, values):
            if value:
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = pickle.loads(value)
        
        return result

    async def set_many(self, data: dict[str, Any], ttl: int = 3600):
        """Set multiple values in cache"""
        redis = await self.get_redis()
        pipe = redis.pipeline()
        
        for key, value in data.items():
            try:
                serialized = json.dumps(value, default=str)
            except (TypeError, ValueError):
                serialized = pickle.dumps(value)
            pipe.setex(key, ttl, serialized)
        
        await pipe.execute()

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        redis = await self.get_redis()
        return await redis.exists(key)

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter"""
        redis = await self.get_redis()
        return await redis.incrby(key, amount)

    async def expire(self, key: str, ttl: int):
        """Set expiration for existing key"""
        redis = await self.get_redis()
        await redis.expire(key, ttl)

    async def get_recommendations_cache_key(
        self, 
        user_id: str, 
        profile_id: str, 
        recommendation_type: str, 
        **params
    ) -> str:
        """Generate cache key for recommendations"""
        param_str = "_".join(f"{k}:{v}" for k, v in sorted(params.items()) if v is not None)
        return f"rec:{recommendation_type}:{user_id}:{profile_id}:{param_str}"

    async def get_user_cache_key(self, user_id: str, data_type: str) -> str:
        """Generate cache key for user data"""
        return f"user:{data_type}:{user_id}"

    async def get_content_cache_key(self, content_id: str, data_type: str) -> str:
        """Generate cache key for content data"""
        return f"content:{data_type}:{content_id}"

    async def clear_user_cache(self, user_id: str):
        """Clear all cache entries for a user"""
        redis = await self.get_redis()
        pattern = f"*:{user_id}:*"
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)

    async def clear_content_cache(self, content_id: str):
        """Clear all cache entries for content"""
        redis = await self.get_redis()
        pattern = f"*:{content_id}:*"
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)

    async def get_trending_cache_key(self, time_window_hours: int, **filters) -> str:
        """Generate cache key for trending data"""
        filter_str = "_".join(f"{k}:{v}" for k, v in sorted(filters.items()) if v is not None)
        return f"trending:{time_window_hours}h:{filter_str}"

# Global cache instance
cache_service = RedisCacheService()