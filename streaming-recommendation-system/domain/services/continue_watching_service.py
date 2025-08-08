from typing import List
from datetime import datetime, timedelta
from ..entities.recommendation import (
    RecommendationRequest, RecommendationResponse, ContentRecommendation,
    RecommendationType, RecommendationReason, RecommendationScore
)
from ..entities.interaction import ViewingProgress
from ..repositories.content_repository import ContentRepositoryInterface
from ..repositories.interaction_repository import InteractionRepositoryInterface

class ContinueWatchingService:
    def __init__(
        self,
        content_repository: ContentRepositoryInterface,
        interaction_repository: InteractionRepositoryInterface
    ):
        self._content_repository = content_repository
        self._interaction_repository = interaction_repository

    async def get_continue_watching_recommendations(
        self,
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """Get content that user can continue watching"""
        
        # Get all incomplete viewing progress
        continue_watching = await self._interaction_repository.get_continue_watching(
            request.user_id, request.profile_id, limit=request.limit * 2
        )
        
        if not continue_watching:
            return RecommendationResponse(
                user_id=request.user_id,
                profile_id=request.profile_id,
                recommendations=[],
                recommendation_type=RecommendationType.CONTINUE_WATCHING,
                total_count=0,
                generated_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24),
                personalization_score=1.0
            )

        # Get content details
        content_ids = [progress.content_id for progress in continue_watching]
        content_list = await self._content_repository.get_by_ids(content_ids)
        content_dict = {content.id: content for content in content_list}

        # Build recommendations
        recommendations = []
        
        for progress in continue_watching[:request.limit]:
            content = content_dict.get(progress.content_id)
            if not content:
                continue

            # Calculate priority score based on progress and recency
            priority_score = self._calculate_continue_watching_score(progress)
            
            score = RecommendationScore(
                base_score=priority_score,
                recency_boost=self._calculate_recency_boost(progress.last_watched)
            )

            # Special handling for series episodes
            explanation = self._get_continue_watching_explanation(progress, content)
            
            rec = ContentRecommendation(
                content_id=content.id,
                content_title=content.title,
                content_type=content.content_type.value,
                score=score,
                reason=RecommendationReason.CONTINUE_WATCHING,
                explanation=explanation,
                metadata={
                    "progress_percentage": progress.get_progress_percentage(),
                    "progress_seconds": progress.progress_seconds,
                    "last_watched": progress.last_watched.isoformat(),
                    "watch_count": progress.watch_count
                },
                rank_position=len(recommendations) + 1,
                confidence=0.95  # High confidence for continue watching
            )
            rec.score.calculate_final_score()
            recommendations.append(rec)

        # Sort by priority (most recent and highest progress first)
        recommendations.sort(key=lambda x: x.score.final_score, reverse=True)
        
        # Update rank positions
        for i, rec in enumerate(recommendations):
            rec.rank_position = i + 1

        return RecommendationResponse(
            user_id=request.user_id,
            profile_id=request.profile_id,
            recommendations=recommendations,
            recommendation_type=RecommendationType.CONTINUE_WATCHING,
            total_count=len(recommendations),
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
            personalization_score=1.0
        )

    async def get_next_episode_recommendations(
        self,
        user_id: str,
        profile_id: str,
        series_id: str,
        current_episode_id: str
    ) -> List[ContentRecommendation]:
        """Get next episode recommendations for series"""
        
        # Get current episode details
        current_episode = await self._content_repository.get_by_id(current_episode_id)
        if not current_episode:
            return []

        # Get next episode in series
        all_episodes = await self._content_repository.get_episodes_for_series(series_id)
        
        # Find current episode and get next one
        current_index = -1
        for i, episode in enumerate(all_episodes):
            if episode.id == current_episode_id:
                current_index = i
                break
        
        if current_index == -1 or current_index >= len(all_episodes) - 1:
            return []  # No next episode

        next_episode = all_episodes[current_index + 1]
        
        score = RecommendationScore(base_score=1.0)  # Maximum priority for next episode
        
        rec = ContentRecommendation(
            content_id=next_episode.id,
            content_title=next_episode.title,
            content_type=next_episode.content_type.value,
            score=score,
            reason=RecommendationReason.CONTINUE_WATCHING,
            explanation=f"Next episode: S{next_episode.season_number}E{next_episode.episode_number}",
            metadata={
                "is_next_episode": True,
                "season": next_episode.season_number,
                "episode": next_episode.episode_number,
                "series_id": series_id
            },
            rank_position=1,
            confidence=1.0
        )
        rec.score.calculate_final_score()
        
        return [rec]

    def _calculate_continue_watching_score(self, progress: ViewingProgress) -> float:
        """Calculate priority score for continue watching content"""
        
        # Base score from progress percentage (sweet spot is 10-80%)
        progress_pct = progress.get_progress_percentage()
        
        if progress_pct < 5:
            progress_score = 0.3  # Just started, lower priority
        elif progress_pct < 80:
            progress_score = 0.8 + (progress_pct / 100) * 0.2  # Higher priority for partially watched
        else:
            progress_score = 0.5  # Almost finished, medium priority
        
        # Recency factor
        days_since_watched = (datetime.utcnow() - progress.last_watched).days
        if days_since_watched < 1:
            recency_score = 1.0
        elif days_since_watched < 7:
            recency_score = 0.8
        elif days_since_watched < 30:
            recency_score = 0.6
        else:
            recency_score = 0.3
        
        # Watch count factor (rewatching is lower priority)
        watch_count_score = max(0.5, 1.0 - (progress.watch_count - 1) * 0.1)
        
        return progress_score * recency_score * watch_count_score

    def _calculate_recency_boost(self, last_watched: datetime) -> float:
        """Calculate boost based on how recently content was watched"""
        hours_ago = (datetime.utcnow() - last_watched).total_seconds() / 3600
        
        if hours_ago < 1:
            return 0.3
        elif hours_ago < 24:
            return 0.2
        elif hours_ago < 72:
            return 0.1
        else:
            return 0.0

    def _get_continue_watching_explanation(self, progress: ViewingProgress, content) -> str:
        """Get human-readable explanation for continue watching"""
        
        progress_pct = progress.get_progress_percentage()
        
        if hasattr(content, 'episode_number') and content.episode_number:
            # For episodes
            return f"Continue S{content.season_number}E{content.episode_number} ({progress_pct:.0f}% watched)"
        else:
            # For movies
            if progress_pct < 10:
                return "You started watching this"
            elif progress_pct < 50:
                return f"Continue watching ({progress_pct:.0f}% watched)"
            else:
                return f"Finish watching ({progress_pct:.0f}% watched)"