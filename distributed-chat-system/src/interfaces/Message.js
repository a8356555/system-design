/**
 * Message Interface for Chat System
 */
class Message {
  constructor({
    id,
    chatId,
    senderId,
    content,
    type = 'text',
    timestamp = new Date(),
    metadata = {}
  }) {
    this.id = id;
    this.chatId = chatId;
    this.senderId = senderId;
    this.content = content;
    this.type = type; // text, image, file, system
    this.timestamp = timestamp;
    this.metadata = metadata;
  }

  static validate(messageData) {
    const required = ['chatId', 'senderId', 'content'];
    for (const field of required) {
      if (!messageData[field]) {
        throw new Error(`Missing required field: ${field}`);
      }
    }
    return true;
  }

  toJSON() {
    return {
      id: this.id,
      chatId: this.chatId,
      senderId: this.senderId,
      content: this.content,
      type: this.type,
      timestamp: this.timestamp,
      metadata: this.metadata
    };
  }
}

module.exports = Message;