const Follow = require('../models/followModel');
const User = require('../models/userModel');
const redis = require('redis');

class SocialGraphService {
  constructor() {
    this.redisClient = redis.createClient({
      url: process.env.REDIS_URL || 'redis://localhost:6379'
    });
    this.redisClient.connect().catch(console.error);
    
    this.CACHE_TTL = 3600; // 1 hour
    this.GRAPH_CACHE_TTL = 7200; // 2 hours for relationship graphs
  }

  async followUser(followerId, followingId) {
    if (followerId === followingId) {
      throw new Error('Users cannot follow themselves');
    }
    
    const existingFollow = await Follow.isFollowing(followerId, followingId);
    if (existingFollow) {
      throw new Error('Already following this user');
    }
    
    const followingUser = await User.findById(followingId);
    if (!followingUser) {
      throw new Error('User to follow not found');
    }
    
    if (followingUser.settings.privacy === 'private') {
      // In a real system, this would create a follow request
      throw new Error('Follow request sent (private account)');
    }
    
    const follow = new Follow({
      followerId,
      followingId
    });
    
    await Promise.all([
      follow.save(),
      User.findByIdAndUpdate(followerId, { $inc: { followingCount: 1 } }),
      User.findByIdAndUpdate(followingId, { $inc: { followerCount: 1 } })
    ]);
    
    await this.invalidateUserGraphCache(followerId);
    await this.invalidateUserGraphCache(followingId);
    await this.updateFollowGraph(followerId, followingId, 'add');
    
    return follow;
  }

  async unfollowUser(followerId, followingId) {
    const follow = await Follow.findOneAndDelete({
      followerId,
      followingId
    });
    
    if (!follow) {
      throw new Error('Not following this user');
    }
    
    await Promise.all([
      User.findByIdAndUpdate(followerId, { $inc: { followingCount: -1 } }),
      User.findByIdAndUpdate(followingId, { $inc: { followerCount: -1 } })
    ]);
    
    await this.invalidateUserGraphCache(followerId);
    await this.invalidateUserGraphCache(followingId);
    await this.updateFollowGraph(followerId, followingId, 'remove');
    
    return true;
  }

