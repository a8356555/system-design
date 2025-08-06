const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const Redis = require('redis');
const mongoose = require('mongoose');
const jwt = require('jsonwebtoken');
const rateLimit = require('express-rate-limit');
const { RateLimiterRedis } = require('rate-limiter-flexible');

// Chat Service for Live Streaming Platform
class ChatService {
    constructor() {
        this.app = express();
        this.server = http.createServer(this.app);
        this.io = socketIo(this.server, {
            cors: {
                origin: process.env.ALLOWED_ORIGINS?.split(',') || ['*'],
                methods: ['GET', 'POST']
            },
            transports: ['websocket', 'polling']
        });

        this.redisClient = Redis.createClient({
            host: process.env.REDIS_HOST || 'localhost',
            port: process.env.REDIS_PORT || 6379
        });

        this.activeRooms = new Map(); // streamKey -> room info
        this.userConnections = new Map(); // userId -> socket mapping
        this.moderators = new Map(); // streamKey -> Set of moderator userIds

        this.setupMiddleware();
        this.setupRateLimiting();
        this.setupRoutes();
        this.setupSocketHandlers();
        this.connectDatabase();
    }

    async setupMiddleware() {
        this.app.use(express.json());
        this.app.use(express.urlencoded({ extended: true }));

        // CORS
        this.app.use((req, res, next) => {
            res.header('Access-Control-Allow-Origin', '*');
            res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
            res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
            next();
        });
    }

    async setupRateLimiting() {
        // Rate limiting for REST API
        const apiLimiter = rateLimit({
            windowMs: 15 * 60 * 1000, // 15 minutes
            max: 100, // limit each IP to 100 requests per windowMs
            message: 'Too many requests from this IP'
        });

        this.app.use('/api/', apiLimiter);

        // Rate limiting for chat messages
        this.chatRateLimiter = new RateLimiterRedis({
            storeClient: this.redisClient,
            keyPrefix: 'chat_rl',
            points: 10, // Number of messages
            duration: 60, // Per 60 seconds
        });

        // Rate limiting for emotes/reactions
        this.emoteRateLimiter = new RateLimiterRedis({
            storeClient: this.redisClient,
            keyPrefix: 'emote_rl',
            points: 30, // Number of emotes
            duration: 60, // Per 60 seconds
        });
    }

    setupRoutes() {
        // Health check
        this.app.get('/health', (req, res) => {
            res.json({
                status: 'healthy',
                timestamp: new Date(),
                activeRooms: this.activeRooms.size,
                connectedUsers: this.userConnections.size
            });
        });

        // Chat room management
        this.app.post('/api/rooms/:streamKey/create', this.authenticateToken, this.createChatRoom);
        this.app.delete('/api/rooms/:streamKey', this.authenticateToken, this.deleteChatRoom);
        this.app.get('/api/rooms/:streamKey/stats', this.getChatRoomStats);
        this.app.get('/api/rooms/:streamKey/history', this.getChatHistory);

        // Moderation endpoints
        this.app.post('/api/rooms/:streamKey/moderators', this.authenticateToken, this.addModerator);
        this.app.delete('/api/rooms/:streamKey/moderators/:userId', this.authenticateToken, this.removeModerator);
        this.app.post('/api/rooms/:streamKey/ban', this.authenticateToken, this.banUser);
        this.app.post('/api/rooms/:streamKey/timeout', this.authenticateToken, this.timeoutUser);
        this.app.delete('/api/rooms/:streamKey/messages/:messageId', this.authenticateToken, this.deleteMessage);

        // Chat settings
        this.app.put('/api/rooms/:streamKey/settings', this.authenticateToken, this.updateChatSettings);
        this.app.get('/api/rooms/:streamKey/settings', this.getChatSettings);

        // Emotes and reactions
        this.app.get('/api/emotes', this.getAvailableEmotes);
        this.app.post('/api/rooms/:streamKey/reaction', this.authenticateToken, this.addReaction);
    }

    setupSocketHandlers() {
        this.io.use(async (socket, next) => {
            try {
                const token = socket.handshake.auth.token;
                const streamKey = socket.handshake.query.streamKey;
                
                if (!token || !streamKey) {
                    return next(new Error('Authentication failed'));
                }

                const decoded = jwt.verify(token, process.env.JWT_SECRET || 'secret');
                socket.userId = decoded.userId;
                socket.username = decoded.username;
                socket.streamKey = streamKey;
                socket.userRole = decoded.role || 'viewer';
                
                next();
            } catch (err) {
                next(new Error('Authentication failed'));
            }
        });

        this.io.on('connection', (socket) => {
            this.handleSocketConnection(socket);
        });
    }

