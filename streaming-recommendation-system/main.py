from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

# Import routers
from presentation.api.recommendations import router as recommendations_router

# Import infrastructure
from infrastructure.database.models import engine, Base
from infrastructure.dependencies import container

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await startup_event()
    yield
    # Shutdown
    await shutdown_event()

app = FastAPI(
    title="Streaming Recommendation System",
    description="High-performance streaming recommendation system built with Clean Architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(recommendations_router)

async def startup_event():
    """Initialize application on startup"""
    # Initialize database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Initialize dependency container
    container.wire(modules=["presentation.api.recommendations"])
    
    print("🎬 Streaming Recommendation System started successfully!")
    print("📚 API Documentation: http://localhost:8000/docs")

async def shutdown_event():
    """Cleanup on shutdown"""
    await engine.dispose()
    print("👋 Streaming Recommendation System shut down gracefully")

@app.get("/")
async def root():
    """Root endpoint with system information"""
    return {
        "service": "Streaming Recommendation System",
        "version": "1.0.0",
        "architecture": "Clean Architecture",
        "core_features": [
            "Content Discovery",
            "Continue Watching",
            "Similar Content",
            "Trending Content",
            "Genre-based Recommendations",
            "Real-time Recommendations"
        ],
        "api_docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "streaming-recommendation-system",
        "architecture": "clean-architecture"
    }

@app.get("/features")
async def get_features():
    """List all available recommendation features"""
    return {
        "content_discovery": {
            "endpoint": "/recommendations/personalized/{user_id}/{profile_id}",
            "description": "Personalized content recommendations using collaborative and content-based filtering"
        },
        "continue_watching": {
            "endpoint": "/recommendations/continue-watching/{user_id}/{profile_id}",
            "description": "Resume watching content with progress tracking"
        },
        "similar_content": {
            "endpoint": "/recommendations/similar/{content_id}",
            "description": "Find content similar to what user is currently watching"
        },
        "trending": {
            "endpoint": "/recommendations/trending",
            "description": "Popular content based on recent user interactions"
        },
        "genre_based": {
            "endpoint": "/recommendations/genre/{user_id}/{profile_id}",
            "description": "Recommendations based on preferred genres"
        },
        "realtime": {
            "endpoint": "/recommendations/realtime/{user_id}/{profile_id}",
            "description": "Context-aware recommendations based on current session"
        },
        "device_optimized": {
            "endpoint": "/recommendations/device-optimized/{user_id}/{profile_id}",
            "description": "Recommendations optimized for specific device types"
        },
        "homepage_feed": {
            "endpoint": "/recommendations/homepage/{user_id}/{profile_id}",
            "description": "Comprehensive homepage feed with mixed content types"
        },
        "interaction_tracking": {
            "endpoint": "/recommendations/interaction",
            "description": "Track user interactions to improve recommendations"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1  # Use 1 worker for development
    )