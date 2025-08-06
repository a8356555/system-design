const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
require('dotenv').config();

const urlController = require('./controllers/urlController');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

app.set('trust proxy', true);

const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // limit each IP to 100 requests per windowMs
  message: 'Too many requests from this IP, please try again later.',
  standardHeaders: true,
  legacyHeaders: false,
});

const createLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 10, // limit each IP to 10 URL creations per minute
  message: 'Too many URL creations, please try again later.',
});

app.use('/api', limiter);
app.use('/api/shorten', createLimiter);

mongoose.connect(process.env.MONGODB_URL || 'mongodb://localhost:27017/urlshortener', {
  useNewUrlParser: true,
  useUnifiedTopology: true,
})
.then(() => console.log('Connected to MongoDB'))
.catch(err => console.error('MongoDB connection error:', err));

app.get('/', (req, res) => {
  res.json({
    service: 'URL Shortener API',
    version: '1.0.0',
    endpoints: {
      'POST /api/shorten': 'Create short URL',
      'GET /:shortCode': 'Redirect to original URL',
      'GET /api/analytics/:shortCode': 'Get URL analytics',
      'GET /api/info/:shortCode': 'Get URL information',
      'POST /api/bulk': 'Create multiple short URLs'
    },
    docs: '/api/docs'
  });
});

app.post('/api/shorten', urlController.createShortUrl);
app.post('/api/bulk', urlController.bulkCreate);
app.get('/api/analytics/:shortCode', urlController.getAnalytics);
app.get('/api/info/:shortCode', urlController.getUrlInfo);

app.get('/:shortCode', urlController.redirectUrl);

app.get('/api/health', async (req, res) => {
  try {
    const dbStatus = mongoose.connection.readyState === 1 ? 'connected' : 'disconnected';
    res.json({
      status: 'healthy',
      timestamp: new Date().toISOString(),
      database: dbStatus,
      uptime: process.uptime(),
      memory: process.memoryUsage()
    });
  } catch (error) {
    res.status(500).json({
      status: 'unhealthy',
      error: error.message
    });
  }
});

app.use('*', (req, res) => {
  res.status(404).json({ error: 'Endpoint not found' });
});

app.use((error, req, res, next) => {
  console.error(error);
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  console.log(`URL Shortener service running on port ${PORT}`);
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
});

process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  process.exit(0);
});

module.exports = app;