    handleSocketConnection(socket) {
        const { streamKey, userId, username, userRole } = socket;
        
        console.log(`User ${username} connected to chat room ${streamKey}`);

        // Track user connection
        this.userConnections.set(userId, socket);

        // Join chat room
        socket.join(streamKey);

        // Initialize or update room info
        if (!this.activeRooms.has(streamKey)) {
            this.activeRooms.set(streamKey, {
                streamKey,
                connectedUsers: new Set(),
                messageCount: 0,
                createdAt: new Date(),
                settings: {
                    slowMode: false,
                    slowModeDelay: 5,
                    subscribersOnly: false,
                    emotesOnly: false,
                    linksAllowed: true,
                    maxMessageLength: 500
                }
            });
        }

        const room = this.activeRooms.get(streamKey);
        room.connectedUsers.add(userId);

        // Send welcome message and room info
        socket.emit('room_joined', {
            streamKey,
            connectedUsers: room.connectedUsers.size,
            settings: room.settings,
            moderators: Array.from(this.moderators.get(streamKey) || [])
        });

        // Broadcast user joined to room
        socket.to(streamKey).emit('user_joined', {
            userId,
            username,
            userRole,
            timestamp: new Date()
        });

        // Handle chat messages
        socket.on('chat_message', async (data) => {
            await this.handleChatMessage(socket, data);
        });

        // Handle emotes/reactions
        socket.on('emote', async (data) => {
            await this.handleEmote(socket, data);
        });

        // Handle typing indicators
        socket.on('typing_start', () => {
            socket.to(streamKey).emit('user_typing', { userId, username });
        });

        socket.on('typing_stop', () => {
            socket.to(streamKey).emit('user_stopped_typing', { userId });
        });

        // Handle moderation actions
        socket.on('moderate_message', async (data) => {
            await this.handleModerationAction(socket, data);
        });

        // Handle user mentions
        socket.on('mention_user', (data) => {
            this.handleUserMention(socket, data);
        });

        // Handle disconnection
        socket.on('disconnect', () => {
            this.handleSocketDisconnection(socket);
        });
    }

    async handleChatMessage(socket, data) {
        const { streamKey, userId, username, userRole } = socket;
        const { message, mentions = [], emotes = [] } = data;

        try {
            // Rate limiting check
            await this.chatRateLimiter.consume(userId);

            // Validate message
            if (!message || message.trim().length === 0) {
                return socket.emit('error', { message: 'Message cannot be empty' });
            }

            const room = this.activeRooms.get(streamKey);
            if (!room) {
                return socket.emit('error', { message: 'Chat room not found' });
            }

            // Check message length
            if (message.length > room.settings.maxMessageLength) {
                return socket.emit('error', { 
                    message: `Message too long. Maximum ${room.settings.maxMessageLength} characters` 
                });
            }

            // Check if user is banned or timed out
            const isBanned = await this.redisClient.get(`ban:${streamKey}:${userId}`);
            const isTimedOut = await this.redisClient.get(`timeout:${streamKey}:${userId}`);
            
            if (isBanned || isTimedOut) {
                return socket.emit('error', { message: 'You are banned or timed out from this chat' });
            }

            // Apply chat room settings
            if (room.settings.subscribersOnly && userRole === 'viewer') {
                return socket.emit('error', { message: 'This chat is in subscribers-only mode' });
            }

            if (room.settings.emotesOnly && !this.containsOnlyEmotes(message, emotes)) {
                return socket.emit('error', { message: 'This chat is in emotes-only mode' });
            }

            if (!room.settings.linksAllowed && this.containsLinks(message)) {
                return socket.emit('error', { message: 'Links are not allowed in this chat' });
            }

            // Check slow mode
            if (room.settings.slowMode) {
                const lastMessage = await this.redisClient.get(`lastmsg:${streamKey}:${userId}`);
                if (lastMessage) {
                    const timeSinceLastMessage = Date.now() - parseInt(lastMessage);
                    if (timeSinceLastMessage < room.settings.slowModeDelay * 1000) {
                        const remainingTime = Math.ceil((room.settings.slowModeDelay * 1000 - timeSinceLastMessage) / 1000);
                        return socket.emit('error', { 
                            message: `Slow mode is enabled. Please wait ${remainingTime} seconds` 
                        });
                    }
                }
                await this.redisClient.set(`lastmsg:${streamKey}:${userId}`, Date.now(), 'EX', room.settings.slowModeDelay);
            }

            // Create message object
            const messageObj = {
                id: this.generateMessageId(),
                streamKey,
                userId,
                username,
                userRole,
                message: this.sanitizeMessage(message),
                mentions,
                emotes,
                timestamp: new Date(),
                deleted: false
            };

            // Store message in database
            await this.storeMessage(messageObj);

            // Update room stats
            room.messageCount++;

            // Broadcast message to room
            this.io.to(streamKey).emit('chat_message', messageObj);

            // Handle mentions
            if (mentions.length > 0) {
                this.processMentions(messageObj, mentions);
            }

            // Store in Redis for recent messages cache
            await this.redisClient.lpush(`recent:${streamKey}`, JSON.stringify(messageObj));
            await this.redisClient.ltrim(`recent:${streamKey}`, 0, 99); // Keep last 100 messages

            console.log(`Message from ${username} in ${streamKey}: ${message}`);

        } catch (rejRes) {
            if (rejRes.remainingHits !== undefined) {
                socket.emit('rate_limited', {
                    message: 'You are sending messages too fast',
                    retryAfter: rejRes.msBeforeNext
                });
            } else {
                console.error('Error handling chat message:', rejRes);
                socket.emit('error', { message: 'Failed to send message' });
            }
        }
    }

