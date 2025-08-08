from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from ...application.dto.recommendation_dto import (
    RecommendationRequestDTO, RecommendationResponseDTO, ContentRecommendationDTO,
    ContinueWatchingItemDTO, TrendingRequestDTO, GenreRecommendationRequestDTO,
    SimilarContentRequestDTO, RealtimeRecommendationRequestDTO, InteractionRequestDTO
)
from ...application.handlers.recommendation_handler import RecommendationHandler
from ...infrastructure.dependencies import get_recommendation_handler

router = APIRouter(prefix="/recommendations", tags=["Streaming Recommendations"])

@router.get("/personalized/{user_id}/{profile_id}", response_model=RecommendationResponseDTO)
async def get_personalized_recommendations(
    user_id: str,
    profile_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get personalized content recommendations for a user profile.
    Uses collaborative filtering, content-based filtering, and trending data.
    """
    try:
        request = RecommendationRequestDTO(
            user_id=user_id,
            profile_id=profile_id,
            recommendation_type="personalized",
            limit=limit,
            offset=offset
        )
        return await handler.get_personalized_recommendations(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recommendation error: {str(e)}")

@router.get("/continue-watching/{user_id}/{profile_id}", response_model=List[ContinueWatchingItemDTO])
async def get_continue_watching(
    user_id: str,
    profile_id: str,
    limit: int = Query(20, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get content that user can continue watching.
    Returns content with viewing progress and watch history.
    """
    try:
        return await handler.get_continue_watching(user_id, profile_id, limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Continue watching error: {str(e)}")

@router.get("/similar/{content_id}", response_model=RecommendationResponseDTO)
async def get_similar_content(
    content_id: str,
    user_id: str,
    profile_id: str,
    limit: int = Query(20, ge=1, le=100),
    similarity_threshold: float = Query(0.3, ge=0.0, le=1.0),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get content similar to a specific movie, series, or episode.
    Uses content-based filtering with genre, cast, and metadata similarity.
    """
    try:
        request = SimilarContentRequestDTO(
            content_id=content_id,
            user_id=user_id,
            profile_id=profile_id,
            similarity_threshold=similarity_threshold,
            limit=limit
        )
        return await handler.get_similar_content(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Similar content error: {str(e)}")

@router.get("/trending", response_model=RecommendationResponseDTO)
async def get_trending_content(
    user_id: str,
    profile_id: str,
    time_window_hours: int = Query(24, ge=1, le=168),
    content_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get trending content based on recent user interactions.
    Can be filtered by content type, genre, or country.
    """
    try:
        request = TrendingRequestDTO(
            time_window_hours=time_window_hours,
            content_type=content_type,
            genre=genre,
            country=country,
            limit=limit
        )
        return await handler.get_trending_content(request, user_id, profile_id)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trending content error: {str(e)}")

@router.get("/genre/{user_id}/{profile_id}", response_model=RecommendationResponseDTO)
async def get_genre_recommendations(
    user_id: str,
    profile_id: str,
    genres: Optional[str] = Query(None, description="Comma-separated list of genres"),
    exploration_mode: bool = Query(False, description="Recommend unexplored genres"),
    mixed_genres: bool = Query(False, description="Mix primary with complementary genres"),
    limit: int = Query(20, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get recommendations based on genre preferences.
    Can explore new genres or mix complementary genres.
    """
    try:
        genre_list = [g.strip() for g in genres.split(",")] if genres else None
        
        request = GenreRecommendationRequestDTO(
            user_id=user_id,
            profile_id=profile_id,
            genres=genre_list,
            exploration_mode=exploration_mode,
            mixed_genres=mixed_genres,
            limit=limit
        )
        return await handler.get_genre_recommendations(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Genre recommendations error: {str(e)}")

@router.get("/realtime/{user_id}/{profile_id}", response_model=RecommendationResponseDTO)
async def get_realtime_recommendations(
    user_id: str,
    profile_id: str,
    session_id: str,
    device_type: str = Query(..., description="Device type: mobile, tv, tablet, desktop"),
    current_content_id: Optional[str] = Query(None),
    time_of_day: Optional[str] = Query(None, description="morning, afternoon, evening, night"),
    limit: int = Query(20, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get real-time context-aware recommendations.
    Considers current session, device type, and contextual factors.
    """
    try:
        context = {}
        if time_of_day:
            context["time_of_day"] = time_of_day
        
        request = RealtimeRecommendationRequestDTO(
            user_id=user_id,
            profile_id=profile_id,
            session_id=session_id,
            current_content_id=current_content_id,
            device_type=device_type,
            context=context,
            limit=limit
        )
        return await handler.get_realtime_recommendations(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Real-time recommendations error: {str(e)}")

@router.get("/device-optimized/{user_id}/{profile_id}", response_model=List[ContentRecommendationDTO])
async def get_device_optimized_recommendations(
    user_id: str,
    profile_id: str,
    device_type: str = Query(..., description="Device type: mobile, tv, tablet, desktop"),
    limit: int = Query(20, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get recommendations optimized for specific device types.
    Mobile: shorter content, TV: movies/series, etc.
    """
    try:
        return await handler.get_device_optimized_recommendations(
            user_id, profile_id, device_type, limit
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device-optimized recommendations error: {str(e)}")

@router.post("/interaction")
async def track_user_interaction(
    request: InteractionRequestDTO,
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Track user interactions for improving recommendations.
    Supports: play, pause, stop, seek, complete, rate, like, dislike, etc.
    """
    try:
        return await handler.track_user_interaction(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Interaction tracking error: {str(e)}")

@router.get("/homepage/{user_id}/{profile_id}", response_model=RecommendationResponseDTO)
async def get_homepage_feed(
    user_id: str,
    profile_id: str,
    limit: int = Query(50, ge=1, le=100),
    handler: RecommendationHandler = Depends(get_recommendation_handler)
):
    """
    Get comprehensive homepage feed with mixed recommendation types.
    Combines personalized, trending, and continue watching content.
    """
    try:
        request = RecommendationRequestDTO(
            user_id=user_id,
            profile_id=profile_id,
            recommendation_type="homepage",
            limit=limit
        )
        return await handler.get_personalized_recommendations(request)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Homepage feed error: {str(e)}")