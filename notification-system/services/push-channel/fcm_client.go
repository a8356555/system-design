package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "sync"
    "time"

    firebase "firebase.google.com/go/v4"
    "firebase.google.com/go/v4/messaging"
    "google.golang.org/api/option"
)

// FCMClient handles Firebase Cloud Messaging for Android and web push notifications
type FCMClient struct {
    client       *messaging.Client
    config       *FCMConfig
    rateLimiter  *TokenBucketRateLimiter
    metrics      *FCMMetrics
    mu           sync.RWMutex
    healthStatus bool
}

// FCMConfig holds Firebase configuration
type FCMConfig struct {
    ProjectID           string `json:"project_id"`
    PrivateKeyID        string `json:"private_key_id"`
    PrivateKey          string `json:"private_key"`
    ClientEmail         string `json:"client_email"`
    ClientID            string `json:"client_id"`
    AuthURI             string `json:"auth_uri"`
    TokenURI            string `json:"token_uri"`
    ServiceAccountPath  string `json:"service_account_path"`
    MaxRetries          int    `json:"max_retries"`
    BatchSize           int    `json:"batch_size"`
    RateLimitPerSecond  int    `json:"rate_limit_per_second"`
}

// FCMMetrics tracks Firebase messaging metrics
type FCMMetrics struct {
    MessagesSent      int64     `json:"messages_sent"`
    MessagesDelivered int64     `json:"messages_delivered"`
    MessagesFailed    int64     `json:"messages_failed"`
    TokensInvalidated int64     `json:"tokens_invalidated"`
    LastHealthCheck   time.Time `json:"last_health_check"`
    mu                sync.RWMutex
}

// FCMMessage represents a Firebase Cloud Message
type FCMMessage struct {
    Token        string            `json:"token"`
    Title        string            `json:"title"`
    Body         string            `json:"body"`
    Data         map[string]string `json:"data,omitempty"`
    ImageURL     string            `json:"image_url,omitempty"`
    ClickAction  string            `json:"click_action,omitempty"`
    Priority     string            `json:"priority"` // normal, high
    TimeToLive   int               `json:"ttl,omitempty"`
    CollapseKey  string            `json:"collapse_key,omitempty"`
    Badge        int               `json:"badge,omitempty"`
    Sound        string            `json:"sound,omitempty"`
    Category     string            `json:"category,omitempty"`
    ContentAvailable bool          `json:"content_available,omitempty"`
}

// FCMResponse represents the response from FCM
type FCMResponse struct {
    MessageID    string `json:"message_id"`
    Success      bool   `json:"success"`
    Error        string `json:"error,omitempty"`
    ErrorCode    string `json:"error_code,omitempty"`
    CanonicalID  string `json:"canonical_id,omitempty"`
    TokenInvalid bool   `json:"token_invalid"`
}

// TokenBucketRateLimiter implements token bucket algorithm for rate limiting
type TokenBucketRateLimiter struct {
    capacity     int
    tokens       int
    refillRate   int // tokens per second
    lastRefill   time.Time
    mu           sync.Mutex
}

// NewFCMClient creates a new Firebase Cloud Messaging client
func NewFCMClient(config *FCMConfig) (*FCMClient, error) {
    // Initialize Firebase app
    opt := option.WithCredentialsFile(config.ServiceAccountPath)
    app, err := firebase.NewApp(context.Background(), nil, opt)
    if err != nil {
        return nil, fmt.Errorf("error initializing firebase app: %w", err)
    }

    // Get messaging client
    client, err := app.Messaging(context.Background())
    if err != nil {
        return nil, fmt.Errorf("error getting messaging client: %w", err)
    }

    // Initialize rate limiter
    rateLimiter := &TokenBucketRateLimiter{
        capacity:   config.RateLimitPerSecond * 10, // 10 seconds buffer
        tokens:     config.RateLimitPerSecond * 10,
        refillRate: config.RateLimitPerSecond,
        lastRefill: time.Now(),
    }

    fcmClient := &FCMClient{
        client:       client,
        config:       config,
        rateLimiter:  rateLimiter,
        metrics:      &FCMMetrics{},
        healthStatus: true,
    }

    // Start health check routine
    go fcmClient.healthCheckRoutine()

    log.Printf("FCM client initialized for project: %s", config.ProjectID)
    return fcmClient, nil
}

