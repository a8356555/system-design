package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "sync"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    "github.com/segmentio/kafka-go"
    "go.mongodb.org/mongo-driver/mongo"
    "go.mongodb.org/mongo-driver/mongo/options"
)

// NotificationGateway handles high-throughput notification processing
type NotificationGateway struct {
    config         *Config
    redisClient    *redis.Client
    mongoClient    *mongo.Client
    kafkaWriter    *kafka.Writer
    kafkaReader    *kafka.Reader
    templateEngine *TemplateEngine
    deliveryChannels map[string]DeliveryChannel
    rateLimiters   map[string]*RateLimiter
    metrics        *Metrics
    ctx            context.Context
    cancel         context.CancelFunc
    wg             sync.WaitGroup
}

// NotificationRequest represents an incoming notification request
type NotificationRequest struct {
    ID          string                 `json:"id" bson:"_id"`
    UserID      string                 `json:"user_id" bson:"user_id"`
    UserIDs     []string               `json:"user_ids,omitempty" bson:"user_ids,omitempty"`
    Template    string                 `json:"template" bson:"template"`
    Channels    []string               `json:"channels" bson:"channels"` // push, email, sms, in_app
    Priority    string                 `json:"priority" bson:"priority"` // low, normal, high, urgent
    Data        map[string]interface{} `json:"data" bson:"data"`
    ScheduledAt *time.Time             `json:"scheduled_at,omitempty" bson:"scheduled_at,omitempty"`
    ExpiresAt   *time.Time             `json:"expires_at,omitempty" bson:"expires_at,omitempty"`
    CreatedAt   time.Time              `json:"created_at" bson:"created_at"`
    Metadata    map[string]interface{} `json:"metadata,omitempty" bson:"metadata,omitempty"`
}

// ProcessedNotification represents a notification ready for delivery
type ProcessedNotification struct {
    ID                string                 `json:"id" bson:"_id"`
    OriginalRequestID string                 `json:"original_request_id" bson:"original_request_id"`
    UserID            string                 `json:"user_id" bson:"user_id"`
    Channel           string                 `json:"channel" bson:"channel"`
    Title             string                 `json:"title" bson:"title"`
    Body              string                 `json:"body" bson:"body"`
    Data              map[string]interface{} `json:"data" bson:"data"`
    Priority          string                 `json:"priority" bson:"priority"`
    DeliveryAttempts  int                    `json:"delivery_attempts" bson:"delivery_attempts"`
    Status            string                 `json:"status" bson:"status"` // pending, sent, delivered, failed
    CreatedAt         time.Time              `json:"created_at" bson:"created_at"`
    UpdatedAt         time.Time              `json:"updated_at" bson:"updated_at"`
    DeliveredAt       *time.Time             `json:"delivered_at,omitempty" bson:"delivered_at,omitempty"`
    FailureReason     string                 `json:"failure_reason,omitempty" bson:"failure_reason,omitempty"`
}

// UserPreferences stores user notification preferences
type UserPreferences struct {
    UserID       string            `json:"user_id" bson:"_id"`
    Channels     map[string]bool   `json:"channels" bson:"channels"`
    QuietHours   *QuietHours       `json:"quiet_hours,omitempty" bson:"quiet_hours,omitempty"`
    Frequency    map[string]string `json:"frequency" bson:"frequency"` // immediate, batched, daily, weekly
    Categories   map[string]bool   `json:"categories" bson:"categories"`
    DeviceTokens map[string]string `json:"device_tokens" bson:"device_tokens"` // platform -> token
    UpdatedAt    time.Time         `json:"updated_at" bson:"updated_at"`
}

// QuietHours defines when user doesn't want notifications
type QuietHours struct {
    Enabled   bool   `json:"enabled" bson:"enabled"`
    StartTime string `json:"start_time" bson:"start_time"` // HH:MM format
    EndTime   string `json:"end_time" bson:"end_time"`     // HH:MM format
    Timezone  string `json:"timezone" bson:"timezone"`
}

// Config holds application configuration
type Config struct {
    Port                string
    RedisAddr           string
    MongoURI            string
    KafkaBootstrapServers string
    MaxWorkers          int
    BatchSize           int
    RateLimitPerMinute  int
    DeliveryRetries     int
    Templates           map[string]NotificationTemplate
}

// DeliveryChannel interface for different notification channels
type DeliveryChannel interface {
    Send(ctx context.Context, notification *ProcessedNotification) error
    GetName() string
    IsHealthy() bool
}

