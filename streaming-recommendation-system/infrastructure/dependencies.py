from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from .database.models import AsyncSessionLocal
from .cache.redis_cache import cache_service
from ..domain.services.content_discovery_service import ContentDiscoveryService
from ..domain.services.continue_watching_service import ContinueWatchingService
from ..domain.services.similar_content_service import SimilarContentService
from ..domain.services.trending_service import TrendingService
from ..domain.services.genre_based_service import GenreBasedService
from ..domain.services.realtime_service import RealtimeRecommendationService
from ..application.handlers.recommendation_handler import RecommendationHandler

class Container(containers.DeclarativeContainer):
    """Dependency injection container"""
    
    # Database
    db_session = providers.Resource(
        AsyncSessionLocal
    )
    
    # Cache
    cache = providers.Singleton(lambda: cache_service)
    
    # Repositories would be injected here
    # For this implementation, we'll create mock repositories
    
    # Services
    content_discovery_service = providers.Factory(
        ContentDiscoveryService,
        # content_repository=content_repository,
        # user_repository=user_repository,
        # interaction_repository=interaction_repository,
    )
    
    continue_watching_service = providers.Factory(
        ContinueWatchingService,
        # content_repository=content_repository,
        # interaction_repository=interaction_repository,
    )
    
    similar_content_service = providers.Factory(
        SimilarContentService,
        # content_repository=content_repository,
        # interaction_repository=interaction_repository,
    )
    
    trending_service = providers.Factory(
        TrendingService,
        # content_repository=content_repository,
        # interaction_repository=interaction_repository,
    )
    
    genre_based_service = providers.Factory(
        GenreBasedService,
        # content_repository=content_repository,
        # interaction_repository=interaction_repository,
    )
    
    realtime_service = providers.Factory(
        RealtimeRecommendationService,
        # content_repository=content_repository,
        # interaction_repository=interaction_repository,
    )
    
    # Application layer
    recommendation_handler = providers.Factory(
        RecommendationHandler,
        content_discovery_service=content_discovery_service,
        continue_watching_service=continue_watching_service,
        similar_content_service=similar_content_service,
        trending_service=trending_service,
        genre_based_service=genre_based_service,
        realtime_service=realtime_service,
    )

# Global container instance
container = Container()

async def get_recommendation_handler() -> RecommendationHandler:
    """Dependency injection for recommendation handler"""
    return container.recommendation_handler()

async def get_db() -> AsyncSession:
    """Get database session"""
    async with AsyncSessionLocal() as session:
        yield session