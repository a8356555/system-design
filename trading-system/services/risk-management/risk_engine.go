package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"sync"
	"sync/atomic"
	"time"

	"github.com/go-redis/redis/v8"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

// High-Frequency Trading Risk Management Engine
// Implements real-time risk monitoring and position management

type RiskEngine struct {
	config           *RiskConfig
	redisClient      *redis.Client
	mongoClient      *mongo.Client
	positions        *PositionManager
	riskLimits       *RiskLimitManager
	portfolioMonitor *PortfolioMonitor
	metrics          *RiskMetrics
	ctx              context.Context
	cancel           context.CancelFunc
	mu               sync.RWMutex
}

type RiskConfig struct {
	MaxPositionSize    float64           `json:"max_position_size"`
	MaxOrderSize       float64           `json:"max_order_size"`
	MaxDailyLoss       float64           `json:"max_daily_loss"`
	MaxDrawdown        float64           `json:"max_drawdown"`
	VaRLimit           float64           `json:"var_limit"`           // Value at Risk limit
	ConcentrationLimit float64           `json:"concentration_limit"` // Max concentration per symbol
	LeverageLimit      float64           `json:"leverage_limit"`
	ClientLimits       map[string]Client `json:"client_limits"`
	SymbolLimits       map[string]Symbol `json:"symbol_limits"`
	UpdateIntervalMs   int               `json:"update_interval_ms"`
}

type Client struct {
	ID               string  `json:"id"`
	MaxPositionSize  float64 `json:"max_position_size"`
	MaxOrderSize     float64 `json:"max_order_size"`
	MaxDailyLoss     float64 `json:"max_daily_loss"`
	MaxDrawdown      float64 `json:"max_drawdown"`
	TradingEnabled   bool    `json:"trading_enabled"`
	RiskTolerance    string  `json:"risk_tolerance"` // low, medium, high
	LastRiskCheck    int64   `json:"last_risk_check"`
}

type Symbol struct {
	ID                 string  `json:"id"`
	MaxPositionSize    float64 `json:"max_position_size"`
	MaxOrderSize       float64 `json:"max_order_size"`
	VolatilityLimit    float64 `json:"volatility_limit"`
	LiquidityThreshold float64 `json:"liquidity_threshold"`
	PriceDeviation     float64 `json:"price_deviation"` // Max % deviation from market
	TradingEnabled     bool    `json:"trading_enabled"`
	CircuitBreaker     bool    `json:"circuit_breaker"`
}

type Position struct {
	ClientID        string    `json:"client_id" bson:"client_id"`
	SymbolID        string    `json:"symbol_id" bson:"symbol_id"`
	Quantity        float64   `json:"quantity" bson:"quantity"`       // Positive = long, Negative = short
	AveragePrice    float64   `json:"average_price" bson:"average_price"`
	MarketValue     float64   `json:"market_value" bson:"market_value"`
	UnrealizedPnL   float64   `json:"unrealized_pnl" bson:"unrealized_pnl"`
	RealizedPnL     float64   `json:"realized_pnl" bson:"realized_pnl"`
	LastUpdate      time.Time `json:"last_update" bson:"last_update"`
	DayOpenQuantity float64   `json:"day_open_quantity" bson:"day_open_quantity"`
	DayOpenValue    float64   `json:"day_open_value" bson:"day_open_value"`
}

type OrderRiskCheck struct {
	ClientID      string  `json:"client_id"`
	SymbolID      string  `json:"symbol_id"`
	OrderID       string  `json:"order_id"`
	Side          string  `json:"side"`          // "buy" or "sell"
	OrderType     string  `json:"order_type"`    // "market", "limit", etc.
	Quantity      float64 `json:"quantity"`
	Price         float64 `json:"price"`
	TimeInForce   string  `json:"time_in_force"` // "GTC", "IOC", "FOK"
	Timestamp     int64   `json:"timestamp"`
	PreTradeCheck bool    `json:"pre_trade_check"`
}

type RiskCheckResult struct {
	Approved        bool                   `json:"approved"`
	RejectionReason string                 `json:"rejection_reason,omitempty"`
	RiskMetrics     map[string]interface{} `json:"risk_metrics"`
	CheckLatencyUs  int64                  `json:"check_latency_us"`
	Timestamp       int64                  `json:"timestamp"`
}

