package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"
    "time"

    "ride-sharing-system/internal/handlers"
    "ride-sharing-system/internal/middleware"
    "ride-sharing-system/internal/repositories"
    "ride-sharing-system/internal/services"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    influxdb2 "github.com/influxdata/influxdb-client-go/v2"
    "go.mongodb.org/mongo-driver/mongo"
    "go.mongodb.org/mongo-driver/mongo/options"
)

func main() {
    // Load configuration
    config := loadConfig()
    
    // Initialize database connections
    mongoClient, err := initMongoDB(config.MongoURI)
    if err != nil {
        log.Fatalf("Failed to connect to MongoDB: %v", err)
    }
    defer mongoClient.Disconnect(context.Background())

    redisClient := initRedis(config.RedisAddr, config.RedisPassword)
    defer redisClient.Close()

    influxClient := influxdb2.NewClient(config.InfluxDBURL, config.InfluxDBToken)
    defer influxClient.Close()

    // Initialize repositories
    driverRepo := repositories.NewDriverRepository(mongoClient.Database("rideshare"))
    riderRepo := repositories.NewRiderRepository(mongoClient.Database("rideshare"))
    tripRepo := repositories.NewTripRepository(mongoClient.Database("rideshare"))
    locationRepo := repositories.NewLocationRepository(influxClient)

    // Initialize services
    locationService := services.NewLocationService(locationRepo, redisClient)
    pricingService := services.NewPricingService(redisClient)
    matchingEngine := services.NewMatchingEngine(redisClient, driverRepo, locationRepo, pricingService)
    wsManager := services.NewWebSocketManager(redisClient, locationService, matchingEngine)
    
    // Start WebSocket manager
    wsManager.Start()
    defer wsManager.Stop()

    // Initialize handlers
    driverHandler := handlers.NewDriverHandler(driverRepo, locationService, wsManager)
    riderHandler := handlers.NewRiderHandler(riderRepo, matchingEngine, wsManager)
    tripHandler := handlers.NewTripHandler(tripRepo, wsManager)
    locationHandler := handlers.NewLocationHandler(locationService)

    // Setup Gin router
    router := setupRouter(config, driverHandler, riderHandler, tripHandler, locationHandler, wsManager)

    // Start HTTP server
    server := &http.Server{
        Addr:    ":" + config.Port,
        Handler: router,
    }

    // Graceful shutdown
    go func() {
        sigChan := make(chan os.Signal, 1)
        signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
        <-sigChan

        log.Println("Shutting down server...")
        
        ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
        defer cancel()
        
        if err := server.Shutdown(ctx); err != nil {
            log.Printf("Server shutdown error: %v", err)
        }
    }()

    log.Printf("Starting ride-sharing server on port %s", config.Port)
    if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
        log.Fatalf("Server failed to start: %v", err)
    }
}

// Config holds application configuration
type Config struct {
    Port           string
    MongoURI       string
    RedisAddr      string
    RedisPassword  string
    InfluxDBURL    string
    InfluxDBToken  string
    JWTSecret      string
    Environment    string
}

// loadConfig loads configuration from environment variables
func loadConfig() *Config {
    config := &Config{
        Port:           getEnv("PORT", "8080"),
        MongoURI:       getEnv("MONGO_URI", "mongodb://localhost:27017"),
        RedisAddr:      getEnv("REDIS_ADDR", "localhost:6379"),
        RedisPassword:  getEnv("REDIS_PASSWORD", ""),
        InfluxDBURL:    getEnv("INFLUXDB_URL", "http://localhost:8086"),
        InfluxDBToken:  getEnv("INFLUXDB_TOKEN", ""),
        JWTSecret:      getEnv("JWT_SECRET", "your-secret-key"),
        Environment:    getEnv("ENVIRONMENT", "development"),
    }
    
    return config
}

// getEnv gets environment variable with fallback
func getEnv(key, fallback string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return fallback
}

// initMongoDB initializes MongoDB connection
func initMongoDB(uri string) (*mongo.Client, error) {
    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    
    client, err := mongo.Connect(ctx, options.Client().ApplyURI(uri))
    if err != nil {
        return nil, err
    }
    
    // Ping the database
    if err := client.Ping(ctx, nil); err != nil {
        return nil, err
    }
    
    log.Println("Connected to MongoDB")
    return client, nil
}

