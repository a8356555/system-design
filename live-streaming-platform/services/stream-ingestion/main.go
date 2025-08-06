package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "os"
    "os/exec"
    "path/filepath"
    "sync"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    "github.com/gorilla/websocket"
)

// StreamIngestionService handles RTMP stream ingestion and processing
type StreamIngestionService struct {
    redisClient    *redis.Client
    activeStreams  map[string]*ActiveStream
    streamsMutex   sync.RWMutex
    upgrader       websocket.Upgrader
    config         *Config
}

// ActiveStream represents an active streaming session
type ActiveStream struct {
    StreamKey    string            `json:"stream_key"`
    StreamerID   string            `json:"streamer_id"`
    Title        string            `json:"title"`
    Category     string            `json:"category"`
    StartTime    time.Time         `json:"start_time"`
    ViewerCount  int64             `json:"viewer_count"`
    Status       string            `json:"status"` // "live", "starting", "stopping", "ended"
    Bitrates     []int             `json:"bitrates"` // Available bitrates
    InputURL     string            `json:"input_url"`
    OutputURLs   map[string]string `json:"output_urls"` // bitrate -> URL mapping
    FFmpegCmd    *exec.Cmd         `json:"-"`
    Metadata     map[string]interface{} `json:"metadata"`
}

// Config holds service configuration
type Config struct {
    RTMPPort         string
    HTTPPort         string
    RedisAddr        string
    CDNBaseURL       string
    HLSOutputDir     string
    DASHOutputDir    string
    FFmpegPath       string
    MaxStreams       int
    DefaultBitrates  []int
}

// StreamEvent represents stream lifecycle events
type StreamEvent struct {
    Type      string      `json:"type"`
    StreamKey string      `json:"stream_key"`
    Data      interface{} `json:"data"`
    Timestamp time.Time   `json:"timestamp"`
}

func main() {
    config := loadConfig()
    
    redisClient := redis.NewClient(&redis.Options{
        Addr: config.RedisAddr,
    })
    
    service := &StreamIngestionService{
        redisClient:   redisClient,
        activeStreams: make(map[string]*ActiveStream),
        config:        config,
        upgrader: websocket.Upgrader{
            CheckOrigin: func(r *http.Request) bool { return true },
        },
    }
    
    // Start RTMP server
    go service.startRTMPServer()
    
    // Start HTTP API server
    service.startHTTPServer()
}

// startRTMPServer starts the RTMP ingestion server using nginx-rtmp
func (s *StreamIngestionService) startRTMPServer() {
    // Generate nginx-rtmp configuration
    configPath := s.generateNginxConfig()
    
    // Start nginx with RTMP module
    cmd := exec.Command("nginx", "-c", configPath)
    if err := cmd.Start(); err != nil {
        log.Fatalf("Failed to start RTMP server: %v", err)
    }
    
    log.Printf("RTMP server started on port %s", s.config.RTMPPort)
    cmd.Wait()
}