type PositionManager struct {
	positions sync.Map // clientID+symbolID -> *Position
	mu        sync.RWMutex
}

func NewPositionManager() *PositionManager {
	return &PositionManager{}
}

func (pm *PositionManager) GetPosition(clientID, symbolID string) *Position {
	key := fmt.Sprintf("%s:%s", clientID, symbolID)
	if value, ok := pm.positions.Load(key); ok {
		return value.(*Position)
	}
	return &Position{
		ClientID: clientID,
		SymbolID: symbolID,
		Quantity: 0,
	}
}

func (pm *PositionManager) UpdatePosition(clientID, symbolID string, quantity, price float64) {
	key := fmt.Sprintf("%s:%s", clientID, symbolID)
	
	// Get or create position
	var position *Position
	if value, ok := pm.positions.Load(key); ok {
		position = value.(*Position)
	} else {
		position = &Position{
			ClientID:        clientID,
			SymbolID:        symbolID,
			Quantity:        0,
			AveragePrice:    0,
			LastUpdate:      time.Now(),
			DayOpenQuantity: 0,
		}
	}
	
	// Update position
	if position.Quantity == 0 {
		// New position
		position.Quantity = quantity
		position.AveragePrice = price
	} else {
		// Update existing position
		if (position.Quantity > 0 && quantity > 0) || (position.Quantity < 0 && quantity < 0) {
			// Same direction - update average price
			totalValue := position.Quantity*position.AveragePrice + quantity*price
			totalQuantity := position.Quantity + quantity
			position.AveragePrice = totalValue / totalQuantity
			position.Quantity = totalQuantity
		} else {
			// Opposite direction - reduce position or flip
			position.Quantity += quantity
			if position.Quantity == 0 {
				position.AveragePrice = 0
			} else if (position.Quantity > 0 && quantity > 0) || (position.Quantity < 0 && quantity < 0) {
				// Position flipped
				position.AveragePrice = price
			}
		}
	}
	
	position.LastUpdate = time.Now()
	pm.positions.Store(key, position)
}

func (pm *PositionManager) GetAllPositions(clientID string) []*Position {
	var positions []*Position
	
	pm.positions.Range(func(key, value interface{}) bool {
		position := value.(*Position)
		if position.ClientID == clientID {
			positions = append(positions, position)
		}
		return true
	})
	
	return positions
}

func (pm *PositionManager) CalculatePortfolioValue(clientID string, marketPrices map[string]float64) float64 {
	totalValue := 0.0
	
	positions := pm.GetAllPositions(clientID)
	for _, position := range positions {
		if marketPrice, exists := marketPrices[position.SymbolID]; exists {
			totalValue += position.Quantity * marketPrice
		}
	}
	
	return totalValue
}

type RiskLimitManager struct {
	clientLimits map[string]*Client
	symbolLimits map[string]*Symbol
	mu           sync.RWMutex
}

func NewRiskLimitManager(config *RiskConfig) *RiskLimitManager {
	rlm := &RiskLimitManager{
		clientLimits: make(map[string]*Client),
		symbolLimits: make(map[string]*Symbol),
	}
	
	// Load limits from config
	for id, client := range config.ClientLimits {
		clientCopy := client
		rlm.clientLimits[id] = &clientCopy
	}
	
	for id, symbol := range config.SymbolLimits {
		symbolCopy := symbol
		rlm.symbolLimits[id] = &symbolCopy
	}
	
	return rlm
}

