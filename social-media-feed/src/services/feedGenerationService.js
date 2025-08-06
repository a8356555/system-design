const Post = require('../models/postModel');
const Follow = require('../models/followModel');
const User = require('../models/userModel');
const Bull = require('bull');
const redis = require('redis');

class FeedGenerationService {
  constructor() {
    this.redisClient = redis.createClient({
      url: process.env.REDIS_URL || 'redis://localhost:6379'
    });
    this.redisClient.connect().catch(console.error);
    
    this.feedQueue = new Bull('feed generation', process.env.REDIS_URL || 'redis://localhost:6379');
    this.setupQueueProcessors();
    
    this.CELEBRITY_THRESHOLD = 10000; // Users with >10k followers are celebrities
    this.ACTIVE_USER_THRESHOLD = 1000; // Users with <1k followers are regular users
    this.FEED_CACHE_TTL = 300; // 5 minutes
    this.HOT_FEED_TTL = 60; // 1 minute for trending content
  }

  async generateFeed(userId, page = 1, limit = 20) {
    const user = await User.findById(userId);
    if (!user) throw new Error('User not found');
    
    const cacheKey = `feed:${userId}:${page}:${limit}`;
    const cachedFeed = await this.redisClient.get(cacheKey);
    
    if (cachedFeed) {
      return JSON.parse(cachedFeed);
    }
    
    const followingIds = await this.getFollowingIds(userId);
    
    let feed;
    if (followingIds.length === 0) {
      feed = await this.generateDiscoveryFeed(userId, limit);
    } else {
      feed = await this.generatePersonalizedFeed(userId, followingIds, page, limit);
    }
    
    await this.cacheFeed(cacheKey, feed, this.FEED_CACHE_TTL);
    
    return feed;
  }

  async generatePersonalizedFeed(userId, followingIds, page, limit) {
    const skip = (page - 1) * limit;
    
    const [timelinePosts, trendingPosts] = await Promise.all([
      this.getTimelinePosts(followingIds, skip, Math.floor(limit * 0.8)),
      this.getTrendingPosts(Math.floor(limit * 0.2))
    ]);
    
    const combinedPosts = this.mergePosts(timelinePosts, trendingPosts);
    const rankedPosts = await this.rankPosts(combinedPosts, userId);
    
    return this.formatFeedResponse(rankedPosts, page, limit);
  }

  async generateDiscoveryFeed(userId, limit) {
    const [trendingPosts, popularUsers] = await Promise.all([
      this.getTrendingPosts(Math.floor(limit * 0.7)),
      this.getPopularUsersPosts(Math.floor(limit * 0.3))
    ]);
    
    const combinedPosts = this.mergePosts(trendingPosts, popularUsers);
    const rankedPosts = await this.rankPosts(combinedPosts, userId);
    
    return this.formatFeedResponse(rankedPosts, 1, limit);
  }

  async handleNewPost(postId, authorId) {
    const post = await Post.findById(postId).populate('authorId');
    if (!post) return;
    
    const author = post.authorId;
    const isCelebrity = author.followerCount > this.CELEBRITY_THRESHOLD;
    
    if (isCelebrity) {
      await this.handleCelebrityPost(post);
    } else {
      await this.handleRegularPost(post, authorId);
    }
  }

  async handleCelebrityPost(post) {
    const jobData = {
      type: 'celebrity_post',
      postId: post._id,
      authorId: post.authorId._id
    };
    
    await this.feedQueue.add('process_celebrity_post', jobData, {
      priority: 10,
      delay: 0
    });
  }

  async handleRegularPost(post, authorId) {
    const followers = await this.getActiveFollowers(authorId);
    
    const batchSize = 1000;
    for (let i = 0; i < followers.length; i += batchSize) {
      const batch = followers.slice(i, i + batchSize);
      
      await this.feedQueue.add('push_to_followers', {
        postId: post._id,
        followers: batch.map(f => f.followerId)
      }, {
        priority: 5,
        delay: 0
      });
    }
  }

  async getTimelinePosts(followingIds, skip, limit) {
    return await Post.find({
      authorId: { $in: followingIds }
    })
    .populate('authorId', 'username displayName avatarUrl isVerified')
    .sort({ createdAt: -1 })
    .skip(skip)
    .limit(limit);
  }

  async getTrendingPosts(limit) {
    const cacheKey = 'trending:posts';
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const trending = await Post.findTrendingPosts(limit);
    await this.redisClient.setEx(cacheKey, this.HOT_FEED_TTL, JSON.stringify(trending));
    
    return trending;
  }

