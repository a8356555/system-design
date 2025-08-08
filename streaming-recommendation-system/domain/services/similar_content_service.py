from typing import List, Optional
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation,
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class SimilarContentService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._interaction_repository = interaction_repository

    async def get_similar_content_recommendations(
        self,
        content_id: str,
        user_id: str,
        profile_id: str,
        limit: int = 20
    ) -> RecommendationResponse:
        """Get recommendations similar to a specific content"""
        
        # Get the base content
        base_content = await self._content_repository.get_by_id(content_id)
        if not base_content:
            return self._empty_response(user_id, profile_id)

        # Get similar content using different methods
        similar_content = await self._content_repository.get_similar_content(
            content_id, limit=limit * 2
        )

        if not similar_content:
            # Fallback to genre-based similarity
            similar_content = await self._content_repository.get_by_genre(
                base_content.genres, limit=limit * 2
            )

        # Get user's completed content to exclude
        completed_content = await self._interaction_repository.get_completed_content(
            user_id, profile_id, limit=500
        )
        exclude_ids = set([content_id] + completed_content)

        # Build recommendations
        recommendations = []
        
        for content in similar_content:
            if content.id in exclude_ids:
                continue

            # Calculate similarity score
            similarity_score = self._calculate_similarity_score(base_content, content)
            
            score = RecommendationScore(
                base_score=similarity_score,
                genre_match_boost=self._calculate_genre_match_boost(base_content.genres, content.genres),
                recency_boost=self._calculate_recency_boost(content.release_date),
                popularity_boost=self._calculate_popularity_boost(content.imdb_rating)
            )

            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.CONTENT_SIMILARITY,
                explanation=f"More like {base_content.title}",
                metadata={
                    "reference_content_id": content_id,
                    "reference_content_title": base_content.title,
                    "similarity_score": similarity_score,
                    "common_genres": list(set(base_content.genres) & set(content.genres))
                },
                rank_position=len(recommendations) + 1,
                confidence=self._calculate_confidence(similarity_score)
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)

            if len(recommendations) >= limit:
                break

        # Sort by final score
        recommendations.sort(key=lambda x: x.score.final_score, reverse=True)
        
        # Update rank positions
        for i, rec in enumerate(recommendations):
            rec.rank_position = i + 1

        return RecommendationResponse(
            user_id=user_id,
            profile_id=profile_id,
            recommendations=recommendations,
            recommendation_type=RecommendationType.SIMILAR,
            total_count=len(recommendations),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=6),
            personalization_score=0.3,  # Content-based, less personalized
            algorithm_version="1.0"
        )

    async def get_because_you_watched_recommendations(
        self,
        user_id: str,
        profile_id: str,
        reference_content_id: str,
        limit: int = 10
    ) -> List[ContentRecommendation]:
        """Get 'Because you watched X' recommendations"""
        
        response = await self.get_similar_content_recommendations(
            reference_content_id, user_id, profile_id, limit
        )
        
        # Update reason and explanation
        reference_content = await self._content_repository.get_by_id(reference_content_id)
        reference_title = reference_content.title if reference_content else "this content"
        
        for rec in response.recommendations:
            rec.reason = RecommendationReason.CONTENT_SIMILARITY
            rec.explanation = f"Because you watched {reference_title}"
            rec.metadata["reference_content_title"] = reference_title

        return response.recommendations

    def _calculate_similarity_score(self, content1, content2) -> float:
        """Calculate similarity score between two content items"""
        score = 0.0
        
        # Genre similarity (40% weight)
        common_genres = set(content1.genres) & set(content2.genres)
        all_genres = set(content1.genres) | set(content2.genres)
        genre_similarity = len(common_genres) / len(all_genres) if all_genres else 0
        score += genre_similarity * 0.4
        
        # Content type match (20% weight)
        if content1.content_type == content2.content_type:
            score += 0.2
        
        # Rating similarity (15% weight)
        if content1.rating == content2.rating:
            score += 0.15
        
        # Release year similarity (10% weight)
        year_diff = abs(content1.release_date.year - content2.release_date.year)
        year_similarity = max(0, 1 - year_diff / 10)  # Similar if within 10 years
        score += year_similarity * 0.1
        
        # Language match (10% weight)
        if content1.language == content2.language:
            score += 0.1
        
        # Cast/Director similarity (5% weight)
        common_cast = set(content1.cast) & set(content2.cast)
        common_directors = set(content1.directors) & set(content2.directors)
        if common_cast or common_directors:
            score += 0.05
        
        return min(score, 1.0)

    def _calculate_genre_match_boost(self, genres1: List[str], genres2: List[str]) -> float:
        """Calculate boost for genre matches"""
        if not genres1 or not genres2:
            return 0.0
        
        common_genres = set(genres1) & set(genres2)
        return len(common_genres) * 0.05  # 5% boost per common genre

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
        
        if rating >= 8.0:
            return 0.1
        elif rating >= 7.0:
            return 0.05
        else:
            return 0.0

    def _calculate_confidence(self, similarity_score: float) -> float:
        """Calculate confidence in the recommendation"""
        return min(similarity_score + 0.1, 1.0)

    def _empty_response(self, user_id: str, profile_id: str) -> RecommendationResponse:
        """Return empty response when no similar content found"""
        return RecommendationResponse(
            user_id=user_id,
            profile_id=profile_id,
            recommendations=[],
            recommendation_type=RecommendationType.SIMILAR,
            total_count=0,
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            personalization_score=0.0
        )