func (rlm *RiskLimitManager) CheckOrderRisk(check *OrderRiskCheck, position *Position, portfolioValue float64) *RiskCheckResult {
	startTime := time.Now()
	
	result := &RiskCheckResult{
		Approved:    true,
		RiskMetrics: make(map[string]interface{}),
		Timestamp:   time.Now().UnixNano(),
	}
	
	// Check client limits
	rlm.mu.RLock()
	clientLimit, clientExists := rlm.clientLimits[check.ClientID]
	symbolLimit, symbolExists := rlm.symbolLimits[check.SymbolID]
	rlm.mu.RUnlock()
	
	if !clientExists {
		result.Approved = false
		result.RejectionReason = "Client not found or not authorized for trading"
		return result
	}
	
	if !clientLimit.TradingEnabled {
		result.Approved = false
		result.RejectionReason = "Trading disabled for client"
		return result
	}
	
	if symbolExists && !symbolLimit.TradingEnabled {
		result.Approved = false
		result.RejectionReason = "Trading disabled for symbol"
		return result
	}
	
	// Check order size limits
	orderValue := check.Quantity * check.Price
	if orderValue > clientLimit.MaxOrderSize {
		result.Approved = false
		result.RejectionReason = fmt.Sprintf("Order size %.2f exceeds client limit %.2f", 
			orderValue, clientLimit.MaxOrderSize)
		return result
	}
	
	if symbolExists && orderValue > symbolLimit.MaxOrderSize {
		result.Approved = false
		result.RejectionReason = fmt.Sprintf("Order size %.2f exceeds symbol limit %.2f", 
			orderValue, symbolLimit.MaxOrderSize)
		return result
	}
	
	// Check position limits
	newQuantity := position.Quantity
	if check.Side == "buy" {
		newQuantity += check.Quantity
	} else {
		newQuantity -= check.Quantity
	}
	
	newPositionValue := math.Abs(newQuantity * check.Price)
	if newPositionValue > clientLimit.MaxPositionSize {
		result.Approved = false
		result.RejectionReason = fmt.Sprintf("New position value %.2f exceeds client limit %.2f", 
			newPositionValue, clientLimit.MaxPositionSize)
		return result
	}
	
	if symbolExists && newPositionValue > symbolLimit.MaxPositionSize {
		result.Approved = false
		result.RejectionReason = fmt.Sprintf("New position value %.2f exceeds symbol limit %.2f", 
			newPositionValue, symbolLimit.MaxPositionSize)
		return result
	}
	
	// Check concentration limits
	concentrationRatio := newPositionValue / portfolioValue
	if portfolioValue > 0 && concentrationRatio > 0.5 { // 50% concentration limit
		result.Approved = false
		result.RejectionReason = fmt.Sprintf("Position concentration %.2f%% exceeds limit", 
			concentrationRatio*100)
		return result
	}
	
	// Check price deviation (for limit orders)
	if check.OrderType == "limit" && symbolExists {
		// This would need current market price - simplified for demo
		// priceDeviation := math.Abs(check.Price - marketPrice) / marketPrice
		// if priceDeviation > symbolLimit.PriceDeviation {
		//     result.Approved = false
		//     result.RejectionReason = "Order price deviates too much from market"
		//     return result
		// }
	}
	
	// Add risk metrics to result
	result.RiskMetrics["position_value"] = newPositionValue
	result.RiskMetrics["concentration_ratio"] = concentrationRatio
	result.RiskMetrics["portfolio_value"] = portfolioValue
	result.RiskMetrics["order_value"] = orderValue
	
	// Calculate check latency
	result.CheckLatencyUs = time.Since(startTime).Microseconds()
	
	return result
}

type PortfolioMonitor struct {
	riskEngine *RiskEngine
	running    int64
	stopChan   chan struct{}
}

func NewPortfolioMonitor(riskEngine *RiskEngine) *PortfolioMonitor {
	return &PortfolioMonitor{
		riskEngine: riskEngine,
		stopChan:   make(chan struct{}),
	}
}

func (pm *PortfolioMonitor) Start() {
	if atomic.CompareAndSwapInt64(&pm.running, 0, 1) {
		go pm.monitorLoop()
		log.Println("Portfolio monitor started")
	}
}

func (pm *PortfolioMonitor) Stop() {
	if atomic.CompareAndSwapInt64(&pm.running, 1, 0) {
		close(pm.stopChan)
		log.Println("Portfolio monitor stopped")
	}
}

func (pm *PortfolioMonitor) monitorLoop() {
	ticker := time.NewTicker(time.Duration(pm.riskEngine.config.UpdateIntervalMs) * time.Millisecond)
	defer ticker.Stop()
	
	for {
		select {
		case <-pm.stopChan:
			return
		case <-ticker.C:
			pm.performRiskChecks()
		}
	}
}

func (pm *PortfolioMonitor) performRiskChecks() {
	// Get all active clients
	clients := pm.getActiveClients()
	
	for _, clientID := range clients {
		pm.checkClientRisk(clientID)
	}
}

