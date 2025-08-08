from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .service import UserRecommendationService
from .schemas import UserRecommendationResponse
from ...shared.database import get_db

router = APIRouter(prefix="/recommendations", tags=["User Recommendations"])

@router.get("/user/{user_id}", response_model=UserRecommendationResponse)
async def get_user_recommendations(
    user_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    Get personalized recommendations for a user.
    Uses collaborative filtering for existing users, popular items for new users.
    """
    try:
        service = UserRecommendationService(db)
        return await service.get_recommendations(user_id, limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recommendation error: {str(e)}")

@router.get("/homepage/{user_id}", response_model=UserRecommendationResponse)
async def get_homepage_recommendations(
    user_id: str,
    limit: int = 12,
    db: AsyncSession = Depends(get_db)
):
    """
    Get homepage recommendations optimized for display.
    Returns fewer, higher-quality recommendations for homepage.
    """
    try:
        service = UserRecommendationService(db)
        return await service.get_recommendations(user_id, limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Homepage recommendation error: {str(e)}")