  async getPopularUsersPosts(limit) {
    const popularUsers = await User.find({ followerCount: { $gte: 1000 } })
      .sort({ followerCount: -1 })
      .limit(50);
    
    const userIds = popularUsers.map(u => u._id);
    
    return await Post.find({ authorId: { $in: userIds } })
      .populate('authorId', 'username displayName avatarUrl isVerified')
      .sort({ engagementScore: -1 })
      .limit(limit);
  }

  async rankPosts(posts, userId) {
    const userPreferences = await this.getUserPreferences(userId);
    
    return posts
      .map(post => ({
        ...post.toObject(),
        personalizedScore: this.calculatePersonalizedScore(post, userPreferences)
      }))
      .sort((a, b) => b.personalizedScore - a.personalizedScore);
  }

  calculatePersonalizedScore(post, preferences) {
    let score = post.engagementScore;
    
    const ageHours = (Date.now() - post.createdAt.getTime()) / (1000 * 60 * 60);
    const recencyBoost = Math.max(0, 24 - ageHours) / 24;
    score += recencyBoost * 10;
    
    if (post.authorId.isVerified) {
      score += 5;
    }
    
    if (post.hashtags && preferences.interests) {
      const hashtagBoost = post.hashtags.filter(tag => 
        preferences.interests.includes(tag)
      ).length * 3;
      score += hashtagBoost;
    }
    
    const engagementRate = (post.likeCount + post.commentCount) / 
                          Math.max(1, post.authorId.followerCount);
    score += engagementRate * 100;
    
    return score;
  }

  async getUserPreferences(userId) {
    const cacheKey = `preferences:${userId}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const recentInteractions = await this.getRecentUserInteractions(userId);
    const interests = this.extractInterests(recentInteractions);
    
    const preferences = { interests };
    await this.redisClient.setEx(cacheKey, 3600, JSON.stringify(preferences));
    
    return preferences;
  }

  async getRecentUserInteractions(userId) {
    // Implementation would track user likes, comments, shares
    return [];
  }

  extractInterests(interactions) {
    // Implementation would analyze hashtags, mentions, etc.
    return [];
  }

  mergePosts(timelinePosts, trendingPosts) {
    const postsMap = new Map();
    
    [...timelinePosts, ...trendingPosts].forEach(post => {
      const id = post._id.toString();
      if (!postsMap.has(id)) {
        postsMap.set(id, post);
      }
    });
    
    return Array.from(postsMap.values());
  }

  formatFeedResponse(posts, page, limit) {
    return {
      posts,
      pagination: {
        page,
        limit,
        hasMore: posts.length === limit
      },
      metadata: {
        generatedAt: new Date().toISOString(),
        algorithm: 'personalized_ranking_v2'
      }
    };
  }

  async getFollowingIds(userId) {
    const follows = await Follow.getFollowingIds(userId);
    return follows.map(f => f.followingId);
  }

  async getActiveFollowers(userId) {
    return await Follow.find({ followingId: userId })
      .populate({
        path: 'followerId',
        match: { 
          isActive: true,
          lastActiveAt: { $gte: new Date(Date.now() - 24 * 60 * 60 * 1000) }
        }
      })
      .select('followerId');
  }

  async cacheFeed(key, feed, ttl) {
    await this.redisClient.setEx(key, ttl, JSON.stringify(feed));
  }

  async invalidateUserFeed(userId) {
    const pattern = `feed:${userId}:*`;
    const keys = await this.redisClient.keys(pattern);
    if (keys.length > 0) {
      await this.redisClient.del(keys);
    }
  }

  setupQueueProcessors() {
    this.feedQueue.process('push_to_followers', 10, async (job) => {
      const { postId, followers } = job.data;
      
      for (const followerId of followers) {
        await this.addPostToUserFeed(followerId, postId);
      }
    });
    
    this.feedQueue.process('process_celebrity_post', 5, async (job) => {
      const { postId, authorId } = job.data;
      
      await this.addToTrendingFeed(postId);
      await this.invalidateGlobalFeedCaches();
    });
  }

  async addPostToUserFeed(userId, postId) {
    const feedKey = `user_feed:${userId}`;
    await this.redisClient.lPush(feedKey, postId.toString());
    await this.redisClient.lTrim(feedKey, 0, 999); // Keep last 1000 posts
    await this.redisClient.expire(feedKey, 86400); // 24 hour TTL
  }

  async addToTrendingFeed(postId) {
    const trendingKey = 'trending:posts';
    await this.redisClient.del(trendingKey); // Invalidate trending cache
  }

  async invalidateGlobalFeedCaches() {
    const patterns = ['feed:*', 'trending:*'];
    
    for (const pattern of patterns) {
      const keys = await this.redisClient.keys(pattern);
      if (keys.length > 0) {
        await this.redisClient.del(keys);
      }
    }
  }
}

module.exports = new FeedGenerationService();