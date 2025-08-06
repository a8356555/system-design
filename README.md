# High Concurrency System Design Implementations

This repository contains implementations of high-concurrency systems based on the designs documented in `high-concurrency-system-designs.md`.

## Implemented Systems

### 1. URL Shortener System
**Location**: `url-shortener/`

A high-performance URL shortening service similar to bit.ly/TinyURL with the following features:

#### Key Features:
- **Base62 Encoding**: Efficient URL encoding/decoding algorithm
- **Multi-level Caching**: Redis caching with CDN support
- **Analytics Tracking**: Real-time click tracking and analytics
- **Rate Limiting**: Protection against abuse
- **Custom Aliases**: Support for custom short URLs
- **Bulk Operations**: Batch URL creation support

#### Architecture:
- **Encoding Service**: Base62 algorithm with collision handling
- **Redirect Service**: High-performance redirects with caching
- **Analytics Service**: Real-time metrics and batch processing
- **Cache Service**: Multi-level caching strategy

#### Scalability Features:
- Database sharding by URL hash
- Read-heavy optimization (99:1 read-write ratio)
- Distributed ID generation
- Geographic load balancing
- Hot URL detection and preferential caching

### 2. Social Media Feed System
**Location**: `social-media-feed/`

A high-concurrency social media feed system similar to Twitter/Facebook with the following features:

#### Key Features:
- **Personalized Feeds**: ML-powered content ranking
- **Real-time Updates**: WebSocket connections for live feeds
- **Social Graph**: Follow/unfollow with relationship management
- **Content Discovery**: Trending posts and hashtag feeds
- **Push/Pull Models**: Hybrid approach for different user types
- **Celebrity Handling**: Separate processing for high-follower users

#### Architecture:
- **Feed Generation Service**: Push/pull hybrid model with queue processing
- **Social Graph Service**: Relationship management with caching
- **Content Ranking**: Engagement-based scoring with personalization
- **Real-time Service**: WebSocket connections for live updates

#### Scalability Features:
- Fan-out strategies for different user types
- Timeline pre-computation for active users
- Content deduplication and caching
- Async processing for non-critical operations
- Queue-based celebrity post handling

## Technology Stack

### Common Technologies:
- **Backend**: Node.js with Express
- **Database**: MongoDB with proper indexing
- **Cache**: Redis for multi-level caching
- **Queue**: Bull (Redis-based) for background jobs
- **Real-time**: Socket.io for WebSocket connections

### URL Shortener Specific:
- **Analytics**: ClickHouse-compatible batch processing
- **Rate Limiting**: Express rate limiting middleware
- **Monitoring**: Health checks and metrics endpoints

### Social Media Feed Specific:
- **Graph Processing**: Optimized relationship queries
- **ML Ranking**: Personalized content scoring
- **Real-time**: Live feed updates and notifications

## Getting Started

### Prerequisites:
- Node.js 16+
- MongoDB 5+
- Redis 6+

### URL Shortener Setup:
```bash
cd url-shortener
npm install
npm run dev
```

### Social Media Feed Setup:
```bash
cd social-media-feed
npm install
npm run dev
```

## API Endpoints

### URL Shortener:
- `POST /api/shorten` - Create short URL
- `GET /:shortCode` - Redirect to original URL  
- `GET /api/analytics/:shortCode` - Get URL analytics
- `POST /api/bulk` - Bulk URL creation

### Social Media Feed:
- `GET /api/feed` - Get personalized feed
- `GET /api/feed/trending` - Get trending posts
- `POST /api/posts` - Create new post
- `POST /api/social/follow/:userId` - Follow user
- `GET /api/social/suggestions` - Get follow suggestions

## High Concurrency Patterns Implemented

### Database Optimization:
- Proper indexing strategies
- Connection pooling
- Read replicas support
- Horizontal sharding patterns

### Caching Strategies:
- Multi-level caching (L1: App, L2: Redis, L3: CDN)
- Cache invalidation patterns
- Hot data identification
- Time-based expiration

### Queue Processing:
- Background job processing
- Priority queues
- Batch processing
- Dead letter queues

### Rate Limiting:
- IP-based rate limiting
- User-based rate limiting
- Sliding window implementation
- Graceful degradation

## Performance Characteristics

### URL Shortener:
- **Throughput**: 10K+ redirects/second
- **Latency**: <10ms for cached URLs
- **Availability**: 99.9% uptime target
- **Scalability**: Horizontal scaling ready

### Social Media Feed:
- **Feed Generation**: <100ms for personalized feeds
- **Real-time Updates**: <50ms for live notifications
- **Throughput**: 1K+ posts/second processing
- **User Capacity**: 1M+ concurrent users

## Monitoring and Observability

Both systems include:
- Health check endpoints
- Performance metrics
- Error tracking
- Memory and CPU monitoring
- Database connection monitoring

## Testing

Run tests for each system:
```bash
# URL Shortener
cd url-shortener && npm test

# Social Media Feed  
cd social-media-feed && npm test
```

## Production Considerations

### Security:
- Input validation and sanitization
- Rate limiting and DDoS protection
- Authentication and authorization
- Malicious URL detection

### Scalability:
- Load balancer configuration
- Database replication setup
- CDN integration
- Auto-scaling policies

### Monitoring:
- Application performance monitoring
- Database query optimization
- Cache hit rate monitoring
- Queue processing metrics

## Contributing

1. Fork the repository
2. Create feature branch
3. Implement changes with tests
4. Submit pull request

## License

MIT License - see LICENSE file for details