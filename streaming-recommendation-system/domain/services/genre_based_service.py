from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation,
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..entities.content import ContentType
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class GenreBasedService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._interaction_repository = interaction_repository

    async def get_genre_recommendations(
        self,
        request: RecommendationRequest,
        specific_genres: Optional[List[str]] = None
    ) -> RecommendationResponse:
        """Get recommendations based on user's preferred genres"""
        
        # Get user's genre preferences from interaction history
        if not specific_genres:
            genre_preferences = await self._interaction_repository.get_user_genre_preferences(
                request.user_id, request.profile_id
            )
        else:
            # Use provided genres with equal weighting
            genre_preferences = {genre: 1.0 for genre in specific_genres}

        if not genre_preferences:
            return await self._get_fallback_genre_recommendations(request)

        # Get user's completed content to exclude
        completed_content = await self._interaction_repository.get_completed_content(
            request.user_id, request.profile_id, limit=500
        )
        exclude_ids = set(completed_content + (request.exclude_content_ids or []))

        # Get recommendations for each preferred genre
        recommendations = []
        
        # Sort genres by preference score
        sorted_genres = sorted(genre_preferences.items(), key=lambda x: x[1], reverse=True)
        
        for genre, preference_score in sorted_genres[:5]:  # Top 5 genres
            genre_content = await self._content_repository.get_by_genre(
                [genre], 
                limit=max(2, request.limit // len(sorted_genres))
            )
            
            for content in genre_content:
                if content.id in exclude_ids:
                    continue
                
                score = RecommendationScore(
                    base_score=preference_score,
                    genre_match_boost=0.2,
                    recency_boost=self._calculate_recency_boost(content.release_date),
                    popularity_boost=self._calculate_popularity_boost(content.imdb_rating)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.GENRE_PREFERENCE,
                    explanation=f"Because you like {genre}",
                    metadata={
                        "preferred_genre": genre,
                        "preference_score": preference_score,
                        "all_genres": content.genres
                    },
                    rank_position=0,  # Will be set later
                    confidence=self._calculate_confidence(preference_score, content.genres)
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
                
                exclude_ids.add(content.id)  # Avoid duplicates
                
                if len(recommendations) >= request.limit:
                    break
            
            if len(recommendations) >= request.limit:
                break

        # Sort by final score
        recommendations.sort(key=lambda x: x.score.final_score, reverse=True)
        
        # Update rank positions
        for i, rec in enumerate(recommendations):
            rec.rank_position = i + 1

        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=recommendations,
            recommendation_type=RecommendationType.GENRE_BASED,
            total_count=len(recommendations),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=4),
            personalization_score=self._calculate_personalization_score(genre_preferences),
            algorithm_version="1.0"
        )

    async def get_mixed_genre_recommendations(
        self,
        user_id: str,
        profile_id: str,
        primary_genre: str,
        limit: int = 20
    ) -> List[ContentRecommendation]:
        """Get recommendations mixing primary genre with complementary genres"""
        
        # Define complementary genre combinations
        genre_combinations = {
            "action": ["thriller", "adventure", "crime"],
            "comedy": ["romance", "drama", "family"],
            "drama": ["romance", "thriller", "biography"],
            "horror": ["thriller", "mystery", "supernatural"],
            "romance": ["comedy", "drama", "family"],
            "sci-fi": ["action", "thriller", "adventure"],
            "thriller": ["action", "crime", "mystery"],
            "documentary": ["biography", "history", "nature"]
        }
        
        complementary_genres = genre_combinations.get(primary_genre.lower(), [])
        all_genres = [primary_genre] + complementary_genres[:2]  # Primary + 2 complementary
        
        recommendations = []
        
        # Get content for each genre with different weightings
        for i, genre in enumerate(all_genres):
            weight = 1.0 if i == 0 else 0.7 - (i * 0.2)  # Decreasing weight
            genre_limit = limit // len(all_genres) if i == 0 else limit // (len(all_genres) * 2)
            
            genre_content = await self._content_repository.get_by_genre([genre], limit=genre_limit)
            
            for content in genre_content:
                score = RecommendationScore(
                    base_score=weight,
                    genre_match_boost=0.1 if i == 0 else 0.05,
                    recency_boost=self._calculate_recency_boost(content.release_date)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.GENRE_PREFERENCE,
                    explanation=f"Mixed {primary_genre} recommendation",
                    metadata={
                        "primary_genre": primary_genre,
                        "content_genre": genre,
                        "is_primary": i == 0
                    },
                    rank_position=0,
                    confidence=weight
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
        
        # Sort and limit
        recommendations.sort(key=lambda x: x.score.final_score, reverse=True)
        return recommendations[:limit]

    async def get_new_genre_exploration(
        self,
        user_id: str,
        profile_id: str,
        limit: int = 10
    ) -> List[ContentRecommendation]:
        """Recommend content from genres user hasn't explored much"""
        
        # Get user's genre preferences
        genre_preferences = await self._interaction_repository.get_user_genre_preferences(
            user_id, profile_id
        )
        
        # Define all available genres
        all_genres = [
            "action", "adventure", "animation", "biography", "comedy", "crime",
            "documentary", "drama", "family", "fantasy", "history", "horror",
            "music", "mystery", "romance", "sci-fi", "sport", "thriller", "war", "western"
        ]
        
        # Find unexplored or less-preferred genres
        unexplored_genres = []
        for genre in all_genres:
            preference = genre_preferences.get(genre, 0.0)
            if preference < 0.3:  # Low or no interaction with this genre
                unexplored_genres.append((genre, 1.0 - preference))  # Higher score for less explored
        
        # Sort by exploration potential
        unexplored_genres.sort(key=lambda x: x[1], reverse=True)
        
        recommendations = []
        
        # Get highly rated content from unexplored genres
        for genre, exploration_score in unexplored_genres[:3]:
            genre_content = await self._content_repository.get_by_genre(
                [genre], limit=limit // 3
            )
            
            # Filter for highly rated content to increase acceptance
            high_quality_content = [c for c in genre_content if (c.imdb_rating or 0) >= 7.5]
            
            for content in high_quality_content:
                score = RecommendationScore(
                    base_score=exploration_score * 0.6,  # Lower base for exploration
                    popularity_boost=0.3,  # Boost popular content for genre exploration
                    recency_boost=self._calculate_recency_boost(content.release_date)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.GENRE_PREFERENCE,
                    explanation=f"Explore {genre} - highly rated",
                    metadata={
                        "exploration_genre": genre,
                        "exploration_score": exploration_score,
                        "is_exploration": True
                    },
                    rank_position=0,
                    confidence=0.6  # Lower confidence for exploration
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
        
        return recommendations[:limit]

    def _calculate_recency_boost(self, release_date: datetime) -> float:
        """Calculate boost for recent releases"""
        days_ago = (datetime.utcnow() - release_date).days
        
        if days_ago < 30:
            return 0.1
        elif days_ago < 365:
            return 0.05
        else:
            return 0.0

    def _calculate_popularity_boost(self, rating: Optional[float]) -> float:
        """Calculate boost based on content rating"""
        if not rating:
            return 0.0
        
        if rating >= 8.5:
            return 0.15
        elif rating >= 7.5:
            return 0.1
        elif rating >= 6.5:
            return 0.05
        else:
            return 0.0

    def _calculate_confidence(self, preference_score: float, content_genres: List[str]) -> float:
        """Calculate confidence in genre-based recommendation"""
        base_confidence = min(preference_score, 1.0)
        
        # Boost confidence for content with multiple matching genres
        # This would require checking against all user's preferred genres
        genre_match_bonus = min(len(content_genres) * 0.05, 0.2)
        
        return min(base_confidence + genre_match_bonus, 1.0)

    def _calculate_personalization_score(self, genre_preferences: Dict[str, float]) -> float:
        """Calculate how personalized the recommendations are"""
        if not genre_preferences:
            return 0.1
        
        # Higher personalization score for users with clear genre preferences
        max_preference = max(genre_preferences.values())
        genre_diversity = len([p for p in genre_preferences.values() if p > 0.2])
        
        return min(max_preference * (genre_diversity / 10.0), 1.0)

    async def _get_fallback_genre_recommendations(
        self,
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """Fallback recommendations for users without clear genre preferences"""
        
        # Get popular content from diverse genres
        popular_genres = ["action", "comedy", "drama", "thriller"]
        recommendations = []
        
        for genre in popular_genres:
            genre_content = await self._content_repository.get_by_genre(
                [genre], limit=request.limit // len(popular_genres)
            )
            
            for content in genre_content:
                if (content.imdb_rating or 0) >= 7.0:  # Only high-quality content
                    score = RecommendationScore(
                        base_score=0.6,
                        popularity_boost=0.2,
                        recency_boost=self._calculate_recency_boost(content.release_date)
                    )
                    
                    rec = ContentRecommendation(
                        content_id=content.id,
                        content_title=content.title,
                        content_type=content.content_type.value,
                        score=score,
                        reason=RecommendationReason.HIGHLY_RATED,
                        explanation=f"Popular {genre}",
                        metadata={"fallback_genre": genre},
                        rank_position=len(recommendations) + 1,
                        confidence=0.6
                    )
                    rec.score.calculate_final_score()
                    recommendations.append(rec)
        
        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=recommendations[:request.limit],
            recommendation_type=RecommendationType.GENRE_BASED,
            total_count=len(recommendations[:request.limit]),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=2),
            personalization_score=0.2
        )