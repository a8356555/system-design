from typing import List, Dict, Set
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from ...shared.cache import cache_service
from ...shared.ml_engine import ml_engine
from .repository import UserRecommendationRepository
from .schemas import UserRecommendationResponse, UserRecommendation

class UserRecommendationService:
    def __init__(self, db: AsyncSession):
        self.repository = UserRecommendationRepository(db)

    async def get_recommendations(
        self, 
        user_id: str, 
        limit: int = 20
    ) -> UserRecommendationResponse:
        
        # Try cache first
        cache_key = f"user_rec:{user_id}:{limit}"
        cached = await cache_service.get(cache_key)
        if cached:
            cached['cached'] = True
            return UserRecommendationResponse(**cached)

        # Get user and their interactions
        user, user_interactions = await asyncio.gather(
            self.repository.get_user(user_id),
            self.repository.get_user_interactions(user_id)
        )

        # Determine recommendation strategy
        if not user or len(user_interactions) < 5:
            # Cold start - show popular products
            response = await self._get_popular_recommendations(user_id, limit)
        else:
            # Personalized recommendations
            response = await self._get_personalized_recommendations(user_id, user_interactions, limit)

        # Cache for 30 minutes
        await cache_service.set(cache_key, response.dict(exclude={'cached'}), ttl=1800)
        return response

    async def _get_popular_recommendations(self, user_id: str, limit: int) -> UserRecommendationResponse:
        """Cold start recommendations using popular products"""
        popular_products = await self.repository.get_popular_products(limit)
        
        recommendations = []
        for item in popular_products:
            product = item['product']
            score = min(item['interaction_count'] / 100, 1.0)  # Normalize score
            
            recommendations.append(UserRecommendation(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                score=round(score, 3),
                reason="Popular among customers"
            ))

        return UserRecommendationResponse(
            user_id=user_id,
            recommendations=recommendations,
            total_count=len(recommendations),
            cached=False,
            recommendation_type="popular"
        )

    async def _get_personalized_recommendations(
        self, 
        user_id: str, 
        user_interactions: List[Dict], 
        limit: int
    ) -> UserRecommendationResponse:
        """Personalized recommendations using collaborative filtering"""
        
        # Get user's interacted products
        user_products = set(i['product_id'] for i in user_interactions)
        
        # Get similar users and popular products in parallel
        similar_users_task = self.repository.get_similar_users(user_id)
        popular_products_task = self.repository.get_popular_products(limit * 2)
        
        similar_users, popular_products = await asyncio.gather(
            similar_users_task, 
            popular_products_task
        )

        # Get recommendations from similar users
        collaborative_recs = await self._get_collaborative_recommendations(
            similar_users, user_products, limit
        )
        
        # Get content-based recommendations
        content_recs = await self._get_content_based_recommendations(
            user_interactions, user_products, limit
        )
        
        # Combine and rank recommendations
        combined_recs = self._combine_recommendations(
            collaborative_recs, content_recs, popular_products, user_products, limit
        )

        return UserRecommendationResponse(
            user_id=user_id,
            recommendations=combined_recs,
            total_count=len(combined_recs),
            cached=False,
            recommendation_type="personalized"
        )

    async def _get_collaborative_recommendations(
        self, 
        similar_users: List[str], 
        user_products: Set[str], 
        limit: int
    ) -> Dict[str, float]:
        """Get recommendations from similar users"""
        product_scores = {}
        
        for similar_user in similar_users:
            user_interactions = await self.repository.get_user_interactions(similar_user, 50)
            
            for interaction in user_interactions:
                product_id = interaction['product_id']
                if product_id not in user_products:  # Don't recommend already interacted products
                    weight = {
                        'view': 1.0,
                        'cart_add': 2.0,
                        'purchase': 5.0
                    }.get(interaction['interaction_type'], 1.0)
                    
                    product_scores[product_id] = product_scores.get(product_id, 0) + weight
        
        return product_scores

    async def _get_content_based_recommendations(
        self, 
        user_interactions: List[Dict], 
        user_products: Set[str], 
        limit: int
    ) -> Dict[str, float]:
        """Get content-based recommendations using item similarities"""
        product_scores = {}
        
        # Get user's most interacted products
        user_product_weights = {}
        for interaction in user_interactions:
            product_id = interaction['product_id']
            weight = {
                'view': 1.0,
                'cart_add': 2.0,
                'purchase': 5.0
            }.get(interaction['interaction_type'], 1.0)
            user_product_weights[product_id] = user_product_weights.get(product_id, 0) + weight
        
        # Get similar products for user's top products
        top_products = sorted(user_product_weights.items(), key=lambda x: x[1], reverse=True)[:5]
        
        for product_id, user_weight in top_products:
            similar_products = await ml_engine.get_similar_products(product_id, 10)
            
            for similar_id, similarity_score in similar_products:
                if similar_id not in user_products:
                    score = similarity_score * (user_weight / 10)  # Scale by user interest
                    product_scores[similar_id] = product_scores.get(similar_id, 0) + score
        
        return product_scores

    def _combine_recommendations(
        self, 
        collaborative_recs: Dict[str, float],
        content_recs: Dict[str, float],
        popular_products: List[Dict],
        user_products: Set[str],
        limit: int
    ) -> List[UserRecommendation]:
        """Combine different recommendation sources"""
        
        # Combine scores with weights
        combined_scores = {}
        
        # Collaborative filtering (40% weight)
        for product_id, score in collaborative_recs.items():
            combined_scores[product_id] = combined_scores.get(product_id, 0) + score * 0.4
        
        # Content-based (40% weight)
        for product_id, score in content_recs.items():
            combined_scores[product_id] = combined_scores.get(product_id, 0) + score * 0.4
        
        # Popular products (20% weight) - for diversity
        for item in popular_products[:limit]:
            product_id = item['product'].id
            if product_id not in user_products:
                popularity_score = item['interaction_count'] / 100
                combined_scores[product_id] = combined_scores.get(product_id, 0) + popularity_score * 0.2
        
        # Sort by combined score
        sorted_recs = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        # Convert to recommendation objects (simplified - would need product details)
        recommendations = []
        for product_id, score in sorted_recs:
            recommendations.append(UserRecommendation(
                product_id=product_id,
                name=f"Product {product_id}",  # Would fetch from database
                price=0.0,  # Would fetch from database
                image_url=None,
                score=round(score, 3),
                reason=self._get_recommendation_reason(collaborative_recs.get(product_id, 0), 
                                                    content_recs.get(product_id, 0))
            ))
        
        return recommendations

    def _get_recommendation_reason(self, collab_score: float, content_score: float) -> str:
        if collab_score > content_score:
            return "People like you also bought this"
        elif content_score > 0:
            return "Based on your interests"
        else:
            return "Popular among customers"