// SendMessage sends a single FCM message
func (f *FCMClient) SendMessage(ctx context.Context, fcmMsg *FCMMessage) (*FCMResponse, error) {
    // Check rate limiting
    if !f.rateLimiter.Allow() {
        return &FCMResponse{
            Success: false,
            Error:   "Rate limit exceeded",
        }, fmt.Errorf("rate limit exceeded")
    }

    // Build Firebase message
    message := &messaging.Message{
        Token: fcmMsg.Token,
        Notification: &messaging.Notification{
            Title:    fcmMsg.Title,
            Body:     fcmMsg.Body,
            ImageURL: fcmMsg.ImageURL,
        },
        Data: fcmMsg.Data,
        Android: &messaging.AndroidConfig{
            Priority: fcmMsg.Priority,
            TTL:      time.Duration(fcmMsg.TimeToLive) * time.Second,
            Notification: &messaging.AndroidNotification{
                ClickAction: fcmMsg.ClickAction,
                Sound:       fcmMsg.Sound,
                Badge:       &fcmMsg.Badge,
            },
            CollapseKey: fcmMsg.CollapseKey,
        },
        APNS: &messaging.APNSConfig{
            Payload: &messaging.APNSPayload{
                Aps: &messaging.Aps{
                    Badge:            &fcmMsg.Badge,
                    Sound:            fcmMsg.Sound,
                    Category:         fcmMsg.Category,
                    ContentAvailable: fcmMsg.ContentAvailable,
                },
            },
        },
        Webpush: &messaging.WebpushConfig{
            Notification: &messaging.WebpushNotification{
                Title:       fcmMsg.Title,
                Body:        fcmMsg.Body,
                Icon:        fcmMsg.ImageURL,
                Badge:       fcmMsg.ImageURL,
                RequireInteraction: fcmMsg.Priority == "high",
            },
            FCMOptions: &messaging.WebpushFCMOptions{
                Link: fcmMsg.ClickAction,
            },
        },
    }

    // Send with retries
    var response *FCMResponse
    var err error

    for attempt := 0; attempt <= f.config.MaxRetries; attempt++ {
        response, err = f.sendWithRetry(ctx, message, attempt)
        if err == nil && response.Success {
            break
        }

        if attempt < f.config.MaxRetries {
            backoffDelay := time.Duration(attempt*attempt) * time.Second
            time.Sleep(backoffDelay)
            log.Printf("FCM send attempt %d failed, retrying in %v", attempt+1, backoffDelay)
        }
    }

    // Update metrics
    f.updateMetrics(response, err)

    return response, err
}

// sendWithRetry attempts to send a message with exponential backoff
func (f *FCMClient) sendWithRetry(ctx context.Context, message *messaging.Message, attempt int) (*FCMResponse, error) {
    // Add timeout context
    sendCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
    defer cancel()

    messageID, err := f.client.Send(sendCtx, message)
    if err != nil {
        // Parse Firebase error
        response := &FCMResponse{
            Success: false,
            Error:   err.Error(),
        }

        // Handle specific error types
        if messaging.IsRegistrationTokenNotRegistered(err) {
            response.TokenInvalid = true
            response.ErrorCode = "registration-token-not-registered"
        } else if messaging.IsInvalidArgument(err) {
            response.ErrorCode = "invalid-argument"
        } else if messaging.IsQuotaExceeded(err) {
            response.ErrorCode = "quota-exceeded"
        } else if messaging.IsUnavailable(err) {
            response.ErrorCode = "unavailable"
        }

        return response, err
    }

    return &FCMResponse{
        MessageID: messageID,
        Success:   true,
    }, nil
}

// SendBatchMessages sends multiple FCM messages in batch
func (f *FCMClient) SendBatchMessages(ctx context.Context, messages []*FCMMessage) ([]*FCMResponse, error) {
    if len(messages) == 0 {
        return nil, fmt.Errorf("no messages to send")
    }

    // Process in chunks of batch size
    var allResponses []*FCMResponse
    chunkSize := f.config.BatchSize
    if chunkSize <= 0 {
        chunkSize = 500 // Default FCM batch limit
    }

    for i := 0; i < len(messages); i += chunkSize {
        end := i + chunkSize
        if end > len(messages) {
            end = len(messages)
        }

        chunk := messages[i:end]
        responses, err := f.sendBatch(ctx, chunk)
        if err != nil {
            log.Printf("Error sending batch chunk %d-%d: %v", i, end-1, err)
            // Create error responses for failed chunk
            for range chunk {
                allResponses = append(allResponses, &FCMResponse{
                    Success: false,
                    Error:   err.Error(),
                })
            }
        } else {
            allResponses = append(allResponses, responses...)
        }

        // Rate limiting between batches
        time.Sleep(100 * time.Millisecond)
    }

    return allResponses, nil
}