    async handleEmote(socket, data) {
        const { streamKey, userId, username } = socket;
        const { emoteId, position } = data;

        try {
            await this.emoteRateLimiter.consume(userId);

            // Validate emote
            const emote = await this.getEmoteById(emoteId);
            if (!emote) {
                return socket.emit('error', { message: 'Invalid emote' });
            }

            const emoteEvent = {
                id: this.generateMessageId(),
                type: 'emote',
                streamKey,
                userId,
                username,
                emoteId,
                emoteName: emote.name,
                emoteUrl: emote.url,
                position: position || { x: Math.random() * 100, y: Math.random() * 100 },
                timestamp: new Date()
            };

            // Broadcast emote to room
            this.io.to(streamKey).emit('emote_event', emoteEvent);

            // Store emote stats
            await this.redisClient.zincrby(`emotes:${streamKey}`, 1, emoteId);

        } catch (rejRes) {
            if (rejRes.remainingHits !== undefined) {
                socket.emit('rate_limited', {
                    message: 'You are using emotes too fast',
                    retryAfter: rejRes.msBeforeNext
                });
            }
        }
    }

    async handleModerationAction(socket, data) {
        const { streamKey, userId, userRole } = socket;
        const { action, targetUserId, reason, duration } = data;

        // Check if user has moderation permissions
        const isModerator = this.moderators.get(streamKey)?.has(userId) || userRole === 'broadcaster';
        if (!isModerator) {
            return socket.emit('error', { message: 'Insufficient permissions' });
        }

        switch (action) {
            case 'timeout':
                await this.timeoutUserAction(streamKey, targetUserId, duration || 600, reason);
                break;
            case 'ban':
                await this.banUserAction(streamKey, targetUserId, reason);
                break;
            case 'delete_message':
                await this.deleteMessageAction(streamKey, data.messageId);
                break;
            case 'clear_chat':
                await this.clearChatAction(streamKey);
                break;
        }

        // Log moderation action
        console.log(`Moderation action by ${socket.username}: ${action} on ${targetUserId} in ${streamKey}`);
    }

    handleSocketDisconnection(socket) {
        const { streamKey, userId, username } = socket;
        
        console.log(`User ${username} disconnected from chat room ${streamKey}`);

        // Remove from tracking
        this.userConnections.delete(userId);

        // Update room info
        const room = this.activeRooms.get(streamKey);
        if (room) {
            room.connectedUsers.delete(userId);
            
            // Remove empty rooms
            if (room.connectedUsers.size === 0) {
                this.activeRooms.delete(streamKey);
            }
        }

        // Broadcast user left
        socket.to(streamKey).emit('user_left', {
            userId,
            username,
            timestamp: new Date()
        });
    }