// generateNginxConfig creates nginx-rtmp configuration
func (s *StreamIngestionService) generateNginxConfig() string {
    configTemplate := fmt.Sprintf(`
worker_processes auto;
events {
    worker_connections 1024;
}

http {
    access_log /var/log/nginx/access.log;
    
    server {
        listen 8080;
        location /hls {
            types {
                application/vnd.apple.mpegurl m3u8;
                video/mp2t ts;
            }
            root %s;
            add_header Cache-Control no-cache;
            add_header Access-Control-Allow-Origin *;
        }
        
        location /dash {
            root %s;
            add_header Cache-Control no-cache;
            add_header Access-Control-Allow-Origin *;
        }
        
        location /stats {
            rtmp_stat all;
            rtmp_stat_stylesheet stat.xsl;
        }
    }
}

rtmp {
    server {
        listen %s;
        chunk_size 4096;
        
        application live {
            live on;
            
            # HLS settings
            hls on;
            hls_path %s;
            hls_fragment 2s;
            hls_playlist_length 6s;
            
            # DASH settings  
            dash on;
            dash_path %s;
            dash_fragment 2s;
            dash_playlist_length 6s;
            
            # Authentication
            on_publish http://localhost:%s/api/auth/stream;
            on_publish_done http://localhost:%s/api/events/publish_done;
            
            # Multiple bitrate transcoding
            exec_push ffmpeg -i rtmp://localhost:%s/live/$name
                -c:v libx264 -preset veryfast -tune zerolatency
                -c:a aac -b:a 128k -ar 44100
                -f flv rtmp://localhost:%s/live/$name_720p
                
                -c:v libx264 -preset veryfast -tune zerolatency  
                -s 854x480 -b:v 1000k -maxrate 1000k -bufsize 2000k
                -c:a aac -b:a 96k -ar 44100
                -f flv rtmp://localhost:%s/live/$name_480p
                
                -c:v libx264 -preset veryfast -tune zerolatency
                -s 640x360 -b:v 500k -maxrate 500k -bufsize 1000k  
                -c:a aac -b:a 64k -ar 44100
                -f flv rtmp://localhost:%s/live/$name_360p;
        }
        
        # Internal transcoding streams
        application transcode {
            live on;
            allow publish 127.0.0.1;
            deny publish all;
            
            hls on;
            hls_path %s;
            hls_variant _720p BANDWIDTH=2048000;
            hls_variant _480p BANDWIDTH=1024000;  
            hls_variant _360p BANDWIDTH=512000;
        }
    }
}
`, s.config.HLSOutputDir, s.config.DASHOutputDir, s.config.RTMPPort,
   s.config.HLSOutputDir, s.config.DASHOutputDir, s.config.HTTPPort, s.config.HTTPPort,
   s.config.RTMPPort, s.config.RTMPPort, s.config.RTMPPort, s.config.RTMPPort, s.config.HLSOutputDir)
    
    configPath := "/tmp/nginx-rtmp.conf"
    if err := os.WriteFile(configPath, []byte(configTemplate), 0644); err != nil {
        log.Fatalf("Failed to write nginx config: %v", err)
    }
    
    return configPath
}

// startHTTPServer starts the HTTP API server
func (s *StreamIngestionService) startHTTPServer() {
    gin.SetMode(gin.ReleaseMode)
    router := gin.New()
    router.Use(gin.Logger(), gin.Recovery())
    
    // Stream authentication
    router.POST("/api/auth/stream", s.authenticateStream)
    
    // Stream events
    router.POST("/api/events/publish_done", s.handleStreamEnd)
    
    // Stream management
    api := router.Group("/api/v1")
    {
        api.GET("/streams", s.getActiveStreams)
        api.GET("/streams/:key", s.getStream)
        api.POST("/streams/:key/start", s.startStream)
        api.POST("/streams/:key/stop", s.stopStream)
        api.GET("/streams/:key/stats", s.getStreamStats)
        api.WebSocket("/streams/:key/ws", s.handleWebSocket)
    }
    
    // Health check
    router.GET("/health", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{
            "status": "healthy",
            "active_streams": len(s.activeStreams),
            "timestamp": time.Now(),
        })
    })
    
    log.Printf("HTTP API server starting on port %s", s.config.HTTPPort)
    log.Fatal(http.ListenAndServe(":"+s.config.HTTPPort, router))
}