// sendBatch sends a batch of messages using FCM batch API
func (f *FCMClient) sendBatch(ctx context.Context, messages []*FCMMessage) ([]*FCMResponse, error) {
    // Convert to Firebase messages
    var firebaseMessages []*messaging.Message
    for _, fcmMsg := range messages {
        message := &messaging.Message{
            Token: fcmMsg.Token,
            Notification: &messaging.Notification{
                Title:    fcmMsg.Title,
                Body:     fcmMsg.Body,
                ImageURL: fcmMsg.ImageURL,
            },
            Data: fcmMsg.Data,
        }
        firebaseMessages = append(firebaseMessages, message)
    }

    // Send batch
    batchResponse, err := f.client.SendAll(ctx, firebaseMessages)
    if err != nil {
        return nil, fmt.Errorf("error sending batch: %w", err)
    }

    // Process responses
    var responses []*FCMResponse
    for i, response := range batchResponse.Responses {
        fcmResponse := &FCMResponse{
            Success: response.Success,
        }

        if response.Success {
            fcmResponse.MessageID = response.MessageID
        } else {
            fcmResponse.Error = response.Error.Error()
            
            // Handle specific error types for batch responses
            if messaging.IsRegistrationTokenNotRegistered(response.Error) {
                fcmResponse.TokenInvalid = true
                fcmResponse.ErrorCode = "registration-token-not-registered"
            }
        }

        responses = append(responses, fcmResponse)
        f.updateMetrics(fcmResponse, response.Error)
    }

    log.Printf("Sent batch of %d messages, success: %d, failed: %d", 
        len(messages), batchResponse.SuccessCount, batchResponse.FailureCount)

    return responses, nil
}

// SendTopicMessage sends a message to a topic
func (f *FCMClient) SendTopicMessage(ctx context.Context, topic string, fcmMsg *FCMMessage) (*FCMResponse, error) {
    message := &messaging.Message{
        Topic: topic,
        Notification: &messaging.Notification{
            Title:    fcmMsg.Title,
            Body:     fcmMsg.Body,
            ImageURL: fcmMsg.ImageURL,
        },
        Data: fcmMsg.Data,
    }

    messageID, err := f.client.Send(ctx, message)
    if err != nil {
        response := &FCMResponse{
            Success: false,
            Error:   err.Error(),
        }
        f.updateMetrics(response, err)
        return response, err
    }

    response := &FCMResponse{
        MessageID: messageID,
        Success:   true,
    }
    f.updateMetrics(response, nil)

    return response, nil
}

// SubscribeToTopic subscribes device tokens to a topic
func (f *FCMClient) SubscribeToTopic(ctx context.Context, tokens []string, topic string) error {
    if len(tokens) == 0 {
        return fmt.Errorf("no tokens provided")
    }

    // FCM allows up to 1000 tokens per request
    chunkSize := 1000
    for i := 0; i < len(tokens); i += chunkSize {
        end := i + chunkSize
        if end > len(tokens) {
            end = len(tokens)
        }

        chunk := tokens[i:end]
        response, err := f.client.SubscribeToTopic(ctx, chunk, topic)
        if err != nil {
            return fmt.Errorf("error subscribing to topic: %w", err)
        }

        log.Printf("Subscribed %d tokens to topic %s, success: %d, failed: %d", 
            len(chunk), topic, response.SuccessCount, response.FailureCount)
    }

    return nil
}

