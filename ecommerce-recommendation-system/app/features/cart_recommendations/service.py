from typing import List, Dict
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from ...shared.cache import cache_service
from ...shared.ml_engine import ml_engine
from .repository import CartRecommendationRepository
from .schemas import CartRecommendationResponse, CartRecommendation

class CartRecommendationService:
    def __init__(self, db: AsyncSession):
        self.repository = CartRecommendationRepository(db)

    async def get_recommendations(
        self, 
        user_id: str, 
        cart_product_ids: List[str],
        limit: int = 10
    ) -> CartRecommendationResponse:
        
        if not cart_product_ids:
            return CartRecommendationResponse(
                user_id=user_id,
                cart_items=[],
                recommendations=[],
                total_count=0,
                recommendation_type="empty_cart"
            )
        
        # Try cache first
        cache_key = f"cart_rec:{user_id}:{':'.join(sorted(cart_product_ids))}:{limit}"
        cached = await cache_service.get(cache_key)
        if cached:
            cached['cached'] = True
            return CartRecommendationResponse(**cached)

        # Get different types of recommendations in parallel
        complement_task = self._get_complement_recommendations(cart_product_ids, limit)
        upsell_task = self._get_upsell_recommendations(cart_product_ids, limit // 2)
        bundle_task = self._get_bundle_recommendations(cart_product_ids, limit // 3)
        
        complement_recs, upsell_recs, bundle_recs = await asyncio.gather(
            complement_task, upsell_task, bundle_task
        )

        # Combine and rank recommendations
        all_recommendations = complement_recs + upsell_recs + bundle_recs
        
        # Remove duplicates and sort by score
        seen_products = set()
        unique_recs = []
        for rec in sorted(all_recommendations, key=lambda x: x.score, reverse=True):
            if rec.product_id not in seen_products and rec.product_id not in cart_product_ids:
                seen_products.add(rec.product_id)
                unique_recs.append(rec)
                if len(unique_recs) >= limit:
                    break

        response = CartRecommendationResponse(
            user_id=user_id,
            cart_items=cart_product_ids,
            recommendations=unique_recs,
            total_count=len(unique_recs),
            cached=False,
            recommendation_type="mixed"
        )

        # Cache for 10 minutes (shorter because cart changes frequently)
        await cache_service.set(cache_key, response.dict(exclude={'cached'}), ttl=600)
        return response

    async def _get_complement_recommendations(self, cart_product_ids: List[str], limit: int) -> List[CartRecommendation]:
        """Get complementary products frequently bought together"""
        
        # Get frequently bought together items
        frequently_bought = await self.repository.get_frequently_bought_together(cart_product_ids, limit * 2)
        
        if not frequently_bought:
            return []

        # Get product details
        product_ids = [item['product_id'] for item in frequently_bought]
        products = await self.repository.get_products_batch(product_ids)
        product_lookup = {p.id: p for p in products}

        recommendations = []
        for item in frequently_bought:
            product = product_lookup.get(item['product_id'])
            if not product:
                continue

            # Calculate score based on frequency
            max_frequency = max(i['frequency'] for i in frequently_bought)
            score = item['frequency'] / max_frequency

            recommendations.append(CartRecommendation(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                score=round(score, 3),
                reason=f"Frequently bought with items in your cart"
            ))

        return recommendations[:limit]

    async def _get_upsell_recommendations(self, cart_product_ids: List[str], limit: int) -> List[CartRecommendation]:
        """Get higher-value alternatives"""
        
        upsell_products = await self.repository.get_upsell_products(cart_product_ids)
        
        recommendations = []
        for item in upsell_products[:limit]:
            product = item['product']
            upgrade_pct = item['upgrade_percentage']
            
            # Score based on reasonable upgrade price
            if upgrade_pct <= 50:  # Up to 50% more expensive
                score = 1.0 - (upgrade_pct / 100)  # Higher score for smaller price increases
            else:
                score = 0.3  # Lower score for expensive upgrades
            
            recommendations.append(CartRecommendation(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                score=round(score, 3),
                reason=f"Premium alternative (+{upgrade_pct:.0f}%)"
            ))

        return recommendations

    async def _get_bundle_recommendations(self, cart_product_ids: List[str], limit: int) -> List[CartRecommendation]:
        """Get bundle deals and accessories"""
        
        # Get similar products to cart items
        all_similar = []
        for product_id in cart_product_ids[:3]:  # Limit to avoid too many API calls
            similar = await ml_engine.get_similar_products(product_id, limit)
            all_similar.extend(similar)

        # Get unique similar products
        similar_products = {}
        for product_id, score in all_similar:
            if product_id not in similar_products:
                similar_products[product_id] = score
            else:
                similar_products[product_id] = max(similar_products[product_id], score)

        # Filter and get product details
        filtered_ids = [pid for pid, score in similar_products.items() 
                       if score > 0.3 and pid not in cart_product_ids]
        
        if not filtered_ids:
            return []

        products = await self.repository.get_products_batch(filtered_ids[:limit])
        
        # Check for bundle discounts
        bundle_discounts = await self.repository.get_bundle_discounts(cart_product_ids + filtered_ids[:3])
        
        recommendations = []
        for product in products:
            similarity_score = similar_products.get(product.id, 0)
            
            # Add bundle discount if available
            discount = bundle_discounts.get('multi_item', 0)
            
            recommendations.append(CartRecommendation(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                score=round(similarity_score, 3),
                reason="Complete your purchase" + (f" (Save {discount}%)" if discount else ""),
                discount_percentage=discount if discount else None
            ))

        return recommendations[:limit]