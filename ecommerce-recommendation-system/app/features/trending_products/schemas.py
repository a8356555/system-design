from pydantic import BaseModel
from typing import List, Optional

class TrendingProduct(BaseModel):
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    trend_score: float
    category: Optional[str] = None
    interaction_count: int
    growth_rate: float  # Percentage growth in interactions

class TrendingProductsResponse(BaseModel):
    recommendations: List[TrendingProduct]
    total_count: int
    time_window: str  # "24h", "7d", "30d"
    cached: bool = False