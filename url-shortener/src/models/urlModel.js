const mongoose = require('mongoose');

const urlSchema = new mongoose.Schema({
  shortCode: {
    type: String,
    required: true,
    unique: true,
    index: true
  },
  originalUrl: {
    type: String,
    required: true
  },
  clickCount: {
    type: Number,
    default: 0
  },
  createdAt: {
    type: Date,
    default: Date.now,
    expires: 86400 * 365 // 1 year TTL
  },
  expiresAt: {
    type: Date,
    default: () => new Date(Date.now() + 86400000 * 365) // 1 year from creation
  },
  isCustom: {
    type: Boolean,
    default: false
  },
  userId: {
    type: String,
    default: null
  },
  metadata: {
    userAgent: String,
    ip: String,
    referrer: String
  }
});

urlSchema.index({ createdAt: 1 });
urlSchema.index({ userId: 1, createdAt: -1 });

urlSchema.methods.incrementClick = function() {
  this.clickCount++;
  return this.save();
};

urlSchema.statics.findByShortCode = function(shortCode) {
  return this.findOne({ shortCode, expiresAt: { $gt: new Date() } });
};

module.exports = mongoose.model('Url', urlSchema);