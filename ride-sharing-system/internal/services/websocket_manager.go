package services

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "sync"
    "time"

    "ride-sharing-system/internal/models"

    "github.com/gin-gonic/gin"
    "github.com/gorilla/websocket"
    "github.com/go-redis/redis/v8"
)

// WebSocketManager manages real-time WebSocket connections for drivers and riders
type WebSocketManager struct {
    upgrader      websocket.Upgrader
    connections   map[string]*Connection // userID -> connection
    connectionsMu sync.RWMutex
    redisClient   *redis.Client
    locationService *LocationService
    matchingEngine  *MatchingEngine
    broadcast     chan BroadcastMessage
    register      chan *Connection
    unregister    chan *Connection
    done          chan struct{}
}

// Connection represents a WebSocket connection with user context
type Connection struct {
    ID       string
    UserID   string
    UserType string // "driver" or "rider"
    Conn     *websocket.Conn
    Send     chan []byte
    Manager  *WebSocketManager
}

// WebSocketMessage represents the structure of WebSocket messages
type WebSocketMessage struct {
    Type      string      `json:"type"`
    UserID    string      `json:"user_id,omitempty"`
    UserType  string      `json:"user_type,omitempty"`
    Data      interface{} `json:"data"`
    Timestamp time.Time   `json:"timestamp"`
}

// BroadcastMessage represents a message to be broadcasted
type BroadcastMessage struct {
    UserIDs  []string    `json:"user_ids,omitempty"` // Specific users, empty for all
    UserType string      `json:"user_type,omitempty"` // "driver", "rider", or empty for all
    Message  WebSocketMessage `json:"message"`
}

// LocationUpdateMessage represents location update data
type LocationUpdateMessage struct {
    Latitude  float64 `json:"latitude"`
    Longitude float64 `json:"longitude"`
    Heading   float64 `json:"heading"`
    Speed     float64 `json:"speed"`
    Status    string  `json:"status"`
}

// RideMatchMessage represents ride matching notification
type RideMatchMessage struct {
    RideRequestID string              `json:"ride_request_id"`
    Match         models.DriverMatch  `json:"match,omitempty"`
    RideRequest   models.RideRequest  `json:"ride_request,omitempty"`
    EstimatedFare float64            `json:"estimated_fare"`
    ExpiresAt     time.Time          `json:"expires_at"`
}

// NewWebSocketManager creates a new WebSocket manager
func NewWebSocketManager(redisClient *redis.Client, locationService *LocationService, 
                        matchingEngine *MatchingEngine) *WebSocketManager {
    return &WebSocketManager{
        upgrader: websocket.Upgrader{
            CheckOrigin: func(r *http.Request) bool {
                // In production, implement proper origin checking
                return true
            },
            ReadBufferSize:  1024,
            WriteBufferSize: 1024,
        },
        connections:     make(map[string]*Connection),
        redisClient:     redisClient,
        locationService: locationService,
        matchingEngine:  matchingEngine,
        broadcast:       make(chan BroadcastMessage, 256),
        register:        make(chan *Connection, 256),
        unregister:      make(chan *Connection, 256),
        done:           make(chan struct{}),
    }
}

// Start starts the WebSocket manager
func (wsm *WebSocketManager) Start() {
    go wsm.run()
    log.Println("WebSocket manager started")
}

// Stop stops the WebSocket manager
func (wsm *WebSocketManager) Stop() {
    close(wsm.done)
}

// HandleWebSocket handles WebSocket upgrade and connection
func (wsm *WebSocketManager) HandleWebSocket(c *gin.Context) {
    userID := c.Query("user_id")
    userType := c.Query("user_type")
    
    if userID == "" || userType == "" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "user_id and user_type are required"})
        return
    }
    
    if userType != "driver" && userType != "rider" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "user_type must be 'driver' or 'rider'"})
        return
    }

    conn, err := wsm.upgrader.Upgrade(c.Writer, c.Request, nil)
    if err != nil {
        log.Printf("WebSocket upgrade error: %v", err)
        return
    }

    connection := &Connection{
        ID:       generateConnectionID(),
        UserID:   userID,
        UserType: userType,
        Conn:     conn,
        Send:     make(chan []byte, 256),
        Manager:  wsm,
    }

    wsm.register <- connection
    
    // Start goroutines for this connection
    go connection.writePump()
    go connection.readPump()
}