    // Authentication middleware
    authenticateToken = (req, res, next) => {
        const authHeader = req.headers['authorization'];
        const token = authHeader && authHeader.split(' ')[1];

        if (!token) {
            return res.status(401).json({ error: 'Access token required' });
        }

        jwt.verify(token, process.env.JWT_SECRET || 'secret', (err, user) => {
            if (err) {
                return res.status(403).json({ error: 'Invalid or expired token' });
            }
            req.user = user;
            next();
        });
    };

    // Route handlers
    createChatRoom = async (req, res) => {
        const { streamKey } = req.params;
        const { settings = {} } = req.body;

        // Initialize chat room
        if (!this.activeRooms.has(streamKey)) {
            this.activeRooms.set(streamKey, {
                streamKey,
                connectedUsers: new Set(),
                messageCount: 0,
                createdAt: new Date(),
                settings: {
                    slowMode: false,
                    slowModeDelay: 5,
                    subscribersOnly: false,
                    emotesOnly: false,
                    linksAllowed: true,
                    maxMessageLength: 500,
                    ...settings
                }
            });
        }

        res.json({ message: 'Chat room created', streamKey });
    };

    deleteChatRoom = async (req, res) => {
        const { streamKey } = req.params;

        // Clear all users from room
        this.io.to(streamKey).emit('room_closed', { message: 'Chat room has been closed' });
        
        // Remove room
        this.activeRooms.delete(streamKey);
        this.moderators.delete(streamKey);

        // Clear Redis data
        await this.redisClient.del(`recent:${streamKey}`);
        await this.redisClient.del(`emotes:${streamKey}`);

        res.json({ message: 'Chat room deleted', streamKey });
    };

    getChatRoomStats = async (req, res) => {
        const { streamKey } = req.params;
        const room = this.activeRooms.get(streamKey);

        if (!room) {
            return res.status(404).json({ error: 'Chat room not found' });
        }

        // Get additional stats from Redis
        const topEmotes = await this.redisClient.zrevrange(`emotes:${streamKey}`, 0, 9, 'WITHSCORES');

        res.json({
            streamKey,
            connectedUsers: room.connectedUsers.size,
            messageCount: room.messageCount,
            createdAt: room.createdAt,
            topEmotes: this.parseEmoteStats(topEmotes),
            settings: room.settings
        });
    };

    // Utility methods
    generateMessageId() {
        return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    sanitizeMessage(message) {
        // Basic sanitization - remove harmful content
        return message.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
                     .replace(/<[^>]*>/g, '')
                     .trim();
    }

    containsOnlyEmotes(message, emotes) {
        // Check if message contains only emotes and whitespace
        const emotePattern = /:[\w-]+:/g;
        const messageWithoutEmotes = message.replace(emotePattern, '').trim();
        return messageWithoutEmotes.length === 0;
    }

    containsLinks(message) {
        const urlPattern = /(https?:\/\/[^\s]+)/g;
        return urlPattern.test(message);
    }

    async connectDatabase() {
        try {
            await mongoose.connect(process.env.MONGODB_URI || 'mongodb://localhost:27017/streaming_chat');
            console.log('Connected to MongoDB');
        } catch (error) {
            console.error('MongoDB connection error:', error);
        }
    }

    async storeMessage(messageObj) {
        // Store message in MongoDB (implement ChatMessage model)
        // This is a placeholder - implement actual database storage
        console.log('Storing message:', messageObj.id);
    }

    async getEmoteById(emoteId) {
        // Get emote information from database or cache
        // Placeholder implementation
        return {
            id: emoteId,
            name: `emote_${emoteId}`,
            url: `https://cdn.example.com/emotes/${emoteId}.png`
        };
    }

    parseEmoteStats(redisResult) {
        const stats = [];
        for (let i = 0; i < redisResult.length; i += 2) {
            stats.push({
                emoteId: redisResult[i],
                count: parseInt(redisResult[i + 1])
            });
        }
        return stats;
    }

    start() {
        const port = process.env.PORT || 3000;
        this.server.listen(port, () => {
            console.log(`Chat service listening on port ${port}`);
        });
    }
}

// Start the service
const chatService = new ChatService();
chatService.start();

module.exports = ChatService;