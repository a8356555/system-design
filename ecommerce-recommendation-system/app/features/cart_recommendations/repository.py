from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Dict
from ...shared.database import Product, Purchase, UserInteraction

class CartRecommendationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_products_batch(self, product_ids: List[str]) -> List[Product]:
        query = select(Product).where(Product.id.in_(product_ids), Product.is_available == True)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_frequently_bought_together(self, cart_product_ids: List[str], limit: int = 10) -> List[Dict]:
        """Find products frequently bought together with cart items"""
        
        # Get purchases that include any cart items
        purchase_sessions = (
            select(Purchase.user_id, func.date(Purchase.timestamp).label('purchase_date'))
            .where(Purchase.product_id.in_(cart_product_ids))
            .distinct()
        )
        
        # Find other products bought in those same sessions
        query = (
            select(
                Purchase.product_id,
                func.count().label('frequency')
            )
            .where(
                and_(
                    Purchase.user_id.in_(select(purchase_sessions.c.user_id)),
                    func.date(Purchase.timestamp).in_(select(purchase_sessions.c.purchase_date)),
                    ~Purchase.product_id.in_(cart_product_ids)  # Exclude cart items
                )
            )
            .group_by(Purchase.product_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return [{'product_id': row.product_id, 'frequency': row.frequency} for row in result.all()]

    async def get_category_complements(self, cart_product_ids: List[str]) -> List[str]:
        """Get products from complementary categories"""
        
        # Get categories of cart items
        cart_categories = (
            select(Product.category_id)
            .where(Product.id.in_(cart_product_ids))
            .distinct()
        )
        
        # Define complementary category mappings (simplified)
        complement_categories = {
            'electronics': ['accessories', 'cases'],
            'clothing': ['shoes', 'accessories'],
            'books': ['bookmarks', 'reading_lights'],
            'sports': ['sports_accessories', 'fitness']
        }
        
        # This is a simplified version - in practice, you'd have a more sophisticated mapping
        return []

    async def get_upsell_products(self, cart_product_ids: List[str], price_multiplier: float = 1.5) -> List[Dict]:
        """Get higher-priced alternatives to cart items"""
        
        # Get cart products info
        cart_products = await self.get_products_batch(cart_product_ids)
        cart_categories = {p.category_id for p in cart_products}
        max_cart_price = max(p.price for p in cart_products) if cart_products else 0
        
        # Find products in same categories with higher prices
        query = (
            select(Product)
            .where(
                and_(
                    Product.category_id.in_(cart_categories),
                    Product.price > max_cart_price,
                    Product.price <= max_cart_price * price_multiplier,
                    Product.is_available == True,
                    ~Product.id.in_(cart_product_ids)
                )
            )
            .order_by(Product.price.desc())
            .limit(10)
        )
        
        result = await self.db.execute(query)
        products = result.scalars().all()
        
        return [
            {
                'product': product,
                'price_difference': product.price - max_cart_price,
                'upgrade_percentage': ((product.price - max_cart_price) / max_cart_price) * 100
            }
            for product in products
        ]

    async def get_bundle_discounts(self, product_ids: List[str]) -> Dict[str, float]:
        """Get potential bundle discounts for products"""
        # Simplified - in practice, you'd have a bundles table
        bundle_discounts = {}
        
        if len(product_ids) >= 2:
            bundle_discounts['multi_item'] = 10.0  # 10% discount for 2+ items
        if len(product_ids) >= 3:
            bundle_discounts['bulk'] = 15.0  # 15% discount for 3+ items
            
        return bundle_discounts