const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const { createServer } = require('http');
const socketIo = require('socket.io');
require('dotenv').config();

const feedController = require('./controllers/feedController');
const socialGraphService = require('./services/socialGraphService');

const app = express();
const server = createServer(app);
const io = socketIo(server, {
  cors: {
    origin: process.env.CLIENT_URL || "http://localhost:3000",
    methods: ["GET", "POST"]
  }
});

const PORT = process.env.PORT || 4000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));
app.set('trust proxy', true);

// Rate limiting
const generalLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 1000, // limit each IP to 1000 requests per windowMs
  message: 'Too many requests from this IP',
  standardHeaders: true,
  legacyHeaders: false,
});

const postLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 10, // limit each IP to 10 posts per minute
  message: 'Too many posts created, please try again later.',
});

const followLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 30, // limit each IP to 30 follow actions per minute
  message: 'Too many follow/unfollow actions, please try again later.',
});

app.use(generalLimiter);

// Mock authentication middleware
app.use((req, res, next) => {
  // In a real system, you'd validate JWT tokens here
  const userId = req.headers['x-user-id'] || '507f1f77bcf86cd799439011';
  req.user = { id: userId };
  next();
});

// Database connection
mongoose.connect(process.env.MONGODB_URL || 'mongodb://localhost:27017/socialmedia', {
  useNewUrlParser: true,
  useUnifiedTopology: true,
})
.then(() => console.log('Connected to MongoDB'))
.catch(err => console.error('MongoDB connection error:', err));

// Socket.io for real-time features
io.on('connection', (socket) => {
  console.log('User connected:', socket.id);
  
  socket.on('join_user_room', (userId) => {
    socket.join(`user_${userId}`);
  });
  
  socket.on('new_post', (data) => {
    // Broadcast new post to followers
    socket.to(`user_${data.authorId}`).emit('post_update', data);
  });
  
  socket.on('disconnect', () => {
    console.log('User disconnected:', socket.id);
  });
});

// Routes
app.get('/', (req, res) => {
  res.json({
    service: 'Social Media Feed API',
    version: '1.0.0',
    endpoints: {
      'GET /api/feed': 'Get personalized feed',
      'GET /api/feed/trending': 'Get trending posts',
      'GET /api/feed/hashtag/:hashtag': 'Get hashtag feed',
      'GET /api/feed/user/:userId': 'Get user feed',
      'POST /api/posts': 'Create new post',
      'POST /api/posts/:postId/like': 'Like a post',
      'POST /api/posts/:postId/repost': 'Repost a post',
      'GET /api/posts/:postId/engagement': 'Get post engagement stats',
      'POST /api/social/follow/:userId': 'Follow a user',
      'DELETE /api/social/follow/:userId': 'Unfollow a user',
      'GET /api/social/followers/:userId': 'Get user followers',
      'GET /api/social/following/:userId': 'Get user following',
      'GET /api/social/suggestions': 'Get follow suggestions'
    }
  });
});

// Feed routes
app.get('/api/feed', feedController.getPersonalizedFeed);
app.get('/api/feed/trending', feedController.getTrendingFeed);
app.get('/api/feed/hashtag/:hashtag', feedController.getHashtagFeed);
app.get('/api/feed/user/:userId', feedController.getUserFeed);

// Post routes
app.post('/api/posts', postLimiter, feedController.createPost);
app.post('/api/posts/:postId/like', feedController.likePost);
app.post('/api/posts/:postId/repost', feedController.repost);
app.get('/api/posts/:postId/engagement', feedController.getPostEngagement);

// Social graph routes
app.post('/api/social/follow/:userId', followLimiter, async (req, res) => {
  try {
    const followerId = req.user.id;
    const followingId = req.params.userId;
    
    const follow = await socialGraphService.followUser(followerId, followingId);
    
    // Emit real-time notification
    io.to(`user_${followingId}`).emit('new_follower', {
      followerId,
      timestamp: new Date()
    });
    
    res.json({
      success: true,
      data: follow
    });
  } catch (error) {
    res.status(400).json({
      success: false,
      error: error.message
    });
  }
});

app.delete('/api/social/follow/:userId', followLimiter, async (req, res) => {
  try {
    const followerId = req.user.id;
    const followingId = req.params.userId;
    
    await socialGraphService.unfollowUser(followerId, followingId);
    
    res.json({
      success: true,
      message: 'Successfully unfollowed user'
    });
  } catch (error) {
    res.status(400).json({
      success: false,
      error: error.message
    });
  }
});

app.get('/api/social/followers/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    const { page = 1, limit = 20 } = req.query;
    
    const result = await socialGraphService.getFollowers(userId, parseInt(page), parseInt(limit));
    
    res.json({
      success: true,
      data: result
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to get followers'
    });
  }
});

app.get('/api/social/following/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    const { page = 1, limit = 20 } = req.query;
    
    const result = await socialGraphService.getFollowing(userId, parseInt(page), parseInt(limit));
    
    res.json({
      success: true,
      data: result
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to get following list'
    });
  }
});

app.get('/api/social/suggestions', async (req, res) => {
  try {
    const userId = req.user.id;
    const { limit = 10 } = req.query;
    
    const suggestions = await socialGraphService.getSuggestedConnections(userId, parseInt(limit));
    
    res.json({
      success: true,
      data: suggestions
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to get suggestions'
    });
  }
});

app.get('/api/social/mutual/:userId', async (req, res) => {
  try {
    const userId1 = req.user.id;
    const userId2 = req.params.userId;
    
    const mutual = await socialGraphService.getMutualConnections(userId1, userId2);
    
    res.json({
      success: true,
      data: mutual
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to get mutual connections'
    });
  }
});

app.get('/api/social/network-stats/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    
    const stats = await socialGraphService.getNetworkStats(userId);
    
    res.json({
      success: true,
      data: stats
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to get network stats'
    });
  }
});

// Health check
app.get('/api/health', async (req, res) => {
  try {
    const dbStatus = mongoose.connection.readyState === 1 ? 'connected' : 'disconnected';
    res.json({
      status: 'healthy',
      timestamp: new Date().toISOString(),
      database: dbStatus,
      uptime: process.uptime(),
      memory: process.memoryUsage(),
      activeConnections: io.engine.clientsCount
    });
  } catch (error) {
    res.status(500).json({
      status: 'unhealthy',
      error: error.message
    });
  }
});

// Error handling
app.use('*', (req, res) => {
  res.status(404).json({
    success: false,
    error: 'Endpoint not found'
  });
});

app.use((error, req, res, next) => {
  console.error(error);
  res.status(500).json({
    success: false,
    error: 'Internal server error'
  });
});

// Start server
server.listen(PORT, () => {
  console.log(`Social Media Feed service running on port ${PORT}`);
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  server.close(() => {
    mongoose.connection.close();
    process.exit(0);
  });
});

module.exports = { app, server, io };