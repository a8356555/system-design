from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from ...shared.database import Product, UserInteraction, Purchase, User

class UserRecommendationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user(self, user_id: str) -> Optional[User]:
        query = select(User).where(User.id == user_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_interactions(self, user_id: str, limit: int = 100) -> List[Dict]:
        query = (
            select(UserInteraction)
            .where(UserInteraction.user_id == user_id)
            .order_by(desc(UserInteraction.timestamp))
            .limit(limit)
        )
        result = await self.db.execute(query)
        interactions = result.scalars().all()
        
        return [
            {
                'user_id': i.user_id,
                'product_id': i.product_id,
                'interaction_type': i.interaction_type,
                'rating': i.rating,
                'timestamp': i.timestamp
            }
            for i in interactions
        ]

    async def get_popular_products(self, limit: int = 20, days: int = 7) -> List[Dict]:
        """Get popular products based on recent interactions"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = (
            select(
                UserInteraction.product_id,
                func.count().label('interaction_count'),
                func.avg(UserInteraction.rating).label('avg_rating')
            )
            .where(UserInteraction.timestamp >= cutoff_date)
            .group_by(UserInteraction.product_id)
            .order_by(desc('interaction_count'))
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        popular_data = result.all()
        
        # Get product details
        product_ids = [row.product_id for row in popular_data]
        products = await self.get_products_batch(product_ids)
        product_lookup = {p.id: p for p in products}
        
        popular_products = []
        for row in popular_data:
            product = product_lookup.get(row.product_id)
            if product and product.is_available:
                popular_products.append({
                    'product': product,
                    'interaction_count': row.interaction_count,
                    'avg_rating': row.avg_rating or 0
                })
        
        return popular_products

    async def get_products_batch(self, product_ids: List[str]) -> List[Product]:
        query = select(Product).where(Product.id.in_(product_ids), Product.is_available == True)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_similar_users(self, user_id: str, limit: int = 10) -> List[str]:
        """Find users with similar interaction patterns (simplified)"""
        # Get user's interactions
        user_products = (
            select(UserInteraction.product_id)
            .where(UserInteraction.user_id == user_id)
            .distinct()
        )
        
        # Find other users who interacted with similar products
        query = (
            select(
                UserInteraction.user_id,
                func.count().label('common_products')
            )
            .where(
                UserInteraction.product_id.in_(user_products),
                UserInteraction.user_id != user_id
            )
            .group_by(UserInteraction.user_id)
            .order_by(desc('common_products'))
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return [row.user_id for row in result.all()]