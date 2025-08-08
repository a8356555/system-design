from typing import List, Optional
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from ...shared.cache import cache_service
from ...shared.ml_engine import ml_engine
from .repository import ProductRepository
from .schemas import ProductRecommendationResponse, ProductRecommendation

class ProductRecommendationService:
    def __init__(self, db: AsyncSession):
        self.repository = ProductRepository(db)

    async def get_recommendations(
        self, 
        product_id: str, 
        user_id: Optional[str] = None, 
        limit: int = 10
    ) -> ProductRecommendationResponse:
        
        # Try cache first
        cache_key = f"product_rec:{product_id}:{limit}"
        cached = await cache_service.get(cache_key)
        if cached:
            cached['cached'] = True
            return ProductRecommendationResponse(**cached)

        # Get base product and similar products in parallel
        base_product_task = self.repository.get_product(product_id)
        similar_products_task = ml_engine.get_similar_products(product_id, limit * 2)
        
        base_product, similar_product_scores = await asyncio.gather(
            base_product_task, 
            similar_products_task
        )

        if not base_product:
            raise ValueError(f"Product {product_id} not found")

        # Get similar product details
        similar_ids = [pid for pid, _ in similar_product_scores]
        products = await self.repository.get_products_batch(similar_ids)
        
        # Create product lookup
        product_lookup = {p.id: p for p in products}
        
        # Build recommendations
        recommendations = []
        for product_id_sim, score in similar_product_scores:
            product = product_lookup.get(product_id_sim)
            if not product or product.stock < 1:
                continue
                
            recommendations.append(ProductRecommendation(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                similarity_score=round(score, 3),
                reason=self._get_recommendation_reason(score)
            ))
            
            if len(recommendations) >= limit:
                break

        response = ProductRecommendationResponse(
            product_id=product_id,
            recommendations=recommendations,
            total_count=len(recommendations),
            cached=False
        )

        # Cache for 1 hour
        await cache_service.set(cache_key, response.dict(exclude={'cached'}), ttl=3600)
        return response

    def _get_recommendation_reason(self, score: float) -> str:
        if score > 0.8:
            return "Highly similar to this item"
        elif score > 0.6:
            return "Customers who viewed this also viewed"
        elif score > 0.4:
            return "Similar products you might like"
        else:
            return "Related items"

    async def track_interaction(self, user_id: str, interaction_type: str, product_id: str):
        """Track user interaction for future recommendations"""
        # This would typically go to a message queue for async processing
        # For now, we'll just invalidate relevant caches
        await cache_service.delete(f"user_rec:{user_id}")
        await cache_service.delete(f"trending_products")