# Streaming Recommendation System

A high-performance streaming recommendation system built with **Clean Architecture** principles in Python. Designed for streaming platforms like Netflix, Hulu, or Disney+ with focus on real-time personalization and scalability.

## 🏛️ Architecture Overview

### Clean Architecture Layers

```
┌─────────────────────────────────────────────────┐
│                Presentation                     │ ← FastAPI, API Routes, DTOs
├─────────────────────────────────────────────────┤
│                Application                      │ ← Use Case Handlers, DTOs  
├─────────────────────────────────────────────────┤
│                   Domain                        │ ← Business Logic, Entities
├─────────────────────────────────────────────────┤
│               Infrastructure                    │ ← Database, Cache, External APIs
└─────────────────────────────────────────────────┘
```

### Project Structure
```
streaming-recommendation-system/
├── domain/                          # Business Logic (Core)
│   ├── entities/                   # Business entities
│   │   ├── content.py             # Content, Series entities
│   │   ├── user.py                # User, UserProfile entities
│   │   ├── interaction.py         # UserInteraction, ViewingProgress
│   │   └── recommendation.py      # Recommendation entities
│   ├── repositories/              # Repository interfaces
│   │   ├── content_repository.py
│   │   ├── user_repository.py
│   │   └── interaction_repository.py
│   └── services/                  # Use Cases (Business Logic)
│       ├── content_discovery_service.py
│       ├── continue_watching_service.py
│       ├── similar_content_service.py
│       ├── trending_service.py
│       ├── genre_based_service.py
│       └── realtime_service.py
├── application/                    # Application Layer
│   ├── dto/                       # Data Transfer Objects
│   └── handlers/                  # Use Case Handlers
├── infrastructure/                # External Concerns
│   ├── database/                  # Database models & repositories
│   ├── cache/                     # Redis caching implementation
│   └── dependencies.py           # Dependency injection
├── presentation/                  # API Layer
│   └── api/                      # FastAPI routes
└── main.py                       # Application entry point
```

## 🎯 Core Features Implemented

### 1. **Content Discovery**
- **Personalized Recommendations** - Collaborative + Content-based filtering
- **Cold Start Handling** - Popular content for new users
- **Hybrid Algorithm** - Combines multiple recommendation strategies

### 2. **Continue Watching**  
- **Progress Tracking** - Resume from exact position
- **Smart Prioritization** - Recent and partially watched content first
- **Next Episode** - Auto-recommendations for series

### 3. **Similar Content**
- **"More Like This"** - Content-based similarity matching
- **Genre Matching** - Weighted genre compatibility scoring
- **Cast/Director Similarity** - People-based recommendations

### 4. **Trending Content**
- **Real-time Trending** - Based on recent user interactions
- **Temporal Analysis** - Growth rate and momentum calculation
- **Regional Trending** - Geography-based popular content

### 5. **Genre-based Recommendations**
- **Preference Learning** - Implicit genre preference detection
- **Genre Exploration** - Recommend unexplored genres
- **Mixed Recommendations** - Primary + complementary genres

### 6. **Real-time Recommendations**
- **Session-aware** - Current viewing session context
- **Device Optimization** - Mobile vs TV vs Tablet preferences
- **Contextual** - Time-of-day, mood-based suggestions

## 🚀 API Endpoints

### Core Recommendation APIs
```http
GET /recommendations/personalized/{user_id}/{profile_id}
GET /recommendations/continue-watching/{user_id}/{profile_id}  
GET /recommendations/similar/{content_id}
GET /recommendations/trending
GET /recommendations/genre/{user_id}/{profile_id}
GET /recommendations/realtime/{user_id}/{profile_id}
GET /recommendations/device-optimized/{user_id}/{profile_id}
GET /recommendations/homepage/{user_id}/{profile_id}
POST /recommendations/interaction
```

