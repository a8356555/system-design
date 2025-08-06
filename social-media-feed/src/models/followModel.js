const mongoose = require('mongoose');

const followSchema = new mongoose.Schema({
  followerId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true
  },
  followingId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true
  },
  createdAt: {
    type: Date,
    default: Date.now
  },
  notificationsEnabled: {
    type: Boolean,
    default: true
  }
});

followSchema.index({ followerId: 1 });
followSchema.index({ followingId: 1 });
followSchema.index({ followerId: 1, followingId: 1 }, { unique: true });
followSchema.index({ followingId: 1, createdAt: -1 });

followSchema.statics.getFollowing = function(userId) {
  return this.find({ followerId: userId })
    .populate('followingId', 'username displayName avatarUrl isVerified followerCount')
    .sort({ createdAt: -1 });
};

followSchema.statics.getFollowers = function(userId) {
  return this.find({ followingId: userId })
    .populate('followerId', 'username displayName avatarUrl isVerified followerCount')
    .sort({ createdAt: -1 });
};

followSchema.statics.isFollowing = function(followerId, followingId) {
  return this.exists({ followerId, followingId });
};

followSchema.statics.getFollowingIds = function(userId) {
  return this.find({ followerId: userId }).select('followingId');
};

followSchema.statics.getMutualFollows = function(userId1, userId2) {
  return this.aggregate([
    {
      $match: {
        $or: [
          { followerId: userId1, followingId: userId2 },
          { followerId: userId2, followingId: userId1 }
        ]
      }
    },
    {
      $group: {
        _id: null,
        follows: { $push: '$$ROOT' }
      }
    }
  ]);
};

module.exports = mongoose.model('Follow', followSchema);