from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class RecommendationType(Enum):
    PERSONALIZED = "personalized"
    TRENDING = "trending" 
    SIMILAR = "similar"
    CONTINUE_WATCHING = "continue_watching"
    GENRE_BASED = "genre_based"
    NEW_RELEASES = "new_releases"
    BECAUSE_YOU_WATCHED = "because_you_watched"
    TOP_PICKS = "top_picks"

class RecommendationReason(Enum):
    VIEWING_HISTORY = "based_on_viewing_history"
    SIMILAR_USERS = "users_like_you_watched" 
    CONTENT_SIMILARITY = "similar_to_watched_content"
    TRENDING = "trending_now"
    NEW_RELEASE = "new_release"
    GENRE_PREFERENCE = "matches_preferred_genres"
    HIGHLY_RATED = "highly_rated_content"
    CONTINUE_WATCHING = "continue_where_left_off"

@dataclass
class RecommendationScore:
    base_score: float  # Core algorithm score (0.0 - 1.0)
    trending_boost: float = 0.0
    genre_match_boost: float = 0.0
    recency_boost: float = 0.0
    popularity_boost: float = 0.0
    diversity_penalty: float = 0.0
    final_score: float = 0.0

    def calculate_final_score(self) -> float:
        self.final_score = min(
            self.base_score + 
            self.trending_boost + 
            self.genre_match_boost + 
            self.recency_boost + 
            self.popularity_boost - 
            self.diversity_penalty,
            1.0
        )
        return self.final_score

@dataclass
class ContentRecommendation:
    content_id: str
    content_title: str
    content_type: str
    score: RecommendationScore
    reason: RecommendationReason
    explanation: str
    metadata: Dict[str, Any]
    rank_position: int
    confidence: float  # How confident the algorithm is (0.0 - 1.0)
    
    def get_user_friendly_reason(self) -> str:
        reason_messages = {
            RecommendationReason.VIEWING_HISTORY: "Based on your viewing history",
            RecommendationReason.SIMILAR_USERS: "People like you also watched",
            RecommendationReason.CONTENT_SIMILARITY: f"Because you watched {self.metadata.get('reference_content', 'similar content')}",
            RecommendationReason.TRENDING: "Trending now",
            RecommendationReason.NEW_RELEASE: "New release",
            RecommendationReason.GENRE_PREFERENCE: f"You like {', '.join(self.metadata.get('genres', []))}",
            RecommendationReason.HIGHLY_RATED: "Highly rated by viewers",
            RecommendationReason.CONTINUE_WATCHING: "Continue watching"
        }
        return reason_messages.get(self.reason, self.explanation)

@dataclass
class RecommendationRequest:
    user_id: str
    profile_id: str
    recommendation_type: RecommendationType
    limit: int = 20
    offset: int = 0
    filters: Dict[str, Any] = None
    context: Dict[str, Any] = None  # Current session context
    exclude_content_ids: List[str] = None

    def __post_init__(self):
        if self.filters is None:
            self.filters = {}
        if self.context is None:
            self.context = {}
        if self.exclude_content_ids is None:
            self.exclude_content_ids = []

@dataclass
class RecommendationResponse:
    user_id: str
    profile_id: str
    recommendations: List[ContentRecommendation]
    recommendation_type: RecommendationType
    total_count: int
    generated_at: datetime
    expires_at: datetime
    algorithm_version: str = "1.0"
    personalization_score: float = 0.0  # How personalized these recommendations are
    cached: bool = False

    def get_top_recommendations(self, n: int) -> List[ContentRecommendation]:
        return sorted(self.recommendations, key=lambda x: x.score.final_score, reverse=True)[:n]

    def filter_by_confidence(self, min_confidence: float) -> List[ContentRecommendation]:
        return [r for r in self.recommendations if r.confidence >= min_confidence]