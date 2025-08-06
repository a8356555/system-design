const Url = require('../models/urlModel');
const cacheService = require('./cacheService');

class RedirectService {
  constructor() {
    this.CLICK_THRESHOLD_FOR_HOT = 100; // Mark as hot URL after 100 clicks
  }

  async getOriginalUrl(shortCode) {
    let urlData = await cacheService.getUrlFromCache(shortCode);
    
    if (!urlData) {
      const urlDoc = await Url.findByShortCode(shortCode);
      
      if (!urlDoc) {
        return null;
      }
      
      urlData = {
        originalUrl: urlDoc.originalUrl,
        clickCount: urlDoc.clickCount,
        createdAt: urlDoc.createdAt,
        expiresAt: urlDoc.expiresAt
      };
      
      const isHotUrl = urlDoc.clickCount > this.CLICK_THRESHOLD_FOR_HOT;
      await cacheService.cacheUrl(shortCode, urlData, isHotUrl);
    }
    
    return urlData;
  }

  async performRedirect(shortCode, requestMetadata) {
    const urlData = await this.getOriginalUrl(shortCode);
    
    if (!urlData) {
      throw new Error('URL not found or expired');
    }
    
    if (new Date(urlData.expiresAt) < new Date()) {
      throw new Error('URL has expired');
    }
    
    this.trackClick(shortCode, requestMetadata);
    
    return urlData.originalUrl;
  }

  async trackClick(shortCode, metadata) {
    const analytics = {
      totalClicks: 1,
      [`clicks_${new Date().toISOString().slice(0, 10)}`]: 1 // Daily clicks
    };
    
    if (metadata.country) {
      analytics[`country_${metadata.country}`] = 1;
    }
    
    if (metadata.referrer) {
      const referrerDomain = this.extractDomain(metadata.referrer);
      if (referrerDomain) {
        analytics[`referrer_${referrerDomain}`] = 1;
      }
    }
    
    await cacheService.updateAnalytics(shortCode, analytics);
    
    try {
      await Url.findOneAndUpdate(
        { shortCode },
        { $inc: { clickCount: 1 } }
      );
      
      const currentCount = await this.getCurrentClickCount(shortCode);
      if (currentCount > this.CLICK_THRESHOLD_FOR_HOT) {
        await cacheService.markAsHotUrl(shortCode);
      }
    } catch (error) {
      console.error('Database update error:', error);
    }
  }

  async getCurrentClickCount(shortCode) {
    const analytics = await cacheService.getAnalytics(shortCode);
    return parseInt(analytics.totalClicks || '0');
  }

  extractDomain(url) {
    try {
      const urlObj = new URL(url);
      return urlObj.hostname;
    } catch {
      return null;
    }
  }

  async validateUrl(url) {
    const maliciousPatterns = [
      /malware/i,
      /phishing/i,
      /virus/i,
      /\.exe$/i
    ];
    
    return !maliciousPatterns.some(pattern => pattern.test(url));
  }

  async getBulkUrls(shortCodes) {
    const results = {};
    const uncachedCodes = [];
    
    for (const shortCode of shortCodes) {
      const cached = await cacheService.getUrlFromCache(shortCode);
      if (cached) {
        results[shortCode] = cached;
      } else {
        uncachedCodes.push(shortCode);
      }
    }
    
    if (uncachedCodes.length > 0) {
      const dbResults = await Url.find({ 
        shortCode: { $in: uncachedCodes },
        expiresAt: { $gt: new Date() }
      });
      
      for (const doc of dbResults) {
        const urlData = {
          originalUrl: doc.originalUrl,
          clickCount: doc.clickCount,
          createdAt: doc.createdAt,
          expiresAt: doc.expiresAt
        };
        
        results[doc.shortCode] = urlData;
        const isHotUrl = doc.clickCount > this.CLICK_THRESHOLD_FOR_HOT;
        await cacheService.cacheUrl(doc.shortCode, urlData, isHotUrl);
      }
    }
    
    return results;
  }
}

module.exports = new RedirectService();