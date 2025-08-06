package services

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "math"
    "sort"
    "time"

    "ride-sharing-system/internal/models"
    "ride-sharing-system/internal/repositories"

    "github.com/go-redis/redis/v8"
)

// MatchingEngine handles the core logic for matching riders with drivers
type MatchingEngine struct {
    redisClient    *redis.Client
    driverRepo     repositories.DriverRepository
    locationRepo   repositories.LocationRepository
    priceService   *PricingService
    maxSearchRadius float64 // Maximum search radius in kilometers
    maxDrivers     int     // Maximum number of drivers to consider
}

// NewMatchingEngine creates a new matching engine instance
func NewMatchingEngine(redisClient *redis.Client, driverRepo repositories.DriverRepository, 
                      locationRepo repositories.LocationRepository, priceService *PricingService) *MatchingEngine {
    return &MatchingEngine{
        redisClient:     redisClient,
        driverRepo:      driverRepo,
        locationRepo:    locationRepo,
        priceService:    priceService,
        maxSearchRadius: 10.0, // 10km default search radius
        maxDrivers:      20,    // Consider top 20 nearest drivers
    }
}

// MatchRequest represents a matching request
type MatchRequest struct {
    RideRequest    models.RideRequest `json:"ride_request"`
    MaxWaitTime    int                `json:"max_wait_time"` // in minutes
    PreferredDrivers []string         `json:"preferred_drivers,omitempty"`
    ExcludedDrivers  []string         `json:"excluded_drivers,omitempty"`
}

// MatchResult represents the result of a matching operation
type MatchResult struct {
    Success       bool                   `json:"success"`
    Matches       []models.DriverMatch   `json:"matches"`
    EstimatedFare float64               `json:"estimated_fare"`
    Message       string                `json:"message"`
    SearchRadius  float64               `json:"search_radius"`
    SearchTime    time.Duration         `json:"search_time"`
}

// FindMatches finds suitable drivers for a ride request
func (me *MatchingEngine) FindMatches(ctx context.Context, request MatchRequest) (*MatchResult, error) {
    startTime := time.Now()
    
    // Get available drivers within search radius
    availableDrivers, err := me.getAvailableDriversInRadius(ctx, 
        request.RideRequest.PickupLocation, me.maxSearchRadius)
    if err != nil {
        return nil, fmt.Errorf("failed to get available drivers: %w", err)
    }

    if len(availableDrivers) == 0 {
        return &MatchResult{
            Success:      false,
            Message:      "No available drivers found in the area",
            SearchRadius: me.maxSearchRadius,
            SearchTime:   time.Since(startTime),
        }, nil
    }

    // Calculate estimated fare
    estimatedFare, err := me.priceService.CalculateEstimatedFare(
        request.RideRequest.PickupLocation,
        request.RideRequest.DropoffLocation,
        request.RideRequest.RideType,
    )
    if err != nil {
        log.Printf("Error calculating fare: %v", err)
        estimatedFare = 0 // Continue without fare estimation
    }

    // Score and rank drivers
    matches := me.scoreAndRankDrivers(request, availableDrivers)

    // Filter by preferences and exclusions
    matches = me.applyDriverFilters(matches, request.PreferredDrivers, request.ExcludedDrivers)

    // Limit results
    if len(matches) > 5 {
        matches = matches[:5] // Return top 5 matches
    }

    return &MatchResult{
        Success:       len(matches) > 0,
        Matches:       matches,
        EstimatedFare: estimatedFare,
        Message:       fmt.Sprintf("Found %d potential matches", len(matches)),
        SearchRadius:  me.maxSearchRadius,
        SearchTime:    time.Since(startTime),
    }, nil
}

// getAvailableDriversInRadius retrieves available drivers within specified radius
func (me *MatchingEngine) getAvailableDriversInRadius(ctx context.Context, 
    center models.Location, radiusKm float64) ([]models.Driver, error) {
    
    // Use Redis geospatial commands for efficient location-based queries
    key := "drivers:locations"
    
    // Query drivers within radius using GEORADIUS
    cmd := me.redisClient.GeoRadius(ctx, key, 
        center.Longitude, center.Latitude, 
        &redis.GeoRadiusQuery{
            Radius:      radiusKm,
            Unit:        "km",
            WithCoord:   true,
            WithDist:    true,
            Count:       me.maxDrivers,
            Sort:        "ASC", // Sort by distance
        })
    
    locations, err := cmd.Result()
    if err != nil {
        return nil, fmt.Errorf("failed to query driver locations: %w", err)
    }

    var drivers []models.Driver
    for _, loc := range locations {
        // Get driver details from cache or database
        driver, err := me.getDriverByID(ctx, loc.Name)
        if err != nil {
            log.Printf("Error fetching driver %s: %v", loc.Name, err)
            continue
        }

        // Verify driver is still available (double-check status)
        if driver.Status != "available" {
            continue
        }

        // Update driver's current location with Redis data
        driver.CurrentLocation = models.Location{
            Latitude:  loc.Latitude,
            Longitude: loc.Longitude,
            Timestamp: time.Now(),
        }

        drivers = append(drivers, driver)
    }

    return drivers, nil
}

