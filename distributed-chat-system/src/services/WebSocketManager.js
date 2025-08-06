const socketIo = require('socket.io');
const jwt = require('jsonwebtoken');
const MessageBroker = require('./MessageBroker');
const Message = require('../interfaces/Message');

class WebSocketManager {
  constructor(server) {
    this.io = socketIo(server, {
      cors: {
        origin: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000'],
        methods: ['GET', 'POST']
      },
      transports: ['websocket', 'polling']
    });

    this.messageBroker = new MessageBroker();
    this.connectedUsers = new Map(); // userId -> socketId mapping
    this.userSockets = new Map(); // socketId -> user info mapping
    
    this.setupMiddleware();
    this.setupEventHandlers();
    this.subscribeToMessageBroker();
  }

  setupMiddleware() {
    this.io.use(async (socket, next) => {
      try {
        const token = socket.handshake.auth.token;
        const decoded = jwt.verify(token, process.env.JWT_SECRET || 'secret');
        socket.userId = decoded.userId;
        socket.username = decoded.username;
        next();
      } catch (err) {
        next(new Error('Authentication error'));
      }
    });
  }

  setupEventHandlers() {
    this.io.on('connection', (socket) => {
      console.log(`User ${socket.username} connected: ${socket.id}`);
      
      // Track user connection
      this.connectedUsers.set(socket.userId, socket.id);
      this.userSockets.set(socket.id, {
        userId: socket.userId,
        username: socket.username
      });

      // Set user as online
      this.messageBroker.setUserPresence(socket.userId, 'online');

      // Join user to their chat rooms
      this.joinUserToRooms(socket);

      // Handle new messages
      socket.on('send_message', async (data) => {
        await this.handleNewMessage(socket, data);
      });

      // Handle joining chat rooms
      socket.on('join_chat', (chatId) => {
        socket.join(`chat:${chatId}`);
        console.log(`User ${socket.username} joined chat ${chatId}`);
      });

      // Handle leaving chat rooms
      socket.on('leave_chat', (chatId) => {
        socket.leave(`chat:${chatId}`);
        console.log(`User ${socket.username} left chat ${chatId}`);
      });

      // Handle typing indicators
      socket.on('typing_start', (chatId) => {
        socket.to(`chat:${chatId}`).emit('user_typing', {
          userId: socket.userId,
          username: socket.username,
          chatId
        });
      });

      socket.on('typing_stop', (chatId) => {
        socket.to(`chat:${chatId}`).emit('user_stopped_typing', {
          userId: socket.userId,
          chatId
        });
      });

      // Handle disconnection
      socket.on('disconnect', () => {
        console.log(`User ${socket.username} disconnected: ${socket.id}`);
        this.connectedUsers.delete(socket.userId);
        this.userSockets.delete(socket.id);
        this.messageBroker.setUserPresence(socket.userId, 'offline');
      });
    });
  }

  async handleNewMessage(socket, data) {
    try {
      // Validate message
      Message.validate(data);

      // Create message object
      const message = new Message({
        id: this.generateMessageId(),
        chatId: data.chatId,
        senderId: socket.userId,
        content: data.content,
        type: data.type || 'text',
        timestamp: new Date(),
        metadata: {
          senderUsername: socket.username,
          ...data.metadata
        }
      });

      // Publish to message broker for persistence and distribution
      await this.messageBroker.publishMessage('chat_messages', message.toJSON());

      // Cache message for quick retrieval
      await this.messageBroker.cacheMessage(message.id, message.toJSON());

      // Broadcast to chat room immediately (local delivery)
      this.io.to(`chat:${data.chatId}`).emit('new_message', message.toJSON());

    } catch (error) {
      console.error('Error handling message:', error);
      socket.emit('error', { message: 'Failed to send message' });
    }
  }

  subscribeToMessageBroker() {
    // Subscribe to messages from other server instances
    this.messageBroker.subscribeToTopic('chat_messages', (message) => {
      // Only broadcast if message wasn't sent from this server instance
      if (!this.userSockets.has(message.senderId)) {
        this.io.to(`chat:${message.chatId}`).emit('new_message', message);
      }
    });
  }

  async joinUserToRooms(socket) {
    // In a real implementation, fetch user's chat rooms from database
    // For now, assume user joins based on their ID pattern
    const userChats = await this.getUserChats(socket.userId);
    userChats.forEach(chatId => {
      socket.join(`chat:${chatId}`);
    });
  }

  async getUserChats(userId) {
    // Mock implementation - in reality, query database
    return [`public_${userId}`, `general`];
  }

  generateMessageId() {
    return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  // Utility methods for external use
  sendToUser(userId, event, data) {
    const socketId = this.connectedUsers.get(userId);
    if (socketId) {
      this.io.to(socketId).emit(event, data);
    }
  }

  sendToChat(chatId, event, data) {
    this.io.to(`chat:${chatId}`).emit(event, data);
  }

  getUserCount() {
    return this.connectedUsers.size;
  }
}

module.exports = WebSocketManager;