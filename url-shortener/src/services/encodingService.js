const BASE62_CHARS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
const BASE = BASE62_CHARS.length;

class EncodingService {
  constructor() {
    this.counter = 0;
  }

  encodeBase62(num) {
    if (num === 0) return BASE62_CHARS[0];
    
    let result = '';
    while (num > 0) {
      result = BASE62_CHARS[num % BASE] + result;
      num = Math.floor(num / BASE);
    }
    return result;
  }

  decodeBase62(str) {
    let result = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str[i];
      const value = BASE62_CHARS.indexOf(char);
      if (value === -1) {
        throw new Error(`Invalid character in Base62 string: ${char}`);
      }
      result = result * BASE + value;
    }
    return result;
  }

  generateUniqueId() {
    const timestamp = Date.now();
    const randomNum = Math.floor(Math.random() * 1000);
    const counter = ++this.counter % 1000;
    
    return timestamp * 1000000 + randomNum * 1000 + counter;
  }

  generateShortCode(customAlias = null) {
    if (customAlias) {
      if (this.isValidCustomAlias(customAlias)) {
        return customAlias;
      }
      throw new Error('Invalid custom alias');
    }
    
    const uniqueId = this.generateUniqueId();
    return this.encodeBase62(uniqueId);
  }

  isValidCustomAlias(alias) {
    const regex = /^[a-zA-Z0-9_-]+$/;
    return regex.test(alias) && alias.length >= 3 && alias.length <= 10;
  }

  validateUrl(url) {
    try {
      const urlObj = new URL(url);
      return urlObj.protocol === 'http:' || urlObj.protocol === 'https:';
    } catch {
      return false;
    }
  }
}

module.exports = new EncodingService();