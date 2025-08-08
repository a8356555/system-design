from pydantic import BaseModel
from typing import List, Optional

class CartRecommendation(BaseModel):
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    score: float
    reason: str
    discount_percentage: Optional[float] = None

class CartRecommendationResponse(BaseModel):
    user_id: str
    cart_items: List[str]  # Product IDs in cart
    recommendations: List[CartRecommendation]
    total_count: int
    cached: bool = False
    recommendation_type: str  # "complement", "upsell", "bundle"