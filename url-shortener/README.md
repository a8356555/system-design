# URL Shortener System Implementation

A high-performance, scalable URL shortener system built with Node.js, MongoDB, and Redis, supporting millions of URLs with advanced analytics and caching capabilities.

## Architecture Overview

### Core Components
- **URL Encoding Service**: Base62 encoding for short URL generation
- **Redirect Service**: High-performance URL redirection with caching
- **Analytics Engine**: Real-time click tracking and statistics
- **Cache Layer**: Multi-tier caching for optimal performance
- **Rate Limiting**: Advanced DDoS protection and abuse prevention

### Technology Stack
- **Backend**: Node.js with Express framework
- **Database**: MongoDB for URL storage and analytics
- **Caching**: Redis for high-speed URL lookups
- **Encoding**: Base62 algorithm for compact URL generation
- **Security**: Helmet, CORS, comprehensive rate limiting

## Key Features

### URL Management
- **Short URL Generation**: Compact, collision-resistant URL creation
- **Custom Short Codes**: User-defined short URL aliases
- **Bulk URL Creation**: Batch processing for multiple URLs
- **URL Validation**: Comprehensive input validation and sanitization
- **Expiration Support**: Time-based URL expiration

### Analytics & Tracking
- **Click Analytics**: Real-time click tracking and statistics
- **Geographic Data**: Location-based analytics
- **Referrer Tracking**: Source attribution for clicks
- **Device Analytics**: Browser and device statistics
- **Performance Metrics**: Response time and availability tracking

### Performance Features
- **Multi-tier Caching**: Redis + in-memory caching
- **Database Optimization**: Indexed collections for fast lookups
- **Rate Limiting**: Graduated rate limiting by endpoint
- **Compression**: Response compression for bandwidth optimization

## Installation & Setup

### Prerequisites
- Node.js 18+
- MongoDB 6+
- Redis 7+
- Docker & Docker Compose (optional)

### Development Setup
```bash
# Install dependencies
npm install

# Set environment variables
cp .env.example .env
# Edit .env with your configuration

# Start MongoDB and Redis
docker-compose up -d mongo redis

# Start development server
npm run dev
```

### Production Deployment
```bash
# Start all services with Docker
docker-compose up -d

# Or manual deployment
npm install --production
npm start
```

## Configuration

### Environment Variables
```bash
# Server Configuration
NODE_ENV=production
PORT=3000

# Database Configuration
MONGODB_URL=mongodb://localhost:27017/urlshortener

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# URL Configuration
BASE_URL=https://yourdomain.com
SHORT_CODE_LENGTH=6
CUSTOM_DOMAIN_ENABLED=true

# Analytics
ANALYTICS_ENABLED=true
ANALYTICS_RETENTION_DAYS=365

# Security
RATE_LIMIT_WINDOW=900000
RATE_LIMIT_MAX=100
```

## API Endpoints

### URL Management
- `POST /api/shorten` - Create short URL from long URL
- `POST /api/bulk` - Create multiple short URLs in batch
- `GET /api/info/:shortCode` - Get URL information and metadata
- `DELETE /api/delete/:shortCode` - Delete short URL (admin only)

### Analytics
- `GET /api/analytics/:shortCode` - Get detailed click analytics
- `GET /api/analytics/:shortCode/summary` - Get summary statistics
- `GET /api/analytics/:shortCode/geographic` - Get geographic distribution
- `GET /api/analytics/:shortCode/referrers` - Get referrer statistics
- `GET /api/analytics/:shortCode/devices` - Get device/browser statistics

### Redirection
- `GET /:shortCode` - Redirect to original URL with analytics tracking

### System
- `GET /api/health` - Service health check
- `GET /api/stats` - System-wide statistics (admin only)

## Request/Response Examples

### Create Short URL
```bash
# Request
POST /api/shorten
Content-Type: application/json

{
  "longUrl": "https://www.example.com/very/long/url/path",
  "customCode": "custom123",
  "expiresAt": "2024-12-31T23:59:59Z"
}

# Response
{
  "success": true,
  "data": {
    "shortCode": "custom123",
    "shortUrl": "https://yourdomain.com/custom123",
    "longUrl": "https://www.example.com/very/long/url/path",
    "createdAt": "2024-01-15T10:30:00Z",
    "expiresAt": "2024-12-31T23:59:59Z"
  }
}
```

### Get Analytics
```bash
# Request
GET /api/analytics/abc123

# Response
{
  "success": true,
  "data": {
    "shortCode": "abc123",
    "totalClicks": 1247,
    "uniqueVisitors": 892,
    "clicksToday": 45,
    "topCountries": [
      {"country": "US", "clicks": 456},
      {"country": "UK", "clicks": 234}
    ],
    "topReferrers": [
      {"referrer": "google.com", "clicks": 567},
      {"referrer": "twitter.com", "clicks": 234}
    ],
    "hourlyDistribution": [...],
    "deviceTypes": {
      "desktop": 60,
      "mobile": 35,
      "tablet": 5
    }
  }
}
```

## URL Encoding Algorithm

### Base62 Encoding
```javascript
// Character set for Base62 encoding
const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';

// Encoding function
function encodeBase62(num) {
  if (num === 0) return chars[0];
  
  let result = '';
  while (num > 0) {
    result = chars[num % 62] + result;
    num = Math.floor(num / 62);
  }
  return result;
}

// Generate short code from counter
function generateShortCode(counter) {
  return encodeBase62(counter).padStart(6, '0');
}
```

### Collision Handling
- **Counter-based Generation**: Monotonic counter for unique IDs
- **Distributed Counter**: Redis-based counter for multi-instance deployment
- **Fallback Strategy**: Random generation on counter failure

