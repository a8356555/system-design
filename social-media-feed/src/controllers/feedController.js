const feedGenerationService = require('../services/feedGenerationService');
const socialGraphService = require('../services/socialGraphService');
const Post = require('../models/postModel');
const User = require('../models/userModel');

class FeedController {
  async getPersonalizedFeed(req, res) {
    try {
      const userId = req.user.id;
      const { page = 1, limit = 20, refresh = false } = req.query;
      
      const parsedPage = Math.max(1, parseInt(page));
      const parsedLimit = Math.min(50, Math.max(1, parseInt(limit)));
      
      if (refresh === 'true') {
        await feedGenerationService.invalidateUserFeed(userId);
      }
      
      const feed = await feedGenerationService.generateFeed(
        userId, 
        parsedPage, 
        parsedLimit
      );
      
      await User.findByIdAndUpdate(userId, { lastActiveAt: new Date() });
      
      res.json({
        success: true,
        data: feed
      });
      
    } catch (error) {
      console.error('Feed generation error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to generate feed'
      });
    }
  }
  
  async getTrendingFeed(req, res) {
    try {
      const { limit = 20 } = req.query;
      const parsedLimit = Math.min(50, Math.max(1, parseInt(limit)));
      
      const trendingPosts = await Post.findTrendingPosts(parsedLimit);
      
      res.json({
        success: true,
        data: {
          posts: trendingPosts,
          metadata: {
            type: 'trending',
            generatedAt: new Date().toISOString()
          }
        }
      });
      
    } catch (error) {
      console.error('Trending feed error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to get trending feed'
      });
    }
  }
  
  async getHashtagFeed(req, res) {
    try {
      const { hashtag } = req.params;
      const { limit = 20 } = req.query;
      
      if (!hashtag) {
        return res.status(400).json({
          success: false,
          error: 'Hashtag is required'
        });
      }
      
      const parsedLimit = Math.min(100, Math.max(1, parseInt(limit)));
      
      const posts = await Post.findByHashtag(hashtag, parsedLimit);
      
      res.json({
        success: true,
        data: {
          hashtag: hashtag.toLowerCase(),
          posts,
          count: posts.length,
          metadata: {
            type: 'hashtag_feed',
            generatedAt: new Date().toISOString()
          }
        }
      });
      
    } catch (error) {
      console.error('Hashtag feed error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to get hashtag feed'
      });
    }
  }
  
  async getUserFeed(req, res) {
    try {
      const { userId } = req.params;
      const { page = 1, limit = 20 } = req.query;
      
      const parsedPage = Math.max(1, parseInt(page));
      const parsedLimit = Math.min(50, Math.max(1, parseInt(limit)));
      
      const user = await User.findById(userId)
        .select('username displayName avatarUrl isVerified followerCount followingCount postCount');
      
      if (!user) {
        return res.status(404).json({
          success: false,
          error: 'User not found'
        });
      }
      
      const skip = (parsedPage - 1) * parsedLimit;
      const posts = await Post.find({ authorId: userId })
        .populate('authorId', 'username displayName avatarUrl isVerified')
        .sort({ createdAt: -1 })
        .skip(skip)
        .limit(parsedLimit);
      
      let isFollowing = false;
      if (req.user && req.user.id !== userId) {
        isFollowing = await socialGraphService.isFollowing(req.user.id, userId);
      }
      
      res.json({
        success: true,
        data: {
          user: {
            ...user.toObject(),
            isFollowing
          },
          posts,
          pagination: {
            page: parsedPage,
            limit: parsedLimit,
            hasMore: posts.length === parsedLimit
          }
        }
      });
      
    } catch (error) {
      console.error('User feed error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to get user feed'
      });
    }
  }
  
  async createPost(req, res) {
    try {
      const { content, mediaUrls = [], hashtags = [] } = req.body;
      const authorId = req.user.id;
      
      if (!content || content.trim().length === 0) {
        return res.status(400).json({
          success: false,
          error: 'Post content is required'
        });
      }
      
      if (content.length > 280) {
        return res.status(400).json({
          success: false,
          error: 'Post content exceeds maximum length'
        });
      }
      
      const extractedHashtags = this.extractHashtags(content);
      const allHashtags = [...new Set([...hashtags, ...extractedHashtags])];
      
      const mentions = this.extractMentions(content);
      
      const post = new Post({
        authorId,
        content: content.trim(),
        mediaUrls,
        hashtags: allHashtags,
        mentions
      });
      
      await post.save();
      await User.findByIdAndUpdate(authorId, { $inc: { postCount: 1 } });
      
      const populatedPost = await Post.findById(post._id)
        .populate('authorId', 'username displayName avatarUrl isVerified');
      
      // Trigger feed updates asynchronously
      setImmediate(() => {
        feedGenerationService.handleNewPost(post._id, authorId);
      });
      
      res.status(201).json({
        success: true,
        data: populatedPost
      });
      
    } catch (error) {
      console.error('Create post error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to create post'
      });
    }
  }
  
  async likePost(req, res) {
    try {
      const { postId } = req.params;
      const userId = req.user.id;
      
      const post = await Post.findById(postId);
      if (!post) {
        return res.status(404).json({
          success: false,
          error: 'Post not found'
        });
      }
      
      await post.incrementLikes();
      
      // In a real system, you'd also track which users liked the post
      // to prevent duplicate likes and enable unlike functionality
      
      res.json({
        success: true,
        data: {
          postId,
          likeCount: post.likeCount
        }
      });
      
    } catch (error) {
      console.error('Like post error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to like post'
      });
    }
  }
  
  async repost(req, res) {
    try {
      const { postId } = req.params;
      const { comment = '' } = req.body;
      const userId = req.user.id;
      
      const originalPost = await Post.findById(postId);
      if (!originalPost) {
        return res.status(404).json({
          success: false,
          error: 'Original post not found'
        });
      }
      
      const repost = new Post({
        authorId: userId,
        content: comment,
        isRepost: true,
        originalPostId: postId
      });
      
      await Promise.all([
        repost.save(),
        originalPost.incrementShares(),
        User.findByIdAndUpdate(userId, { $inc: { postCount: 1 } })
      ]);
      
      const populatedRepost = await Post.findById(repost._id)
        .populate('authorId', 'username displayName avatarUrl isVerified')
        .populate('originalPostId');
      
      // Trigger feed updates
      setImmediate(() => {
        feedGenerationService.handleNewPost(repost._id, userId);
      });
      
      res.status(201).json({
        success: true,
        data: populatedRepost
      });
      
    } catch (error) {
      console.error('Repost error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to repost'
      });
    }
  }
  
  async getPostEngagement(req, res) {
    try {
      const { postId } = req.params;
      
      const post = await Post.findById(postId)
        .select('likeCount commentCount shareCount engagementScore createdAt');
      
      if (!post) {
        return res.status(404).json({
          success: false,
          error: 'Post not found'
        });
      }
      
      const ageHours = (Date.now() - post.createdAt.getTime()) / (1000 * 60 * 60);
      
      res.json({
        success: true,
        data: {
          postId,
          engagement: {
            likes: post.likeCount,
            comments: post.commentCount,
            shares: post.shareCount,
            engagementScore: post.engagementScore,
            ageHours: Math.round(ageHours * 100) / 100
          }
        }
      });
      
    } catch (error) {
      console.error('Post engagement error:', error);
      res.status(500).json({
        success: false,
        error: 'Failed to get post engagement'
      });
    }
  }
  
  extractHashtags(content) {
    const hashtagRegex = /#[\w\u0590-\u05ff]+/g;
    const matches = content.match(hashtagRegex);
    return matches ? matches.map(tag => tag.slice(1).toLowerCase()) : [];
  }
  
  extractMentions(content) {
    const mentionRegex = /@(\w+)/g;
    const matches = [];
    let match;
    
    while ((match = mentionRegex.exec(content)) !== null) {
      matches.push({
        username: match[1],
        userId: null // In a real system, you'd resolve usernames to user IDs
      });
    }
    
    return matches;
  }
}

module.exports = new FeedController();