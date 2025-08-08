from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..entities.interaction import UserInteraction, ViewingProgress, ContentRating, InteractionType

class InteractionRepositoryInterface(ABC):
    
    @abstractmethod
    async def save_interaction(self, interaction: UserInteraction) -> UserInteraction:
        """Save user interaction"""
        pass
    
    @abstractmethod
    async def get_user_interactions(
        self,
        user_id: str,
        profile_id: Optional[str] = None,
        interaction_types: Optional[List[InteractionType]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[UserInteraction]:
        """Get user interactions with optional filters"""
        pass
    
    @abstractmethod
    async def get_content_interactions(
        self,
        content_id: str,
        interaction_types: Optional[List[InteractionType]] = None,
        limit: int = 100
    ) -> List[UserInteraction]:
        """Get interactions for specific content"""
        pass
    
    @abstractmethod
    async def get_viewing_progress(
        self,
        user_id: str,
        profile_id: str,
        content_id: str
    ) -> Optional[ViewingProgress]:
        """Get viewing progress for specific content"""
        pass
    
    @abstractmethod
    async def save_viewing_progress(self, progress: ViewingProgress) -> ViewingProgress:
        """Save or update viewing progress"""
        pass
    
    @abstractmethod
    async def get_continue_watching(
        self,
        user_id: str,
        profile_id: str,
        limit: int = 20
    ) -> List[ViewingProgress]:
        """Get content that can be continued watching"""
        pass
    
    @abstractmethod
    async def get_completed_content(
        self,
        user_id: str,
        profile_id: str,
        limit: int = 100
    ) -> List[str]:
        """Get IDs of completed content"""
        pass
    
    @abstractmethod
    async def save_rating(self, rating: ContentRating) -> ContentRating:
        """Save content rating"""
        pass
    
    @abstractmethod
    async def get_user_ratings(
        self,
        user_id: str,
        profile_id: str,
        limit: int = 100
    ) -> List[ContentRating]:
        """Get user's content ratings"""
        pass
    
    @abstractmethod
    async def get_content_ratings(
        self,
        content_id: str,
        limit: int = 100
    ) -> List[ContentRating]:
        """Get ratings for specific content"""
        pass
    
    @abstractmethod
    async def get_user_genre_preferences(
        self,
        user_id: str,
        profile_id: str
    ) -> Dict[str, float]:
        """Get user's genre preferences based on interactions"""
        pass
    
    @abstractmethod
    async def get_trending_interactions(
        self,
        hours_back: int = 24,
        interaction_types: Optional[List[InteractionType]] = None
    ) -> List[Dict[str, Any]]:
        """Get trending content based on recent interactions"""
        pass