  async getFollowers(userId, page = 1, limit = 20) {
    const cacheKey = `followers:${userId}:${page}:${limit}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const skip = (page - 1) * limit;
    const followers = await Follow.find({ followingId: userId })
      .populate('followerId', 'username displayName avatarUrl isVerified followerCount')
      .sort({ createdAt: -1 })
      .skip(skip)
      .limit(limit);
    
    const result = {
      followers: followers.map(f => f.followerId),
      pagination: {
        page,
        limit,
        hasMore: followers.length === limit
      }
    };
    
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(result));
    return result;
  }

  async getFollowing(userId, page = 1, limit = 20) {
    const cacheKey = `following:${userId}:${page}:${limit}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const skip = (page - 1) * limit;
    const following = await Follow.find({ followerId: userId })
      .populate('followingId', 'username displayName avatarUrl isVerified followerCount')
      .sort({ createdAt: -1 })
      .skip(skip)
      .limit(limit);
    
    const result = {
      following: following.map(f => f.followingId),
      pagination: {
        page,
        limit,
        hasMore: following.length === limit
      }
    };
    
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(result));
    return result;
  }

  async getMutualConnections(userId1, userId2) {
    const cacheKey = `mutual:${userId1}:${userId2}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const [user1Following, user2Following] = await Promise.all([
      this.getFollowingIds(userId1),
      this.getFollowingIds(userId2)
    ]);
    
    const mutualIds = user1Following.filter(id => 
      user2Following.includes(id.toString())
    );
    
    const mutualUsers = await User.find({
      _id: { $in: mutualIds }
    }).select('username displayName avatarUrl isVerified followerCount');
    
    const result = {
      count: mutualUsers.length,
      users: mutualUsers
    };
    
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(result));
    return result;
  }

  async getSuggestedConnections(userId, limit = 10) {
    const cacheKey = `suggestions:${userId}:${limit}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const [friendsOfFriends, popularUsers] = await Promise.all([
      this.getFriendsOfFriends(userId, Math.floor(limit * 0.7)),
      this.getPopularUsers(userId, Math.floor(limit * 0.3))
    ]);
    
    const combined = [...friendsOfFriends, ...popularUsers];
    const uniqueSuggestions = this.deduplicateUsers(combined);
    
    const suggestions = await this.scoreSuggestions(userId, uniqueSuggestions);
    
    const result = suggestions.slice(0, limit);
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(result));
    
    return result;
  }

  async getFriendsOfFriends(userId, limit) {
    const following = await this.getFollowingIds(userId);
    
    if (following.length === 0) return [];
    
    const friendsOfFriends = await Follow.aggregate([
      { $match: { followerId: { $in: following } } },
      { $group: { _id: '$followingId', mutualCount: { $sum: 1 } } },
      { $match: { _id: { $ne: userId } } },
      { $lookup: {
          from: 'follows',
          let: { suggestedId: '$_id' },
          pipeline: [
            { $match: {
              $expr: { $and: [
                { $eq: ['$followerId', userId] },
                { $eq: ['$followingId', '$$suggestedId'] }
              ]}
            }}
          ],
          as: 'alreadyFollowing'
        }
      },
      { $match: { alreadyFollowing: { $size: 0 } } },
      { $sort: { mutualCount: -1 } },
      { $limit: limit },
      { $lookup: {
          from: 'users',
          localField: '_id',
          foreignField: '_id',
          as: 'user'
        }
      },
      { $unwind: '$user' }
    ]);
    
    return friendsOfFriends.map(item => ({
      ...item.user,
      suggestionReason: 'mutual_connections',
      mutualCount: item.mutualCount
    }));
  }

  async getPopularUsers(userId, limit) {
    const following = await this.getFollowingIds(userId);
    
    const popularUsers = await User.find({
      _id: { $nin: [...following, userId] },
      followerCount: { $gte: 1000 },
      isActive: true
    })
    .sort({ followerCount: -1 })
    .limit(limit)
    .select('username displayName avatarUrl isVerified followerCount');
    
    return popularUsers.map(user => ({
      ...user.toObject(),
      suggestionReason: 'popular_user'
    }));
  }

  async scoreSuggestions(userId, suggestions) {
    const userPreferences = await this.getUserConnectionPreferences(userId);
    
    return suggestions
      .map(suggestion => ({
        ...suggestion,
        score: this.calculateSuggestionScore(suggestion, userPreferences)
      }))
      .sort((a, b) => b.score - a.score);
  }

  calculateSuggestionScore(suggestion, preferences) {
    let score = 0;
    
    // Mutual connections boost
    if (suggestion.mutualCount) {
      score += suggestion.mutualCount * 10;
    }
    
    // Follower count boost (but not too much for authenticity)
    score += Math.log10(suggestion.followerCount + 1) * 2;
    
    // Verified users get slight boost
    if (suggestion.isVerified) {
      score += 5;
    }
    
    // Activity boost
    if (suggestion.lastActiveAt) {
      const hoursActive = (Date.now() - suggestion.lastActiveAt.getTime()) / (1000 * 60 * 60);
      if (hoursActive < 24) score += 10;
      else if (hoursActive < 168) score += 5; // 1 week
    }
    
    return score;
  }

  async getUserConnectionPreferences(userId) {
    // In a real system, this would analyze user behavior
    return {
      preferredFollowerRange: [100, 10000],
      interests: []
    };
  }

  async getNetworkStats(userId) {
    const cacheKey = `network_stats:${userId}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const user = await User.findById(userId);
    if (!user) throw new Error('User not found');
    
    const [recentFollowers, followingGrowth] = await Promise.all([
      this.getRecentFollowers(userId, 7), // Last 7 days
      this.getFollowingGrowth(userId, 30) // Last 30 days
    ]);
    
    const stats = {
      totalFollowers: user.followerCount,
      totalFollowing: user.followingCount,
      recentFollowersCount: recentFollowers.length,
      followingGrowthRate: followingGrowth,
      engagementRate: await this.calculateEngagementRate(userId),
      networkReach: await this.calculateNetworkReach(userId)
    };
    
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(stats));
    return stats;
  }

  async getRecentFollowers(userId, days) {
    const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
    return await Follow.find({
      followingId: userId,
      createdAt: { $gte: since }
    });
  }

  async getFollowingGrowth(userId, days) {
    const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
    const recentFollows = await Follow.countDocuments({
      followerId: userId,
      createdAt: { $gte: since }
    });
    
    const user = await User.findById(userId);
    return recentFollows / Math.max(1, user.followingCount);
  }

  async calculateEngagementRate(userId) {
    // Simplified calculation - would need post engagement data
    return 0.05; // 5% placeholder
  }

  async calculateNetworkReach(userId) {
    const following = await this.getFollowingIds(userId);
    const totalReach = await User.aggregate([
      { $match: { _id: { $in: following } } },
      { $group: { _id: null, totalFollowers: { $sum: '$followerCount' } } }
    ]);
    
    return totalReach[0]?.totalFollowers || 0;
  }

  async getFollowingIds(userId) {
    const cacheKey = `following_ids:${userId}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached) {
      return JSON.parse(cached);
    }
    
    const follows = await Follow.find({ followerId: userId }).select('followingId');
    const ids = follows.map(f => f.followingId);
    
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, JSON.stringify(ids));
    return ids;
  }

  async updateFollowGraph(followerId, followingId, action) {
    const graphKey = `graph:${followerId}`;
    
    if (action === 'add') {
      await this.redisClient.sAdd(graphKey, followingId.toString());
    } else if (action === 'remove') {
      await this.redisClient.sRem(graphKey, followingId.toString());
    }
    
    await this.redisClient.expire(graphKey, this.GRAPH_CACHE_TTL);
  }

  async invalidateUserGraphCache(userId) {
    const patterns = [
      `followers:${userId}:*`,
      `following:${userId}:*`,
      `following_ids:${userId}`,
      `suggestions:${userId}:*`,
      `network_stats:${userId}`,
      `graph:${userId}`
    ];
    
    for (const pattern of patterns) {
      const keys = await this.redisClient.keys(pattern);
      if (keys.length > 0) {
        await this.redisClient.del(keys);
      }
    }
  }

  deduplicateUsers(users) {
    const seen = new Set();
    return users.filter(user => {
      const id = user._id.toString();
      if (seen.has(id)) {
        return false;
      }
      seen.add(id);
      return true;
    });
  }

  async isFollowing(followerId, followingId) {
    const cacheKey = `is_following:${followerId}:${followingId}`;
    const cached = await this.redisClient.get(cacheKey);
    
    if (cached !== null) {
      return cached === 'true';
    }
    
    const exists = await Follow.isFollowing(followerId, followingId);
    await this.redisClient.setEx(cacheKey, this.CACHE_TTL, exists ? 'true' : 'false');
    
    return !!exists;
  }

  async bulkCheckFollowing(userId, targetIds) {
    const results = {};
    
    for (const targetId of targetIds) {
      results[targetId] = await this.isFollowing(userId, targetId);
    }
    
    return results;
  }
}

module.exports = new SocialGraphService();