"""
Service implementing Lambda Architecture query logic

Merges data from batch layer (accurate historical data) and 
speed layer (recent real-time increments) to provide unified query results.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from functools import lru_cache

from ..models.responses import (
    UserPostCount, TopUsersResponse, SystemHealthResponse, 
    DataFreshnessResponse, UserPostCountData
)
from ..database.clickhouse_client import ClickHouseClient
from ..database.redis_client import RedisClient
from ..config.settings import Settings

logger = logging.getLogger(__name__)


class UserPostService:
    """Service implementing Lambda Architecture query patterns"""
    
    def __init__(self, clickhouse_client: ClickHouseClient, redis_client: RedisClient, settings: Settings):
        self.clickhouse = clickhouse_client
        self.redis = redis_client
        self.settings = settings
        self.cache_ttl = 300  # 5 minutes
        
    async def health_check(self) -> bool:
        """Check health of all dependencies"""
        try:
            # Test ClickHouse connection
            await self.clickhouse.execute("SELECT 1")
            
            # Test Redis connection  
            await self.redis.ping()
            
            logger.info("✅ Health check passed")
            return True
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            raise
    
    async def get_user_post_count(self, user_id: int) -> Optional[UserPostCount]:
        """
        Get user post count using Lambda Architecture query pattern:
        1. Get batch layer data (accurate up to batch cutoff)
        2. Get speed layer increments (from batch cutoff to now)
        3. Merge and return unified result
        """
        try:
            logger.debug(f"Querying post count for user {user_id}")
            
            # Check cache first
            cache_key = f"user_post_count:{user_id}"
            cached_result = await self.redis.get(cache_key)
            if cached_result:
                logger.debug(f"Cache hit for user {user_id}")
                return UserPostCount.parse_obj(cached_result)
            
            # Get batch processing cutoff timestamp
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            
            # Query batch layer (historical accurate data)
            batch_data = await self._get_batch_user_count(user_id)
            
            # Query speed layer (recent incremental data)
            speed_increment = await self._get_speed_user_increment(user_id, batch_cutoff)
            
            # Merge batch + speed layer data
            result = self._merge_user_post_count(batch_data, speed_increment, user_id)
            
            if result:
                # Cache result
                await self.redis.setex(cache_key, self.cache_ttl, result.dict())
                
            return result
            
        except Exception as e:
            logger.error(f"Error querying post count for user {user_id}: {e}")
            return None
    
    async def get_user_post_counts(self, user_ids: List[int]) -> List[UserPostCount]:
        """Get post counts for multiple users (optimized batch query)"""
        try:
            logger.debug(f"Querying post counts for {len(user_ids)} users")
            
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            
            # Try to get cached results first
            cached_results = {}
            uncached_user_ids = []
            
            for user_id in user_ids:
                cache_key = f"user_post_count:{user_id}"
                cached_result = await self.redis.get(cache_key)
                if cached_result:
                    cached_results[user_id] = UserPostCount.parse_obj(cached_result)
                else:
                    uncached_user_ids.append(user_id)
            
            # Query uncached users
            if uncached_user_ids:
                # Batch query from both layers
                batch_data = await self._get_batch_user_counts(uncached_user_ids)
                speed_increments = await self._get_speed_user_increments(uncached_user_ids, batch_cutoff)
                
                # Merge data for each uncached user
                for user_id in uncached_user_ids:
                    result = self._merge_user_post_count(
                        batch_data.get(user_id), 
                        speed_increments.get(user_id), 
                        user_id
                    )
                    if result:
                        cached_results[user_id] = result
                        # Cache the result
                        cache_key = f"user_post_count:{user_id}"
                        await self.redis.setex(cache_key, self.cache_ttl, result.dict())
            
            # Return results in original order
            results = []
            for user_id in user_ids:
                if user_id in cached_results:
                    results.append(cached_results[user_id])
            
            return results
                
        except Exception as e:
            logger.error(f"Error querying post counts for multiple users: {e}")
            return []
    
    async def get_top_users(self, limit: int) -> TopUsersResponse:
        """Get top users by post count (uses pre-computed materialized view + speed layer adjustments)"""
        try:
            logger.debug(f"Querying top {limit} users")
            
            # Check cache
            cache_key = f"top_users:{limit}"
            cached_result = await self.redis.get(cache_key)
            if cached_result:
                return TopUsersResponse.parse_obj(cached_result)
            
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            
            # Get top users from batch layer (pre-computed, get more for safety)
            batch_top_users = await self._get_batch_top_users(limit * 2)
            
            if not batch_top_users:
                return TopUsersResponse(users=[], total_users=0, last_updated=datetime.utcnow())
            
            # Get speed layer adjustments for these users
            user_ids = [user.user_id for user in batch_top_users]
            speed_increments = await self._get_speed_user_increments(user_ids, batch_cutoff)
            
            # Apply speed layer increments and re-sort
            merged_results = []
            for batch_user in batch_top_users:
                merged_user = self._merge_user_post_count(
                    batch_user, 
                    speed_increments.get(batch_user.user_id),
                    batch_user.user_id
                )
                if merged_user:
                    merged_results.append(merged_user)
            
            # Sort by post count descending and limit
            merged_results.sort(key=lambda x: x.post_count, reverse=True)
            merged_results = merged_results[:limit]
            
            result = TopUsersResponse(
                users=merged_results,
                total_users=len(merged_results),
                last_updated=datetime.utcnow(),
                data_freshness_seconds=await self._calculate_data_freshness(batch_cutoff)
            )
            
            # Cache result for shorter time (top users change frequently)
            await self.redis.setex(cache_key, 60, result.dict())  # 1 minute cache
            
            return result
                
        except Exception as e:
            logger.error(f"Error querying top users: {e}")
            return TopUsersResponse(users=[], total_users=0, last_updated=datetime.utcnow())
    
    async def get_users_in_count_range(self, min_count: int, max_count: int, limit: int) -> List[UserPostCount]:
        """Get users within a post count range"""
        try:
            logger.debug(f"Querying users with post count between {min_count} and {max_count}")
            
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            
            # Query batch layer for users in range (with buffer for speed layer adjustments)
            batch_users = await self._get_batch_users_in_range(
                max(0, min_count - 100), max_count + 100, limit * 2
            )
            
            if not batch_users:
                return []
            
            # Get speed layer increments
            user_ids = [user.user_id for user in batch_users]
            speed_increments = await self._get_speed_user_increments(user_ids, batch_cutoff)
            
            # Merge and filter by final range
            results = []
            for batch_user in batch_users:
                merged_user = self._merge_user_post_count(
                    batch_user,
                    speed_increments.get(batch_user.user_id),
                    batch_user.user_id
                )
                if (merged_user and 
                    min_count <= merged_user.post_count <= max_count):
                    results.append(merged_user)
                    
                if len(results) >= limit:
                    break
            
            return results
                
        except Exception as e:
            logger.error(f"Error querying users in count range: {e}")
            return []
    
    async def get_system_health(self) -> SystemHealthResponse:
        """Get system health and statistics"""
        try:
            logger.debug("Querying system health")
            
            # Check cache
            cache_key = "system_health"
            cached_result = await self.redis.get(cache_key)
            if cached_result:
                return SystemHealthResponse.parse_obj(cached_result)
            
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            
            # Get metrics from both layers
            batch_metrics, speed_metrics = await asyncio.gather(
                self._get_batch_system_metrics(),
                self._get_speed_system_metrics(),
                return_exceptions=True
            )
            
            # Handle exceptions
            if isinstance(batch_metrics, Exception):
                logger.error(f"Error getting batch metrics: {batch_metrics}")
                batch_metrics = {"total_users": 0, "total_posts": 0, "active_boards": 0}
                
            if isinstance(speed_metrics, Exception):
                logger.error(f"Error getting speed metrics: {speed_metrics}")
                speed_metrics = {"new_users": 0, "post_increment": 0}
            
            result = SystemHealthResponse(
                total_users=batch_metrics.get("total_users", 0) + speed_metrics.get("new_users", 0),
                total_posts=batch_metrics.get("total_posts", 0) + speed_metrics.get("post_increment", 0),
                active_boards=batch_metrics.get("active_boards", 0),
                batch_cutoff_time=batch_cutoff,
                data_freshness_seconds=await self._calculate_data_freshness(batch_cutoff),
                speed_layer_health="healthy",  # TODO: implement actual health checks
                batch_layer_health="healthy",
                last_updated=datetime.utcnow()
            )
            
            # Cache for 1 minute
            await self.redis.setex(cache_key, 60, result.dict())
            return result
                
        except Exception as e:
            logger.error(f"Error getting system health: {e}")
            return SystemHealthResponse(last_updated=datetime.utcnow())
    
    async def get_user_post_count_async(self, user_id: int) -> Optional[UserPostCount]:
        """Async version of get_user_post_count"""
        return await self.get_user_post_count(user_id)
    
    async def get_data_freshness(self) -> DataFreshnessResponse:
        """Get data freshness information"""
        try:
            batch_cutoff = await self._get_batch_cutoff_timestamp()
            freshness_seconds = await self._calculate_data_freshness(batch_cutoff)
            
            result = DataFreshnessResponse(
                batch_cutoff_time=batch_cutoff,
                data_freshness_seconds=freshness_seconds,
                is_healthy=freshness_seconds < 3600,  # Healthy if < 1 hour old
                last_batch_run=await self._get_last_batch_run_time(),
                speed_layer_delay_seconds=await self._get_speed_layer_delay()
            )
            
            return result
        except Exception as e:
            logger.error(f"Error getting data freshness: {e}")
            return DataFreshnessResponse(
                batch_cutoff_time=datetime.utcnow() - timedelta(days=1),
                data_freshness_seconds=86400,
                is_healthy=False
            )
    
    async def refresh_cache(self, processing_date: Optional[str] = None):
        """Refresh cache and update metadata"""
        try:
            logger.info(f"Refreshing cache for processing date: {processing_date}")
            
            if processing_date:
                await self._update_batch_cutoff(processing_date)
            
            # Clear relevant caches
            await self.redis.delete_pattern("user_post_count:*")
            await self.redis.delete_pattern("top_users:*")
            await self.redis.delete("system_health")
            
            logger.info("Cache refresh completed")
            
        except Exception as e:
            logger.error(f"Error refreshing cache: {e}")
            raise
    
    # Private helper methods
    
    async def _get_batch_cutoff_timestamp(self) -> datetime:
        """Get batch processing cutoff timestamp from metadata"""
        try:
            query = """
            SELECT value 
            FROM processing_metadata 
            WHERE key = 'batch_cutoff_date'
            """
            result = await self.clickhouse.fetch_one(query)
            if result:
                cutoff_date = result['value']
                return datetime.strptime(cutoff_date, '%Y-%m-%d')
            else:
                # Default to yesterday if no metadata
                return datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=1)
        except Exception as e:
            logger.warning(f"Error getting batch cutoff timestamp, using yesterday: {e}")
            return datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=1)
    
    async def _get_batch_user_count(self, user_id: int) -> Optional[UserPostCountData]:
        """Get user count from batch layer"""
        query = """
        SELECT user_id, total_post_count, last_updated
        FROM user_post_counts_batch
        WHERE user_id = %s
        ORDER BY batch_version DESC
        LIMIT 1
        """
        result = await self.clickhouse.fetch_one(query, (user_id,))
        if result:
            return UserPostCountData(
                user_id=result['user_id'],
                post_count=result['total_post_count'],
                last_updated=result['last_updated']
            )
        return None
    
    async def _get_batch_user_counts(self, user_ids: List[int]) -> Dict[int, UserPostCountData]:
        """Get user counts for multiple users from batch layer"""
        if not user_ids:
            return {}
        
        placeholders = ','.join(['%s'] * len(user_ids))
        query = f"""
        SELECT user_id, total_post_count, last_updated
        FROM user_post_counts_batch
        WHERE user_id IN ({placeholders})
        ORDER BY batch_version DESC
        """
        results = await self.clickhouse.fetch_all(query, user_ids)
        
        return {
            row['user_id']: UserPostCountData(
                user_id=row['user_id'],
                post_count=row['total_post_count'],
                last_updated=row['last_updated']
            )
            for row in results
        }
    
    async def _get_speed_user_increment(self, user_id: int, cutoff_time: datetime) -> Optional[int]:
        """Get user post increment from speed layer"""
        query = """
        SELECT SUM(post_count_delta) as increment
        FROM user_post_counts_speed
        WHERE user_id = %s AND window_start > %s
        """
        result = await self.clickhouse.fetch_one(query, (user_id, cutoff_time))
        return result['increment'] if result and result['increment'] else 0
    
    async def _get_speed_user_increments(self, user_ids: List[int], cutoff_time: datetime) -> Dict[int, int]:
        """Get speed layer increments for multiple users"""
        if not user_ids:
            return {}
        
        placeholders = ','.join(['%s'] * len(user_ids))
        query = f"""
        SELECT user_id, SUM(post_count_delta) as increment
        FROM user_post_counts_speed
        WHERE user_id IN ({placeholders}) AND window_start > %s
        GROUP BY user_id
        """
        results = await self.clickhouse.fetch_all(query, user_ids + [cutoff_time])
        
        return {
            row['user_id']: row['increment'] or 0
            for row in results
        }
    
    def _merge_user_post_count(
        self, 
        batch_data: Optional[UserPostCountData], 
        speed_increment: Optional[int], 
        user_id: int
    ) -> Optional[UserPostCount]:
        """Core Lambda Architecture merge logic"""
        batch_count = batch_data.post_count if batch_data else 0
        speed_count = speed_increment or 0
        total_count = max(0, batch_count + speed_count)
        
        # If no data at all, return None
        if total_count == 0 and not batch_data:
            return None
        
        last_updated = batch_data.last_updated if batch_data else datetime.utcnow()
        
        return UserPostCount(
            user_id=user_id,
            post_count=total_count,
            last_updated=last_updated,
            batch_count=batch_count,
            speed_count=speed_count,
            data_source="lambda"  # Indicates merged data
        )
    
    async def _get_batch_top_users(self, limit: int) -> List[UserPostCountData]:
        """Get top users from batch layer"""
        query = """
        SELECT user_id, total_post_count, last_updated
        FROM user_post_counts_batch
        WHERE total_post_count > 0
        ORDER BY total_post_count DESC, user_id ASC
        LIMIT %s
        """
        results = await self.clickhouse.fetch_all(query, (limit,))
        
        return [
            UserPostCountData(
                user_id=row['user_id'],
                post_count=row['total_post_count'],
                last_updated=row['last_updated']
            )
            for row in results
        ]
    
    async def _get_batch_users_in_range(self, min_count: int, max_count: int, limit: int) -> List[UserPostCountData]:
        """Get users in count range from batch layer"""
        query = """
        SELECT user_id, total_post_count, last_updated
        FROM user_post_counts_batch
        WHERE total_post_count BETWEEN %s AND %s
        ORDER BY total_post_count DESC
        LIMIT %s
        """
        results = await self.clickhouse.fetch_all(query, (min_count, max_count, limit))
        
        return [
            UserPostCountData(
                user_id=row['user_id'],
                post_count=row['total_post_count'],
                last_updated=row['last_updated']
            )
            for row in results
        ]
    
    async def _get_batch_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics from batch layer"""
        query = """
        SELECT 
            count() as total_users,
            sum(total_post_count) as total_posts,
            (SELECT count(DISTINCT board_id) FROM board_statistics_batch) as active_boards
        FROM user_post_counts_batch
        WHERE total_post_count > 0
        """
        result = await self.clickhouse.fetch_one(query)
        return result or {"total_users": 0, "total_posts": 0, "active_boards": 0}
    
    async def _get_speed_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics from speed layer"""
        query = """
        SELECT 
            count(DISTINCT user_id) as new_users,
            sum(post_count_delta) as post_increment
        FROM user_post_counts_speed
        WHERE window_start > now() - INTERVAL 1 DAY
        """
        result = await self.clickhouse.fetch_one(query)
        return result or {"new_users": 0, "post_increment": 0}
    
    async def _calculate_data_freshness(self, batch_cutoff: datetime) -> int:
        """Calculate data freshness in seconds"""
        return int((datetime.utcnow() - batch_cutoff).total_seconds())
    
    async def _get_last_batch_run_time(self) -> Optional[datetime]:
        """Get last batch run time from metadata"""
        query = """
        SELECT completion_time
        FROM processing_metadata
        WHERE key = 'last_batch_completion'
        ORDER BY updated_at DESC
        LIMIT 1
        """
        result = await self.clickhouse.fetch_one(query)
        return result['completion_time'] if result else None
    
    async def _get_speed_layer_delay(self) -> int:
        """Get speed layer processing delay in seconds"""
        query = """
        SELECT 
            toUnixTimestamp(now()) - toUnixTimestamp(max(last_updated)) as delay_seconds
        FROM user_post_counts_speed
        """
        result = await self.clickhouse.fetch_one(query)
        return result['delay_seconds'] if result and result['delay_seconds'] else 0
    
    async def _update_batch_cutoff(self, processing_date: str):
        """Update batch cutoff date in metadata"""
        query = """
        INSERT INTO processing_metadata (key, value) VALUES ('batch_cutoff_date', %s)
        """
        await self.clickhouse.execute(query, (processing_date,))