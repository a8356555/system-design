from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict
from ...shared.database import Product, UserInteraction

class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_product(self, product_id: str) -> Optional[Product]:
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_products_batch(self, product_ids: List[str]) -> List[Product]:
        query = select(Product).where(Product.id.in_(product_ids), Product.is_available == True)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_all_products(self) -> List[Dict]:
        query = select(Product).where(Product.is_available == True)
        result = await self.db.execute(query)
        products = result.scalars().all()
        
        return [
            {
                'id': p.id,
                'name': p.name,
                'description': p.description or '',
                'category': p.category_id or '',
                'price': p.price,
                'image_url': p.image_url
            }
            for p in products
        ]

    async def get_product_interactions(self, product_id: str) -> List[Dict]:
        query = select(UserInteraction).where(UserInteraction.product_id == product_id)
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