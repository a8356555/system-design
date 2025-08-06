const mongoose = require('mongoose');

const userSchema = new mongoose.Schema({
  username: {
    type: String,
    required: true,
    unique: true,
    trim: true,
    minlength: 3,
    maxlength: 30
  },
  email: {
    type: String,
    required: true,
    unique: true,
    lowercase: true
  },
  displayName: {
    type: String,
    required: true,
    maxlength: 50
  },
  bio: {
    type: String,
    maxlength: 160
  },
  avatarUrl: {
    type: String
  },
  isVerified: {
    type: Boolean,
    default: false
  },
  followerCount: {
    type: Number,
    default: 0
  },
  followingCount: {
    type: Number,
    default: 0
  },
  postCount: {
    type: Number,
    default: 0
  },
  isActive: {
    type: Boolean,
    default: true
  },
  lastActiveAt: {
    type: Date,
    default: Date.now
  },
  createdAt: {
    type: Date,
    default: Date.now
  },
  settings: {
    privacy: {
      type: String,
      enum: ['public', 'private'],
      default: 'public'
    },
    notifications: {
      likes: { type: Boolean, default: true },
      comments: { type: Boolean, default: true },
      follows: { type: Boolean, default: true },
      mentions: { type: Boolean, default: true }
    }
  }
});

userSchema.index({ username: 1 });
userSchema.index({ email: 1 });
userSchema.index({ followerCount: -1 });
userSchema.index({ lastActiveAt: -1 });

userSchema.methods.updateLastActive = function() {
  this.lastActiveAt = new Date();
  return this.save();
};

userSchema.statics.findActiveUsers = function(limit = 1000) {
  const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
  return this.find({ lastActiveAt: { $gte: oneHourAgo } }).limit(limit);
};

module.exports = mongoose.model('User', userSchema);