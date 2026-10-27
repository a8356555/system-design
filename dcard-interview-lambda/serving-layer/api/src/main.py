"""
Serving Layer API for Dcard Lambda Architecture

This FastAPI application provides the query interface that merges data from both
batch and speed layers to serve real-time queries with historical accuracy.
"""

from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import logging
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from .config.settings import get_settings
from .services.user_post_service import UserPostService
from .models.responses import (
    UserPostCount, TopUsersResponse, SystemHealthResponse, DataFreshnessResponse
)
from .middleware.metrics import MetricsMiddleware
from .middleware.logging import LoggingMiddleware
from .database.clickhouse_client import ClickHouseClient
from .database.redis_client import RedisClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global service instances
user_post_service: Optional[UserPostService] = None
clickhouse_client: Optional[ClickHouseClient] = None
redis_client: Optional[RedisClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global user_post_service, clickhouse_client, redis_client
    
    settings = get_settings()
    
    # Initialize database connections
    logger.info("Initializing database connections...")
    clickhouse_client = ClickHouseClient(settings.clickhouse_url)
    redis_client = RedisClient(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db
    )
    
    # Initialize service
    user_post_service = UserPostService(
        clickhouse_client=clickhouse_client,
        redis_client=redis_client,
        settings=settings
    )
    
    # Test connections
    await user_post_service.health_check()
    logger.info("✅ All services initialized successfully")
    
    yield
    
    # Cleanup
    logger.info("Shutting down services...")
    if redis_client:
        await redis_client.close()
    if clickhouse_client:
        await clickhouse_client.close()


# Create FastAPI app
app = FastAPI(
    title="Dcard Lambda Architecture - Serving Layer API",
    description="Query interface merging batch and speed layer data",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)


# Dependency injection
async def get_user_post_service() -> UserPostService:
    """Get user post service instance"""
    if user_post_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return user_post_service


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for load balancer"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}


@app.get("/api/v1/users/{user_id}/post-count", 
         response_model=UserPostCount, 
         tags=["Users"])
async def get_user_post_count(
    user_id: int = Query(..., ge=1, description="User ID"),
    service: UserPostService = Depends(get_user_post_service)
) -> UserPostCount:
    """
    Get post count for a specific user using Lambda Architecture:
    - Merges batch layer (accurate historical) + speed layer (recent incremental)
    """
    try:
        result = await service.get_user_post_count(user_id)
        if result is None:
            raise HTTPException(status_code=404, detail="User not found")
        return result
    except Exception as e:
        logger.error(f"Error getting post count for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/v1/users/post-counts", 
          response_model=List[UserPostCount], 
          tags=["Users"])
async def get_user_post_counts(
    user_ids: List[int],
    service: UserPostService = Depends(get_user_post_service)
) -> List[UserPostCount]:
    """Get post counts for multiple users (batch query optimization)"""
    if not user_ids or len(user_ids) > 1000:
        raise HTTPException(
            status_code=400, 
            detail="user_ids must be non-empty and contain at most 1000 items"
        )
    
    # Validate all user IDs
    if any(uid <= 0 for uid in user_ids):
        raise HTTPException(status_code=400, detail="All user IDs must be positive")
    
    try:
        results = await service.get_user_post_counts(user_ids)
        return results
    except Exception as e:
        logger.error(f"Error getting post counts for multiple users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/users/top", 
         response_model=TopUsersResponse, 
         tags=["Users"])
async def get_top_users(
    limit: int = Query(100, ge=1, le=1000, description="Number of top users to return"),
    service: UserPostService = Depends(get_user_post_service)
) -> TopUsersResponse:
    """Get top users by post count"""
    try:
        result = await service.get_top_users(limit)
        return result
    except Exception as e:
        logger.error(f"Error getting top users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/users/count-range", 
         response_model=List[UserPostCount], 
         tags=["Users"])
async def get_users_in_count_range(
    min_count: int = Query(..., ge=0, description="Minimum post count"),
    max_count: int = Query(..., ge=0, description="Maximum post count"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results to return"),
    service: UserPostService = Depends(get_user_post_service)
) -> List[UserPostCount]:
    """Get users with post count in a specific range"""
    if min_count > max_count:
        raise HTTPException(status_code=400, detail="min_count cannot be greater than max_count")
    
    try:
        results = await service.get_users_in_count_range(min_count, max_count, limit)
        return results
    except Exception as e:
        logger.error(f"Error getting users in count range: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/system/health", 
         response_model=SystemHealthResponse, 
         tags=["System"])
async def get_system_health(
    service: UserPostService = Depends(get_user_post_service)
) -> SystemHealthResponse:
    """Get system health and statistics"""
    try:
        result = await service.get_system_health()
        return result
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/system/data-freshness", 
         response_model=DataFreshnessResponse, 
         tags=["System"])
async def get_data_freshness(
    service: UserPostService = Depends(get_user_post_service)
) -> DataFreshnessResponse:
    """Get data freshness information"""
    try:
        result = await service.get_data_freshness()
        return result
    except Exception as e:
        logger.error(f"Error getting data freshness: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/v1/cache/refresh", tags=["Cache"])
async def refresh_cache(
    background_tasks: BackgroundTasks,
    processing_date: Optional[str] = None,
    service: UserPostService = Depends(get_user_post_service)
) -> Dict[str, str]:
    """Refresh cache (for manual cache invalidation)"""
    try:
        # Run cache refresh in background
        background_tasks.add_task(service.refresh_cache, processing_date)
        return {"message": "Cache refresh initiated", "processing_date": processing_date}
    except Exception as e:
        logger.error(f"Error initiating cache refresh: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/users/{user_id}/post-count/async", 
         response_model=UserPostCount, 
         tags=["Users"])
async def get_user_post_count_async(
    user_id: int = Query(..., ge=1, description="User ID"),
    service: UserPostService = Depends(get_user_post_service)
) -> UserPostCount:
    """Async endpoint for getting user post count (non-blocking)"""
    try:
        result = await service.get_user_post_count_async(user_id)
        if result is None:
            raise HTTPException(status_code=404, detail="User not found")
        return result
    except Exception as e:
        logger.error(f"Error getting post count async for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/metrics", tags=["Monitoring"])
async def get_metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "timestamp": datetime.utcnow().isoformat()}
    )


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug",
        workers=settings.workers if not settings.debug else 1
    )