// run handles the main event loop for the WebSocket manager
func (wsm *WebSocketManager) run() {
    for {
        select {
        case connection := <-wsm.register:
            wsm.registerConnection(connection)
            
        case connection := <-wsm.unregister:
            wsm.unregisterConnection(connection)
            
        case message := <-wsm.broadcast:
            wsm.broadcastMessage(message)
            
        case <-wsm.done:
            return
        }
    }
}

// registerConnection registers a new connection
func (wsm *WebSocketManager) registerConnection(conn *Connection) {
    wsm.connectionsMu.Lock()
    defer wsm.connectionsMu.Unlock()
    
    // Close existing connection if user is already connected
    if existingConn, exists := wsm.connections[conn.UserID]; exists {
        close(existingConn.Send)
        existingConn.Conn.Close()
    }
    
    wsm.connections[conn.UserID] = conn
    log.Printf("User %s (%s) connected via WebSocket", conn.UserID, conn.UserType)
    
    // Send welcome message
    welcomeMsg := WebSocketMessage{
        Type: "connection_established",
        Data: gin.H{
            "message": "WebSocket connection established",
            "user_id": conn.UserID,
            "user_type": conn.UserType,
        },
        Timestamp: time.Now(),
    }
    
    wsm.sendToConnection(conn, welcomeMsg)
}

// unregisterConnection unregisters a connection
func (wsm *WebSocketManager) unregisterConnection(conn *Connection) {
    wsm.connectionsMu.Lock()
    defer wsm.connectionsMu.Unlock()
    
    if _, exists := wsm.connections[conn.UserID]; exists {
        delete(wsm.connections, conn.UserID)
        close(conn.Send)
        log.Printf("User %s (%s) disconnected from WebSocket", conn.UserID, conn.UserType)
        
        // Update user status to offline if driver
        if conn.UserType == "driver" {
            wsm.updateDriverStatus(conn.UserID, "offline")
        }
    }
}

// broadcastMessage broadcasts a message to specified users or all users
func (wsm *WebSocketManager) broadcastMessage(broadcast BroadcastMessage) {
    wsm.connectionsMu.RLock()
    defer wsm.connectionsMu.RUnlock()
    
    for userID, conn := range wsm.connections {
        shouldSend := false
        
        // Check if message should be sent to this connection
        if len(broadcast.UserIDs) > 0 {
            // Send to specific users
            for _, targetUserID := range broadcast.UserIDs {
                if targetUserID == userID {
                    shouldSend = true
                    break
                }
            }
        } else if broadcast.UserType != "" {
            // Send to specific user type
            if conn.UserType == broadcast.UserType {
                shouldSend = true
            }
        } else {
            // Send to all
            shouldSend = true
        }
        
        if shouldSend {
            wsm.sendToConnection(conn, broadcast.Message)
        }
    }
}

// sendToConnection sends a message to a specific connection
func (wsm *WebSocketManager) sendToConnection(conn *Connection, message WebSocketMessage) {
    messageBytes, err := json.Marshal(message)
    if err != nil {
        log.Printf("Error marshaling message: %v", err)
        return
    }
    
    select {
    case conn.Send <- messageBytes:
    default:
        // Connection is blocked, close it
        wsm.unregister <- conn
    }
}

// SendToUser sends a message to a specific user
func (wsm *WebSocketManager) SendToUser(userID string, messageType string, data interface{}) {
    message := WebSocketMessage{
        Type:      messageType,
        Data:      data,
        Timestamp: time.Now(),
    }
    
    broadcast := BroadcastMessage{
        UserIDs: []string{userID},
        Message: message,
    }
    
    select {
    case wsm.broadcast <- broadcast:
    default:
        log.Printf("Broadcast channel full, dropping message for user %s", userID)
    }
}

// SendToUserType sends a message to all users of a specific type
func (wsm *WebSocketManager) SendToUserType(userType string, messageType string, data interface{}) {
    message := WebSocketMessage{
        Type:      messageType,
        Data:      data,
        Timestamp: time.Now(),
    }
    
    broadcast := BroadcastMessage{
        UserType: userType,
        Message:  message,
    }
    
    select {
    case wsm.broadcast <- broadcast:
    default:
        log.Printf("Broadcast channel full, dropping message for user type %s", userType)
    }
}

// Connection methods

// readPump handles incoming messages from the WebSocket connection
func (c *Connection) readPump() {
    defer func() {
        c.Manager.unregister <- c
        c.Conn.Close()
    }()
    
    c.Conn.SetReadLimit(512)
    c.Conn.SetReadDeadline(time.Now().Add(60 * time.Second))
    c.Conn.SetPongHandler(func(string) error {
        c.Conn.SetReadDeadline(time.Now().Add(60 * time.Second))
        return nil
    })
    
    for {
        var message WebSocketMessage
        err := c.Conn.ReadJSON(&message)
        if err != nil {
            if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
                log.Printf("WebSocket error: %v", err)
            }
            break
        }
        
        // Handle incoming message based on type
        c.handleMessage(message)
    }
}

