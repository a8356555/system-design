from pydantic import BaseModel
from typing import List, Optional

class ProductRecommendation(BaseModel):
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    similarity_score: float
    reason: str = "Customers who viewed this item also viewed"

class ProductRecommendationResponse(BaseModel):
    product_id: str
    recommendations: List[ProductRecommendation]
    total_count: int
    cached: bool = False