from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum

class InteractionType(Enum):
    PLAY = "play"
    PAUSE = "pause"  
    STOP = "stop"
    SEEK = "seek"
    COMPLETE = "complete"
    RATE = "rate"
    LIKE = "like"
    DISLIKE = "dislike"
    ADD_TO_WATCHLIST = "add_to_watchlist"
    REMOVE_FROM_WATCHLIST = "remove_from_watchlist"
    SHARE = "share"

@dataclass
class UserInteraction:
    id: str
    user_id: str
    profile_id: str
    content_id: str
    interaction_type: InteractionType
    timestamp: datetime
    session_id: str
    device_type: str
    progress_seconds: Optional[int] = None  # Current playback position
    rating: Optional[float] = None  # 1-5 stars
    duration_watched_seconds: Optional[int] = None
    metadata: Optional[dict] = None  # Additional context

    def get_completion_percentage(self, content_duration_seconds: int) -> float:
        if not self.progress_seconds or content_duration_seconds <= 0:
            return 0.0
        return min((self.progress_seconds / content_duration_seconds) * 100, 100.0)

    def is_significant_watch(self, content_duration_seconds: int) -> bool:
        """Determine if this represents a meaningful viewing interaction"""
        completion_pct = self.get_completion_percentage(content_duration_seconds)
        
        # Consider it significant if watched more than 10% or at least 2 minutes
        min_watch_seconds = max(120, content_duration_seconds * 0.1)
        return (self.duration_watched_seconds or 0) >= min_watch_seconds

    def is_completed(self, content_duration_seconds: int) -> bool:
        """Check if content was substantially completed (80%+ watched)"""
        return self.get_completion_percentage(content_duration_seconds) >= 80.0

@dataclass
class ViewingProgress:
    user_id: str
    profile_id: str
    content_id: str
    progress_seconds: int
    total_duration_seconds: int
    last_watched: datetime
    is_completed: bool = False
    watch_count: int = 1

    def get_progress_percentage(self) -> float:
        if self.total_duration_seconds <= 0:
            return 0.0
        return min((self.progress_seconds / self.total_duration_seconds) * 100, 100.0)

    def update_progress(self, new_progress_seconds: int) -> None:
        self.progress_seconds = new_progress_seconds
        self.last_watched = datetime.utcnow()
        
        # Mark as completed if watched 90% or more
        if self.get_progress_percentage() >= 90.0:
            self.is_completed = True

    def increment_watch_count(self) -> None:
        self.watch_count += 1

@dataclass
class ContentRating:
    user_id: str
    profile_id: str
    content_id: str
    rating: float  # 1.0 to 5.0
    timestamp: datetime
    review_text: Optional[str] = None

    def is_positive(self) -> bool:
        return self.rating >= 3.5

    def is_negative(self) -> bool:
        return self.rating < 2.5