// writePump handles outgoing messages to the WebSocket connection
func (c *Connection) writePump() {
    ticker := time.NewTicker(54 * time.Second)
    defer func() {
        ticker.Stop()
        c.Conn.Close()
    }()
    
    for {
        select {
        case message, ok := <-c.Send:
            c.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if !ok {
                c.Conn.WriteMessage(websocket.CloseMessage, []byte{})
                return
            }
            
            if err := c.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
                log.Printf("WebSocket write error: %v", err)
                return
            }
            
        case <-ticker.C:
            c.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if err := c.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
                return
            }
        }
    }
}

// handleMessage processes incoming WebSocket messages
func (c *Connection) handleMessage(message WebSocketMessage) {
    ctx := context.Background()
    
    switch message.Type {
    case "location_update":
        if c.UserType == "driver" {
            c.handleLocationUpdate(ctx, message)
        }
        
    case "ride_request":
        if c.UserType == "rider" {
            c.handleRideRequest(ctx, message)
        }
        
    case "accept_ride":
        if c.UserType == "driver" {
            c.handleAcceptRide(ctx, message)
        }
        
    case "cancel_ride":
        c.handleCancelRide(ctx, message)
        
    case "trip_update":
        c.handleTripUpdate(ctx, message)
        
    default:
        log.Printf("Unknown message type: %s from user %s", message.Type, c.UserID)
    }
}

// handleLocationUpdate processes location updates from drivers
func (c *Connection) handleLocationUpdate(ctx context.Context, message WebSocketMessage) {
    var locationData LocationUpdateMessage
    dataBytes, _ := json.Marshal(message.Data)
    if err := json.Unmarshal(dataBytes, &locationData); err != nil {
        log.Printf("Error parsing location data: %v", err)
        return
    }
    
    locationUpdate := models.LocationUpdate{
        UserID:   c.UserID,
        UserType: c.UserType,
        Location: models.Location{
            Latitude:  locationData.Latitude,
            Longitude: locationData.Longitude,
            Timestamp: time.Now(),
        },
        Status:  locationData.Status,
        Heading: locationData.Heading,
        Speed:   locationData.Speed,
    }
    
    // Update location in the matching engine
    if err := c.Manager.matchingEngine.UpdateDriverLocation(ctx, locationUpdate); err != nil {
        log.Printf("Error updating driver location: %v", err)
    }
    
    // Store in location service
    if err := c.Manager.locationService.UpdateLocation(ctx, locationUpdate); err != nil {
        log.Printf("Error storing location update: %v", err)
    }
}

// handleRideRequest processes ride requests from riders
func (c *Connection) handleRideRequest(ctx context.Context, message WebSocketMessage) {
    // Implementation for handling ride requests
    log.Printf("Handling ride request from user %s", c.UserID)
    // This would integrate with the matching engine to find drivers
}

// handleAcceptRide processes ride acceptance from drivers
func (c *Connection) handleAcceptRide(ctx context.Context, message WebSocketMessage) {
    log.Printf("Driver %s accepted a ride", c.UserID)
    // Implementation for handling ride acceptance
}

// handleCancelRide processes ride cancellation
func (c *Connection) handleCancelRide(ctx context.Context, message WebSocketMessage) {
    log.Printf("User %s cancelled a ride", c.UserID)
    // Implementation for handling ride cancellation
}

// handleTripUpdate processes trip status updates
func (c *Connection) handleTripUpdate(ctx context.Context, message WebSocketMessage) {
    log.Printf("Trip update from user %s", c.UserID)
    // Implementation for handling trip updates
}

// updateDriverStatus updates driver status in the system
func (wsm *WebSocketManager) updateDriverStatus(driverID, status string) {
    ctx := context.Background()
    locationUpdate := models.LocationUpdate{
        UserID:   driverID,
        UserType: "driver",
        Status:   status,
        Location: models.Location{
            Timestamp: time.Now(),
        },
    }
    
    wsm.matchingEngine.UpdateDriverLocation(ctx, locationUpdate)
}

// Utility function to generate connection IDs
func generateConnectionID() string {
    return fmt.Sprintf("conn_%d_%d", time.Now().UnixNano(), rand.Intn(1000))
}