// authenticateStream validates stream key and permissions
func (s *StreamIngestionService) authenticateStream(c *gin.Context) {
    streamKey := c.PostForm("name")
    clientIP := c.ClientIP()
    
    log.Printf("Stream authentication request: key=%s, ip=%s", streamKey, clientIP)
    
    // Validate stream key from Redis
    ctx := context.Background()
    streamInfo, err := s.redisClient.HGetAll(ctx, fmt.Sprintf("stream:%s", streamKey)).Result()
    if err != nil || len(streamInfo) == 0 {
        log.Printf("Invalid stream key: %s", streamKey)
        c.Status(http.StatusForbidden)
        return
    }
    
    // Check if stream is already active
    s.streamsMutex.RLock()
    if _, exists := s.activeStreams[streamKey]; exists {
        s.streamsMutex.RUnlock()
        log.Printf("Stream already active: %s", streamKey)
        c.Status(http.StatusConflict)
        return
    }
    s.streamsMutex.RUnlock()
    
    // Create active stream record
    stream := &ActiveStream{
        StreamKey:   streamKey,
        StreamerID:  streamInfo["streamer_id"],
        Title:       streamInfo["title"],
        Category:    streamInfo["category"],
        StartTime:   time.Now(),
        Status:      "starting",
        Bitrates:    s.config.DefaultBitrates,
        InputURL:    fmt.Sprintf("rtmp://localhost:%s/live/%s", s.config.RTMPPort, streamKey),
        OutputURLs:  make(map[string]string),
        Metadata:    make(map[string]interface{}),
    }
    
    // Generate output URLs for different bitrates
    for _, bitrate := range s.config.DefaultBitrates {
        suffix := fmt.Sprintf("_%dp", getBitrateHeight(bitrate))
        stream.OutputURLs[fmt.Sprintf("%d", bitrate)] = fmt.Sprintf("%s/hls/%s%s.m3u8", s.config.CDNBaseURL, streamKey, suffix)
    }
    
    s.streamsMutex.Lock()
    s.activeStreams[streamKey] = stream
    s.streamsMutex.Unlock()
    
    // Publish stream start event
    s.publishStreamEvent("stream_started", streamKey, stream)
    
    // Update Redis with stream status
    s.redisClient.HSet(ctx, fmt.Sprintf("stream:%s", streamKey), "status", "live", "start_time", time.Now().Unix())
    
    log.Printf("Stream authenticated and started: %s", streamKey)
    c.Status(http.StatusOK)
}

// handleStreamEnd handles stream termination
func (s *StreamIngestionService) handleStreamEnd(c *gin.Context) {
    streamKey := c.PostForm("name")
    
    log.Printf("Stream ended: %s", streamKey)
    
    s.streamsMutex.Lock()
    if stream, exists := s.activeStreams[streamKey]; exists {
        stream.Status = "ended"
        delete(s.activeStreams, streamKey)
        
        // Kill FFmpeg process if running
        if stream.FFmpegCmd != nil && stream.FFmpegCmd.Process != nil {
            stream.FFmpegCmd.Process.Kill()
        }
        
        // Publish stream end event
        s.publishStreamEvent("stream_ended", streamKey, stream)
        
        // Update Redis
        ctx := context.Background()
        s.redisClient.HSet(ctx, fmt.Sprintf("stream:%s", streamKey), "status", "ended", "end_time", time.Now().Unix())
    }
    s.streamsMutex.Unlock()
    
    c.Status(http.StatusOK)
}

// getActiveStreams returns list of currently active streams
func (s *StreamIngestionService) getActiveStreams(c *gin.Context) {
    s.streamsMutex.RLock()
    streams := make([]*ActiveStream, 0, len(s.activeStreams))
    for _, stream := range s.activeStreams {
        streams = append(streams, stream)
    }
    s.streamsMutex.RUnlock()
    
    c.JSON(http.StatusOK, gin.H{
        "streams": streams,
        "count":   len(streams),
    })
}

// getStream returns details of a specific stream
func (s *StreamIngestionService) getStream(c *gin.Context) {
    streamKey := c.Param("key")
    
    s.streamsMutex.RLock()
    stream, exists := s.activeStreams[streamKey]
    s.streamsMutex.RUnlock()
    
    if !exists {
        c.JSON(http.StatusNotFound, gin.H{"error": "Stream not found"})
        return
    }
    
    c.JSON(http.StatusOK, stream)
}

// startStream manually starts a stream (for testing)
func (s *StreamIngestionService) startStream(c *gin.Context) {
    streamKey := c.Param("key")
    
    // Implementation for manual stream start
    c.JSON(http.StatusOK, gin.H{"message": "Stream start initiated", "stream_key": streamKey})
}

// stopStream manually stops a stream
func (s *StreamIngestionService) stopStream(c *gin.Context) {
    streamKey := c.Param("key")
    
    s.streamsMutex.Lock()
    if stream, exists := s.activeStreams[streamKey]; exists {
        stream.Status = "stopping"
        if stream.FFmpegCmd != nil && stream.FFmpegCmd.Process != nil {
            stream.FFmpegCmd.Process.Kill()
        }
    }
    s.streamsMutex.Unlock()
    
    c.JSON(http.StatusOK, gin.H{"message": "Stream stop initiated", "stream_key": streamKey})
}

