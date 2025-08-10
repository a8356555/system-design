# Netflix-like Streaming Recommendation System - Complete Architecture & Workflow

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Components](#architecture-components)
3. [Value Objects & Domain Design](#value-objects--domain-design)
4. [Real-time Updates](#real-time-updates)
5. [Background Processing & Event-Driven Updates](#background-processing--event-driven-updates)
6. [Celery Task Triggering Mechanisms](#celery-task-triggering-mechanisms)
7. [WebSocket vs Server-Sent Events](#websocket-vs-server-sent-events)
8. [Event Processing Pipeline](#event-processing-pipeline)
9. [Cache Strategy & Management](#cache-strategy--management)
10. [Production-Ready Architecture](#production-ready-architecture)
11. [Monitoring & Observability](#monitoring--observability)

---

## 🏛️ System Overview

### Core Features Implemented

**Streaming Recommendation System (Clean Architecture)**
- Domain-driven design with separate layers (entities, repositories, services)
- Real-time recommendation engine for content streaming platforms
- Multiple recommendation strategies (trending, genre-based, continue watching)
- Content discovery and similar content recommendations

### Tech Stack

- **Framework:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL with AsyncPG
- **Cache:** Redis for recommendation caching
- **Message Queue:** Redis/Kafka for event streaming
- **Background Processing:** Celery
- **Real-time Communication:** WebSocket/SSE
- **Architecture:** Clean Architecture with Dependency Injection
- **Containerization:** Docker & Docker Compose

---

## 🏗️ Architecture Components

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

### API Endpoints

#### Core Recommendation APIs
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

---

## 💎 Value Objects & Domain Design

### What are Value Objects?

Value Objects are **immutable objects** that represent concepts through their attributes rather than identity. They're defined by their **values**, not by a unique ID.

### Key Value Objects in the System

#### 1. RecommendationScore
```python
@dataclass
class RecommendationScore:
    base_score: float  # Core algorithm score (0.0 - 1.0)
    trending_boost: float = 0.0
    genre_match_boost: float = 0.0
    recency_boost: float = 0.0
    popularity_boost: float = 0.0
    diversity_penalty: float = 0.0
    final_score: float = 0.0

    def calculate_final_score(self) -> float:
        self.final_score = min(
            self.base_score + 
            self.trending_boost + 
            self.genre_match_boost + 
            self.recency_boost + 
            self.popularity_boost - 
            self.diversity_penalty,
            1.0
        )
        return self.final_score
```

#### 2. Enum Value Objects
```python
class ContentType(Enum):
    MOVIE = "movie"
    SERIES = "series"
    EPISODE = "episode"

class DeviceType(Enum):
    TV = "tv"
    MOBILE = "mobile"
    TABLET = "tablet"
    DESKTOP = "desktop"

class InteractionType(Enum):
    PLAY = "play"
    PAUSE = "pause"
    COMPLETE = "complete"
    RATE = "rate"
```

### Benefits of Value Objects

1. **Domain Modeling Clarity** - Express business concepts clearly
2. **Type Safety** - Prevent errors through strong typing
3. **Validation & Business Rules** - Encapsulate domain logic
4. **Immutability** - Thread-safe and predictable behavior

---

## ⚡ Real-time Updates

### Real-time Update Components

Real-time updates provide **immediate, contextual recommendations** that adapt to user behavior **as it happens** during their current viewing session.

#### 1. Session-Based Recommendations
```python
async def get_session_based_recommendations(
    request: RecommendationRequest,
    session_id: str,
    current_content_id: Optional[str] = None
) -> RecommendationResponse:
    # Get current session interactions
    session_interactions = await self._get_session_interactions(
        request.user_id, request.profile_id, session_id
    )
    
    # Analyze session patterns
    session_context = self._analyze_session_context(session_interactions)
    
    # Generate recommendations based on session context
    recommendations = []
    
    # 1. Next episode recommendations (if watching series)
    if current_content_id:
        next_episode_recs = await self._get_next_episode_recommendations(
            current_content_id, request.user_id, request.profile_id
        )
        recommendations.extend(next_episode_recs)
```

#### 2. Device-Optimized Recommendations
```python
async def get_device_optimized_recommendations(
    user_id: str,
    profile_id: str,
    device_type: DeviceType,
    limit: int = 20
) -> List[ContentRecommendation]:
    
    if device_type == DeviceType.MOBILE:
        # Mobile: Shorter content, episodes, clips
        content_filters = {
            "max_duration_minutes": 45,
            "content_types": ["episode", "short", "documentary"]
        }
    elif device_type == DeviceType.TV:
        # TV: Movies, series, high-quality content
        content_filters = {
            "min_duration_minutes": 20,
            "content_types": ["movie", "series", "documentary"],
            "min_rating": 7.0
        }
```

#### 3. Netflix User Journey - Real-time API Calls

**Homepage Load (Primary Experience)**
```http
GET /recommendations/homepage/user123/profile456
├── GET /recommendations/personalized/user123/profile456?limit=20
├── GET /recommendations/continue-watching/user123/profile456?limit=10
├── GET /recommendations/trending?limit=15
└── GET /recommendations/genre/user123/profile456?genres=action,comedy&limit=10
```

**Video Playback Start**
```http
POST /recommendations/interaction
{
  "interaction_type": "play",
  "session_id": "sess001",
  "device_type": "web"
}

# Immediately get next recommendations for autoplay
GET /recommendations/realtime/user123/profile456?session_id=sess001&current_content_id=movie789&limit=5
```

**Video End / Autoplay**
```http
GET /recommendations/realtime/user123/profile456?session_id=sess001&limit=3
# Or specific similar content for autoplay
GET /recommendations/similar/movie789?limit=1&autoplay=true
```

---

## 🔄 Background Processing & Event-Driven Updates

### Background Processing Architecture

The system uses multiple approaches for background processing:

1. **FastAPI BackgroundTasks** - Simple, fast operations
2. **Celery Tasks** - Complex, reliable processing
3. **Kafka Event Streaming** - High-throughput event processing

### FastAPI BackgroundTasks vs Celery

#### Use FastAPI BackgroundTasks When:
- Simple, fast operations (< 5 seconds)
- Operations that don't need persistence
- Cleanup operations that can fail without major impact

```python
@app.post("/user/logout")
async def logout_user(user_id: str, background_tasks: BackgroundTasks):
    # Immediate: Clear session
    clear_user_session(user_id)
    
    # Background: Simple cleanup tasks
    background_tasks.add_task(log_logout_event, user_id)
    background_tasks.add_task(update_last_seen, user_id)
    
    return {"status": "logged_out"}
```

#### Use Celery Tasks When:
- Heavy/Long-running operations (> 5 seconds)
- Critical operations that must complete
- Operations requiring scalability
- Scheduled/Batch operations

```python
@celery_app.task(bind=True, max_retries=3)
def process_user_interaction(self, interaction_data: dict):
    try:
        # Update user behavior model
        update_user_behavior_model(interaction_data)
        
        # Invalidate recommendation cache
        invalidate_recommendation_cache(interaction_data)
        
        # Update trending analysis
        update_trending_analysis(interaction_data)
        
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

### Event-Driven Updates

#### WebSocket Real-time Recommendations
```python
class RecommendationWebSocketManager:
    async def connect(self, websocket: WebSocket, user_id: str, profile_id: str):
        await websocket.accept()
        
        # Add connection to user's connection pool
        user_key = f"{user_id}:{profile_id}"
        if user_key not in self.active_connections:
            self.active_connections[user_key] = set()
        
        self.active_connections[user_key].add(websocket)
        
        # Send initial recommendations
        initial_recs = await self.get_initial_recommendations(user_id, profile_id)
        await websocket.send_json({
            "type": "initial_recommendations",
            "data": initial_recs
        })

    async def broadcast_to_user(self, user_id: str, profile_id: str, message: dict):
        """Send real-time updates to all user's active sessions"""
        user_key = f"{user_id}:{profile_id}"
        
        if user_key in self.active_connections:
            for websocket in self.active_connections[user_key]:
                try:
                    await websocket.send_json(message)
                except:
                    # Handle disconnected websockets
                    pass
```

#### Server-Sent Events Alternative
```python
@app.get("/recommendations/events/{user_id}/{profile_id}")
async def recommendation_events(user_id: str, profile_id: str, request: Request):
    async def event_stream():
        while True:
            # Check if client is still connected
            if await request.is_disconnected():
                break
            
            # Get fresh recommendations based on recent activity
            fresh_recs = await get_contextual_recommendations(user_id, profile_id)
            
            # Format as SSE
            data = json.dumps({
                "recommendations": fresh_recs,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            yield f"data: {data}\n\n"
            await asyncio.sleep(30)
    
    return StreamingResponse(event_stream(), media_type="text/plain")
```

---

## ⏰ Celery Task Triggering Mechanisms

### 1. API-Triggered Tasks (Most Common - 90% of tasks)
```python
@app.post("/recommendations/interaction")
async def track_interaction(interaction: InteractionRequest):
    # Trigger Celery task immediately
    process_user_interaction.delay(interaction.dict())
    return {"status": "interaction_queued"}
```

### 2. Cron-like Scheduled Tasks (Celery Beat)
```python
# Celery Beat scheduler configuration
celery_app.conf.beat_schedule = {
    # Update trending content every 15 minutes
    'update-trending-content': {
        'task': 'tasks.update_trending_analysis',
        'schedule': crontab(minute='*/15'),
    },
    
    # Refresh user recommendations daily at 2 AM
    'refresh-user-recommendations': {
        'task': 'tasks.batch_refresh_recommendations', 
        'schedule': crontab(hour=2, minute=0),
    },
    
    # Update ML models weekly
    'retrain-ml-models': {
        'task': 'tasks.retrain_recommendation_models',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Sunday 3 AM
    },
}
```

### 3. Event-Driven Task Triggers
```python
class EventTriggeredTasks:
    async def listen_for_events(self):
        # Redis pub/sub listener
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe('user_interactions', 'content_updates')
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                await self.handle_event(message)
    
    async def handle_event(self, message):
        channel = message['channel'].decode()
        data = json.loads(message['data'])
        
        if channel == 'user_interactions':
            process_user_interaction.delay(data)
        elif channel == 'content_updates':
            update_content_recommendations.delay(data['content_id'])
```

### 4. Task Chaining and Groups
```python
# Chain: Execute tasks in sequence
recommendation_pipeline = chain(
    collect_user_data.s(user_id),
    analyze_user_behavior.s(),
    generate_recommendations.s(),
    cache_recommendations.s(user_id)
)

# Group: Execute tasks in parallel
parallel_analysis = group(
    analyze_trending_content.s(),
    analyze_user_preferences.s(), 
    analyze_content_similarity.s()
)

# Chord: Execute group in parallel, then run callback
trending_update_pipeline = chord(
    group(
        calculate_hourly_trending.s(),
        calculate_daily_trending.s(), 
        calculate_weekly_trending.s()
    )
)(update_trending_recommendations.s())
```

---

## 📡 WebSocket vs Server-Sent Events

### Communication Patterns Comparison

| Feature | WebSocket | Server-Sent Events |
|---------|-----------|-------------------|
| **Communication** | ⬅️➡️ Bidirectional | ➡️ Server → Client only |
| **Protocol** | Custom WS protocol | Standard HTTP/1.1 or HTTP/2 |
| **Complexity** | Higher | Lower |
| **Auto Reconnection** | Manual implementation | Built-in automatic |
| **Connection Overhead** | Lower | Higher (HTTP headers) |
| **Firewall/Proxy** | Sometimes blocked | HTTP - always works |

### When to Choose Each

#### Choose WebSocket When:
- **Need bidirectional communication** (user can cancel autoplay, request specific recommendations)
- **Low latency critical** (immediate autoplay countdown, real-time video sync)
- **Complex message patterns** (request-response cycles, user commands)

```javascript
// WebSocket: Perfect for Netflix autoplay countdown
class NetflixAutoplay {
    constructor() {
        this.ws = new WebSocket('/recommendations/stream/user123/profile456');
        
        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'autoplay_countdown') {
                this.showCountdown(message.data, message.countdown_seconds);
            }
        };
    }
    
    // User can interact - cancel autoplay
    cancelAutoplay() {
        this.ws.send(JSON.stringify({
            type: "cancel_autoplay",
            reason: "user_cancelled"
        }));
    }
}
```

#### Choose SSE When:
- **Only need server → client updates** (trending content updates, new releases notifications)
- **Simpler implementation preferred** (just push notifications, status updates)
- **Network/firewall concerns** (corporate environments, strict proxy settings)

```javascript
// SSE: Perfect for trending content updates
class TrendingUpdates {
    constructor() {
        this.eventSource = new EventSource('/recommendations/trending/events');
        
        this.eventSource.onmessage = (event) => {
            const trendingData = JSON.parse(event.data);
            this.updateTrendingSection(trendingData.trending_content);
        };
    }
}
```

---

## 🔄 Event Processing Pipeline

### Complete User Interaction Flow

#### Frontend Event Capture
```javascript
class NetflixVideoPlayer {
    setupEventListeners() {
        // Video started playing
        this.video.addEventListener('play', () => {
            this.trackInteraction('play', {
                timestamp: new Date().toISOString(),
                progress_seconds: 0
            });
        });
        
        // Video ended naturally
        this.video.addEventListener('ended', () => {
            this.trackInteraction('complete', {
                progress_seconds: Math.floor(this.video.duration),
                completion_percentage: 100
            });
        });
    }
    
    trackInteraction(interactionType, additionalData = {}) {
        fetch('/recommendations/interaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: this.userId,
                profile_id: this.profileId,
                content_id: this.contentId,
                interaction_type: interactionType,
                session_id: this.getSessionId(),
                device_type: this.getDeviceType(),
                timestamp: new Date().toISOString(),
                ...additionalData
            })
        });
    }
}
```

#### Backend Processing Pipeline
```python
@app.post("/recommendations/interaction")
async def track_interaction(
    interaction: InteractionRequest,
    background_tasks: BackgroundTasks
):
    # Queue background processing
    background_tasks.add_task(
        queue_interaction_processing,
        interaction.dict()
    )
    
    return {"status": "interaction_queued"}

@celery_app.task
def process_user_interaction(interaction_data: dict):
    # Step 1: Clear old cache
    invalidate_recommendation_cache(interaction_data)
    
    # Step 2: Update user behavior model
    update_user_behavior_model(interaction_data)
    
    # Step 3: Generate and cache fresh recommendations
    update_realtime_recommendation_cache(interaction_data)
    
    # Step 4: Notify active clients
    notify_realtime_clients(interaction_data)
```

### Trending Analysis - Why Increment Counters?

Trending content is determined by **interaction velocity over time**, not total historical views.

```python
@celery_app.task
def update_trending_analysis(content_id: str, interaction_type: str):
    # Increment interaction counters for different time windows
    redis_client.zincrby("trending:hourly", 1, content_id)
    redis_client.zincrby("trending:daily", 1, content_id)
    redis_client.zincrby("trending:weekly", 1, content_id)
    
    # Weight different interaction types differently
    interaction_weights = {
        "play": 1.0,           # Standard weight
        "complete": 3.0,       # High value - user watched entire content
        "rate": 2.0,           # High value - user engaged enough to rate
        "share": 4.0,          # Very high value - viral potential
    }
    
    weight = interaction_weights.get(interaction_type, 1.0)
    redis_client.zincrby("trending:hourly", weight, content_id)
```

### Trending Algorithm
```python
def calculate_trending_scores():
    hourly_interactions = redis_client.zrevrange("trending:hourly", 0, -1, withscores=True)
    daily_interactions = redis_client.zrevrange("trending:daily", 0, -1, withscores=True)
    
    for content_id, hourly_count in hourly_interactions:
        daily_count = get_score_for_content(daily_interactions, content_id)
        
        # Trending formula: Recent activity weighted more heavily
        trending_score = (
            hourly_count * 10 +      # Recent activity (highest weight)
            daily_count * 3          # Medium-term activity
        )
        
        # Velocity: How fast is it growing?
        if daily_count > 0:
            velocity = hourly_count / daily_count * 24
            trending_score *= (1 + velocity)
```

---

## 🗂️ Cache Strategy & Management

### Cache Lifecycle Relationship

The relationship between cache invalidation and updates:

```
User Action → Invalidate Old Cache → Generate New Recommendations → Update Cache → Notify Real-time Clients
```

### Cache Invalidation (Clearing Old Data)
```python
async def invalidate_recommendation_cache(user_id: str, profile_id: str, interaction_data: dict):
    # Clear user-specific recommendation caches
    cache_keys_to_remove = [
        f"personalized_recs:{user_id}:{profile_id}",
        f"homepage_feed:{user_id}:{profile_id}",
        f"continue_watching:{user_id}:{profile_id}",
        f"session_recs:{interaction_data.get('session_id')}",
    ]
    
    # If user completed/rated content, also invalidate similar content
    if interaction_data["interaction_type"] in ["complete", "rate"]:
        cache_keys_to_remove.extend([
            f"similar_content:{interaction_data['content_id']}",
            f"because_you_watched:{interaction_data['content_id']}",
        ])
    
    # Remove from Redis
    for key in cache_keys_to_remove:
        await redis_client.delete(key)
```

### Cache Update Strategy
```python
async def update_realtime_recommendation_cache(interaction_data: dict):
    user_id = interaction_data["user_id"] 
    profile_id = interaction_data["profile_id"]
    
    # Generate fresh recommendations
    fresh_recommendations = await generate_fresh_recommendations(
        user_id, profile_id, interaction_data
    )
    
    # Cache with different TTL for different types
    cache_operations = [
        # Personalized (longer TTL - changes less frequently)
        redis_client.setex(
            f"personalized_recs:{user_id}:{profile_id}",
            3600,  # 1 hour TTL
            json.dumps(fresh_recommendations["personalized"])
        ),
        
        # Session-based (shorter TTL - changes frequently)
        redis_client.setex(
            f"session_recs:{interaction_data['session_id']}",
            900,  # 15 minutes TTL
            json.dumps(fresh_recommendations["session_based"])
        )
    ]
    
    await asyncio.gather(*cache_operations)
```

### Cache Strategy Matrix

| Scenario | Invalidation Strategy | Update Strategy | Real-time Notification |
|----------|----------------------|-----------------|----------------------|
| **Video Play** | Session cache only | Lazy update | Session context |
| **Video Complete** | Multiple caches | Eager autoplay + Lazy others | Autoplay countdown |
| **User Rating** | Comprehensive | Eager personalized | Homepage refresh |
| **Add to Watchlist** | Minimal | Lazy update | Watchlist section |

---

## 🏭 Production-Ready Architecture

### Kafka Event Streaming Integration

#### EventProducer - API Layer Integration
```python
# infrastructure/events/kafka_producer.py
class EventProducer:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_BROKERS', 'localhost:9092').split(','),
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            acks='all',  # Wait for all replicas
            retries=3,
            compression_type='snappy'
        )
    
    async def send_user_event(self, user_id: str, event_data: Dict[str, Any]):
        event = {
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "event_data": event_data
        }
        
        # Route to appropriate topic
        topic = self._get_topic_for_event(event_data['interaction_type'])
        self.producer.send(topic, event)
        self.producer.flush()
    
    def _get_topic_for_event(self, interaction_type: str) -> str:
        topic_mapping = {
            'play': 'user_interactions_realtime',
            'complete': 'user_interactions_realtime', 
            'rate': 'user_interactions_realtime',
            'pause': 'user_interactions_standard',
            'progress_update': 'user_interactions_batch'
        }
        return topic_mapping.get(interaction_type, 'user_interactions_standard')
```

#### RecommendationEventConsumer - Separate Microservice
```python
# services/event_consumer_service.py
class RecommendationEventConsumer:
    def __init__(self):
        self.consumer = KafkaConsumer(
            'user_interactions_realtime',
            'user_interactions_standard', 
            'user_interactions_batch',
            bootstrap_servers=os.getenv('KAFKA_BROKERS').split(','),
            group_id='recommendation_processors',
            auto_offset_reset='latest'
        )
    
    async def start_consuming(self):
        for message in self.consumer:
            await self.process_event_message(message)
    
    async def process_event_message(self, message):
        topic = message.topic
        event_data = message.value
        
        if topic == 'user_interactions_realtime':
            await self.process_realtime_event(event_data)
        elif topic == 'user_interactions_standard':
            await self.process_standard_event(event_data)
```

### Production Deployment

#### Docker Compose Production Setup
```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  kafka:
    image: confluentinc/cp-kafka:latest
    environment:
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3

  # Main API service
  streaming_api:
    build: .
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
    environment:
      - KAFKA_BROKERS=kafka:9092
    
  # Separate event consumer service
  event_consumer:
    build: .
    command: python -m services.event_consumer_service
    deploy:
      replicas: 3
      
  # Celery workers
  celery_worker:
    build: .
    command: celery -A streaming_recommendations worker --loglevel=info
    deploy:
      replicas: 5
```

#### Kubernetes Production Deployment
```yaml
# k8s/event-consumer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: recommendation-event-consumer
spec:
  replicas: 10  # Scale based on Kafka partition count
  template:
    spec:
      containers:
      - name: event-consumer
        image: streaming-recommendations:latest
        command: ["python", "-m", "services.event_consumer_service"]
        resources:
          requests:
            cpu: 200m
            memory: 512Mi
```

### Netflix-Scale Production Flow

```
📱 User Action (1M/sec) 
    ↓
🌐 API Gateway (Load Balancer)
    ↓
🚀 FastAPI Instances (10 replicas) 
    ├── EventProducer.send_user_event() 
    └── Return immediate response to user
    ↓
📨 Kafka Cluster (3 brokers, partitioned topics)
    ├── user_interactions_realtime (4 partitions)
    ├── user_interactions_standard (8 partitions)  
    └── user_interactions_batch (12 partitions)
    ↓
🔄 Event Consumer Instances (20 replicas)
    ├── RecommendationEventConsumer.process_realtime_event()
    ├── RecommendationEventConsumer.process_standard_event()
    └── RecommendationEventConsumer.process_batch_event()
    ↓
⚡ Real-time Updates via WebSocket
📊 Background Processing via Celery
🗃️ Cache Updates via Redis
```

---

## 📊 Monitoring & Observability

### Metrics Collection

#### Kafka Metrics
```python
from prometheus_client import Counter, Histogram, Gauge

# Events produced to Kafka
events_produced_total = Counter(
    'kafka_events_produced_total',
    'Total events produced to Kafka',
    ['topic', 'event_type']
)

# Event processing duration
event_processing_duration = Histogram(
    'event_processing_duration_seconds', 
    'Time spent processing consumed events',
    ['event_type', 'processing_result']
)

# Consumer lag
consumer_lag = Gauge(
    'kafka_consumer_lag',
    'Consumer lag behind latest offset',
    ['topic', 'partition', 'consumer_group']
)
```

#### Recommendation Metrics
```python
# Recommendation generation metrics
recommendation_generation_duration = Histogram(
    'recommendation_generation_duration_seconds',
    'Time to generate recommendations',
    ['recommendation_type', 'user_type']
)

# Cache hit/miss rates
cache_requests_total = Counter(
    'cache_requests_total',
    'Total cache requests',
    ['cache_type', 'result']  # result: hit/miss
)

# Real-time update metrics
realtime_updates_sent = Counter(
    'realtime_updates_sent_total',
    'Real-time updates sent to users',
    ['update_type', 'delivery_method']  # websocket/sse
)
```

### Health Checks

```python
@app.get("/health")
async def health_check():
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check Redis connectivity
    try:
        await redis_client.ping()
        health_status["components"]["redis"] = "healthy"
    except Exception as e:
        health_status["components"]["redis"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Kafka connectivity
    try:
        event_producer.producer.bootstrap_connected()
        health_status["components"]["kafka"] = "healthy"
    except Exception as e:
        health_status["components"]["kafka"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status
```

### Performance Targets

| Component | Target Performance | Monitoring |
|-----------|-------------------|------------|
| **API Response** | <100ms (cached), <500ms (computed) | Response time histograms |
| **Cache Hit Rate** | >80% for personalized recommendations | Cache metrics |
| **Event Processing** | <1000ms per event | Processing duration |
| **WebSocket Updates** | <50ms delivery time | Real-time metrics |
| **Kafka Consumer Lag** | <10 seconds | Consumer lag gauges |

---

## 🎯 Key Architectural Decisions Summary

### 1. **Clean Architecture**
- **Domain Layer:** Pure business logic (recommendation algorithms)
- **Application Layer:** Use case orchestration (handlers, DTOs)
- **Infrastructure Layer:** External services (database, cache, messaging)
- **Presentation Layer:** API contracts (FastAPI routes, WebSocket endpoints)

### 2. **Event-Driven Architecture**
- **Kafka** for high-throughput event streaming
- **Celery** for reliable background processing
- **Redis** for fast caching and session management
- **WebSocket/SSE** for real-time user updates

### 3. **Scalability Patterns**
- **Horizontal scaling** of API servers, event consumers, and workers
- **Partitioned topics** in Kafka for parallel processing
- **Multi-layer caching** with different TTL strategies
- **Async/await** throughout for non-blocking I/O

### 4. **Real-time Capabilities**
- **Session-aware recommendations** that adapt to current viewing context
- **Device-optimized content** for different screen sizes and usage patterns  
- **Immediate autoplay suggestions** triggered by video completion events
- **Live trending updates** based on real-time interaction velocity

### 5. **Production Readiness**
- **Comprehensive monitoring** with Prometheus metrics
- **Health checks** for all critical components
- **Graceful error handling** with retry mechanisms
- **Container orchestration** with Docker and Kubernetes
- **Performance optimization** targeting Netflix-scale throughput

This architecture successfully handles the complexity of a modern streaming recommendation system while maintaining clean separation of concerns, high performance, and real-time responsiveness at scale.