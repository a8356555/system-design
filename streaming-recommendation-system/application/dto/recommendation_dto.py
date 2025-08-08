from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class RecommendationRequestDTO(BaseModel):
    user_id: str = Field(..., description="User identifier")
    profile_id: str = Field(..., description="Profile identifier")
    recommendation_type: str = Field(..., description="Type of recommendation requested")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of recommendations")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional filters")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Current session context")
    exclude_content_ids: Optional[List[str]] = Field(default_factory=list, description="Content IDs to exclude")

class ContentRecommendationDTO(BaseModel):
    content_id: str
    content_title: str
    content_type: str
    poster_url: Optional[str] = None
    duration_minutes: Optional[int] = None
    release_year: Optional[int] = None
    rating: Optional[str] = None
    genres: Optional[List[str]] = None
    imdb_rating: Optional[float] = None
    description: Optional[str] = None
    
    # Recommendation metadata
    score: float = Field(..., ge=0.0, le=1.0)
    rank_position: int = Field(..., ge=1)
    reason: str
    explanation: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class RecommendationResponseDTO(BaseModel):
    user_id: str
    profile_id: str
    recommendations: List[ContentRecommendationDTO]
    recommendation_type: str
    total_count: int = Field(..., ge=0)
    generated_at: datetime
    expires_at: datetime
    algorithm_version: str = "1.0"
    personalization_score: float = Field(..., ge=0.0, le=1.0)
    cached: bool = False
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class InteractionRequestDTO(BaseModel):
    user_id: str
    profile_id: str
    content_id: str
    interaction_type: str
    session_id: str
    device_type: str
    progress_seconds: Optional[int] = None
    rating: Optional[float] = Field(None, ge=1.0, le=5.0)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ContinueWatchingItemDTO(BaseModel):
    content_id: str
    content_title: str
    content_type: str
    poster_url: Optional[str] = None
    progress_percentage: float = Field(..., ge=0.0, le=100.0)
    progress_seconds: int = Field(..., ge=0)
    total_duration_seconds: int = Field(..., ge=1)
    last_watched: datetime
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    series_title: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class TrendingRequestDTO(BaseModel):
    time_window_hours: int = Field(default=24, ge=1, le=168)  # Max 1 week
    content_type: Optional[str] = None
    genre: Optional[str] = None
    country: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)

class GenreRecommendationRequestDTO(BaseModel):
    user_id: str
    profile_id: str
    genres: Optional[List[str]] = None
    exploration_mode: bool = Field(default=False, description="Recommend unexplored genres")
    mixed_genres: bool = Field(default=False, description="Mix primary with complementary genres")
    limit: int = Field(default=20, ge=1, le=100)

class SimilarContentRequestDTO(BaseModel):
    content_id: str = Field(..., description="Reference content ID")
    user_id: str
    profile_id: str
    similarity_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)

class RealtimeRecommendationRequestDTO(BaseModel):
    user_id: str
    profile_id: str
    session_id: str
    current_content_id: Optional[str] = None
    device_type: str
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)