from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta
from enum import Enum

class ContentType(Enum):
    MOVIE = "movie"
    SERIES = "series" 
    EPISODE = "episode"
    DOCUMENTARY = "documentary"
    SHORT = "short"

class ContentRating(Enum):
    G = "G"
    PG = "PG" 
    PG_13 = "PG-13"
    R = "R"
    NC_17 = "NC-17"
    TV_Y = "TV-Y"
    TV_PG = "TV-PG"
    TV_14 = "TV-14"
    TV_MA = "TV-MA"

@dataclass
class Content:
    id: str
    title: str
    content_type: ContentType
    duration_minutes: int
    release_date: datetime
    genres: List[str]
    rating: ContentRating
    description: str
    cast: List[str]
    directors: List[str]
    language: str
    country: str
    imdb_rating: Optional[float] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None
    series_id: Optional[str] = None  # For episodes
    season_number: Optional[int] = None  # For episodes
    episode_number: Optional[int] = None  # For episodes
    is_premium: bool = False
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()

    def is_movie(self) -> bool:
        return self.content_type == ContentType.MOVIE

    def is_series(self) -> bool:
        return self.content_type == ContentType.SERIES

    def is_episode(self) -> bool:
        return self.content_type == ContentType.EPISODE

    def get_watch_duration(self) -> timedelta:
        return timedelta(minutes=self.duration_minutes)

    def is_suitable_for_age(self, age: int) -> bool:
        age_restrictions = {
            ContentRating.G: 0,
            ContentRating.PG: 0,
            ContentRating.PG_13: 13,
            ContentRating.R: 17,
            ContentRating.NC_17: 18,
            ContentRating.TV_Y: 0,
            ContentRating.TV_PG: 0,
            ContentRating.TV_14: 14,
            ContentRating.TV_MA: 18
        }
        return age >= age_restrictions.get(self.rating, 18)

@dataclass 
class Series(Content):
    total_seasons: int
    total_episodes: int
    status: str  # "ongoing", "completed", "cancelled"
    
    def __post_init__(self):
        self.content_type = ContentType.SERIES