// scoreAndRankDrivers calculates match scores and ranks drivers
func (me *MatchingEngine) scoreAndRankDrivers(request MatchRequest, 
    drivers []models.Driver) []models.DriverMatch {
    
    var matches []models.DriverMatch
    
    for _, driver := range drivers {
        // Calculate distance to pickup
        distance := driver.CurrentLocation.DistanceBetween(request.RideRequest.PickupLocation)
        
        // Calculate ETA (estimated time of arrival)
        eta := driver.CurrentLocation.EstimateETA(request.RideRequest.PickupLocation, 30) // 30 km/h avg speed
        
        // Calculate match score based on multiple factors
        matchScore := me.calculateMatchScore(driver, request, distance, eta)
        
        match := models.DriverMatch{
            DriverID:   driver.ID,
            Driver:     driver,
            Distance:   distance,
            ETA:        eta,
            MatchScore: matchScore,
        }
        
        matches = append(matches, match)
    }
    
    // Sort by match score (highest first)
    sort.Slice(matches, func(i, j int) bool {
        return matches[i].MatchScore > matches[j].MatchScore
    })
    
    return matches
}

// calculateMatchScore computes a match score based on various factors
func (me *MatchingEngine) calculateMatchScore(driver models.Driver, request MatchRequest, 
    distance float64, eta int) float64 {
    
    score := 100.0 // Base score
    
    // Distance factor (closer is better)
    distanceScore := math.Max(0, 50-distance*5) // Decrease score by 5 points per km
    score += distanceScore
    
    // ETA factor (faster pickup is better)
    etaScore := math.Max(0, 30-float64(eta)) // Decrease score by 1 point per minute
    score += etaScore
    
    // Driver rating factor
    ratingScore := (driver.Rating - 3.0) * 10 // Scale rating from 0-50 points
    score += ratingScore
    
    // Experience factor (more rides = better)
    experienceScore := math.Min(20, float64(driver.TotalRides)/10) // Max 20 points
    score += experienceScore
    
    // Vehicle type matching (if specified in ride request)
    if request.RideRequest.RideType != "" {
        if me.isVehicleTypeMatch(driver.VehicleInfo.Type, request.RideRequest.RideType) {
            score += 15 // Bonus for vehicle type match
        }
    }
    
    // Penalty for very long ETA
    if eta > request.MaxWaitTime && request.MaxWaitTime > 0 {
        score -= 25 // Penalty for exceeding max wait time
    }
    
    return math.Max(0, score) // Ensure non-negative score
}

// isVehicleTypeMatch checks if vehicle type matches ride type requirements
func (me *MatchingEngine) isVehicleTypeMatch(vehicleType, rideType string) bool {
    matchMap := map[string][]string{
        "economy":  {"sedan", "hatchback"},
        "premium":  {"sedan", "suv"},
        "luxury":   {"suv", "luxury"},
    }
    
    allowedVehicles, exists := matchMap[rideType]
    if !exists {
        return true // If ride type not specified, any vehicle is fine
    }
    
    for _, allowed := range allowedVehicles {
        if vehicleType == allowed {
            return true
        }
    }
    return false
}

// applyDriverFilters applies preference and exclusion filters
func (me *MatchingEngine) applyDriverFilters(matches []models.DriverMatch, 
    preferred []string, excluded []string) []models.DriverMatch {
    
    // Create sets for faster lookup
    preferredSet := make(map[string]bool)
    for _, id := range preferred {
        preferredSet[id] = true
    }
    
    excludedSet := make(map[string]bool)
    for _, id := range excluded {
        excludedSet[id] = true
    }
    
    var filtered []models.DriverMatch
    var preferredMatches []models.DriverMatch
    
    for _, match := range matches {
        // Skip excluded drivers
        if excludedSet[match.DriverID] {
            continue
        }
        
        // Separate preferred drivers
        if preferredSet[match.DriverID] {
            preferredMatches = append(preferredMatches, match)
        } else {
            filtered = append(filtered, match)
        }
    }
    
    // Preferred drivers go first
    result := append(preferredMatches, filtered...)
    return result
}

// getDriverByID retrieves driver information by ID (with caching)
func (me *MatchingEngine) getDriverByID(ctx context.Context, driverID string) (models.Driver, error) {
    // Try to get from Redis cache first
    cacheKey := fmt.Sprintf("driver:%s", driverID)
    cached, err := me.redisClient.Get(ctx, cacheKey).Result()
    
    if err == nil {
        var driver models.Driver
        if json.Unmarshal([]byte(cached), &driver) == nil {
            return driver, nil
        }
    }
    
    // If not in cache, get from database
    driver, err := me.driverRepo.GetByID(ctx, driverID)
    if err != nil {
        return models.Driver{}, err
    }
    
    // Cache for future use (5 minutes TTL)
    driverJSON, _ := json.Marshal(driver)
    me.redisClient.Set(ctx, cacheKey, driverJSON, 5*time.Minute)
    
    return driver, nil
}

// UpdateDriverLocation updates a driver's location in the geospatial index
func (me *MatchingEngine) UpdateDriverLocation(ctx context.Context, update models.LocationUpdate) error {
    key := "drivers:locations"
    
    if update.Status == "offline" {
        // Remove driver from geospatial index
        return me.redisClient.ZRem(ctx, key, update.UserID).Err()
    }
    
    // Add/update driver location in geospatial index
    return me.redisClient.GeoAdd(ctx, key, &redis.GeoLocation{
        Name:      update.UserID,
        Longitude: update.Location.Longitude,
        Latitude:  update.Location.Latitude,
    }).Err()
}