### Example API Calls
```bash
# Get personalized recommendations
curl "http://localhost:8000/recommendations/personalized/user123/profile456?limit=20"

# Continue watching with progress
curl "http://localhost:8000/recommendations/continue-watching/user123/profile456"

# Similar content recommendations  
curl "http://localhost:8000/recommendations/similar/movie789?user_id=user123&profile_id=profile456"

# Real-time session-based recommendations
curl "http://localhost:8000/recommendations/realtime/user123/profile456?session_id=sess001&device_type=mobile"

# Track user interaction
curl -X POST "http://localhost:8000/recommendations/interaction" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user123","profile_id":"profile456","content_id":"movie789","interaction_type":"play","session_id":"sess001","device_type":"mobile"}'
```

## 🛠️ Tech Stack

- **Framework:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL with AsyncPG
- **Cache:** Redis for recommendation caching
- **Architecture:** Clean Architecture with Dependency Injection
- **ORM:** SQLAlchemy (Async)
- **Validation:** Pydantic
- **Containerization:** Docker & Docker Compose

## 📦 Quick Start

### Using Docker Compose (Recommended)
```bash
# Clone and navigate to project
cd streaming-recommendation-system

# Start all services
docker-compose up -d

# API available at http://localhost:8000
# API Documentation at http://localhost:8000/docs
# Redis Commander at http://localhost:8081
# pgAdmin at http://localhost:8082
```

### Manual Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your database/redis settings

# Start PostgreSQL and Redis services
# Then run the application
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 🔧 Configuration

### Environment Variables
```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost/streaming
REDIS_URL=redis://localhost:6379
DEBUG=True
CACHE_TTL_SECONDS=3600
MAX_RECOMMENDATIONS=100
SIMILARITY_THRESHOLD=0.3
```

### Feature Flags
- `ENABLE_REALTIME_RECOMMENDATIONS` - Real-time context-aware recommendations
- `ENABLE_DEVICE_OPTIMIZATION` - Device-specific recommendation optimization
- `ENABLE_GENRE_EXPLORATION` - Genre exploration for content discovery
- `ENABLE_TRENDING_BOOST` - Trending content boost in recommendations

## 🎨 Clean Architecture Benefits

### **Dependency Rule**
- Inner layers don't depend on outer layers
- Business logic independent of frameworks/databases
- Easy to test and modify

### **Separation of Concerns**
- **Domain Layer:** Pure business logic
- **Application Layer:** Use case orchestration  
- **Infrastructure Layer:** External services
- **Presentation Layer:** API contracts

### **Testability**
- Mock external dependencies easily
- Unit test business logic in isolation
- Integration tests for full workflows

### **Technology Independence**
- Swap databases without changing business logic
- Change caching strategy without affecting core features
- Replace ML algorithms independently

## 🔮 Future Enhancements (See TODO.md)

- **Session-based Recommendations** - Binge-watching pattern recognition
- **Multi-user Profiles** - Family account optimization
- **A/B Testing Framework** - Algorithm performance comparison
- **Advanced ML Models** - Deep learning recommendation models
- **Real-time Stream Processing** - Kafka + Flink integration
- **Social Features** - Friend-based recommendations

## 🏃‍♂️ Performance Features

- **Async/Await** - Non-blocking I/O operations
- **Redis Caching** - Sub-100ms response times
- **Connection Pooling** - Efficient database utilization  
- **Background Tasks** - Non-blocking interaction tracking
- **Dependency Injection** - Efficient resource management

## 📊 Monitoring

- **Health Checks:** `GET /health`
- **Feature Overview:** `GET /features`  
- **API Documentation:** `GET /docs`
- **Redis Monitoring:** Redis Commander UI
- **Database Monitoring:** pgAdmin UI

## 🧪 Testing

The system is designed for comprehensive testing with Clean Architecture:

```bash
# Unit tests for domain layer
pytest tests/domain/

# Integration tests for application layer  
pytest tests/application/

# API tests for presentation layer
pytest tests/presentation/

# End-to-end tests
pytest tests/e2e/
```

---

**Built with Clean Architecture principles for maintainability, testability, and scalability** 🏛️