func main() {
    config := loadConfig()
    
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()

    gateway := &NotificationGateway{
        config:           config,
        deliveryChannels: make(map[string]DeliveryChannel),
        rateLimiters:     make(map[string]*RateLimiter),
        ctx:             ctx,
        cancel:          cancel,
    }

    if err := gateway.initialize(); err != nil {
        log.Fatalf("Failed to initialize notification gateway: %v", err)
    }

    // Start background workers
    gateway.startWorkers()

    // Start HTTP server
    gateway.startHTTPServer()
}

func (ng *NotificationGateway) initialize() error {
    // Initialize Redis
    ng.redisClient = redis.NewClient(&redis.Options{
        Addr: ng.config.RedisAddr,
    })
    
    if err := ng.redisClient.Ping(ng.ctx).Err(); err != nil {
        return fmt.Errorf("failed to connect to Redis: %w", err)
    }

    // Initialize MongoDB
    client, err := mongo.Connect(ng.ctx, options.Client().ApplyURI(ng.config.MongoURI))
    if err != nil {
        return fmt.Errorf("failed to connect to MongoDB: %w", err)
    }
    ng.mongoClient = client

    // Initialize Kafka
    ng.kafkaWriter = &kafka.Writer{
        Addr:         kafka.TCP(ng.config.KafkaBootstrapServers),
        Topic:        "notifications",
        Balancer:     &kafka.LeastBytes{},
        BatchTimeout: 100 * time.Millisecond,
        BatchSize:    ng.config.BatchSize,
    }

    ng.kafkaReader = kafka.NewReader(kafka.ReaderConfig{
        Brokers:     []string{ng.config.KafkaBootstrapServers},
        Topic:       "notifications",
        GroupID:     "notification-gateway",
        MinBytes:    10e3, // 10KB
        MaxBytes:    10e6, // 10MB
        MaxWait:     1 * time.Second,
    })

    // Initialize template engine
    ng.templateEngine = NewTemplateEngine(ng.config.Templates)

    // Initialize delivery channels
    ng.initializeDeliveryChannels()

    // Initialize rate limiters
    ng.initializeRateLimiters()

    // Initialize metrics
    ng.metrics = NewMetrics()

    log.Println("Notification gateway initialized successfully")
    return nil
}

func (ng *NotificationGateway) initializeDeliveryChannels() {
    // Initialize Push Notification Channel (FCM/APNS)
    pushChannel := &PushNotificationChannel{
        redisClient: ng.redisClient,
        fcmClient:   NewFCMClient(),
        apnsClient:  NewAPNSClient(),
    }
    ng.deliveryChannels["push"] = pushChannel

    // Initialize Email Channel (SMTP/SES)
    emailChannel := &EmailChannel{
        smtpConfig: SMTPConfig{
            Host:     "smtp.example.com",
            Port:     587,
            Username: "notifications@example.com",
            Password: "smtp-password",
        },
        sesClient: NewSESClient(),
    }
    ng.deliveryChannels["email"] = emailChannel

    // Initialize SMS Channel (Twilio/SNS)
    smsChannel := &SMSChannel{
        twilioClient: NewTwilioClient(),
        snsClient:    NewSNSClient(),
    }
    ng.deliveryChannels["sms"] = smsChannel

    // Initialize In-App Channel (WebSocket)
    inAppChannel := &InAppChannel{
        redisClient: ng.redisClient,
        wsManager:   NewWebSocketManager(),
    }
    ng.deliveryChannels["in_app"] = inAppChannel
}

func (ng *NotificationGateway) initializeRateLimiters() {
    // Initialize rate limiters for different channels
    ng.rateLimiters["push"] = NewRateLimiter(ng.redisClient, "push", 1000, time.Minute)
    ng.rateLimiters["email"] = NewRateLimiter(ng.redisClient, "email", 500, time.Minute)
    ng.rateLimiters["sms"] = NewRateLimiter(ng.redisClient, "sms", 100, time.Minute)
    ng.rateLimiters["in_app"] = NewRateLimiter(ng.redisClient, "in_app", 5000, time.Minute)
}

func (ng *NotificationGateway) startWorkers() {
    // Start message processing workers
    for i := 0; i < ng.config.MaxWorkers; i++ {
        ng.wg.Add(1)
        go ng.messageProcessorWorker(i)
    }

    // Start delivery workers for each channel
    for channelName := range ng.deliveryChannels {
        ng.wg.Add(1)
        go ng.deliveryWorker(channelName)
    }

    // Start cleanup worker
    ng.wg.Add(1)
    go ng.cleanupWorker()

    // Start metrics collector
    ng.wg.Add(1)
    go ng.metricsCollector()

    log.Printf("Started %d workers", ng.config.MaxWorkers+len(ng.deliveryChannels)+2)
}

