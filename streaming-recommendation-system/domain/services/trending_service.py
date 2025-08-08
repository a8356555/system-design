from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation,
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..entities.content import ContentType
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class TrendingService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._interaction_repository = interaction_repository

    async def get_trending_recommendations(
        self,
        request: RecommendationRequest,
        time_window_hours: int = 24,
        content_type: Optional[ContentType] = None
    ) -> RecommendationResponse:
        """Get trending content recommendations"""
        
        # Get trending interactions data
        trending_interactions = await self._interaction_repository.get_trending_interactions(
            hours_back=time_window_hours
        )
        
        if not trending_interactions:
            # Fallback to general trending content
            return await self._get_fallback_trending(request, time_window_hours, content_type)

        # Calculate trending scores
        trending_scores = self._calculate_trending_scores(trending_interactions, time_window_hours)
        
        # Get content details
        content_ids = list(trending_scores.keys())
        trending_content = await self._content_repository.get_by_ids(content_ids)
        
        # Filter by content type if specified
        if content_type:
            trending_content = [c for c in trending_content if c.content_type == content_type]

        # Get user's completed content to exclude
        completed_content = await self._interaction_repository.get_completed_content(
            request.user_id, request.profile_id, limit=500
        )
        exclude_ids = set(completed_content + (request.exclude_content_ids or []))

        # Build recommendations
        recommendations = []
        
        for content in trending_content:
            if content.id in exclude_ids:
                continue

            trend_data = trending_scores.get(content.id, {})
            trend_score = trend_data.get('score', 0.0)
            
            score = RecommendationScore(
                base_score=trend_score,
                trending_boost=0.3,
                popularity_boost=self._calculate_popularity_boost(trend_data),
                recency_boost=self._calculate_recency_boost(content.release_date)
            )

            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.TRENDING,
                explanation=self._get_trending_explanation(trend_data, time_window_hours),
                metadata={
                    "trending_score": trend_score,
                    "interaction_count": trend_data.get('total_interactions', 0),
                    "growth_rate": trend_data.get('growth_rate', 0.0),
                    "time_window_hours": time_window_hours,
                    "unique_viewers": trend_data.get('unique_viewers', 0)
                },
                rank_position=len(recommendations) + 1,
                confidence=self._calculate_confidence(trend_data)
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)

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
            recommendation_type=RecommendationType.TRENDING,
            total_count=len(recommendations),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),  # Short expiry for trending
            personalization_score=0.2,  # Low personalization for trending
            algorithm_version="1.0"
        )

    async def get_trending_by_genre(
        self,
        genre: str,
        user_id: str,
        profile_id: str,
        limit: int = 20,
        time_window_hours: int = 24
    ) -> List[ContentRecommendation]:
        """Get trending content for a specific genre"""
        
        # Get trending content
        trending_content = await self._content_repository.get_trending(
            time_window_hours=time_window_hours,
            limit=limit * 2,
            content_type=None
        )
        
        # Filter by genre
        genre_content = [c for c in trending_content if genre.lower() in [g.lower() for g in c.genres]]
        
        # Build recommendations
        recommendations = []
        
        for i, content in enumerate(genre_content[:limit]):
            score = RecommendationScore(
                base_score=0.8,
                trending_boost=0.2,
                genre_match_boost=0.1
            )
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.TRENDING,
                explanation=f"Trending in {genre}",
                metadata={
                    "genre": genre,
                    "trending_in_genre": True
                },
                rank_position=i + 1,
                confidence=0.8
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
        
        return recommendations

    async def get_regional_trending(
        self,
        country: str,
        user_id: str,
        profile_id: str,
        limit: int = 20,
        time_window_hours: int = 24
    ) -> List[ContentRecommendation]:
        """Get trending content for a specific region/country"""
        
        # This would require region-specific interaction data
        # For now, return general trending with country context
        
        request = RecommendationRequest(
            user_id=user_id,
            profile_id=profile_id,
            recommendation_type=RecommendationType.TRENDING,
            limit=limit,
            context={"country": country}
        )
        
        response = await self.get_trending_recommendations(request, time_window_hours)
        
        # Update explanations for regional context
        for rec in response.recommendations:
            rec.explanation = f"Trending in {country}"
            rec.metadata["country"] = country
        
        return response.recommendations

    def _calculate_trending_scores(
        self,
        trending_interactions: List[Dict[str, Any]],
        time_window_hours: int
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate trending scores based on interaction data"""
        
        content_stats = {}
        
        for interaction_data in trending_interactions:
            content_id = interaction_data.get('content_id')
            interaction_type = interaction_data.get('interaction_type')
            user_id = interaction_data.get('user_id')
            timestamp = interaction_data.get('timestamp')
            
            if not all([content_id, interaction_type, user_id, timestamp]):
                continue
            
            if content_id not in content_stats:
                content_stats[content_id] = {
                    'total_interactions': 0,
                    'unique_viewers': set(),
                    'play_count': 0,
                    'complete_count': 0,
                    'like_count': 0,
                    'recent_interactions': []
                }
            
            stats = content_stats[content_id]
            stats['total_interactions'] += 1
            stats['unique_viewers'].add(user_id)
            stats['recent_interactions'].append(timestamp)
            
            # Weight different interaction types
            if interaction_type == 'PLAY':
                stats['play_count'] += 1
            elif interaction_type == 'COMPLETE':
                stats['complete_count'] += 1
            elif interaction_type == 'LIKE':
                stats['like_count'] += 1
        
        # Calculate final scores
        trending_scores = {}
        
        for content_id, stats in content_stats.items():
            # Base score from interaction volume
            unique_viewers = len(stats['unique_viewers'])
            total_interactions = stats['total_interactions']
            
            # Normalize scores
            volume_score = min(unique_viewers / 1000.0, 1.0)  # Max at 1000 unique viewers
            engagement_score = min(total_interactions / unique_viewers, 5.0) / 5.0 if unique_viewers > 0 else 0
            
            # Quality score (completion rate)
            completion_rate = stats['complete_count'] / max(stats['play_count'], 1)
            quality_score = min(completion_rate, 1.0)
            
            # Growth rate (interactions in last few hours vs earlier)
            growth_rate = self._calculate_growth_rate(stats['recent_interactions'], time_window_hours)
            
            # Final trending score
            trending_score = (
                volume_score * 0.4 +
                engagement_score * 0.3 +
                quality_score * 0.2 +
                growth_rate * 0.1
            )
            
            trending_scores[content_id] = {
                'score': trending_score,
                'total_interactions': total_interactions,
                'unique_viewers': unique_viewers,
                'completion_rate': completion_rate,
                'growth_rate': growth_rate
            }
        
        return trending_scores

    def _calculate_growth_rate(self, timestamps: List[datetime], time_window_hours: int) -> float:
        """Calculate growth rate of interactions over time"""
        if len(timestamps) < 2:
            return 0.0
        
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(hours=time_window_hours // 2)
        
        recent_count = sum(1 for ts in timestamps if ts >= recent_cutoff)
        earlier_count = len(timestamps) - recent_count
        
        if earlier_count == 0:
            return 1.0 if recent_count > 0 else 0.0
        
        return min((recent_count / earlier_count) - 1.0, 2.0) / 2.0  # Normalize to 0-1

    def _calculate_popularity_boost(self, trend_data: Dict[str, Any]) -> float:
        """Calculate popularity boost from trending data"""
        unique_viewers = trend_data.get('unique_viewers', 0)
        
        if unique_viewers > 10000:
            return 0.2
        elif unique_viewers > 1000:
            return 0.15
        elif unique_viewers > 100:
            return 0.1
        else:
            return 0.05

    def _calculate_recency_boost(self, release_date: datetime) -> float:
        """Calculate boost for recent releases"""
        days_ago = (datetime.utcnow() - release_date).days
        
        if days_ago < 7:
            return 0.15
        elif days_ago < 30:
            return 0.1
        else:
            return 0.0

    def _calculate_confidence(self, trend_data: Dict[str, Any]) -> float:
        """Calculate confidence in trending recommendation"""
        unique_viewers = trend_data.get('unique_viewers', 0)
        total_interactions = trend_data.get('total_interactions', 0)
        
        # Higher confidence with more data points
        data_confidence = min((unique_viewers * total_interactions) / 10000.0, 1.0)
        
        return max(0.6, data_confidence)  # Minimum 60% confidence

    def _get_trending_explanation(self, trend_data: Dict[str, Any], time_window_hours: int) -> str:
        """Get human-readable explanation for trending content"""
        unique_viewers = trend_data.get('unique_viewers', 0)
        growth_rate = trend_data.get('growth_rate', 0.0)
        
        if growth_rate > 0.5:
            return f"Surging popularity - {unique_viewers:,} viewers in {time_window_hours}h"
        elif unique_viewers > 1000:
            return f"Trending now - {unique_viewers:,} viewers"
        else:
            return "Trending now"

    async def _get_fallback_trending(
        self,
        request: RecommendationRequest,
        time_window_hours: int,
        content_type: Optional[ContentType]
    ) -> RecommendationResponse:
        """Fallback trending recommendations when interaction data is unavailable"""
        
        trending_content = await self._content_repository.get_trending(
            time_window_hours=time_window_hours,
            limit=request.limit,
            content_type=content_type
        )
        
        recommendations = []
        
        for i, content in enumerate(trending_content):
            score = RecommendationScore(base_score=0.6, trending_boost=0.3)
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.TRENDING,
                explanation="Trending now",
                metadata={"fallback": True},
                rank_position=i + 1,
                confidence=0.6
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
        
        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=recommendations,
            recommendation_type=RecommendationType.TRENDING,
            total_count=len(recommendations),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            personalization_score=0.1
        )