## Caching Strategy

### Cache Layers
```javascript
// L1: In-memory cache (fastest)
const memoryCache = new Map();

// L2: Redis cache (fast, shared)
const redisCache = redis.createClient();

// L3: Database (persistent)
const mongodb = mongoose.connection;
```

### Cache Policies
- **Hot URLs**: Permanent cache for frequently accessed URLs
- **Regular URLs**: 1-hour TTL with LRU eviction
- **Analytics**: 15-minute cache for statistics queries
- **Bulk Operations**: Batch cache invalidation

## Data Models

### URL Schema
```javascript
{
  _id: ObjectId,
  shortCode: String,      // Unique short identifier
  longUrl: String,        // Original URL
  customCode: Boolean,    // User-defined short code
  createdAt: Date,
  expiresAt: Date,        // Optional expiration
  isActive: Boolean,      // Active/inactive status
  metadata: {
    title: String,        // Page title
    description: String,  // Meta description
    favicon: String       // Favicon URL
  }
}
```

### Analytics Schema
```javascript
{
  _id: ObjectId,
  shortCode: String,
  timestamp: Date,
  ip: String,
  userAgent: String,
  referrer: String,
  country: String,
  city: String,
  device: String,
  browser: String,
  os: String
}
```

## Performance Optimizations

### Database Indexing
```javascript
// MongoDB indexes for optimal query performance
db.urls.createIndex({ "shortCode": 1 }, { unique: true });
db.urls.createIndex({ "longUrl": 1 });
db.urls.createIndex({ "createdAt": -1 });
db.urls.createIndex({ "expiresAt": 1 }, { expireAfterSeconds: 0 });

db.analytics.createIndex({ "shortCode": 1, "timestamp": -1 });
db.analytics.createIndex({ "timestamp": -1 });
```

### Query Optimization
- **Projection**: Fetch only required fields
- **Aggregation**: MongoDB aggregation pipelines for analytics
- **Connection Pooling**: Optimized database connections
- **Batch Operations**: Bulk inserts for analytics data

## Performance Metrics

### Target Performance
- **URL Creation**: <50ms average response time
- **Redirect Latency**: <20ms for cached URLs
- **Analytics Query**: <200ms for complex statistics
- **Throughput**: 10,000+ requests per second per instance

### Monitoring Metrics
- Request latency by endpoint
- Cache hit/miss ratios
- Database query performance
- Memory and CPU utilization
- Error rates and status codes

## Rate Limiting

### Endpoint-Specific Limits
```javascript
// General API endpoints
app.use('/api', rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100,                  // requests per window
  message: 'Too many requests'
}));

// URL creation endpoint (stricter)
app.use('/api/shorten', rateLimit({
  windowMs: 60 * 1000,      // 1 minute
  max: 10,                  // requests per window
  skipSuccessfulRequests: false
}));
```

### Advanced Rate Limiting
- **IP-based Limiting**: Per-IP request throttling
- **User-based Limiting**: Authenticated user quotas
- **Sliding Window**: More accurate rate limiting
- **Burst Allowance**: Short-term burst handling

## Security Features

### Input Validation
```javascript
// URL validation
function validateUrl(url) {
  const urlPattern = /^https?:\/\/[^\s/$.?#].[^\s]*$/i;
  const maliciousPatterns = [
    /javascript:/i,
    /data:/i,
    /vbscript:/i
  ];
  
  return urlPattern.test(url) && 
         !maliciousPatterns.some(pattern => pattern.test(url));
}
```

### Security Measures
- **URL Sanitization**: Prevention of malicious URL injection
- **XSS Protection**: Content Security Policy headers
- **HTTPS Enforcement**: Secure redirect handling
- **Abuse Detection**: Automatic suspicious pattern detection

## Analytics Implementation

### Real-time Tracking
```javascript
// Click tracking middleware
function trackClick(req, res, next) {
  const analyticsData = {
    shortCode: req.params.shortCode,
    timestamp: new Date(),
    ip: req.ip,
    userAgent: req.headers['user-agent'],
    referrer: req.headers.referer,
    // Additional tracking data...
  };
  
  // Async analytics recording
  analyticsQueue.add('record-click', analyticsData);
  next();
}
```

### Analytics Aggregation
- **Real-time Counters**: Redis-based click counting
- **Batch Processing**: Periodic aggregation jobs
- **Time-series Data**: Efficient time-based analytics
- **Geographic Processing**: IP-to-location mapping

## Testing

```bash
# Run unit tests
npm test

# Run integration tests
npm run test:integration

# Load testing
npm run test:load

# Analytics testing
npm run test:analytics

# Coverage report
npm run test:coverage
```

### Test Coverage
- URL creation and validation
- Redirect functionality
- Analytics tracking
- Rate limiting behavior
- Cache performance
- Error handling

## Deployment

### Docker Deployment
```bash
# Build production image
docker build -t url-shortener .

# Run with docker-compose
docker-compose up -d --scale app=3

# Health check
docker-compose exec app npm run health-check
```

### Production Checklist
- [ ] Configure environment variables
- [ ] Set up MongoDB replica set
- [ ] Configure Redis cluster
- [ ] Set up load balancer (Nginx/HAProxy)
- [ ] Configure SSL certificates
- [ ] Set up monitoring and alerting
- [ ] Configure log aggregation
- [ ] Set up backup strategy

## Monitoring & Alerting

### Key Metrics
- **Availability**: Service uptime percentage
- **Performance**: Response time percentiles
- **Errors**: Error rate by endpoint
- **Capacity**: Request volume and trends

### Alerting Rules
- Service availability < 99.9%
- Average response time > 100ms
- Error rate > 1%
- Cache hit rate < 90%
- Database connection failures

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.