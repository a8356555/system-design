from pydantic import BaseModel
from typing import List, Optional

class UserRecommendation(BaseModel):
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    score: float
    reason: str

class UserRecommendationResponse(BaseModel):
    user_id: str
    recommendations: List[UserRecommendation]
    total_count: int
    cached: bool = False
    recommendation_type: str  # "personalized", "popular", "cold_start"