func (pm *PortfolioMonitor) getActiveClients() []string {
	var clients []string
	
	pm.riskEngine.positions.positions.Range(func(key, value interface{}) bool {
		position := value.(*Position)
		// Add unique client IDs
		found := false
		for _, existing := range clients {
			if existing == position.ClientID {
				found = true
				break
			}
		}
		if !found {
			clients = append(clients, position.ClientID)
		}
		return true
	})
	
	return clients
}

func (pm *PortfolioMonitor) checkClientRisk(clientID string) {
	// Get all positions for client
	positions := pm.riskEngine.positions.GetAllPositions(clientID)
	
	// Calculate portfolio metrics
	totalValue := 0.0
	totalPnL := 0.0
	maxConcentration := 0.0
	
	for _, position := range positions {
		// This would use real market prices in production
		marketPrice := position.AveragePrice * (1 + (float64(time.Now().Unix()%100)-50)/1000) // Mock price movement
		
		positionValue := math.Abs(position.Quantity * marketPrice)
		totalValue += positionValue
		
		unrealizedPnL := position.Quantity * (marketPrice - position.AveragePrice)
		totalPnL += unrealizedPnL + position.RealizedPnL
		
		concentration := positionValue / totalValue
		if concentration > maxConcentration {
			maxConcentration = concentration
		}
	}
	
	// Check risk limits
	pm.riskEngine.riskLimits.mu.RLock()
	clientLimit, exists := pm.riskEngine.riskLimits.clientLimits[clientID]
	pm.riskEngine.riskLimits.mu.RUnlock()
	
	if !exists {
		return
	}
	
	// Check daily loss limit
	if totalPnL < -clientLimit.MaxDailyLoss {
		log.Printf("WARNING: Client %s exceeded daily loss limit: %.2f", clientID, totalPnL)
		pm.disableTrading(clientID, "Daily loss limit exceeded")
	}
	
	// Check concentration limit
	if maxConcentration > 0.5 { // 50% limit
		log.Printf("WARNING: Client %s has high concentration: %.2f%%", clientID, maxConcentration*100)
	}
	
	// Update metrics
	pm.riskEngine.metrics.UpdateClientMetrics(clientID, totalValue, totalPnL, maxConcentration)
}

func (pm *PortfolioMonitor) disableTrading(clientID, reason string) {
	pm.riskEngine.riskLimits.mu.Lock()
	if client, exists := pm.riskEngine.riskLimits.clientLimits[clientID]; exists {
		client.TradingEnabled = false
		log.Printf("Trading disabled for client %s: %s", clientID, reason)
	}
	pm.riskEngine.riskLimits.mu.Unlock()
}

type RiskMetrics struct {
	TotalRiskChecks    int64                      `json:"total_risk_checks"`
	ApprovedOrders     int64                      `json:"approved_orders"`
	RejectedOrders     int64                      `json:"rejected_orders"`
	AverageLatencyUs   int64                      `json:"average_latency_us"`
	ClientMetrics      map[string]*ClientMetrics  `json:"client_metrics"`
	SymbolMetrics      map[string]*SymbolMetrics  `json:"symbol_metrics"`
	mu                 sync.RWMutex
}

type ClientMetrics struct {
	PortfolioValue    float64 `json:"portfolio_value"`
	TotalPnL          float64 `json:"total_pnl"`
	MaxConcentration  float64 `json:"max_concentration"`
	OrdersApproved    int64   `json:"orders_approved"`
	OrdersRejected    int64   `json:"orders_rejected"`
	LastUpdate        int64   `json:"last_update"`
}

type SymbolMetrics struct {
	TotalVolume       float64 `json:"total_volume"`
	OrdersApproved    int64   `json:"orders_approved"`
	OrdersRejected    int64   `json:"orders_rejected"`
	LastUpdate        int64   `json:"last_update"`
}

func NewRiskMetrics() *RiskMetrics {
	return &RiskMetrics{
		ClientMetrics: make(map[string]*ClientMetrics),
		SymbolMetrics: make(map[string]*SymbolMetrics),
	}
}

func (rm *RiskMetrics) RecordRiskCheck(approved bool, latencyUs int64) {
	atomic.AddInt64(&rm.TotalRiskChecks, 1)
	if approved {
		atomic.AddInt64(&rm.ApprovedOrders, 1)
	} else {
		atomic.AddInt64(&rm.RejectedOrders, 1)
	}
	
	// Update average latency (simplified)
	atomic.StoreInt64(&rm.AverageLatencyUs, latencyUs)
}

