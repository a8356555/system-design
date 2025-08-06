const mongoose = require('mongoose');

const postSchema = new mongoose.Schema({
  authorId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
    index: true
  },
  content: {
    type: String,
    required: true,
    maxlength: 280
  },
  mediaUrls: [{
    type: String,
    url: String,
    mediaType: {
      type: String,
      enum: ['image', 'video', 'gif']
    }
  }],
  hashtags: [{
    type: String,
    lowercase: true
  }],
  mentions: [{
    userId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'User'
    },
    username: String
  }],
  likeCount: {
    type: Number,
    default: 0
  },
  commentCount: {
    type: Number,
    default: 0
  },
  shareCount: {
    type: Number,
    default: 0
  },
  engagementScore: {
    type: Number,
    default: 0
  },
  isRepost: {
    type: Boolean,
    default: false
  },
  originalPostId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Post'
  },
  createdAt: {
    type: Date,
    default: Date.now
  },
  updatedAt: {
    type: Date,
    default: Date.now
  }
});

postSchema.index({ authorId: 1, createdAt: -1 });
postSchema.index({ createdAt: -1 });
postSchema.index({ hashtags: 1 });
postSchema.index({ engagementScore: -1, createdAt: -1 });
postSchema.index({ 'mentions.userId': 1 });

postSchema.pre('save', function(next) {
  this.updatedAt = new Date();
  
  this.engagementScore = this.calculateEngagementScore();
  next();
});

postSchema.methods.calculateEngagementScore = function() {
  const ageInHours = (Date.now() - this.createdAt.getTime()) / (1000 * 60 * 60);
  const baseScore = (this.likeCount * 1) + (this.commentCount * 2) + (this.shareCount * 3);
  
  const timeDecay = Math.exp(-ageInHours / 24);
  
  return baseScore * timeDecay;
};

postSchema.methods.incrementLikes = function() {
  this.likeCount++;
  this.engagementScore = this.calculateEngagementScore();
  return this.save();
};

postSchema.methods.incrementComments = function() {
  this.commentCount++;
  this.engagementScore = this.calculateEngagementScore();
  return this.save();
};

postSchema.methods.incrementShares = function() {
  this.shareCount++;
  this.engagementScore = this.calculateEngagementScore();
  return this.save();
};

postSchema.statics.findTrendingPosts = function(limit = 50) {
  const oneWeekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  return this.find({ 
    createdAt: { $gte: oneWeekAgo },
    engagementScore: { $gte: 10 }
  })
  .sort({ engagementScore: -1 })
  .limit(limit);
};

postSchema.statics.findByHashtag = function(hashtag, limit = 100) {
  return this.find({ hashtags: hashtag.toLowerCase() })
    .sort({ createdAt: -1 })
    .limit(limit)
    .populate('authorId', 'username displayName avatarUrl isVerified');
};

module.exports = mongoose.model('Post', postSchema);