func (ng *NotificationGateway) messageProcessorWorker(workerID int) {
    defer ng.wg.Done()
    log.Printf("Starting message processor worker %d", workerID)

    for {
        select {
        case <-ng.ctx.Done():
            return
        default:
            message, err := ng.kafkaReader.ReadMessage(ng.ctx)
            if err != nil {
                log.Printf("Worker %d: Error reading message: %v", workerID, err)
                continue
            }

            var request NotificationRequest
            if err := json.Unmarshal(message.Value, &request); err != nil {
                log.Printf("Worker %d: Error unmarshaling message: %v", workerID, err)
                continue
            }

            if err := ng.processNotificationRequest(&request); err != nil {
                log.Printf("Worker %d: Error processing notification: %v", workerID, err)
                ng.metrics.IncrementCounter("processing_errors")
            } else {
                ng.metrics.IncrementCounter("notifications_processed")
            }
        }
    }
}

func (ng *NotificationGateway) processNotificationRequest(request *NotificationRequest) error {
    // Handle scheduled notifications
    if request.ScheduledAt != nil && time.Now().Before(*request.ScheduledAt) {
        return ng.scheduleNotification(request)
    }

    // Handle expired notifications
    if request.ExpiresAt != nil && time.Now().After(*request.ExpiresAt) {
        log.Printf("Notification %s expired, skipping", request.ID)
        return nil
    }

    // Get user IDs to process
    userIDs := request.UserIDs
    if len(userIDs) == 0 && request.UserID != "" {
        userIDs = []string{request.UserID}
    }

    // Process for each user
    for _, userID := range userIDs {
        if err := ng.processUserNotification(request, userID); err != nil {
            log.Printf("Error processing notification for user %s: %v", userID, err)
            continue
        }
    }

    return nil
}

func (ng *NotificationGateway) processUserNotification(request *NotificationRequest, userID string) error {
    // Get user preferences
    preferences, err := ng.getUserPreferences(userID)
    if err != nil {
        log.Printf("Error getting user preferences for %s: %v", userID, err)
        // Use default preferences
        preferences = &UserPreferences{
            UserID:   userID,
            Channels: map[string]bool{"push": true, "in_app": true},
        }
    }

    // Check quiet hours
    if ng.isInQuietHours(preferences) {
        log.Printf("User %s is in quiet hours, scheduling for later", userID)
        return ng.scheduleForLater(request, userID)
    }

    // Process each requested channel
    for _, channel := range request.Channels {
        // Check if user has enabled this channel
        if enabled, exists := preferences.Channels[channel]; !exists || !enabled {
            continue
        }

        // Check rate limiting
        if ng.rateLimiters[channel] != nil {
            if !ng.rateLimiters[channel].Allow(userID) {
                log.Printf("Rate limit exceeded for user %s on channel %s", userID, channel)
                continue
            }
        }

        // Create processed notification
        processed, err := ng.createProcessedNotification(request, userID, channel, preferences)
        if err != nil {
            log.Printf("Error creating processed notification: %v", err)
            continue
        }

        // Queue for delivery
        if err := ng.queueForDelivery(processed); err != nil {
            log.Printf("Error queuing notification for delivery: %v", err)
            continue
        }
    }

    return nil
}

func (ng *NotificationGateway) createProcessedNotification(request *NotificationRequest, userID, channel string, preferences *UserPreferences) (*ProcessedNotification, error) {
    // Render template
    content, err := ng.templateEngine.Render(request.Template, request.Data, channel)
    if err != nil {
        return nil, fmt.Errorf("error rendering template: %w", err)
    }

    processed := &ProcessedNotification{
        ID:                ng.generateID(),
        OriginalRequestID: request.ID,
        UserID:            userID,
        Channel:           channel,
        Title:             content.Title,
        Body:              content.Body,
        Data:              request.Data,
        Priority:          request.Priority,
        Status:            "pending",
        CreatedAt:         time.Now(),
        UpdatedAt:         time.Now(),
    }

    // Add channel-specific data
    if channel == "push" && preferences.DeviceTokens != nil {
        if token, exists := preferences.DeviceTokens["fcm"]; exists {
            processed.Data["device_token"] = token
        }
        if token, exists := preferences.DeviceTokens["apns"]; exists {
            processed.Data["apns_token"] = token
        }
    }

    return processed, nil
}

