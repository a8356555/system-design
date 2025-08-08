# E-commerce Recommendation System

A high-concurrency recommendation system built with Python FastAPI using Vertical Slice Architecture.

## Features (High Priority - Implemented)

- **Product Recommendations** - Item-based collaborative filtering ("Customers who viewed this also viewed")
- **User Recommendations** - Personalized homepage recommendations using collaborative filtering
- **Cart Recommendations** - Smart cart suggestions including frequently bought together, upsells, and bundles
- **Trending Products** - Popular products based on recent user interactions

## Architecture

### Vertical Slice Architecture
```
app/
├── features/                    # Feature-based organization
│   ├── product_recommendations/ # Complete feature slice
│   ├── user_recommendations/   
│   ├── cart_recommendations/   
│   └── trending_products/      
├── shared/                     # Shared infrastructure
│   ├── database.py            # Database models & connection
│   ├── cache.py               # Redis caching service  
│   └── ml_engine.py           # ML algorithms
└── main.py                    # FastAPI application
```

### Tech Stack
- **FastAPI** - Async Python web framework
- **PostgreSQL** - Primary database for transactional data
- **Redis** - Caching layer for recommendations
- **SQLAlchemy** - Async ORM
- **scikit-learn** - Machine learning algorithms
- **Docker** - Containerization

## API Endpoints

### Product Recommendations
- `GET /recommendations/product/{product_id}` - Get similar products
- `POST /recommendations/interaction` - Track user interactions

### User Recommendations  
- `GET /recommendations/user/{user_id}` - Get personalized recommendations
- `GET /recommendations/homepage/{user_id}` - Get homepage recommendations

### Cart Recommendations
- `POST /recommendations/cart/{user_id}` - Get cart-based suggestions
- `GET /recommendations/cart/{user_id}` - GET version with comma-separated cart items

### Trending Products
- `GET /recommendations/trending` - Get trending products

## Quick Start

### Development Setup
```bash
# Clone and navigate
cd ecommerce-recommendation-system

# Start services
docker-compose up -d

# API will be available at http://localhost:8000
# Documentation at http://localhost:8000/docs
```

### Manual Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://user:password@localhost/ecommerce"
export REDIS_URL="redis://localhost:6379"

# Run the application
uvicorn app.main:app --reload
```

## Performance Targets

- **API Response Time**: <100ms (cached), <500ms (computed)
- **Concurrent Users**: 10,000+ simultaneous requests
- **Cache Strategy**: Redis with TTL-based invalidation
- **Database**: Async PostgreSQL with connection pooling

## Future Features

See [TODO.md](TODO.md) for detailed roadmap including:
- Recently viewed products
- Search-based recommendations  
- Advanced ML models (deep learning)
- A/B testing framework
- Real-time model updates

## Monitoring

- Health check: `GET /health`
- Redis Commander: http://localhost:8081 (if enabled)
- Database metrics via PostgreSQL logs

## Testing

```bash
# Example API calls
curl "http://localhost:8000/recommendations/product/prod123"
curl "http://localhost:8000/recommendations/user/user456"
curl "http://localhost:8000/recommendations/cart/user456?cart_items=prod1,prod2"
```