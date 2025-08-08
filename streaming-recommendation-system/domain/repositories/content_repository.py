from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from ..entities.content import Content, ContentType

class ContentRepositoryInterface(ABC):
    
    @abstractmethod
    async def get_by_id(self, content_id: str) -> Optional[Content]:
        """Get content by ID"""
        pass
    
    @abstractmethod
    async def get_by_ids(self, content_ids: List[str]) -> List[Content]:
        """Get multiple content items by IDs"""
        pass
    
    @abstractmethod
    async def search(
        self, 
        query: str, 
        filters: Dict[str, Any] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Content]:
        """Search content with filters"""
        pass
    
    @abstractmethod
    async def get_by_genre(
        self, 
        genres: List[str], 
        limit: int = 20,
        offset: int = 0
    ) -> List[Content]:
        """Get content by genres"""
        pass
    
    @abstractmethod
    async def get_by_type(
        self, 
        content_type: ContentType,
        limit: int = 20,
        offset: int = 0
    ) -> List[Content]:
        """Get content by type (movie, series, etc.)"""
        pass
    
    @abstractmethod
    async def get_trending(
        self,
        time_window_hours: int = 24,
        limit: int = 20,
        content_type: Optional[ContentType] = None
    ) -> List[Content]:
        """Get trending content"""
        pass
    
    @abstractmethod
    async def get_new_releases(
        self,
        days_back: int = 30,
        limit: int = 20
    ) -> List[Content]:
        """Get recently released content"""
        pass
    
    @abstractmethod
    async def get_highly_rated(
        self,
        min_rating: float = 4.0,
        min_vote_count: int = 100,
        limit: int = 20
    ) -> List[Content]:
        """Get highly rated content"""
        pass
    
    @abstractmethod
    async def get_similar_content(
        self,
        content_id: str,
        similarity_threshold: float = 0.3,
        limit: int = 20
    ) -> List[Content]:
        """Get content similar to given content"""
        pass
    
    @abstractmethod
    async def get_episodes_for_series(
        self,
        series_id: str,
        season_number: Optional[int] = None
    ) -> List[Content]:
        """Get episodes for a series"""
        pass