// initRedis initializes Redis connection
func initRedis(addr, password string) *redis.Client {
    client := redis.NewClient(&redis.Options{
        Addr:     addr,
        Password: password,
        DB:       0,
    })
    
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    if err := client.Ping(ctx).Err(); err != nil {
        log.Fatalf("Failed to connect to Redis: %v", err)
    }
    
    log.Println("Connected to Redis")
    return client
}

// setupRouter configures the Gin router with all routes and middleware
func setupRouter(config *Config, driverHandler *handlers.DriverHandler, 
                riderHandler *handlers.RiderHandler, tripHandler *handlers.TripHandler,
                locationHandler *handlers.LocationHandler, wsManager *services.WebSocketManager) *gin.Engine {
    
    if config.Environment == "production" {
        gin.SetMode(gin.ReleaseMode)
    }
    
    router := gin.New()
    
    // Middleware
    router.Use(gin.Logger())
    router.Use(gin.Recovery())
    router.Use(middleware.CORS())
    router.Use(middleware.RateLimit())
    
    // Health check
    router.GET("/health", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{
            "status":    "healthy",
            "timestamp": time.Now(),
            "version":   "1.0.0",
        })
    })
    
    // WebSocket endpoint
    router.GET("/ws", wsManager.HandleWebSocket)
    
    // API routes
    v1 := router.Group("/api/v1")
    {
        // Authentication routes (implement as needed)
        auth := v1.Group("/auth")
        {
            auth.POST("/login", func(c *gin.Context) {
                // Implement login logic
                c.JSON(http.StatusOK, gin.H{"message": "Login endpoint"})
            })
            auth.POST("/register", func(c *gin.Context) {
                // Implement registration logic
                c.JSON(http.StatusOK, gin.H{"message": "Register endpoint"})
            })
        }
        
        // Driver routes
        drivers := v1.Group("/drivers")
        drivers.Use(middleware.AuthMiddleware(config.JWTSecret))
        {
            drivers.POST("/", driverHandler.CreateDriver)
            drivers.GET("/:id", driverHandler.GetDriver)
            drivers.PUT("/:id", driverHandler.UpdateDriver)
            drivers.POST("/:id/location", driverHandler.UpdateLocation)
            drivers.GET("/:id/status", driverHandler.GetStatus)
            drivers.PUT("/:id/status", driverHandler.UpdateStatus)
        }
        
        // Rider routes
        riders := v1.Group("/riders")
        riders.Use(middleware.AuthMiddleware(config.JWTSecret))
        {
            riders.POST("/", riderHandler.CreateRider)
            riders.GET("/:id", riderHandler.GetRider)
            riders.PUT("/:id", riderHandler.UpdateRider)
            riders.POST("/:id/ride-request", riderHandler.CreateRideRequest)
            riders.GET("/:id/ride-requests", riderHandler.GetRideRequests)
        }
        
        // Trip routes
        trips := v1.Group("/trips")
        trips.Use(middleware.AuthMiddleware(config.JWTSecret))
        {
            trips.GET("/:id", tripHandler.GetTrip)
            trips.PUT("/:id/status", tripHandler.UpdateTripStatus)
            trips.POST("/:id/location", tripHandler.UpdateTripLocation)
            trips.GET("/:id/route", tripHandler.GetTripRoute)
        }
        
        // Location routes
        locations := v1.Group("/locations")
        locations.Use(middleware.AuthMiddleware(config.JWTSecret))
        {
            locations.GET("/drivers/nearby", locationHandler.GetNearbyDrivers)
            locations.GET("/heatmap", locationHandler.GetLocationHeatmap)
            locations.GET("/analytics", locationHandler.GetLocationAnalytics)
        }
        
        // Admin routes
        admin := v1.Group("/admin")
        admin.Use(middleware.AuthMiddleware(config.JWTSecret))
        admin.Use(middleware.AdminMiddleware())
        {
            admin.GET("/metrics", func(c *gin.Context) {
                // Return system metrics
                c.JSON(http.StatusOK, gin.H{
                    "active_connections": "TODO", // Get from wsManager
                    "active_trips":      "TODO", // Get from trip service
                    "online_drivers":    "TODO", // Get from driver service
                })
            })
            admin.GET("/system/health", func(c *gin.Context) {
                // Detailed system health check
                c.JSON(http.StatusOK, gin.H{
                    "database":    "healthy",
                    "redis":       "healthy",
                    "influxdb":    "healthy",
                    "websockets":  "healthy",
                })
            })
        }
    }
    
    return router
}