// getStreamStats returns real-time stream statistics
func (s *StreamIngestionService) getStreamStats(c *gin.Context) {
    streamKey := c.Param("key")
    
    // Get viewer count from Redis
    ctx := context.Background()
    viewerCount, _ := s.redisClient.Get(ctx, fmt.Sprintf("viewers:%s", streamKey)).Int64()
    
    s.streamsMutex.RLock()
    stream, exists := s.activeStreams[streamKey]
    s.streamsMutex.RUnlock()
    
    if !exists {
        c.JSON(http.StatusNotFound, gin.H{"error": "Stream not found"})
        return
    }
    
    stats := gin.H{
        "stream_key":    streamKey,
        "viewer_count":  viewerCount,
        "uptime":        time.Since(stream.StartTime),
        "status":        stream.Status,
        "bitrates":      stream.Bitrates,
        "last_updated":  time.Now(),
    }
    
    c.JSON(http.StatusOK, stats)
}

// handleWebSocket manages WebSocket connections for real-time updates
func (s *StreamIngestionService) handleWebSocket(c *gin.Context) {
    streamKey := c.Param("key")
    
    conn, err := s.upgrader.Upgrade(c.Writer, c.Request, nil)
    if err != nil {
        log.Printf("WebSocket upgrade error: %v", err)
        return
    }
    defer conn.Close()
    
    // Subscribe to stream events
    ctx := context.Background()
    pubsub := s.redisClient.Subscribe(ctx, fmt.Sprintf("stream_events:%s", streamKey))
    defer pubsub.Close()
    
    // Send current stream status
    s.streamsMutex.RLock()
    if stream, exists := s.activeStreams[streamKey]; exists {
        conn.WriteJSON(gin.H{
            "type": "stream_status",
            "data": stream,
        })
    }
    s.streamsMutex.RUnlock()
    
    // Listen for events
    ch := pubsub.Channel()
    for msg := range ch {
        var event StreamEvent
        if err := json.Unmarshal([]byte(msg.Payload), &event); err != nil {
            continue
        }
        
        if err := conn.WriteJSON(event); err != nil {
            log.Printf("WebSocket write error: %v", err)
            break
        }
    }
}

// publishStreamEvent publishes stream events to Redis
func (s *StreamIngestionService) publishStreamEvent(eventType, streamKey string, data interface{}) {
    event := StreamEvent{
        Type:      eventType,
        StreamKey: streamKey,
        Data:      data,
        Timestamp: time.Now(),
    }
    
    eventJSON, _ := json.Marshal(event)
    ctx := context.Background()
    s.redisClient.Publish(ctx, fmt.Sprintf("stream_events:%s", streamKey), eventJSON)
    s.redisClient.Publish(ctx, "stream_events:all", eventJSON)
}

// Utility functions

func loadConfig() *Config {
    return &Config{
        RTMPPort:        getEnv("RTMP_PORT", "1935"),
        HTTPPort:        getEnv("HTTP_PORT", "8080"),
        RedisAddr:       getEnv("REDIS_ADDR", "localhost:6379"),
        CDNBaseURL:      getEnv("CDN_BASE_URL", "http://localhost:8080"),
        HLSOutputDir:    getEnv("HLS_OUTPUT_DIR", "/tmp/hls"),
        DASHOutputDir:   getEnv("DASH_OUTPUT_DIR", "/tmp/dash"),
        FFmpegPath:      getEnv("FFMPEG_PATH", "ffmpeg"),
        MaxStreams:      100,
        DefaultBitrates: []int{1080, 720, 480, 360},
    }
}

func getEnv(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}

func getBitrateHeight(bitrate int) int {
    switch bitrate {
    case 1080:
        return 1080
    case 720:
        return 720
    case 480:
        return 480
    case 360:
        return 360
    default:
        return 720
    }
}