from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation, 
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..entities.user import User, UserProfile
from ..entities.content import Content
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.user_repository import UserRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class ContentDiscoveryService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        user_repository: UserRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._user_repository = user_repository
        self._interaction_repository = interaction_repository

    async def get_personalized_recommendations(
        self,
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """Generate personalized content recommendations"""
        
        # Get user and profile
        user = await self._user_repository.get_by_id(request.user_id)
        profile = await self._user_repository.get_profile_by_id(request.profile_id)
        
        if not user or not profile:
            return await self._get_fallback_recommendations(request)

        # Get user's interaction history
        user_interactions = await self._interaction_repository.get_user_interactions(
            request.user_id, request.profile_id, limit=200
        )

        # Get user's completed content to exclude
        completed_content = await self._interaction_repository.get_completed_content(
            request.user_id, request.profile_id, limit=500
        )
        
        exclude_ids = set(request.exclude_content_ids + completed_content)

        # Generate recommendations from different sources
        recommendations = []
        
        # 1. Content-based recommendations (40% weight)
        if user_interactions:
            content_based = await self._get_content_based_recommendations(
                user_interactions, exclude_ids, limit=request.limit // 2
            )
            recommendations.extend(content_based)

        # 2. Genre-based recommendations (30% weight)
        genre_prefs = await self._interaction_repository.get_user_genre_preferences(
            request.user_id, request.profile_id
        )
        if genre_prefs:
            genre_based = await self._get_genre_based_recommendations(
                genre_prefs, exclude_ids, limit=request.limit // 3
            )
            recommendations.extend(genre_based)

        # 3. Trending content (20% weight)
        trending = await self._get_trending_recommendations(
            exclude_ids, limit=request.limit // 4
        )
        recommendations.extend(trending)

        # 4. Highly rated content (10% weight)  
        highly_rated = await self._get_highly_rated_recommendations(
            exclude_ids, limit=request.limit // 10
        )
        recommendations.extend(highly_rated)

        # Remove duplicates and sort by score
        unique_recs = self._deduplicate_and_rank(recommendations, request.limit)

        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=unique_recs,
            recommendation_type=RecommendationType.PERSONALIZED,
            total_count=len(unique_recs),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=2),
            personalization_score=self._calculate_personalization_score(user_interactions)
        )

    async def _get_content_based_recommendations(
        self,
        user_interactions: List,
        exclude_ids: set,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get recommendations based on content similarity"""
        
        recommendations = []
        
        # Get user's most watched/highly rated content
        preferred_content = self._extract_preferred_content(user_interactions)
        
        for content_id, preference_score in preferred_content[:5]:  # Top 5 preferred content
            similar_content = await self._content_repository.get_similar_content(
                content_id, limit=10
            )
            
            for content in similar_content:
                if content.id in exclude_ids:
                    continue
                    
                score = RecommendationScore(
                    base_score=preference_score * 0.8,  # Reduce by similarity confidence
                    recency_boost=self._calculate_recency_boost(content.release_date)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.CONTENT_SIMILARITY,
                    explanation=f"Because you watched similar content",
                    metadata={"reference_content": content_id},
                    rank_position=0,  # Will be set later
                    confidence=0.8
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
                
                if len(recommendations) >= limit:
                    break
                    
            if len(recommendations) >= limit:
                break
        
        return recommendations

    async def _get_genre_based_recommendations(
        self,
        genre_preferences: Dict[str, float],
        exclude_ids: set,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get recommendations based on preferred genres"""
        
        recommendations = []
        top_genres = sorted(genre_preferences.items(), key=lambda x: x[1], reverse=True)[:3]
        
        for genre, preference_score in top_genres:
            genre_content = await self._content_repository.get_by_genre(
                [genre], limit=limit // len(top_genres) + 2
            )
            
            for content in genre_content:
                if content.id in exclude_ids:
                    continue
                    
                score = RecommendationScore(
                    base_score=preference_score,
                    genre_match_boost=0.1,
                    recency_boost=self._calculate_recency_boost(content.release_date)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.GENRE_PREFERENCE,
                    explanation=f"Because you like {genre}",
                    metadata={"genres": [genre]},
                    rank_position=0,
                    confidence=0.7
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
                
                if len(recommendations) >= limit:
                    break
        
        return recommendations

    async def _get_trending_recommendations(
        self,
        exclude_ids: set,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get trending content recommendations"""
        
        trending_content = await self._content_repository.get_trending(
            time_window_hours=24, limit=limit * 2
        )
        
        recommendations = []
        for content in trending_content:
            if content.id in exclude_ids:
                continue
                
            score = RecommendationScore(
                base_score=0.6,
                trending_boost=0.3,
                popularity_boost=0.1
            )
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.TRENDING,
                explanation="Trending now",
                metadata={"trending": True},
                rank_position=0,
                confidence=0.6
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
            
            if len(recommendations) >= limit:
                break
        
        return recommendations

    async def _get_highly_rated_recommendations(
        self,
        exclude_ids: set,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get highly rated content recommendations"""
        
        highly_rated = await self._content_repository.get_highly_rated(
            min_rating=4.5, limit=limit * 2
        )
        
        recommendations = []
        for content in highly_rated:
            if content.id in exclude_ids:
                continue
                
            score = RecommendationScore(
                base_score=0.7,
                popularity_boost=0.2
            )
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.HIGHLY_RATED,
                explanation="Highly rated by viewers",
                metadata={"rating": content.imdb_rating},
                rank_position=0,
                confidence=0.75
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
            
            if len(recommendations) >= limit:
                break
        
        return recommendations

    def _extract_preferred_content(self, interactions: List) -> List[tuple]:
        """Extract user's preferred content from interactions"""
        content_scores = {}
        
        for interaction in interactions:
            content_id = interaction.content_id
            
            # Weight different interaction types
            weight = {
                'COMPLETE': 5.0,
                'RATE': interaction.rating or 3.0,
                'LIKE': 4.0,
                'PLAY': 1.0
            }.get(interaction.interaction_type.value, 1.0)
            
            content_scores[content_id] = content_scores.get(content_id, 0) + weight
        
        # Sort by score and normalize
        sorted_content = sorted(content_scores.items(), key=lambda x: x[1], reverse=True)
        max_score = max(content_scores.values()) if content_scores else 1.0
        
        return [(cid, score / max_score) for cid, score in sorted_content]

    def _calculate_recency_boost(self, release_date: datetime) -> float:
        """Calculate boost for recent releases"""
        days_ago = (datetime.utcnow() - release_date).days
        
        if days_ago < 7:
            return 0.2
        elif days_ago < 30:
            return 0.1
        elif days_ago < 90:
            return 0.05
        else:
            return 0.0

    def _calculate_personalization_score(self, interactions: List) -> float:
        """Calculate how personalized these recommendations can be"""
        if not interactions:
            return 0.1
        
        interaction_count = len(interactions)
        return min(interaction_count / 100.0, 1.0)  # Max personalization at 100+ interactions

    def _deduplicate_and_rank(
        self,
        recommendations: List[ContentRecommendation],
        limit: int
    ) -> List[ContentRecommendation]:
        """Remove duplicates and rank recommendations"""
        
        # Remove duplicates
        seen = set()
        unique_recs = []
        for rec in recommendations:
            if rec.content_id not in seen:
                seen.add(rec.content_id)
                unique_recs.append(rec)
        
        # Sort by final score
        unique_recs.sort(key=lambda x: x.score.final_score, reverse=True)
        
        # Set rank positions
        for i, rec in enumerate(unique_recs[:limit]):
            rec.rank_position = i + 1
        
        return unique_recs[:limit]

    async def _get_fallback_recommendations(
        self,
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """Fallback recommendations for new users"""
        
        trending = await self._content_repository.get_trending(limit=request.limit // 2)
        highly_rated = await self._content_repository.get_highly_rated(limit=request.limit // 2)
        
        recommendations = []
        
        for i, content in enumerate(trending + highly_rated):
            score = RecommendationScore(base_score=0.5, trending_boost=0.2)
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.TRENDING,
                explanation="Popular content",
                metadata={},
                rank_position=i + 1,
                confidence=0.5
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
        
        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=recommendations[:request.limit],
            recommendation_type=RecommendationType.TRENDING,
            total_count=len(recommendations[:request.limit]),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            personalization_score=0.1
        )