func (ng *NotificationGateway) queueForDelivery(notification *ProcessedNotification) error {
    // Store in MongoDB
    collection := ng.mongoClient.Database("notifications").Collection("processed")
    _, err := collection.InsertOne(ng.ctx, notification)
    if err != nil {
        return fmt.Errorf("error storing notification: %w", err)
    }

    // Queue in Redis for delivery
    queueKey := fmt.Sprintf("delivery_queue:%s", notification.Channel)
    notificationJSON, _ := json.Marshal(notification)
    
    return ng.redisClient.LPush(ng.ctx, queueKey, notificationJSON).Err()
}

func (ng *NotificationGateway) deliveryWorker(channelName string) {
    defer ng.wg.Done()
    log.Printf("Starting delivery worker for channel: %s", channelName)

    channel := ng.deliveryChannels[channelName]
    queueKey := fmt.Sprintf("delivery_queue:%s", channelName)

    for {
        select {
        case <-ng.ctx.Done():
            return
        default:
            // Get notification from queue
            result, err := ng.redisClient.BRPop(ng.ctx, time.Second, queueKey).Result()
            if err != nil {
                if err != redis.Nil {
                    log.Printf("Error popping from queue %s: %v", queueKey, err)
                }
                continue
            }

            var notification ProcessedNotification
            if err := json.Unmarshal([]byte(result[1]), &notification); err != nil {
                log.Printf("Error unmarshaling notification: %v", err)
                continue
            }

            // Check if channel is healthy
            if !channel.IsHealthy() {
                log.Printf("Channel %s is unhealthy, requeueing notification", channelName)
                ng.requeueNotification(&notification)
                continue
            }

            // Attempt delivery
            if err := ng.deliverNotification(channel, &notification); err != nil {
                log.Printf("Error delivering notification: %v", err)
                ng.handleDeliveryFailure(&notification, err)
            } else {
                ng.handleDeliverySuccess(&notification)
            }
        }
    }
}

func (ng *NotificationGateway) deliverNotification(channel DeliveryChannel, notification *ProcessedNotification) error {
    // Update delivery attempt count
    notification.DeliveryAttempts++
    notification.UpdatedAt = time.Now()

    // Attempt delivery
    ctx, cancel := context.WithTimeout(ng.ctx, 30*time.Second)
    defer cancel()

    if err := channel.Send(ctx, notification); err != nil {
        notification.Status = "failed"
        notification.FailureReason = err.Error()
        return err
    }

    notification.Status = "sent"
    return nil
}

func (ng *NotificationGateway) handleDeliverySuccess(notification *ProcessedNotification) {
    notification.Status = "delivered"
    notification.DeliveredAt = &time.Time{}
    *notification.DeliveredAt = time.Now()

    // Update in database
    ng.updateNotificationStatus(notification)

    // Update metrics
    ng.metrics.IncrementCounter(fmt.Sprintf("delivery_success_%s", notification.Channel))

    log.Printf("Successfully delivered notification %s via %s to user %s", 
        notification.ID, notification.Channel, notification.UserID)
}

func (ng *NotificationGateway) handleDeliveryFailure(notification *ProcessedNotification, err error) {
    ng.metrics.IncrementCounter(fmt.Sprintf("delivery_failure_%s", notification.Channel))

    // Retry logic
    if notification.DeliveryAttempts < ng.config.DeliveryRetries {
        // Exponential backoff
        delay := time.Duration(notification.DeliveryAttempts*notification.DeliveryAttempts) * time.Second
        time.Sleep(delay)
        
        // Requeue for retry
        ng.requeueNotification(notification)
        return
    }

    // Max retries reached, mark as failed
    notification.Status = "failed"
    notification.FailureReason = fmt.Sprintf("Max retries reached: %v", err)
    ng.updateNotificationStatus(notification)

    log.Printf("Failed to deliver notification %s after %d attempts: %v", 
        notification.ID, notification.DeliveryAttempts, err)
}

