const cacheService = require('./cacheService');
const Url = require('../models/urlModel');

class AnalyticsService {
  constructor() {
    this.BATCH_SIZE = 100;
    this.FLUSH_INTERVAL = 60000; // 1 minute
    this.pendingAnalytics = new Map();
    
    this.startBatchProcessor();
  }

  async trackClick(shortCode, metadata) {
    const timestamp = Date.now();
    const dateKey = new Date().toISOString().slice(0, 10);
    const hourKey = new Date().toISOString().slice(0, 13);
    
    const analyticsData = {
      timestamp,
      shortCode,
      ip: metadata.ip,
      userAgent: metadata.userAgent,
      referrer: metadata.referrer,
      country: metadata.country || 'unknown',
      city: metadata.city || 'unknown',
      device: this.detectDevice(metadata.userAgent),
      browser: this.detectBrowser(metadata.userAgent)
    };
    
    await this.batchAnalytics(shortCode, analyticsData);
    await this.updateRealTimeMetrics(shortCode, dateKey, hourKey, analyticsData);
  }

  async batchAnalytics(shortCode, data) {
    if (!this.pendingAnalytics.has(shortCode)) {
      this.pendingAnalytics.set(shortCode, []);
    }
    
    this.pendingAnalytics.get(shortCode).push(data);
    
    if (this.pendingAnalytics.get(shortCode).length >= this.BATCH_SIZE) {
      await this.flushAnalytics(shortCode);
    }
  }

  async updateRealTimeMetrics(shortCode, dateKey, hourKey, data) {
    const pipeline = [
      // Daily metrics
      { key: `daily:${shortCode}:${dateKey}`, field: 'total', increment: 1 },
      { key: `daily:${shortCode}:${dateKey}`, field: `country_${data.country}`, increment: 1 },
      { key: `daily:${shortCode}:${dateKey}`, field: `device_${data.device}`, increment: 1 },
      
      // Hourly metrics
      { key: `hourly:${shortCode}:${hourKey}`, field: 'total', increment: 1 },
      
      // Overall metrics
      { key: `stats:${shortCode}`, field: 'totalClicks', increment: 1 },
      { key: `stats:${shortCode}`, field: `country_${data.country}`, increment: 1 },
      { key: `stats:${shortCode}`, field: `device_${data.device}`, increment: 1 },
      { key: `stats:${shortCode}`, field: `browser_${data.browser}`, increment: 1 }
    ];
    
    if (data.referrer && data.referrer !== 'direct') {
      const referrerDomain = this.extractDomain(data.referrer);
      if (referrerDomain) {
        pipeline.push(
          { key: `daily:${shortCode}:${dateKey}`, field: `referrer_${referrerDomain}`, increment: 1 },
          { key: `stats:${shortCode}`, field: `referrer_${referrerDomain}`, increment: 1 }
        );
      }
    }
    
    for (const update of pipeline) {
      await cacheService.increment(update.key, update.field);
    }
  }

  async getAnalytics(shortCode, timeRange = '7d') {
    const stats = await cacheService.getAnalytics(shortCode);
    const timeSeriesData = await this.getTimeSeriesData(shortCode, timeRange);
    
    return {
      totalClicks: parseInt(stats.totalClicks || '0'),
      uniqueVisitors: await this.getUniqueVisitors(shortCode, timeRange),
      countries: this.extractMetricsByPrefix(stats, 'country_'),
      referrers: this.extractMetricsByPrefix(stats, 'referrer_'),
      devices: this.extractMetricsByPrefix(stats, 'device_'),
      browsers: this.extractMetricsByPrefix(stats, 'browser_'),
      timeSeries: timeSeriesData,
      topHours: await this.getTopHours(shortCode),
      clickThroughRate: await this.calculateClickThroughRate(shortCode)
    };
  }

