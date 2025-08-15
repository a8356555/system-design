"""
Redis client for caching in Lambda Architecture Serving Layer
"""

import asyncio
import json
import logging
from typing import Any, Optional, Dict, List
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client with connection pooling and serialization"""
    
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0, 
                 password: Optional[str] = None, max_connections: int = 20):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        
        # Create connection pool
        self.pool = ConnectionPool.from_url(
            f"redis://{host}:{port}/{db}",
            password=password,
            max_connections=max_connections,
            retry_on_timeout=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        
        self.client = redis.Redis(connection_pool=self.pool, decode_responses=True)
        
        logger.info(f"Redis client initialized for {host}:{port}/{db}")
    
    async def ping(self) -> bool:
        """Test Redis connection"""
        try:
            result = await self.client.ping()
            logger.debug("✅ Redis ping successful")
            return result
        except Exception as e:
            logger.error(f"❌ Redis ping failed: {e}")
            return False
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from Redis with JSON deserialization"""
        try:
            value = await self.client.get(key)
            if value is None:
                return None
            
            # Try to deserialize JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Return raw value if not JSON
                return value
                
        except Exception as e:
            logger.error(f"Error getting key '{key}': {e}")
            return None
    
    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set value in Redis with JSON serialization"""
        try:
            # Serialize non-string values to JSON
            if not isinstance(value, str):
                value = json.dumps(value, default=str)
            
            result = await self.client.set(key, value, ex=ex)
            return result
        except Exception as e:
            logger.error(f"Error setting key '{key}': {e}")
            return False
    
    async def setex(self, key: str, time: int, value: Any) -> bool:
        """Set value with expiration time"""
        return await self.set(key, value, ex=time)
    
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys"""
        try:
            result = await self.client.delete(*keys)
            logger.debug(f"Deleted {result} keys")
            return result
        except Exception as e:
            logger.error(f"Error deleting keys {keys}: {e}")
            return 0
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern"""
        try:
            keys = await self.client.keys(pattern)
            if keys:
                result = await self.client.delete(*keys)
                logger.debug(f"Deleted {result} keys matching pattern '{pattern}'")
                return result
            return 0
        except Exception as e:
            logger.error(f"Error deleting pattern '{pattern}': {e}")
            return 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            result = await self.client.exists(key)
            return bool(result)
        except Exception as e:
            logger.error(f"Error checking existence of key '{key}': {e}")
            return False
    
    async def expire(self, key: str, time: int) -> bool:
        """Set expiration time for a key"""
        try:
            result = await self.client.expire(key, time)
            return result
        except Exception as e:
            logger.error(f"Error setting expiration for key '{key}': {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Get time to live for a key"""
        try:
            result = await self.client.ttl(key)
            return result
        except Exception as e:
            logger.error(f"Error getting TTL for key '{key}': {e}")
            return -2  # Key doesn't exist
    
    async def mget(self, keys: List[str]) -> List[Optional[Any]]:
        """Get multiple values at once"""
        try:
            values = await self.client.mget(keys)
            results = []
            
            for value in values:
                if value is None:
                    results.append(None)
                else:
                    try:
                        results.append(json.loads(value))
                    except json.JSONDecodeError:
                        results.append(value)
            
            return results
        except Exception as e:
            logger.error(f"Error getting multiple keys {keys}: {e}")
            return [None] * len(keys)
    
    async def mset(self, mapping: Dict[str, Any], ex: Optional[int] = None) -> bool:
        """Set multiple key-value pairs"""
        try:
            # Serialize values to JSON
            serialized_mapping = {}
            for key, value in mapping.items():
                if not isinstance(value, str):
                    serialized_mapping[key] = json.dumps(value, default=str)
                else:
                    serialized_mapping[key] = value
            
            # Use pipeline for atomic operation
            async with self.client.pipeline() as pipe:
                await pipe.mset(serialized_mapping)
                
                # Set expiration if specified
                if ex is not None:
                    for key in mapping.keys():
                        await pipe.expire(key, ex)
                
                results = await pipe.execute()
                return all(results)
                
        except Exception as e:
            logger.error(f"Error setting multiple keys: {e}")
            return False
    
    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment a key's value"""
        try:
            result = await self.client.incrby(key, amount)
            return result
        except Exception as e:
            logger.error(f"Error incrementing key '{key}': {e}")
            raise
    
    async def decr(self, key: str, amount: int = 1) -> int:
        """Decrement a key's value"""
        try:
            result = await self.client.decrby(key, amount)
            return result
        except Exception as e:
            logger.error(f"Error decrementing key '{key}': {e}")
            raise
    
    async def hget(self, name: str, key: str) -> Optional[Any]:
        """Get field from hash"""
        try:
            value = await self.client.hget(name, key)
            if value is None:
                return None
            
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception as e:
            logger.error(f"Error getting hash field '{key}' from '{name}': {e}")
            return None
    
    async def hset(self, name: str, key: str, value: Any) -> bool:
        """Set field in hash"""
        try:
            if not isinstance(value, str):
                value = json.dumps(value, default=str)
            
            result = await self.client.hset(name, key, value)
            return bool(result)
        except Exception as e:
            logger.error(f"Error setting hash field '{key}' in '{name}': {e}")
            return False
    
    async def hgetall(self, name: str) -> Dict[str, Any]:
        """Get all fields from hash"""
        try:
            result = await self.client.hgetall(name)
            
            # Deserialize JSON values
            deserialized = {}
            for key, value in result.items():
                try:
                    deserialized[key] = json.loads(value)
                except json.JSONDecodeError:
                    deserialized[key] = value
            
            return deserialized
        except Exception as e:
            logger.error(f"Error getting all hash fields from '{name}': {e}")
            return {}
    
    async def hmset(self, name: str, mapping: Dict[str, Any], ex: Optional[int] = None) -> bool:
        """Set multiple fields in hash"""
        try:
            # Serialize values
            serialized_mapping = {}
            for key, value in mapping.items():
                if not isinstance(value, str):
                    serialized_mapping[key] = json.dumps(value, default=str)
                else:
                    serialized_mapping[key] = value
            
            result = await self.client.hset(name, mapping=serialized_mapping)
            
            # Set expiration if specified
            if ex is not None:
                await self.client.expire(name, ex)
            
            return bool(result)
        except Exception as e:
            logger.error(f"Error setting multiple hash fields in '{name}': {e}")
            return False
    
    async def keys(self, pattern: str = '*') -> List[str]:
        """Get keys matching pattern"""
        try:
            result = await self.client.keys(pattern)
            return result
        except Exception as e:
            logger.error(f"Error getting keys with pattern '{pattern}': {e}")
            return []
    
    async def flushdb(self) -> bool:
        """Flush current database"""
        try:
            result = await self.client.flushdb()
            logger.warning("Redis database flushed")
            return result
        except Exception as e:
            logger.error(f"Error flushing database: {e}")
            return False
    
    async def info(self) -> Dict[str, Any]:
        """Get Redis server info"""
        try:
            result = await self.client.info()
            return result
        except Exception as e:
            logger.error(f"Error getting Redis info: {e}")
            return {}
    
    async def close(self):
        """Close Redis connection pool"""
        try:
            await self.client.close()
            logger.info("Redis connection pool closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        try:
            # Test basic connectivity
            ping_result = await self.ping()
            
            # Get server info
            info = await self.info()
            
            # Test set/get operations
            test_key = "health_check_test"
            test_value = {"timestamp": str(asyncio.get_event_loop().time())}
            
            await self.set(test_key, test_value, ex=60)
            retrieved_value = await self.get(test_key)
            await self.delete(test_key)
            
            operations_ok = retrieved_value is not None
            
            return {
                "ping": ping_result,
                "operations": operations_ok,
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory_human", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "status": "healthy" if ping_result and operations_ok else "unhealthy"
            }
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {
                "ping": False,
                "operations": False,
                "status": "unhealthy",
                "error": str(e)
            }