func (ng *NotificationGateway) startHTTPServer() {
    gin.SetMode(gin.ReleaseMode)
    router := gin.New()
    router.Use(gin.Logger(), gin.Recovery())

    // API routes
    v1 := router.Group("/api/v1")
    {
        v1.POST("/notifications", ng.sendNotification)
        v1.POST("/notifications/batch", ng.sendBatchNotifications)
        v1.GET("/notifications/:id", ng.getNotification)
        v1.GET("/notifications/:id/status", ng.getNotificationStatus)
        
        // User preferences
        v1.GET("/users/:userId/preferences", ng.getUserPreferencesHandler)
        v1.PUT("/users/:userId/preferences", ng.updateUserPreferences)
        
        // Templates
        v1.GET("/templates", ng.getTemplates)
        v1.POST("/templates", ng.createTemplate)
        
        // Analytics
        v1.GET("/analytics/delivery-stats", ng.getDeliveryStats)
        v1.GET("/analytics/channel-performance", ng.getChannelPerformance)
    }

    // Health check
    router.GET("/health", func(c *gin.Context) {
        health := ng.getSystemHealth()
        if health.Status == "healthy" {
            c.JSON(http.StatusOK, health)
        } else {
            c.JSON(http.StatusServiceUnavailable, health)
        }
    })

    // Metrics endpoint
    router.GET("/metrics", func(c *gin.Context) {
        c.JSON(http.StatusOK, ng.metrics.GetAll())
    })

    port := ng.config.Port
    if port == "" {
        port = "8080"
    }

    log.Printf("Starting HTTP server on port %s", port)
    log.Fatal(http.ListenAndServe(":"+port, router))
}

// HTTP Handlers

func (ng *NotificationGateway) sendNotification(c *gin.Context) {
    var request NotificationRequest
    if err := c.ShouldBindJSON(&request); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }

    // Validate request
    if err := ng.validateNotificationRequest(&request); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }

    // Set default values
    if request.ID == "" {
        request.ID = ng.generateID()
    }
    request.CreatedAt = time.Now()

    // Send to Kafka for processing
    message := kafka.Message{
        Key:   []byte(request.ID),
        Value: mustMarshal(request),
    }

    if err := ng.kafkaWriter.WriteMessages(ng.ctx, message); err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to queue notification"})
        return
    }

    ng.metrics.IncrementCounter("notifications_received")

    c.JSON(http.StatusAccepted, gin.H{
        "id":      request.ID,
        "status":  "accepted",
        "message": "Notification queued for processing",
    })
}

func (ng *NotificationGateway) sendBatchNotifications(c *gin.Context) {
    var requests []NotificationRequest
    if err := c.ShouldBindJSON(&requests); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }

    if len(requests) > 1000 {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Maximum 1000 notifications per batch"})
        return
    }

    var messages []kafka.Message
    var responseIDs []string

    for i, request := range requests {
        // Validate and set defaults
        if err := ng.validateNotificationRequest(&request); err != nil {
            c.JSON(http.StatusBadRequest, gin.H{
                "error": fmt.Sprintf("Request %d: %s", i, err.Error()),
            })
            return
        }

        if request.ID == "" {
            request.ID = ng.generateID()
        }
        request.CreatedAt = time.Now()

        messages = append(messages, kafka.Message{
            Key:   []byte(request.ID),
            Value: mustMarshal(request),
        })
        responseIDs = append(responseIDs, request.ID)
    }

    // Send batch to Kafka
    if err := ng.kafkaWriter.WriteMessages(ng.ctx, messages...); err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to queue notifications"})
        return
    }

    ng.metrics.AddToCounter("notifications_received", float64(len(requests)))

    c.JSON(http.StatusAccepted, gin.H{
        "ids":     responseIDs,
        "count":   len(requests),
        "status":  "accepted",
        "message": "Notifications queued for processing",
    })
}

// Utility functions

func (ng *NotificationGateway) generateID() string {
    return fmt.Sprintf("notif_%d_%s", time.Now().UnixNano(), randomString(8))
}

func (ng *NotificationGateway) validateNotificationRequest(request *NotificationRequest) error {
    if request.Template == "" {
        return fmt.Errorf("template is required")
    }
    if len(request.Channels) == 0 {
        return fmt.Errorf("at least one channel is required")
    }
    if request.UserID == "" && len(request.UserIDs) == 0 {
        return fmt.Errorf("user_id or user_ids is required")
    }
    return nil
}

func loadConfig() *Config {
    return &Config{
        Port:                  getEnv("PORT", "8080"),
        RedisAddr:             getEnv("REDIS_ADDR", "localhost:6379"),
        MongoURI:              getEnv("MONGO_URI", "mongodb://localhost:27017"),
        KafkaBootstrapServers: getEnv("KAFKA_SERVERS", "localhost:9092"),
        MaxWorkers:            10,
        BatchSize:             100,
        RateLimitPerMinute:    1000,
        DeliveryRetries:       3,
        Templates:             loadTemplates(),
    }
}

func getEnv(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}

func mustMarshal(v interface{}) []byte {
    data, _ := json.Marshal(v)
    return data
}

func randomString(length int) string {
    const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
    b := make([]byte, length)
    for i := range b {
        b[i] = charset[rand.Intn(len(charset))]
    }
    return string(b)
}