  async getTimeSeriesData(shortCode, timeRange) {
    const days = this.parseDays(timeRange);
    const data = [];
    
    for (let i = days - 1; i >= 0; i--) {
      const date = new Date();
      date.setDate(date.getDate() - i);
      const dateKey = date.toISOString().slice(0, 10);
      
      const dailyStats = await cacheService.client.hGetAll(`daily:${shortCode}:${dateKey}`);
      data.push({
        date: dateKey,
        clicks: parseInt(dailyStats.total || '0'),
        countries: this.extractMetricsByPrefix(dailyStats, 'country_'),
        devices: this.extractMetricsByPrefix(dailyStats, 'device_'),
        referrers: this.extractMetricsByPrefix(dailyStats, 'referrer_')
      });
    }
    
    return data;
  }

  async getUniqueVisitors(shortCode, timeRange) {
    const uniqueKey = `unique:${shortCode}:${timeRange}`;
    return await cacheService.client.pfCount(uniqueKey) || 0;
  }

  async getTopHours(shortCode) {
    const hours = [];
    const now = new Date();
    
    for (let i = 23; i >= 0; i--) {
      const hour = new Date(now.getTime() - (i * 60 * 60 * 1000));
      const hourKey = hour.toISOString().slice(0, 13);
      
      const hourlyStats = await cacheService.client.hGetAll(`hourly:${shortCode}:${hourKey}`);
      hours.push({
        hour: hourKey,
        clicks: parseInt(hourlyStats.total || '0')
      });
    }
    
    return hours.sort((a, b) => b.clicks - a.clicks).slice(0, 5);
  }

  async calculateClickThroughRate(shortCode) {
    const stats = await cacheService.getAnalytics(shortCode);
    const impressions = parseInt(stats.impressions || '0');
    const clicks = parseInt(stats.totalClicks || '0');
    
    return impressions > 0 ? (clicks / impressions * 100).toFixed(2) : 0;
  }

  async flushAnalytics(shortCode) {
    const analytics = this.pendingAnalytics.get(shortCode);
    if (!analytics || analytics.length === 0) return;
    
    try {
      const bulkOps = analytics.map(data => ({
        insertOne: {
          document: {
            shortCode: data.shortCode,
            timestamp: new Date(data.timestamp),
            ip: data.ip,
            userAgent: data.userAgent,
            referrer: data.referrer,
            country: data.country,
            city: data.city,
            device: data.device,
            browser: data.browser
          }
        }
      }));
      
      // In a real implementation, you'd write to a time-series database
      // For demo purposes, we'll just log the batch
      console.log(`Flushing ${analytics.length} analytics records for ${shortCode}`);
      
      // Add unique visitors to HyperLogLog
      for (const data of analytics) {
        const uniqueKey = `unique:${shortCode}:7d`;
        await cacheService.client.pfAdd(uniqueKey, data.ip);
      }
      
      this.pendingAnalytics.set(shortCode, []);
    } catch (error) {
      console.error('Failed to flush analytics:', error);
    }
  }

  startBatchProcessor() {
    setInterval(async () => {
      for (const shortCode of this.pendingAnalytics.keys()) {
        await this.flushAnalytics(shortCode);
      }
    }, this.FLUSH_INTERVAL);
  }

  detectDevice(userAgent) {
    if (!userAgent) return 'unknown';
    
    const ua = userAgent.toLowerCase();
    if (ua.includes('mobile')) return 'mobile';
    if (ua.includes('tablet')) return 'tablet';
    return 'desktop';
  }

  detectBrowser(userAgent) {
    if (!userAgent) return 'unknown';
    
    const ua = userAgent.toLowerCase();
    if (ua.includes('chrome')) return 'chrome';
    if (ua.includes('firefox')) return 'firefox';
    if (ua.includes('safari')) return 'safari';
    if (ua.includes('edge')) return 'edge';
    return 'other';
  }

  extractDomain(url) {
    try {
      const urlObj = new URL(url);
      return urlObj.hostname;
    } catch {
      return null;
    }
  }

  extractMetricsByPrefix(stats, prefix) {
    const result = {};
    Object.entries(stats).forEach(([key, value]) => {
      if (key.startsWith(prefix)) {
        const metric = key.substring(prefix.length);
        result[metric] = parseInt(value);
      }
    });
    return result;
  }

  parseDays(timeRange) {
    const match = timeRange.match(/(\d+)d/);
    return match ? parseInt(match[1]) : 7;
  }
}

module.exports = new AnalyticsService();