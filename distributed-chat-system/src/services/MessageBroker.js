const kafka = require('kafka-node');
const Redis = require('redis');

class MessageBroker {
  constructor() {
    this.kafkaClient = new kafka.KafkaClient({ kafkaHost: process.env.KAFKA_HOST || 'localhost:9092' });
    this.producer = new kafka.Producer(this.kafkaClient);
    this.consumer = new kafka.Consumer(this.kafkaClient, []);
    this.redisClient = Redis.createClient({
      host: process.env.REDIS_HOST || 'localhost',
      port: process.env.REDIS_PORT || 6379
    });
    
    this.setupProducer();
  }

  setupProducer() {
    this.producer.on('ready', () => {
      console.log('Kafka Producer is ready');
    });

    this.producer.on('error', (err) => {
      console.error('Kafka Producer error:', err);
    });
  }

  async publishMessage(topic, message) {
    return new Promise((resolve, reject) => {
      const payload = [{
        topic: topic,
        messages: JSON.stringify(message),
        partition: this.getPartition(message.chatId)
      }];

      this.producer.send(payload, (err, data) => {
        if (err) reject(err);
        else resolve(data);
      });
    });
  }

  subscribeToTopic(topic, callback) {
    const consumer = new kafka.Consumer(
      this.kafkaClient,
      [{ topic: topic, partition: 0 }],
      { autoCommit: true }
    );

    consumer.on('message', (message) => {
      try {
        const parsedMessage = JSON.parse(message.value);
        callback(parsedMessage);
      } catch (err) {
        console.error('Error parsing message:', err);
      }
    });

    consumer.on('error', (err) => {
      console.error('Kafka Consumer error:', err);
    });
  }

  getPartition(chatId) {
    // Simple hash-based partitioning
    return Math.abs(chatId.toString().split('').reduce((a, b) => {
      a = ((a << 5) - a) + b.charCodeAt(0);
      return a & a;
    }, 0)) % 3; // 3 partitions
  }

  async cacheMessage(messageId, message, ttl = 3600) {
    await this.redisClient.setEx(`msg:${messageId}`, ttl, JSON.stringify(message));
  }

  async getCachedMessage(messageId) {
    const cached = await this.redisClient.get(`msg:${messageId}`);
    return cached ? JSON.parse(cached) : null;
  }

  async setUserPresence(userId, status) {
    await this.redisClient.setEx(`presence:${userId}`, 300, status); // 5 min TTL
  }

  async getUserPresence(userId) {
    return await this.redisClient.get(`presence:${userId}`);
  }
}

module.exports = MessageBroker;