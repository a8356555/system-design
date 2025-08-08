from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation,
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..entities.user import ViewingSession, DeviceType
from ..entities.interaction import UserInteraction, InteractionType
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class RealtimeRecommendationService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._interaction_repository = interaction_repository

    async def get_session_based_recommendations(
        self,
        request: RecommendationRequest,
        session_id: str,
        current_content_id: Optional[str] = None
    ) -> RecommendationResponse:
        """Get real-time recommendations based on current viewing session"""
        
        # Get current session interactions
        session_interactions = await self._get_session_interactions(
            request.user_id, request.profile_id, session_id
        )
        
        if not session_interactions:
            return await self._get_fallback_realtime_recommendations(request)

        # Analyze session patterns
        session_context = self._analyze_session_context(session_interactions)
        
        # Generate recommendations based on session context
        recommendations = []
        
        # 1. Next episode recommendations (if watching series)
        if current_content_id:
            next_episode_recs = await self._get_next_episode_recommendations(
                current_content_id, request.user_id, request.profile_id
            )
            recommendations.extend(next_episode_recs)
        
        # 2. Session mood-based recommendations
        mood_recs = await self._get_mood_based_recommendations(
            session_context, request.user_id, request.profile_id, 
            limit=request.limit // 2
        )
        recommendations.extend(mood_recs)
        
        # 3. Immediate similar content
        if session_interactions:
            recent_content_id = session_interactions[-1].content_id
            similar_recs = await self._get_immediate_similar_recommendations(
                recent_content_id, request.user_id, request.profile_id,
                limit=request.limit // 3
            )
            recommendations.extend(similar_recs)
        
        # Remove duplicates and rank
        unique_recs = self._deduplicate_and_rank(recommendations, request.limit)
        
        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=unique_recs,
            recommendation_type=RecommendationType.PERSONALIZED,
            total_count=len(unique_recs),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=15),  # Short expiry for real-time
            personalization_score=0.9,
            algorithm_version="realtime-1.0"
        )

    async def get_device_optimized_recommendations(
        self,
        user_id: str,
        profile_id: str,
        device_type: DeviceType,
        limit: int = 20
    ) -> List[ContentRecommendation]:
        """Get recommendations optimized for specific device type"""
        
        recommendations = []
        
        if device_type == DeviceType.MOBILE:
            # Mobile: Shorter content, episodes, clips
            content_filters = {
                "max_duration_minutes": 45,
                "content_types": ["episode", "short", "documentary"]
            }
            explanation_suffix = "perfect for mobile"
            
        elif device_type == DeviceType.TV:
            # TV: Movies, series, high-quality content
            content_filters = {
                "min_duration_minutes": 20,
                "content_types": ["movie", "series", "documentary"],
                "min_rating": 7.0
            }
            explanation_suffix = "great for TV viewing"
            
        elif device_type == DeviceType.TABLET:
            # Tablet: Mixed content, good for binge-watching
            content_filters = {
                "content_types": ["episode", "movie", "documentary"]
            }
            explanation_suffix = "perfect for tablet"
            
        else:  # DESKTOP/LAPTOP
            # Desktop: Any content, work-friendly during breaks
            content_filters = {
                "max_duration_minutes": 60,
                "content_types": ["episode", "short", "documentary"]
            }
            explanation_suffix = "good for quick viewing"

        # This would integrate with content repository filtering
        # For now, simulate device-optimized recommendations
        
        base_recommendations = await self._content_repository.get_highly_rated(limit=limit)
        
        for i, content in enumerate(base_recommendations):
            # Apply device-specific scoring
            device_score = self._calculate_device_compatibility_score(content, device_type)
            
            score = RecommendationScore(
                base_score=device_score,
                popularity_boost=0.1,
                recency_boost=self._calculate_recency_boost(content.release_date)
            )
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.HIGHLY_RATED,
                explanation=f"Highly rated - {explanation_suffix}",
                metadata={
                    "device_optimized": True,
                    "device_type": device_type.value,
                    "device_score": device_score
                },
                rank_position=i + 1,
                confidence=0.8
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
        
        return recommendations

    async def get_contextual_recommendations(
        self,
        user_id: str,
        profile_id: str,
        context: Dict[str, Any],
        limit: int = 20
    ) -> List[ContentRecommendation]:
        """Get recommendations based on contextual information"""
        
        # Extract context
        time_of_day = context.get("time_of_day", "evening")
        day_of_week = context.get("day_of_week", "weekday")
        location = context.get("location")
        weather = context.get("weather")
        
        # Determine context-based preferences
        context_preferences = self._determine_context_preferences(
            time_of_day, day_of_week, location, weather
        )
        
        recommendations = []
        
        # Get content based on contextual preferences
        for genre, weight in context_preferences.items():
            genre_content = await self._content_repository.get_by_genre(
                [genre], limit=max(2, int(limit * weight))
            )
            
            for content in genre_content:
                contextual_score = weight + self._get_context_bonus(content, context)
                
                score = RecommendationScore(
                    base_score=contextual_score,
                    recency_boost=self._calculate_recency_boost(content.release_date)
                )
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.GENRE_PREFERENCE,
                    explanation=f"Perfect for {time_of_day} viewing",
                    metadata={
                        "contextual": True,
                        "time_of_day": time_of_day,
                        "context_score": contextual_score
                    },
                    rank_position=0,
                    confidence=0.7
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
                
                if len(recommendations) >= limit:
                    break
            
            if len(recommendations) >= limit:
                break
        
        return recommendations[:limit]

    async def _get_session_interactions(
        self,
        user_id: str,
        profile_id: str,
        session_id: str
    ) -> List[UserInteraction]:
        """Get interactions from current viewing session"""
        
        # This would filter interactions by session_id
        # For now, get recent interactions (last hour)
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        
        all_interactions = await self._interaction_repository.get_user_interactions(
            user_id, profile_id, limit=50
        )
        
        # Filter to recent interactions (simulating session)
        session_interactions = [
            interaction for interaction in all_interactions
            if interaction.timestamp >= cutoff_time
        ]
        
        return session_interactions

    def _analyze_session_context(self, interactions: List[UserInteraction]) -> Dict[str, Any]:
        """Analyze current session to determine viewing patterns and mood"""
        
        if not interactions:
            return {"mood": "neutral", "pace": "normal", "genre_trend": []}
        
        # Analyze interaction patterns
        total_interactions = len(interactions)
        play_count = sum(1 for i in interactions if i.interaction_type == InteractionType.PLAY)
        complete_count = sum(1 for i in interactions if i.interaction_type == InteractionType.COMPLETE)
        seek_count = sum(1 for i in interactions if i.interaction_type == InteractionType.SEEK)
        
        # Determine viewing pace
        if complete_count / max(play_count, 1) > 0.8:
            pace = "binge"  # High completion rate
        elif seek_count / total_interactions > 0.3:
            pace = "browsing"  # Lots of seeking/skipping
        else:
            pace = "normal"
        
        # Determine session mood based on interaction timing
        interaction_intervals = []
        for i in range(1, len(interactions)):
            interval = (interactions[i].timestamp - interactions[i-1].timestamp).total_seconds()
            interaction_intervals.append(interval)
        
        avg_interval = sum(interaction_intervals) / len(interaction_intervals) if interaction_intervals else 60
        
        if avg_interval < 30:
            mood = "impatient"  # Quick switching
        elif avg_interval > 300:
            mood = "relaxed"  # Long viewing sessions
        else:
            mood = "engaged"
        
        return {
            "mood": mood,
            "pace": pace,
            "total_interactions": total_interactions,
            "completion_rate": complete_count / max(play_count, 1),
            "avg_interaction_interval": avg_interval
        }

    async def _get_next_episode_recommendations(
        self,
        current_content_id: str,
        user_id: str,
        profile_id: str
    ) -> List[ContentRecommendation]:
        """Get next episode recommendations"""
        
        current_content = await self._content_repository.get_by_id(current_content_id)
        if not current_content or not hasattr(current_content, 'series_id'):
            return []
        
        # Get all episodes for the series
        all_episodes = await self._content_repository.get_episodes_for_series(
            current_content.series_id
        )
        
        # Find next episode
        current_index = next(
            (i for i, ep in enumerate(all_episodes) if ep.id == current_content_id), -1
        )
        
        if current_index == -1 or current_index >= len(all_episodes) - 1:
            return []
        
        next_episode = all_episodes[current_index + 1]
        
        score = RecommendationScore(base_score=1.0)
        
        rec = ContentRecommendation(
            content_id=next_episode.id,
            content_title=next_episode.title,
            content_type=next_episode.content_type.value,
            score=score,
            reason=RecommendationReason.CONTINUE_WATCHING,
            explanation="Next episode",
            metadata={
                "is_next_episode": True,
                "auto_play_eligible": True
            },
            rank_position=1,
            confidence=1.0
        )
        rec.score.calculate_final_score()
        
        return [rec]

    async def _get_mood_based_recommendations(
        self,
        session_context: Dict[str, Any],
        user_id: str,
        profile_id: str,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get recommendations based on detected session mood"""
        
        mood = session_context.get("mood", "neutral")
        pace = session_context.get("pace", "normal")
        
        # Map mood and pace to content preferences
        if mood == "impatient" or pace == "browsing":
            # Short, engaging content
            target_genres = ["action", "comedy", "thriller"]
            explanation = "Quick and engaging"
        elif mood == "relaxed" and pace == "binge":
            # Long-form, series content
            target_genres = ["drama", "documentary", "mystery"]
            explanation = "Perfect for binge-watching"
        else:
            # Balanced content
            target_genres = ["comedy", "drama", "action"]
            explanation = "Matches your viewing mood"
        
        recommendations = []
        
        for genre in target_genres:
            genre_content = await self._content_repository.get_by_genre(
                [genre], limit=limit // len(target_genres)
            )
            
            for content in genre_content:
                mood_score = 0.8 + (0.2 if genre in target_genres[:2] else 0.0)
                
                score = RecommendationScore(base_score=mood_score, genre_match_boost=0.1)
                
                rec = ContentRecommendation(
                    content_id=content.id,
                    content_title=content.title,
                    content_type=content.content_type.value,
                    score=score,
                    reason=RecommendationReason.VIEWING_HISTORY,
                    explanation=explanation,
                    metadata={
                        "mood_based": True,
                        "detected_mood": mood,
                        "detected_pace": pace
                    },
                    rank_position=0,
                    confidence=0.75
                )
                rec.score.calculate_final_score()
                recommendations.append(rec)
        
        return recommendations

    async def _get_immediate_similar_recommendations(
        self,
        content_id: str,
        user_id: str,
        profile_id: str,
        limit: int
    ) -> List[ContentRecommendation]:
        """Get immediately similar content recommendations"""
        
        similar_content = await self._content_repository.get_similar_content(
            content_id, limit=limit
        )
        
        recommendations = []
        
        for content in similar_content:
            score = RecommendationScore(base_score=0.7, recency_boost=0.2)
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.CONTENT_SIMILARITY,
                explanation="Similar to what you're watching",
                metadata={"immediate_similar": True},
                rank_position=0,
                confidence=0.8
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)
        
        return recommendations

    def _calculate_device_compatibility_score(self, content, device_type: DeviceType) -> float:
        """Calculate how well content fits the device type"""
        
        duration = content.duration_minutes
        
        if device_type == DeviceType.MOBILE:
            # Prefer shorter content on mobile
            if duration <= 30:
                return 0.9
            elif duration <= 60:
                return 0.7
            else:
                return 0.5
        elif device_type == DeviceType.TV:
            # Prefer longer, high-quality content on TV
            if duration >= 90 and (content.imdb_rating or 0) >= 7.5:
                return 0.9
            elif duration >= 45:
                return 0.8
            else:
                return 0.6
        else:
            # Balanced for other devices
            return 0.7

    def _determine_context_preferences(
        self,
        time_of_day: str,
        day_of_week: str,
        location: Optional[str],
        weather: Optional[str]
    ) -> Dict[str, float]:
        """Determine content preferences based on context"""
        
        preferences = {}
        
        # Time-based preferences
        if time_of_day in ["morning", "afternoon"]:
            preferences.update({"comedy": 0.3, "documentary": 0.25, "family": 0.2})
        elif time_of_day == "evening":
            preferences.update({"drama": 0.3, "thriller": 0.25, "action": 0.2})
        elif time_of_day in ["night", "late_night"]:
            preferences.update({"horror": 0.25, "thriller": 0.3, "mystery": 0.2})
        
        # Day-based preferences
        if day_of_week in ["friday", "saturday"]:
            preferences["action"] = preferences.get("action", 0) + 0.1
            preferences["comedy"] = preferences.get("comedy", 0) + 0.1
        elif day_of_week == "sunday":
            preferences["family"] = preferences.get("family", 0) + 0.15
            preferences["documentary"] = preferences.get("documentary", 0) + 0.1
        
        # Weather-based preferences (if available)
        if weather == "rainy":
            preferences["drama"] = preferences.get("drama", 0) + 0.1
            preferences["romance"] = preferences.get("romance", 0) + 0.1
        
        return preferences

    def _get_context_bonus(self, content, context: Dict[str, Any]) -> float:
        """Get bonus score for content matching context"""
        bonus = 0.0
        
        # Award bonus for content that fits context
        if content.content_type.value == "movie" and context.get("time_of_day") == "evening":
            bonus += 0.05
        elif content.content_type.value == "episode" and context.get("day_of_week") in ["weekday"]:
            bonus += 0.05
        
        return bonus

    def _calculate_recency_boost(self, release_date: datetime) -> float:
        """Calculate boost for recent releases"""
        days_ago = (datetime.utcnow() - release_date).days
        
        if days_ago < 7:
            return 0.15
        elif days_ago < 30:
            return 0.1
        else:
            return 0.0

    def _deduplicate_and_rank(
        self,
        recommendations: List[ContentRecommendation],
        limit: int
    ) -> List[ContentRecommendation]:
        """Remove duplicates and rank recommendations"""
        
        seen = set()
        unique_recs = []
        
        for rec in recommendations:
            if rec.content_id not in seen:
                seen.add(rec.content_id)
                unique_recs.append(rec)
        
        # Sort by final score
        unique_recs.sort(key=lambda x: x.score.final_score, reverse=True)
        
        # Update rank positions
        for i, rec in enumerate(unique_recs[:limit]):
            rec.rank_position = i + 1
        
        return unique_recs[:limit]

    async def _get_fallback_realtime_recommendations(
        self,
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """Fallback for when session data is unavailable"""
        
        trending_content = await self._content_repository.get_trending(limit=request.limit)
        
        recommendations = []
        
        for i, content in enumerate(trending_content):
            score = RecommendationScore(base_score=0.6, trending_boost=0.2)
            
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
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            personalization_score=0.3
        )