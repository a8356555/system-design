from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from .service import CartRecommendationService
from .schemas import CartRecommendationResponse
from ...shared.database import get_db

router = APIRouter(prefix="/recommendations", tags=["Cart Recommendations"])

@router.post("/cart/{user_id}", response_model=CartRecommendationResponse)
async def get_cart_recommendations(
    user_id: str,
    cart_product_ids: List[str],
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """
    Get recommendations based on current cart contents.
    Includes frequently bought together, upsells, and bundle deals.
    """
    try:
        service = CartRecommendationService(db)
        return await service.get_recommendations(user_id, cart_product_ids, limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cart recommendation error: {str(e)}")

@router.get("/cart/{user_id}", response_model=CartRecommendationResponse)
async def get_cart_recommendations_get(
    user_id: str,
    cart_items: str,  # Comma-separated product IDs
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """
    GET version of cart recommendations for easier testing.
    cart_items should be comma-separated product IDs.
    """
    try:
        cart_product_ids = [item.strip() for item in cart_items.split(',') if item.strip()]
        service = CartRecommendationService(db)
        return await service.get_recommendations(user_id, cart_product_ids, limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cart recommendation error: {str(e)}")