func (rm *RiskMetrics) UpdateClientMetrics(clientID string, portfolioValue, totalPnL, maxConcentration float64) {
	rm.mu.Lock()
	defer rm.mu.Unlock()
	
	if _, exists := rm.ClientMetrics[clientID]; !exists {
		rm.ClientMetrics[clientID] = &ClientMetrics{}
	}
	
	metrics := rm.ClientMetrics[clientID]
	metrics.PortfolioValue = portfolioValue
	metrics.TotalPnL = totalPnL
	metrics.MaxConcentration = maxConcentration
	metrics.LastUpdate = time.Now().Unix()
}

func (rm *RiskMetrics) GetStatistics() map[string]interface{} {
	rm.mu.RLock()
	defer rm.mu.RUnlock()
	
	stats := make(map[string]interface{})
	stats["total_risk_checks"] = atomic.LoadInt64(&rm.TotalRiskChecks)
	stats["approved_orders"] = atomic.LoadInt64(&rm.ApprovedOrders)
	stats["rejected_orders"] = atomic.LoadInt64(&rm.RejectedOrders)
	stats["average_latency_us"] = atomic.LoadInt64(&rm.AverageLatencyUs)
	stats["client_count"] = len(rm.ClientMetrics)
	stats["symbol_count"] = len(rm.SymbolMetrics)
	
	return stats
}

// Main Risk Engine
func NewRiskEngine(config *RiskConfig) (*RiskEngine, error) {
	ctx, cancel := context.WithCancel(context.Background())
	
	// Initialize Redis client
	redisClient := redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
	})
	
	// Test Redis connection
	if err := redisClient.Ping(ctx).Err(); err != nil {
		cancel()
		return nil, fmt.Errorf("failed to connect to Redis: %w", err)
	}
	
	// Initialize MongoDB client
	mongoClient, err := mongo.Connect(ctx, options.Client().ApplyURI("mongodb://localhost:27017"))
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to connect to MongoDB: %w", err)
	}
	
	engine := &RiskEngine{
		config:      config,
		redisClient: redisClient,
		mongoClient: mongoClient,
		positions:   NewPositionManager(),
		riskLimits:  NewRiskLimitManager(config),
		metrics:     NewRiskMetrics(),
		ctx:         ctx,
		cancel:      cancel,
	}
	
	engine.portfolioMonitor = NewPortfolioMonitor(engine)
	
	return engine, nil
}

func (re *RiskEngine) Start() {
	re.portfolioMonitor.Start()
	log.Println("Risk engine started")
}

func (re *RiskEngine) Stop() {
	re.portfolioMonitor.Stop()
	re.cancel()
	
	if re.redisClient != nil {
		re.redisClient.Close()
	}
	
	if re.mongoClient != nil {
		re.mongoClient.Disconnect(re.ctx)
	}
	
	log.Println("Risk engine stopped")
}

func (re *RiskEngine) CheckOrder(check *OrderRiskCheck) *RiskCheckResult {
	// Get current position
	position := re.positions.GetPosition(check.ClientID, check.SymbolID)
	
	// Get portfolio value (simplified - would use real market prices)
	portfolioValue := 1000000.0 // Mock portfolio value
	
	// Perform risk check
	result := re.riskLimits.CheckOrderRisk(check, position, portfolioValue)
	
	// Record metrics
	re.metrics.RecordRiskCheck(result.Approved, result.CheckLatencyUs)
	
	return result
}

func (re *RiskEngine) UpdatePosition(clientID, symbolID string, quantity, price float64) {
	re.positions.UpdatePosition(clientID, symbolID, quantity, price)
}

func (re *RiskEngine) GetPosition(clientID, symbolID string) *Position {
	return re.positions.GetPosition(clientID, symbolID)
}

func (re *RiskEngine) GetAllPositions(clientID string) []*Position {
	return re.positions.GetAllPositions(clientID)
}

func (re *RiskEngine) GetMetrics() map[string]interface{} {
	return re.metrics.GetStatistics()
}

