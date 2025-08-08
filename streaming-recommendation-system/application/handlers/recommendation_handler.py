from typing import List
from ..dto.recommendation_dto import (
    RecommendationRequestDTO, RecommendationResponseDTO, ContentRecommendationDTO,
    ContinueWatchingItemDTO, TrendingRequestDTO, GenreRecommendationRequestDTO,
    SimilarContentRequestDTO, RealtimeRecommendationRequestDTO, InteractionRequestDTO
)
from ...domain.services.content_discovery_service import ContentDiscoveryService
from ...domain.services.continue_watching_service import ContinueWatchingService
from ...domain.services.similar_content_service import SimilarContentService
from ...domain.services.trending_service import TrendingService
from ...domain.services.genre_based_service import GenreBasedService
from ...domain.services.realtime_service import RealtimeRecommendationService
from ...domain.entities.recommendation import RecommendationRequest, RecommendationType
from ...domain.entities.user import DeviceType
from ...domain.entities.interaction import UserInteraction, InteractionType

class RecommendationHandler:
    def __init__(
        self,
        content_discovery_service: ContentDiscoveryService,
        continue_watching_service: ContinueWatchingService,
        similar_content_service: SimilarContentService,
        trending_service: TrendingService,
        genre_based_service: GenreBasedService,
        realtime_service: RealtimeRecommendationService
    ):
        self._content_discovery = content_discovery_service
        self._continue_watching = continue_watching_service
        self._similar_content = similar_content_service
        self._trending = trending_service
        self._genre_based = genre_based_service
        self._realtime = realtime_service

    async def get_personalized_recommendations(
        self,
        request: RecommendationRequestDTO
    ) -> RecommendationResponseDTO:
        """Get personalized content recommendations"""
        
        domain_request = RecommendationRequest(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendation_type=RecommendationType.PERSONALIZED,
            limit=request.limit,
            offset=request.offset,
            filters=request.filters,
            context=request.context,
            exclude_content_ids=request.exclude_content_ids
        )
        
        response = await self._content_discovery.get_personalized_recommendations(domain_request)
        return self._map_recommendation_response_to_dto(response)

    async def get_continue_watching(
        self,
        user_id: str,
        profile_id: str,
        limit: int = 20
    ) -> List[ContinueWatchingItemDTO]:
        """Get continue watching recommendations"""
        
        request = RecommendationRequest(
            user_id=user_id,
            profile_id=profile_id,
            recommendation_type=RecommendationType.CONTINUE_WATCHING,
            limit=limit
        )
        
        response = await self._continue_watching.get_continue_watching_recommendations(request)
        
        # Map to ContinueWatchingItemDTO
        continue_watching_items = []
        for rec in response.recommendations:
            metadata = rec.metadata
            
            item = ContinueWatchingItemDTO(
                content_id=rec.content_id,
                content_title=rec.content_title,
                content_type=rec.content_type,
                poster_url=metadata.get("poster_url"),
                progress_percentage=metadata.get("progress_percentage", 0.0),
                progress_seconds=metadata.get("progress_seconds", 0),
                total_duration_seconds=metadata.get("total_duration_seconds", 0),
                last_watched=metadata.get("last_watched"),
                season_number=metadata.get("season_number"),
                episode_number=metadata.get("episode_number"),
                series_title=metadata.get("series_title")
            )
            continue_watching_items.append(item)
        
        return continue_watching_items

    async def get_similar_content(
        self,
        request: SimilarContentRequestDTO
    ) -> RecommendationResponseDTO:
        """Get similar content recommendations"""
        
        response = await self._similar_content.get_similar_content_recommendations(
            request.content_id,
            request.user_id,
            request.profile_id,
            request.limit
        )
        
        return self._map_recommendation_response_to_dto(response)

    async def get_trending_content(
        self,
        request: TrendingRequestDTO,
        user_id: str,
        profile_id: str
    ) -> RecommendationResponseDTO:
        """Get trending content recommendations"""
        
        domain_request = RecommendationRequest(
            user_id=user_id,
            profile_id=profile_id,
            recommendation_type=RecommendationType.TRENDING,
            limit=request.limit
        )
        
        response = await self._trending.get_trending_recommendations(
            domain_request,
            time_window_hours=request.time_window_hours
        )
        
        return self._map_recommendation_response_to_dto(response)

    async def get_genre_recommendations(
        self,
        request: GenreRecommendationRequestDTO
    ) -> RecommendationResponseDTO:
        """Get genre-based recommendations"""
        
        domain_request = RecommendationRequest(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendation_type=RecommendationType.GENRE_BASED,
            limit=request.limit
        )
        
        if request.exploration_mode:
            # Get genre exploration recommendations
            recs = await self._genre_based.get_new_genre_exploration(
                request.user_id,
                request.profile_id,
                request.limit
            )
            
            # Convert to response format
            response = RecommendationResponseDTO(
                user_id=request.user_id,
                profile_id=request.profile_id,
                recommendations=[self._map_content_recommendation_to_dto(rec) for rec in recs],
                recommendation_type="genre_exploration",
                total_count=len(recs),
                generated_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=4),
                personalization_score=0.8
            )
            
        else:
            response = await self._genre_based.get_genre_recommendations(
                domain_request,
                specific_genres=request.genres
            )
            response = self._map_recommendation_response_to_dto(response)
        
        return response

    async def get_realtime_recommendations(
        self,
        request: RealtimeRecommendationRequestDTO
    ) -> RecommendationResponseDTO:
        """Get real-time context-aware recommendations"""
        
        domain_request = RecommendationRequest(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendation_type=RecommendationType.PERSONALIZED,
            limit=request.limit,
            context=request.context
        )
        
        response = await self._realtime.get_session_based_recommendations(
            domain_request,
            request.session_id,
            request.current_content_id
        )
        
        return self._map_recommendation_response_to_dto(response)

    async def get_device_optimized_recommendations(
        self,
        user_id: str,
        profile_id: str,
        device_type: str,
        limit: int = 20
    ) -> List[ContentRecommendationDTO]:
        """Get device-optimized recommendations"""
        
        device_enum = DeviceType(device_type)
        
        recs = await self._realtime.get_device_optimized_recommendations(
            user_id,
            profile_id,
            device_enum,
            limit
        )
        
        return [self._map_content_recommendation_to_dto(rec) for rec in recs]

    async def track_user_interaction(
        self,
        request: InteractionRequestDTO
    ) -> dict:
        """Track user interaction for improving recommendations"""
        
        # This would typically send to a message queue or event stream
        # For now, just return acknowledgment
        
        return {
            "status": "interaction_tracked",
            "user_id": request.user_id,
            "content_id": request.content_id,
            "interaction_type": request.interaction_type
        }

    def _map_recommendation_response_to_dto(self, response) -> RecommendationResponseDTO:
        """Map domain RecommendationResponse to DTO"""
        
        recommendations_dto = [
            self._map_content_recommendation_to_dto(rec) 
            for rec in response.recommendations
        ]
        
        return RecommendationResponseDTO(
            user_id=response.user_id,
            profile_id=response.profile_id,
            recommendations=recommendations_dto,
            recommendation_type=response.recommendation_type.value,
            total_count=response.total_count,
            generated_at=response.generated_at,
            expires_at=response.expires_at,
            algorithm_version=response.algorithm_version,
            personalization_score=response.personalization_score,
            cached=response.cached
        )

    def _map_content_recommendation_to_dto(self, rec) -> ContentRecommendationDTO:
        """Map domain ContentRecommendation to DTO"""
        
        return ContentRecommendationDTO(
            content_id=rec.content_id,
            content_title=rec.content_title,
            content_type=rec.content_type,
            poster_url=rec.metadata.get("poster_url"),
            duration_minutes=rec.metadata.get("duration_minutes"),
            release_year=rec.metadata.get("release_year"),
            rating=rec.metadata.get("rating"),
            genres=rec.metadata.get("genres"),
            imdb_rating=rec.metadata.get("imdb_rating"),
            description=rec.metadata.get("description"),
            score=rec.score.final_score,
            rank_position=rec.rank_position,
            reason=rec.get_user_friendly_reason(),
            explanation=rec.explanation,
            confidence=rec.confidence,
            metadata=rec.metadata
        )