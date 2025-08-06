const Url = require('../models/urlModel');
const encodingService = require('../services/encodingService');
const redirectService = require('../services/redirectService');
const analyticsService = require('../services/analyticsService');
const cacheService = require('../services/cacheService');

class UrlController {
  async createShortUrl(req, res) {
    try {
      const { originalUrl, customAlias, expiresIn } = req.body;
      
      if (!encodingService.validateUrl(originalUrl)) {
        return res.status(400).json({ error: 'Invalid URL provided' });
      }
      
      if (!(await redirectService.validateUrl(originalUrl))) {
        return res.status(400).json({ error: 'URL appears to be malicious' });
      }
      
      const existingUrl = await Url.findOne({ originalUrl });
      if (existingUrl && !customAlias) {
        return res.json({
          shortCode: existingUrl.shortCode,
          shortUrl: `${process.env.BASE_URL || 'http://localhost:3000'}/${existingUrl.shortCode}`,
          originalUrl: existingUrl.originalUrl,
          createdAt: existingUrl.createdAt,
          expiresAt: existingUrl.expiresAt
        });
      }
      
      const shortCode = encodingService.generateShortCode(customAlias);
      
      if (customAlias) {
        const existing = await Url.findOne({ shortCode: customAlias });
        if (existing) {
          return res.status(409).json({ error: 'Custom alias already exists' });
        }
      }
      
      const expiresAt = expiresIn 
        ? new Date(Date.now() + expiresIn * 1000)
        : new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
      
      const url = new Url({
        shortCode,
        originalUrl,
        isCustom: !!customAlias,
        userId: req.user?.id || null,
        expiresAt,
        metadata: {
          userAgent: req.headers['user-agent'],
          ip: req.ip,
          referrer: req.headers.referer
        }
      });
      
      await url.save();
      
      const urlData = {
        originalUrl: url.originalUrl,
        clickCount: 0,
        createdAt: url.createdAt,
        expiresAt: url.expiresAt
      };
      await cacheService.cacheUrl(shortCode, urlData);
      
      res.status(201).json({
        shortCode,
        shortUrl: `${process.env.BASE_URL || 'http://localhost:3000'}/${shortCode}`,
        originalUrl,
        createdAt: url.createdAt,
        expiresAt: url.expiresAt,
        qrCode: `${process.env.BASE_URL || 'http://localhost:3000'}/qr/${shortCode}`
      });
      
    } catch (error) {
      console.error('Create URL error:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  }
  
  async redirectUrl(req, res) {
    try {
      const { shortCode } = req.params;
      
      const requestMetadata = {
        ip: req.ip,
        userAgent: req.headers['user-agent'],
        referrer: req.headers.referer || 'direct',
        timestamp: Date.now(),
        country: req.headers['cf-ipcountry'] || 'unknown',
        city: req.headers['cf-ipcity'] || 'unknown'
      };
      
      const originalUrl = await redirectService.performRedirect(shortCode, requestMetadata);
      
      await analyticsService.trackClick(shortCode, requestMetadata);
      
      res.redirect(301, originalUrl);
      
    } catch (error) {
      console.error('Redirect error:', error);
      
      if (error.message === 'URL not found or expired') {
        return res.status(404).json({ error: 'Short URL not found or has expired' });
      }
      
      res.status(500).json({ error: 'Internal server error' });
    }
  }
  
  async getAnalytics(req, res) {
    try {
      const { shortCode } = req.params;
      const { timeRange = '7d' } = req.query;
      
      const url = await Url.findOne({ shortCode });
      if (!url) {
        return res.status(404).json({ error: 'Short URL not found' });
      }
      
      if (req.user?.id && url.userId !== req.user.id) {
        return res.status(403).json({ error: 'Access denied' });
      }
      
      const analytics = await analyticsService.getAnalytics(shortCode, timeRange);
      
      res.json({
        shortCode,
        originalUrl: url.originalUrl,
        createdAt: url.createdAt,
        analytics
      });
      
    } catch (error) {
      console.error('Analytics error:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  }
  
  async getUrlInfo(req, res) {
    try {
      const { shortCode } = req.params;
      
      const url = await Url.findOne({ shortCode });
      if (!url) {
        return res.status(404).json({ error: 'Short URL not found' });
      }
      
      const analytics = await analyticsService.getAnalytics(shortCode, '1d');
      
      res.json({
        shortCode,
        originalUrl: url.originalUrl,
        createdAt: url.createdAt,
        expiresAt: url.expiresAt,
        clickCount: url.clickCount,
        isCustom: url.isCustom,
        recentClicks: analytics.timeSeries[0]?.clicks || 0,
        status: new Date(url.expiresAt) > new Date() ? 'active' : 'expired'
      });
      
    } catch (error) {
      console.error('URL info error:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  }
  
  async bulkCreate(req, res) {
    try {
      const { urls } = req.body;
      
      if (!Array.isArray(urls) || urls.length > 100) {
        return res.status(400).json({ error: 'Invalid request. Max 100 URLs per batch.' });
      }
      
      const results = [];
      const bulkOps = [];
      
      for (const urlData of urls) {
        if (!encodingService.validateUrl(urlData.originalUrl)) {
          results.push({
            originalUrl: urlData.originalUrl,
            error: 'Invalid URL'
          });
          continue;
        }
        
        const shortCode = encodingService.generateShortCode(urlData.customAlias);
        
        bulkOps.push({
          insertOne: {
            document: {
              shortCode,
              originalUrl: urlData.originalUrl,
              isCustom: !!urlData.customAlias,
              userId: req.user?.id || null,
              expiresAt: urlData.expiresIn 
                ? new Date(Date.now() + urlData.expiresIn * 1000)
                : new Date(Date.now() + 365 * 24 * 60 * 60 * 1000)
            }
          }
        });
        
        results.push({
          originalUrl: urlData.originalUrl,
          shortCode,
          shortUrl: `${process.env.BASE_URL || 'http://localhost:3000'}/${shortCode}`
        });
      }
      
      if (bulkOps.length > 0) {
        await Url.bulkWrite(bulkOps);
      }
      
      res.json({ results });
      
    } catch (error) {
      console.error('Bulk create error:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  }
}

module.exports = new UrlController();