// Example usage and testing
func main() {
	log.Println("High-Frequency Trading Risk Management Engine")
	log.Println("============================================")
	
	// Load configuration
	config := &RiskConfig{
		MaxPositionSize:    1000000.0,
		MaxOrderSize:       100000.0,
		MaxDailyLoss:       50000.0,
		MaxDrawdown:        100000.0,
		VaRLimit:           75000.0,
		ConcentrationLimit: 0.3,
		LeverageLimit:      3.0,
		UpdateIntervalMs:   1000,
		ClientLimits: map[string]Client{
			"client1": {
				ID:              "client1",
				MaxPositionSize: 500000.0,
				MaxOrderSize:    50000.0,
				MaxDailyLoss:    25000.0,
				MaxDrawdown:     50000.0,
				TradingEnabled:  true,
				RiskTolerance:   "medium",
			},
			"client2": {
				ID:              "client2",
				MaxPositionSize: 200000.0,
				MaxOrderSize:    20000.0,
				MaxDailyLoss:    10000.0,
				MaxDrawdown:     20000.0,
				TradingEnabled:  true,
				RiskTolerance:   "low",
			},
		},
		SymbolLimits: map[string]Symbol{
			"AAPL": {
				ID:                 "AAPL",
				MaxPositionSize:    300000.0,
				MaxOrderSize:       30000.0,
				VolatilityLimit:    0.05,
				LiquidityThreshold: 1000000.0,
				PriceDeviation:     0.02,
				TradingEnabled:     true,
				CircuitBreaker:     false,
			},
		},
	}
	
	// Create risk engine
	engine, err := NewRiskEngine(config)
	if err != nil {
		log.Fatalf("Failed to create risk engine: %v", err)
	}
	defer engine.Stop()
	
	// Start engine
	engine.Start()
	
	// Test order risk checks
	log.Println("Testing order risk checks...")
	
	testOrders := []OrderRiskCheck{
		{
			ClientID:      "client1",
			SymbolID:      "AAPL",
			OrderID:       "order1",
			Side:          "buy",
			OrderType:     "limit",
			Quantity:      100,
			Price:         150.0,
			TimeInForce:   "GTC",
			Timestamp:     time.Now().UnixNano(),
			PreTradeCheck: true,
		},
		{
			ClientID:      "client1",
			SymbolID:      "AAPL",
			OrderID:       "order2",
			Side:          "buy",
			OrderType:     "limit",
			Quantity:      1000,
			Price:         150.0,
			TimeInForce:   "GTC",
			Timestamp:     time.Now().UnixNano(),
			PreTradeCheck: true,
		},
		{
			ClientID:      "client2",
			SymbolID:      "AAPL",
			OrderID:       "order3",
			Side:          "sell",
			OrderType:     "market",
			Quantity:      50,
			Price:         150.0,
			TimeInForce:   "IOC",
			Timestamp:     time.Now().UnixNano(),
			PreTradeCheck: true,
		},
	}
	
	for i, order := range testOrders {
		result := engine.CheckOrder(&order)
		
		log.Printf("Order %d:", i+1)
		log.Printf("  Client: %s, Symbol: %s, Side: %s, Quantity: %.0f, Price: %.2f",
			order.ClientID, order.SymbolID, order.Side, order.Quantity, order.Price)
		log.Printf("  Approved: %t", result.Approved)
		if !result.Approved {
			log.Printf("  Rejection Reason: %s", result.RejectionReason)
		}
		log.Printf("  Check Latency: %d microseconds", result.CheckLatencyUs)
		
		// If approved, simulate position update
		if result.Approved {
			qty := order.Quantity
			if order.Side == "sell" {
				qty = -qty
			}
			engine.UpdatePosition(order.ClientID, order.SymbolID, qty, order.Price)
		}
		
		log.Println()
	}
	
	// Display positions
	log.Println("Current Positions:")
	for _, clientID := range []string{"client1", "client2"} {
		positions := engine.GetAllPositions(clientID)
		log.Printf("Client %s:", clientID)
		for _, pos := range positions {
			log.Printf("  %s: Quantity=%.2f, Avg Price=%.2f, Value=%.2f",
				pos.SymbolID, pos.Quantity, pos.AveragePrice, pos.Quantity*pos.AveragePrice)
		}
	}
	
	// Run for a while to show monitoring
	log.Println("\nMonitoring portfolio risk for 10 seconds...")
	time.Sleep(10 * time.Second)
	
	// Display final metrics
	log.Println("\nFinal Risk Metrics:")
	metrics := engine.GetMetrics()
	metricsJSON, _ := json.MarshalIndent(metrics, "", "  ")
	log.Println(string(metricsJSON))
}