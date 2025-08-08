from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from .service import ProductRecommendationService
from .schemas import ProductRecommendationResponse
from ...shared.database import get_db

router = APIRouter(prefix="/recommendations", tags=["Product Recommendations"])

@router.get("/product/{product_id}", response_model=ProductRecommendationResponse)
async def get_product_recommendations(
    product_id: str,
    user_id: str = None,
    limit: int = 10,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """
    Get product recommendations based on item-item collaborative filtering.
    Returns products similar to the given product_id.
    """
    try:
        service = ProductRecommendationService(db)
        
        # Track user interaction asynchronously if user_id provided
        if user_id:
            background_tasks.add_task(
                service.track_interaction, 
                user_id, 
                "view_recommendations", 
                product_id
            )
        
        return await service.get_recommendations(product_id, user_id, limit)
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recommendation error: {str(e)}")

@router.post("/interaction")
async def track_interaction(
    user_id: str,
    product_id: str,
    interaction_type: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """
    Track user interactions for improving recommendations.
    interaction_type: view, cart_add, purchase, rating
    """
    try:
        service = ProductRecommendationService(db)
        background_tasks.add_task(
            service.track_interaction,
            user_id,
            interaction_type,
            product_id
        )
        return {"status": "interaction_tracked"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tracking error: {str(e)}")