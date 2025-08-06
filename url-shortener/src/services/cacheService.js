const redis = require('redis');

class CacheService {
  constructor() {
    this.client = redis.createClient({
      url: process.env.REDIS_URL || 'redis://localhost:6379'
    });
    this.client.connect().catch(console.error);
    
    this.DEFAULT_TTL = 3600; // 1 hour
    this.HOT_URL_TTL = 86400; // 24 hours for frequently accessed URLs
  }

  async get(key) {
    try {
      const value = await this.client.get(key);
      return value ? JSON.parse(value) : null;
    } catch (error) {
      console.error('Cache get error:', error);
      return null;
    }
  }

  async set(key, value, ttl = this.DEFAULT_TTL) {
    try {
      await this.client.setEx(key, ttl, JSON.stringify(value));
      return true;
    } catch (error) {
      console.error('Cache set error:', error);
      return false;
    }
  }

  async del(key) {
    try {
      await this.client.del(key);
      return true;
    } catch (error) {
      console.error('Cache delete error:', error);
      return false;
    }
  }

  async increment(key, field = 'count') {
    try {
      return await this.client.hIncrBy(key, field, 1);
    } catch (error) {
      console.error('Cache increment error:', error);
      return 0;
    }
  }

  async getUrlFromCache(shortCode) {
    const cacheKey = `url:${shortCode}`;
    const cachedUrl = await this.get(cacheKey);
    
    if (cachedUrl) {
      await this.increment(`stats:${shortCode}`, 'cacheHits');
      return cachedUrl;
    }
    
    return null;
  }

  async cacheUrl(shortCode, urlData, isHotUrl = false) {
    const cacheKey = `url:${shortCode}`;
    const ttl = isHotUrl ? this.HOT_URL_TTL : this.DEFAULT_TTL;
    
    await this.set(cacheKey, urlData, ttl);
    
    if (isHotUrl) {
      await this.client.sAdd('hot_urls', shortCode);
    }
  }

  async markAsHotUrl(shortCode) {
    const cacheKey = `url:${shortCode}`;
    const urlData = await this.get(cacheKey);
    
    if (urlData) {
      await this.cacheUrl(shortCode, urlData, true);
    }
  }

  async getAnalytics(shortCode) {
    const statsKey = `stats:${shortCode}`;
    return await this.client.hGetAll(statsKey);
  }

  async updateAnalytics(shortCode, analytics) {
    const statsKey = `stats:${shortCode}`;
    const pipeline = this.client.multi();
    
    Object.entries(analytics).forEach(([key, value]) => {
      pipeline.hIncrBy(statsKey, key, value);
    });
    
    await pipeline.exec();
  }

  async cleanup() {
    await this.client.quit();
  }
}

module.exports = new CacheService();