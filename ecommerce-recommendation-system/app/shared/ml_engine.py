import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from typing import List, Tuple, Dict
import asyncio
from .cache import cache_service

class SimilarityEngine:
    def __init__(self):
        self.product_similarities = {}
        self.user_item_matrix = None
        self.tfidf_vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        
    async def compute_product_similarities(self, products: List[Dict]) -> Dict[str, List[Tuple[str, float]]]:
        """Compute item-based collaborative filtering similarities"""
        
        # Create product features matrix
        descriptions = [p.get('description', '') + ' ' + p.get('category', '') for p in products]
        product_ids = [p['id'] for p in products]
        
        # TF-IDF for content-based similarity
        tfidf_matrix = self.tfidf_vectorizer.fit_transform(descriptions)
        content_similarities = cosine_similarity(tfidf_matrix)
        
        # Store similarities for each product
        similarities = {}
        for i, product_id in enumerate(product_ids):
            similar_products = []
            for j, other_id in enumerate(product_ids):
                if i != j and content_similarities[i][j] > 0.1:
                    similar_products.append((other_id, float(content_similarities[i][j])))
            
            # Sort by similarity score
            similar_products.sort(key=lambda x: x[1], reverse=True)
            similarities[product_id] = similar_products[:20]  # Top 20 similar products
        
        # Cache the similarities
        await cache_service.set("product_similarities", similarities, ttl=86400)  # 24 hours
        return similarities
    
    async def get_similar_products(self, product_id: str, limit: int = 10) -> List[Tuple[str, float]]:
        """Get similar products for a given product"""
        
        # Try to get from cache first
        similarities = await cache_service.get("product_similarities")
        if not similarities:
            return []
        
        return similarities.get(product_id, [])[:limit]
    
    async def compute_user_recommendations(self, user_interactions: List[Dict], all_products: List[str]) -> Dict[str, float]:
        """Compute user-based collaborative filtering recommendations"""
        
        # Create user-item interaction matrix
        user_items = {}
        for interaction in user_interactions:
            user_id = interaction['user_id']
            product_id = interaction['product_id']
            
            # Weight different interaction types
            weight = {
                'view': 1.0,
                'cart_add': 2.0,
                'purchase': 5.0,
                'rating': interaction.get('rating', 3.0)
            }.get(interaction['interaction_type'], 1.0)
            
            if user_id not in user_items:
                user_items[user_id] = {}
            user_items[user_id][product_id] = user_items[user_id].get(product_id, 0) + weight
        
        return user_items
    
    async def get_trending_products(self, recent_interactions: List[Dict], time_window_hours: int = 24) -> List[Tuple[str, float]]:
        """Calculate trending products based on recent interactions"""
        
        product_scores = {}
        
        for interaction in recent_interactions:
            product_id = interaction['product_id']
            
            # Weight by interaction type and recency
            weight = {
                'view': 1.0,
                'cart_add': 3.0,
                'purchase': 10.0
            }.get(interaction['interaction_type'], 1.0)
            
            product_scores[product_id] = product_scores.get(product_id, 0) + weight
        
        # Sort by score
        trending = [(pid, score) for pid, score in product_scores.items()]
        trending.sort(key=lambda x: x[1], reverse=True)
        
        return trending

ml_engine = SimilarityEngine()