// UnsubscribeFromTopic unsubscribes device tokens from a topic
func (f *FCMClient) UnsubscribeFromTopic(ctx context.Context, tokens []string, topic string) error {
    if len(tokens) == 0 {
        return fmt.Errorf("no tokens provided")
    }

    chunkSize := 1000
    for i := 0; i < len(tokens); i += chunkSize {
        end := i + chunkSize
        if end > len(tokens) {
            end = len(tokens)
        }

        chunk := tokens[i:end]
        response, err := f.client.UnsubscribeFromTopic(ctx, chunk, topic)
        if err != nil {
            return fmt.Errorf("error unsubscribing from topic: %w", err)
        }

        log.Printf("Unsubscribed %d tokens from topic %s, success: %d, failed: %d", 
            len(chunk), topic, response.SuccessCount, response.FailureCount)
    }

    return nil
}

// GetMetrics returns current FCM metrics
func (f *FCMClient) GetMetrics() *FCMMetrics {
    f.metrics.mu.RLock()
    defer f.metrics.mu.RUnlock()

    return &FCMMetrics{
        MessagesSent:      f.metrics.MessagesSent,
        MessagesDelivered: f.metrics.MessagesDelivered,
        MessagesFailed:    f.metrics.MessagesFailed,
        TokensInvalidated: f.metrics.TokensInvalidated,
        LastHealthCheck:   f.metrics.LastHealthCheck,
    }
}

// IsHealthy returns the current health status
func (f *FCMClient) IsHealthy() bool {
    f.mu.RLock()
    defer f.mu.RUnlock()
    return f.healthStatus
}

// updateMetrics updates internal metrics
func (f *FCMClient) updateMetrics(response *FCMResponse, err error) {
    f.metrics.mu.Lock()
    defer f.metrics.mu.Unlock()

    f.metrics.MessagesSent++

    if err != nil || !response.Success {
        f.metrics.MessagesFailed++
        if response != nil && response.TokenInvalid {
            f.metrics.TokensInvalidated++
        }
    } else {
        f.metrics.MessagesDelivered++
    }
}

// healthCheckRoutine performs periodic health checks
func (f *FCMClient) healthCheckRoutine() {
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()

    for range ticker.C {
        f.performHealthCheck()
    }
}

// performHealthCheck checks if FCM service is responsive
func (f *FCMClient) performHealthCheck() {
    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()

    // Send a test message to a fake token to check service availability
    testMessage := &messaging.Message{
        Token: "fake-token-for-health-check",
        Notification: &messaging.Notification{
            Title: "Health Check",
            Body:  "This is a health check message",
        },
    }

    _, err := f.client.Send(ctx, testMessage)
    
    f.mu.Lock()
    f.metrics.mu.Lock()
    
    // We expect this to fail with "registration-token-not-registered" 
    // which means the service is working
    if err != nil && messaging.IsRegistrationTokenNotRegistered(err) {
        f.healthStatus = true
    } else if err == nil {
        // Unexpected success (shouldn't happen with fake token)
        f.healthStatus = true
    } else {
        // Other errors indicate service issues
        f.healthStatus = false
        log.Printf("FCM health check failed: %v", err)
    }
    
    f.metrics.LastHealthCheck = time.Now()
    f.metrics.mu.Unlock()
    f.mu.Unlock()
}

// Token bucket rate limiter implementation

// Allow checks if an operation is allowed under the current rate limit
func (tb *TokenBucketRateLimiter) Allow() bool {
    tb.mu.Lock()
    defer tb.mu.Unlock()

    now := time.Now()
    elapsed := now.Sub(tb.lastRefill)
    
    // Refill tokens based on elapsed time
    tokensToAdd := int(elapsed.Seconds()) * tb.refillRate
    if tokensToAdd > 0 {
        tb.tokens += tokensToAdd
        if tb.tokens > tb.capacity {
            tb.tokens = tb.capacity
        }
        tb.lastRefill = now
    }

    // Check if we have tokens available
    if tb.tokens > 0 {
        tb.tokens--
        return true
    }

    return false
}

// AllowN checks if N operations are allowed
func (tb *TokenBucketRateLimiter) AllowN(n int) bool {
    tb.mu.Lock()
    defer tb.mu.Unlock()

    now := time.Now()
    elapsed := now.Sub(tb.lastRefill)
    
    // Refill tokens
    tokensToAdd := int(elapsed.Seconds()) * tb.refillRate
    if tokensToAdd > 0 {
        tb.tokens += tokensToAdd
        if tb.tokens > tb.capacity {
            tb.tokens = tb.capacity
        }
        tb.lastRefill = now
    }

    // Check if we have enough tokens
    if tb.tokens >= n {
        tb.tokens -= n
        return true
    }

    return false
}