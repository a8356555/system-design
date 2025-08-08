from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .schemas import TrendingProductsResponse
from ...shared.database import get_db
from ...shared.cache import cache_service

router = APIRouter(prefix="/recommendations", tags=["Trending Products"])

@router.get("/trending", response_model=TrendingProductsResponse)
async def get_trending_products(
    limit: int = 20,
    time_window: str = "24h",
    category: str = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get trending products based on recent interactions.
    time_window: 24h, 7d, or 30d
    category: Filter by product category (optional)
    """
    try:
        # For now, return a simplified trending response
        # In a real implementation, this would calculate trends from UserInteraction data
        
        cache_key = f"trending:{time_window}:{category or 'all'}:{limit}"
        cached = await cache_service.get(cache_key)
        if cached:
            cached['cached'] = True
            return TrendingProductsResponse(**cached)

        # Placeholder trending data
        trending_data = {
            "recommendations": [],
            "total_count": 0,
            "time_window": time_window,
            "cached": False
        }
        
        # Cache for 15 minutes
        await cache_service.set(cache_key, trending_data, ttl=900)
        return TrendingProductsResponse(**trending_data)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trending products error: {str(e)}")