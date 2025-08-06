package models

import (
    "time"
    "math"
)

// Location represents a geographical location
type Location struct {
    Latitude  float64 `json:"latitude" bson:"latitude"`
    Longitude float64 `json:"longitude" bson:"longitude"`
    Timestamp time.Time `json:"timestamp" bson:"timestamp"`
}

// LocationUpdate represents real-time location update
type LocationUpdate struct {
    UserID    string    `json:"user_id" bson:"user_id"`
    UserType  string    `json:"user_type" bson:"user_type"` // "driver" or "rider"
    Location  Location  `json:"location" bson:"location"`
    Status    string    `json:"status" bson:"status"` // "available", "busy", "offline"
    Heading   float64   `json:"heading" bson:"heading"` // Direction in degrees
    Speed     float64   `json:"speed" bson:"speed"` // Speed in km/h
}

// Driver represents a driver's information and current state
type Driver struct {
    ID           string    `json:"id" bson:"_id"`
    Name         string    `json:"name" bson:"name"`
    Phone        string    `json:"phone" bson:"phone"`
    VehicleInfo  Vehicle   `json:"vehicle_info" bson:"vehicle_info"`
    CurrentLocation Location `json:"current_location" bson:"current_location"`
    Status       string    `json:"status" bson:"status"` // "available", "busy", "offline"
    Rating       float64   `json:"rating" bson:"rating"`
    TotalRides   int       `json:"total_rides" bson:"total_rides"`
    CreatedAt    time.Time `json:"created_at" bson:"created_at"`
    UpdatedAt    time.Time `json:"updated_at" bson:"updated_at"`
}

// Vehicle represents vehicle information
type Vehicle struct {
    Make         string `json:"make" bson:"make"`
    Model        string `json:"model" bson:"model"`
    Year         int    `json:"year" bson:"year"`
    LicensePlate string `json:"license_plate" bson:"license_plate"`
    Color        string `json:"color" bson:"color"`
    Type         string `json:"type" bson:"type"` // "sedan", "suv", "hatchback"
}

// Rider represents a rider's information
type Rider struct {
    ID        string    `json:"id" bson:"_id"`
    Name      string    `json:"name" bson:"name"`
    Phone     string    `json:"phone" bson:"phone"`
    Email     string    `json:"email" bson:"email"`
    Rating    float64   `json:"rating" bson:"rating"`
    CreatedAt time.Time `json:"created_at" bson:"created_at"`
    UpdatedAt time.Time `json:"updated_at" bson:"updated_at"`
}

// RideRequest represents a ride request from a rider
type RideRequest struct {
    ID              string    `json:"id" bson:"_id"`
    RiderID         string    `json:"rider_id" bson:"rider_id"`
    PickupLocation  Location  `json:"pickup_location" bson:"pickup_location"`
    DropoffLocation Location  `json:"dropoff_location" bson:"dropoff_location"`
    Status          string    `json:"status" bson:"status"` // "pending", "matched", "accepted", "in_progress", "completed", "cancelled"
    RequestedAt     time.Time `json:"requested_at" bson:"requested_at"`
    EstimatedFare   float64   `json:"estimated_fare" bson:"estimated_fare"`
    RideType        string    `json:"ride_type" bson:"ride_type"` // "economy", "premium", "luxury"
    SpecialRequests string    `json:"special_requests" bson:"special_requests"`
}

// Trip represents an active or completed trip
type Trip struct {
    ID              string    `json:"id" bson:"_id"`
    RideRequestID   string    `json:"ride_request_id" bson:"ride_request_id"`
    DriverID        string    `json:"driver_id" bson:"driver_id"`
    RiderID         string    `json:"rider_id" bson:"rider_id"`
    PickupLocation  Location  `json:"pickup_location" bson:"pickup_location"`
    DropoffLocation Location  `json:"dropoff_location" bson:"dropoff_location"`
    ActualRoute     []Location `json:"actual_route" bson:"actual_route"`
    Status          string    `json:"status" bson:"status"`
    StartTime       *time.Time `json:"start_time" bson:"start_time"`
    EndTime         *time.Time `json:"end_time" bson:"end_time"`
    EstimatedFare   float64   `json:"estimated_fare" bson:"estimated_fare"`
    ActualFare      float64   `json:"actual_fare" bson:"actual_fare"`
    Distance        float64   `json:"distance" bson:"distance"` // in kilometers
    Duration        int       `json:"duration" bson:"duration"` // in minutes
    CreatedAt       time.Time `json:"created_at" bson:"created_at"`
    UpdatedAt       time.Time `json:"updated_at" bson:"updated_at"`
}

// DriverMatch represents a potential driver match for a ride request
type DriverMatch struct {
    DriverID     string  `json:"driver_id"`
    Driver       Driver  `json:"driver"`
    Distance     float64 `json:"distance"` // Distance to pickup in km
    ETA          int     `json:"eta"` // Estimated time to pickup in minutes
    MatchScore   float64 `json:"match_score"` // Algorithm-calculated match score
}

// GeofenceArea represents a geographical area for supply/demand analysis
type GeofenceArea struct {
    ID       string    `json:"id" bson:"_id"`
    Name     string    `json:"name" bson:"name"`
    Bounds   []Location `json:"bounds" bson:"bounds"` // Polygon coordinates
    Center   Location  `json:"center" bson:"center"`
    Radius   float64   `json:"radius" bson:"radius"` // in kilometers
    IsActive bool      `json:"is_active" bson:"is_active"`
}

// Utility functions

// DistanceBetween calculates the distance between two locations using Haversine formula
func (l1 Location) DistanceBetween(l2 Location) float64 {
    const R = 6371 // Earth's radius in kilometers

    lat1Rad := l1.Latitude * math.Pi / 180
    lat2Rad := l2.Latitude * math.Pi / 180
    deltaLatRad := (l2.Latitude - l1.Latitude) * math.Pi / 180
    deltaLngRad := (l2.Longitude - l1.Longitude) * math.Pi / 180

    a := math.Sin(deltaLatRad/2)*math.Sin(deltaLatRad/2) +
        math.Cos(lat1Rad)*math.Cos(lat2Rad)*
        math.Sin(deltaLngRad/2)*math.Sin(deltaLngRad/2)
    
    c := 2 * math.Atan2(math.Sqrt(a), math.Sqrt(1-a))
    
    return R * c
}

// IsWithinRadius checks if a location is within a certain radius of another location
func (l1 Location) IsWithinRadius(l2 Location, radiusKm float64) bool {
    return l1.DistanceBetween(l2) <= radiusKm
}

// EstimateETA calculates estimated time of arrival based on distance and average speed
func (l1 Location) EstimateETA(l2 Location, avgSpeedKmh float64) int {
    distance := l1.DistanceBetween(l2)
    if avgSpeedKmh <= 0 {
        avgSpeedKmh = 30 // Default city driving speed
    }
    return int(math.Ceil(distance / avgSpeedKmh * 60)) // Convert to minutes
}