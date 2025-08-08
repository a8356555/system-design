from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import feature routers
from .features.product_recommendations.router import router as product_router
from .features.user_recommendations.router import router as user_router
from .features.cart_recommendations.router import router as cart_router
from .features.trending_products.router import router as trending_router

# Import shared components
from .shared.database import engine, Base

app = FastAPI(
    title="E-commerce Recommendation System",
    description="High-concurrency recommendation system with vertical slice architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include feature routers
app.include_router(product_router)
app.include_router(user_router)
app.include_router(cart_router)
app.include_router(trending_router)

@app.on_event("startup")
async def startup_event():
    """Initialize database tables and ML models"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Initialize ML models (in production, this would be a separate service)
    print("Starting E-commerce Recommendation System...")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources"""
    await engine.dispose()

@app.get("/")
async def root():
    return {
        "message": "E-commerce Recommendation System API",
        "version": "1.0.0",
        "features": [
            "Product Recommendations",
            "User Recommendations", 
            "Cart Recommendations",
            "Trending Products"
        ]
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers"""
    return {"status": "healthy", "service": "recommendation-system"}

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1  # For development
    )