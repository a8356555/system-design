const express = require('express');
const http = require('http');
const cors = require('cors');
const helmet = require('helmet');
const { RateLimiterRedis } = require('rate-limiter-flexible');
const Redis = require('redis');

const WebSocketManager = require('./services/WebSocketManager');
const authRoutes = require('./routes/auth');
const chatRoutes = require('./routes/chat');

class ChatServer {
  constructor() {
    this.app = express();
    this.server = http.createServer(this.app);
    this.port = process.env.PORT || 3000;
    
    this.setupMiddleware();
    this.setupRateLimiting();
    this.setupRoutes();
    this.setupWebSocket();
  }

  setupMiddleware() {
    this.app.use(helmet());
    this.app.use(cors({
      origin: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000'],
      credentials: true
    }));
    this.app.use(express.json({ limit: '10mb' }));
    this.app.use(express.urlencoded({ extended: true }));
  }

  async setupRateLimiting() {
    const redisClient = Redis.createClient({
      host: process.env.REDIS_HOST || 'localhost',
      port: process.env.REDIS_PORT || 6379
    });

    // Rate limiting for API endpoints
    this.rateLimiter = new RateLimiterRedis({
      storeClient: redisClient,
      keyPrefix: 'rl_api',
      points: 100, // Number of requests
      duration: 60, // Per 60 seconds
    });

    // Rate limiting for WebSocket messages
    this.wsRateLimiter = new RateLimiterRedis({
      storeClient: redisClient,
      keyPrefix: 'rl_ws',
      points: 50, // Number of messages
      duration: 60, // Per 60 seconds
    });

    this.app.use(async (req, res, next) => {
      try {
        await this.rateLimiter.consume(req.ip);
        next();
      } catch (rejRes) {
        res.status(429).json({
          error: 'Too many requests',
          retryAfter: rejRes.msBeforeNext
        });
      }
    });
  }

  setupRoutes() {
    this.app.use('/api/auth', authRoutes);
    this.app.use('/api/chat', chatRoutes);
    
    // Health check endpoint
    this.app.get('/health', (req, res) => {
      res.json({
        status: 'healthy',
        timestamp: new Date().toISOString(),
        connectedUsers: this.wsManager ? this.wsManager.getUserCount() : 0
      });
    });

    // Metrics endpoint
    this.app.get('/metrics', (req, res) => {
      res.json({
        connectedUsers: this.wsManager ? this.wsManager.getUserCount() : 0,
        uptime: process.uptime(),
        memory: process.memoryUsage(),
        cpu: process.cpuUsage()
      });
    });
  }

  setupWebSocket() {
    this.wsManager = new WebSocketManager(this.server);
  }

  start() {
    this.server.listen(this.port, () => {
      console.log(`Chat server listening on port ${this.port}`);
      console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
    });

    // Graceful shutdown
    process.on('SIGTERM', () => {
      console.log('SIGTERM received, shutting down gracefully');
      this.server.close(() => {
        console.log('Server closed');
        process.exit(0);
      });
    });
  }
}

// Start server if this file is run directly
if (require.main === module) {
  const server = new ChatServer();
  server.start();
}

module.exports = ChatServer;