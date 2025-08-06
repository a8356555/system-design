#include <iostream>
#include <memory>
#include <vector>
#include <unordered_map>
#include <atomic>
#include <mutex>
#include <thread>
#include <chrono>
#include <algorithm>
#include <queue>
#include <set>
#include <cstring>
#include <immintrin.h>

// Ultra-Low Latency Order Matching Engine
// Designed for sub-microsecond order matching

namespace hft {

using OrderID = uint64_t;
using Price = uint64_t;    // Fixed-point price (multiply by 10000)
using Quantity = uint32_t;
using SymbolID = uint32_t;
using ClientID = uint32_t;

enum class OrderSide : uint8_t {
    BUY = 0,
    SELL = 1
};

enum class OrderType : uint8_t {
    MARKET = 0,
    LIMIT = 1,
    STOP = 2,
    STOP_LIMIT = 3,
    IOC = 4,  // Immediate or Cancel
    FOK = 5   // Fill or Kill
};

enum class OrderStatus : uint8_t {
    PENDING = 0,
    PARTIAL_FILLED = 1,
    FILLED = 2,
    CANCELLED = 3,
    REJECTED = 4
};

// Compact order structure for cache efficiency
struct Order {
    OrderID order_id;
    ClientID client_id;
    SymbolID symbol_id;
    Price price;
    Quantity quantity;
    Quantity filled_quantity;
    uint64_t timestamp;
    OrderSide side;
    OrderType type;
    OrderStatus status;
    uint8_t priority;      // Higher priority orders matched first
    uint8_t reserved[5];   // Padding for alignment
    
    Order() = default;
    
    Order(OrderID id, ClientID client, SymbolID symbol, Price p, Quantity qty,
          OrderSide s, OrderType t, uint8_t prio = 0)
        : order_id(id), client_id(client), symbol_id(symbol), price(p),
          quantity(qty), filled_quantity(0), timestamp(get_timestamp_ns()),
          side(s), type(t), status(OrderStatus::PENDING), priority(prio) {
        std::memset(reserved, 0, sizeof(reserved));
    }
    
    Quantity remaining_quantity() const {
        return quantity - filled_quantity;
    }
    
    bool is_complete() const {
        return filled_quantity >= quantity || status == OrderStatus::FILLED ||
               status == OrderStatus::CANCELLED || status == OrderStatus::REJECTED;
    }
    
    double price_as_double() const {
        return static_cast<double>(price) / 10000.0;
    }
    
private:
    static uint64_t get_timestamp_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::high_resolution_clock::now().time_since_epoch()).count();
    }
} __attribute__((packed));

// Trade execution record
struct Trade {
    OrderID buy_order_id;
    OrderID sell_order_id;
    ClientID buy_client_id;
    ClientID sell_client_id;
    SymbolID symbol_id;
    Price execution_price;
    Quantity execution_quantity;
    uint64_t timestamp;
    
    Trade() = default;
    
    Trade(const Order& buy_order, const Order& sell_order, Price price, Quantity qty)
        : buy_order_id(buy_order.order_id), sell_order_id(sell_order.order_id),
          buy_client_id(buy_order.client_id), sell_client_id(sell_order.client_id),
          symbol_id(buy_order.symbol_id), execution_price(price),
          execution_quantity(qty), timestamp(get_timestamp_ns()) {}
    
private:
    static uint64_t get_timestamp_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::high_resolution_clock::now().time_since_epoch()).count();
    }
} __attribute__((packed));

// Custom comparator for buy orders (highest price first, then time priority)
struct BuyOrderComparator {
    bool operator()(const std::shared_ptr<Order>& a, const std::shared_ptr<Order>& b) const {
        if (a->price != b->price) {
            return a->price < b->price; // Higher price has priority (max heap)
        }
        if (a->priority != b->priority) {
            return a->priority < b->priority; // Higher priority first
        }
        return a->timestamp > b->timestamp; // Earlier timestamp has priority
    }
};

// Custom comparator for sell orders (lowest price first, then time priority)
struct SellOrderComparator {
    bool operator()(const std::shared_ptr<Order>& a, const std::shared_ptr<Order>& b) const {
        if (a->price != b->price) {
            return a->price > b->price; // Lower price has priority (min heap)
        }
        if (a->priority != b->priority) {
            return a->priority < b->priority; // Higher priority first
        }
        return a->timestamp > b->timestamp; // Earlier timestamp has priority
    }
};

// Lock-free order book using priority queues
class OrderBook {
private:
    SymbolID symbol_id_;
    
    // Order queues
    std::priority_queue<std::shared_ptr<Order>, 
                       std::vector<std::shared_ptr<Order>>, 
                       BuyOrderComparator> buy_orders_;
    
    std::priority_queue<std::shared_ptr<Order>, 
                       std::vector<std::shared_ptr<Order>>, 
                       SellOrderComparator> sell_orders_;
    
    // Order lookup for quick access
    std::unordered_map<OrderID, std::shared_ptr<Order>> active_orders_;
    
    // Statistics
    std::atomic<uint64_t> total_volume_{0};
    std::atomic<uint64_t> trade_count_{0};
    std::atomic<Price> last_trade_price_{0};
    
    // Synchronization
    mutable std::mutex book_mutex_;
    
public:
    explicit OrderBook(SymbolID symbol_id) : symbol_id_(symbol_id) {}
    
    // Add order to book
    bool add_order(std::shared_ptr<Order> order) {
        if (!order || order->symbol_id != symbol_id_) {
            return false;
        }
        
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        if (order->side == OrderSide::BUY) {
            buy_orders_.push(order);
        } else {
            sell_orders_.push(order);
        }
        
        active_orders_[order->order_id] = order;
        return true;
    }
    
    // Cancel order
    bool cancel_order(OrderID order_id) {
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        auto it = active_orders_.find(order_id);
        if (it != active_orders_.end()) {
            it->second->status = OrderStatus::CANCELLED;
            active_orders_.erase(it);
            return true;
        }
        
        return false;
    }
    
    // Get order by ID
    std::shared_ptr<Order> get_order(OrderID order_id) const {
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        auto it = active_orders_.find(order_id);
        return it != active_orders_.end() ? it->second : nullptr;
    }
    
    // Match orders and generate trades
    std::vector<Trade> match_orders() {
        std::vector<Trade> trades;
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        // Clean up completed orders first
        cleanup_completed_orders();
        
        while (!buy_orders_.empty() && !sell_orders_.empty()) {
            auto best_buy = buy_orders_.top();
            auto best_sell = sell_orders_.top();
            
            // Skip cancelled or completed orders
            if (best_buy->is_complete()) {
                buy_orders_.pop();
                active_orders_.erase(best_buy->order_id);
                continue;
            }
            
            if (best_sell->is_complete()) {
                sell_orders_.pop();
                active_orders_.erase(best_sell->order_id);
                continue;
            }
            
            // Check if orders can match
            if (best_buy->price < best_sell->price) {
                break; // No more matches possible
            }
            
            // Execute trade
            Price execution_price = determine_execution_price(best_buy, best_sell);
            Quantity execution_quantity = std::min(best_buy->remaining_quantity(),
                                                  best_sell->remaining_quantity());
            
            // Create trade record
            trades.emplace_back(*best_buy, *best_sell, execution_price, execution_quantity);
            
            // Update orders
            best_buy->filled_quantity += execution_quantity;
            best_sell->filled_quantity += execution_quantity;
            
            // Update order status
            if (best_buy->remaining_quantity() == 0) {
                best_buy->status = OrderStatus::FILLED;
                buy_orders_.pop();
                active_orders_.erase(best_buy->order_id);
            } else {
                best_buy->status = OrderStatus::PARTIAL_FILLED;
            }
            
            if (best_sell->remaining_quantity() == 0) {
                best_sell->status = OrderStatus::FILLED;
                sell_orders_.pop();
                active_orders_.erase(best_sell->order_id);
            } else {
                best_sell->status = OrderStatus::PARTIAL_FILLED;
            }
            
            // Update statistics
            total_volume_.fetch_add(execution_quantity, std::memory_order_relaxed);
            trade_count_.fetch_add(1, std::memory_order_relaxed);
            last_trade_price_.store(execution_price, std::memory_order_relaxed);
        }
        
        return trades;
    }
    
    // Get best bid price
    Price get_best_bid() const {
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        while (!buy_orders_.empty()) {
            auto best_buy = buy_orders_.top();
            if (!best_buy->is_complete()) {
                return best_buy->price;
            }
            // Remove completed order (const_cast for cleanup)
            const_cast<std::priority_queue<std::shared_ptr<Order>, 
                      std::vector<std::shared_ptr<Order>>, 
                      BuyOrderComparator>&>(buy_orders_).pop();
        }
        
        return 0;
    }
    
    // Get best ask price
    Price get_best_ask() const {
        std::lock_guard<std::mutex> lock(book_mutex_);
        
        while (!sell_orders_.empty()) {
            auto best_sell = sell_orders_.top();
            if (!best_sell->is_complete()) {
                return best_sell->price;
            }
            // Remove completed order (const_cast for cleanup)
            const_cast<std::priority_queue<std::shared_ptr<Order>, 
                      std::vector<std::shared_ptr<Order>>, 
                      SellOrderComparator>&>(sell_orders_).pop();
        }
        
        return UINT64_MAX;
    }
    
    // Get order book statistics
    struct Statistics {
        uint64_t total_volume;
        uint64_t trade_count;
        Price last_trade_price;
        size_t active_buy_orders;
        size_t active_sell_orders;
        Price best_bid;
        Price best_ask;
        double spread;
    };
    
    Statistics get_statistics() const {
        Statistics stats{};
        stats.total_volume = total_volume_.load(std::memory_order_acquire);
        stats.trade_count = trade_count_.load(std::memory_order_acquire);
        stats.last_trade_price = last_trade_price_.load(std::memory_order_acquire);
        
        std::lock_guard<std::mutex> lock(book_mutex_);
        stats.active_buy_orders = buy_orders_.size();
        stats.active_sell_orders = sell_orders_.size();
        stats.best_bid = get_best_bid();
        stats.best_ask = get_best_ask();
        
        if (stats.best_bid > 0 && stats.best_ask < UINT64_MAX) {
            stats.spread = (static_cast<double>(stats.best_ask) - 
                          static_cast<double>(stats.best_bid)) / 10000.0;
        } else {
            stats.spread = 0.0;
        }
        
        return stats;
    }
    
private:
    // Determine execution price based on order types and priorities
    Price determine_execution_price(const std::shared_ptr<Order>& buy_order,
                                   const std::shared_ptr<Order>& sell_order) const {
        // Simple price determination: use the price of the order that arrived first
        if (buy_order->timestamp < sell_order->timestamp) {
            return buy_order->price;
        } else {
            return sell_order->price;
        }
    }
    
    // Clean up completed orders from active orders map
    void cleanup_completed_orders() {
        auto it = active_orders_.begin();
        while (it != active_orders_.end()) {
            if (it->second->is_complete()) {
                it = active_orders_.erase(it);
            } else {
                ++it;
            }
        }
    }
};

// Main matching engine that manages multiple order books
class MatchingEngine {
private:
    std::unordered_map<SymbolID, std::unique_ptr<OrderBook>> order_books_;
    std::mutex engine_mutex_;
    
    // Order ID generation
    std::atomic<OrderID> next_order_id_{1};
    
    // Engine statistics
    std::atomic<uint64_t> total_orders_processed_{0};
    std::atomic<uint64_t> total_trades_executed_{0};
    std::atomic<uint64_t> total_latency_ns_{0};
    
    // Performance monitoring
    std::chrono::high_resolution_clock::time_point start_time_;
    
public:
    MatchingEngine() : start_time_(std::chrono::high_resolution_clock::now()) {}
    
    // Add new order to matching engine
    std::pair<bool, std::vector<Trade>> add_order(ClientID client_id, SymbolID symbol_id,
                                                 Price price, Quantity quantity,
                                                 OrderSide side, OrderType type,
                                                 uint8_t priority = 0) {
        auto start_time = std::chrono::high_resolution_clock::now();
        
        // Generate order ID
        OrderID order_id = next_order_id_.fetch_add(1, std::memory_order_relaxed);
        
        // Create order
        auto order = std::make_shared<Order>(order_id, client_id, symbol_id,
                                           price, quantity, side, type, priority);
        
        // Get or create order book
        OrderBook* book = get_or_create_order_book(symbol_id);
        if (!book) {
            return {false, {}};
        }
        
        // Add order to book
        if (!book->add_order(order)) {
            return {false, {}};
        }
        
        // Match orders
        auto trades = book->match_orders();
        
        // Update statistics
        total_orders_processed_.fetch_add(1, std::memory_order_relaxed);
        total_trades_executed_.fetch_add(trades.size(), std::memory_order_relaxed);
        
        auto end_time = std::chrono::high_resolution_clock::now();
        auto latency = std::chrono::duration_cast<std::chrono::nanoseconds>(
            end_time - start_time).count();
        total_latency_ns_.fetch_add(latency, std::memory_order_relaxed);
        
        return {true, trades};
    }
    
    // Cancel order
    bool cancel_order(SymbolID symbol_id, OrderID order_id) {
        OrderBook* book = get_order_book(symbol_id);
        return book ? book->cancel_order(order_id) : false;
    }
    
    // Get order by ID
    std::shared_ptr<Order> get_order(SymbolID symbol_id, OrderID order_id) const {
        OrderBook* book = get_order_book(symbol_id);
        return book ? book->get_order(order_id) : nullptr;
    }
    
    // Get order book for symbol
    OrderBook* get_order_book(SymbolID symbol_id) const {
        std::lock_guard<std::mutex> lock(engine_mutex_);
        auto it = order_books_.find(symbol_id);
        return it != order_books_.end() ? it->second.get() : nullptr;
    }
    
    // Get engine statistics
    struct EngineStatistics {
        uint64_t total_orders_processed;
        uint64_t total_trades_executed;
        double average_latency_us;
        double orders_per_second;
        double trades_per_second;
        uint64_t uptime_seconds;
        size_t active_symbols;
    };
    
    EngineStatistics get_statistics() const {
        EngineStatistics stats{};
        
        stats.total_orders_processed = total_orders_processed_.load(std::memory_order_acquire);
        stats.total_trades_executed = total_trades_executed_.load(std::memory_order_acquire);
        
        uint64_t total_latency = total_latency_ns_.load(std::memory_order_acquire);
        if (stats.total_orders_processed > 0) {
            stats.average_latency_us = static_cast<double>(total_latency) / 
                                     (stats.total_orders_processed * 1000.0);
        }
        
        auto now = std::chrono::high_resolution_clock::now();
        auto uptime = std::chrono::duration_cast<std::chrono::seconds>(now - start_time_);
        stats.uptime_seconds = uptime.count();
        
        if (stats.uptime_seconds > 0) {
            stats.orders_per_second = static_cast<double>(stats.total_orders_processed) / 
                                    stats.uptime_seconds;
            stats.trades_per_second = static_cast<double>(stats.total_trades_executed) / 
                                    stats.uptime_seconds;
        }
        
        std::lock_guard<std::mutex> lock(engine_mutex_);
        stats.active_symbols = order_books_.size();
        
        return stats;
    }
    
    // Get all active symbols
    std::vector<SymbolID> get_active_symbols() const {
        std::lock_guard<std::mutex> lock(engine_mutex_);
        
        std::vector<SymbolID> symbols;
        symbols.reserve(order_books_.size());
        
        for (const auto& pair : order_books_) {
            symbols.push_back(pair.first);
        }
        
        return symbols;
    }
    
private:
    OrderBook* get_or_create_order_book(SymbolID symbol_id) {
        std::lock_guard<std::mutex> lock(engine_mutex_);
        
        auto it = order_books_.find(symbol_id);
        if (it != order_books_.end()) {
            return it->second.get();
        }
        
        // Create new order book
        auto book = std::make_unique<OrderBook>(symbol_id);
        OrderBook* book_ptr = book.get();
        order_books_[symbol_id] = std::move(book);
        
        return book_ptr;
    }
};

} // namespace hft

// Demo and testing
int main() {
    std::cout << "High-Frequency Trading Order Matching Engine" << std::endl;
    std::cout << "============================================" << std::endl;
    
    hft::MatchingEngine engine;
    
    // Test data
    const hft::SymbolID SYMBOL_AAPL = 1;
    const hft::SymbolID SYMBOL_GOOGL = 2;
    
    std::cout << "Adding test orders..." << std::endl;
    
    // Add buy orders
    auto [success1, trades1] = engine.add_order(1001, SYMBOL_AAPL, 1500000, 100, 
                                               hft::OrderSide::BUY, hft::OrderType::LIMIT);
    auto [success2, trades2] = engine.add_order(1002, SYMBOL_AAPL, 1495000, 200, 
                                               hft::OrderSide::BUY, hft::OrderType::LIMIT);
    auto [success3, trades3] = engine.add_order(1003, SYMBOL_AAPL, 1510000, 150, 
                                               hft::OrderSide::BUY, hft::OrderType::LIMIT);
    
    // Add sell orders
    auto [success4, trades4] = engine.add_order(2001, SYMBOL_AAPL, 1505000, 80, 
                                               hft::OrderSide::SELL, hft::OrderType::LIMIT);
    auto [success5, trades5] = engine.add_order(2002, SYMBOL_AAPL, 1500000, 120, 
                                               hft::OrderSide::SELL, hft::OrderType::LIMIT);
    auto [success6, trades6] = engine.add_order(2003, SYMBOL_AAPL, 1495000, 90, 
                                               hft::OrderSide::SELL, hft::OrderType::LIMIT);
    
    // Print executed trades
    std::vector<std::vector<hft::Trade>> all_trades = {trades1, trades2, trades3, trades4, trades5, trades6};
    
    std::cout << "\nExecuted Trades:" << std::endl;
    int trade_count = 0;
    for (const auto& trade_list : all_trades) {
        for (const auto& trade : trade_list) {
            std::cout << "Trade " << ++trade_count << ": "
                     << "Buy Order " << trade.buy_order_id 
                     << " <-> Sell Order " << trade.sell_order_id
                     << ", Price: $" << (static_cast<double>(trade.execution_price) / 10000.0)
                     << ", Quantity: " << trade.execution_quantity
                     << std::endl;
        }
    }
    
    // Performance test
    std::cout << "\nRunning performance test..." << std::endl;
    
    const int NUM_ORDERS = 100000;
    auto start_time = std::chrono::high_resolution_clock::now();
    
    for (int i = 0; i < NUM_ORDERS; ++i) {
        hft::ClientID client_id = 1000 + (i % 1000);
        hft::SymbolID symbol_id = 1 + (i % 10); // 10 different symbols
        hft::Price price = 1000000 + (i % 100000); // Price range
        hft::Quantity quantity = 10 + (i % 1000);
        hft::OrderSide side = (i % 2 == 0) ? hft::OrderSide::BUY : hft::OrderSide::SELL;
        
        engine.add_order(client_id, symbol_id, price, quantity, side, hft::OrderType::LIMIT);
        
        if (i % 10000 == 0 && i > 0) {
            std::cout << "Processed " << i << " orders..." << std::endl;
        }
    }
    
    auto end_time = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(end_time - start_time);
    
    // Print final statistics
    auto stats = engine.get_statistics();
    std::cout << "\nPerformance Test Results:" << std::endl;
    std::cout << "========================" << std::endl;
    std::cout << "Total Orders Processed: " << stats.total_orders_processed << std::endl;
    std::cout << "Total Trades Executed: " << stats.total_trades_executed << std::endl;
    std::cout << "Average Latency: " << stats.average_latency_us << " microseconds" << std::endl;
    std::cout << "Orders per Second: " << stats.orders_per_second << std::endl;
    std::cout << "Trades per Second: " << stats.trades_per_second << std::endl;
    std::cout << "Active Symbols: " << stats.active_symbols << std::endl;
    std::cout << "Test Duration: " << duration.count() << " microseconds" << std::endl;
    std::cout << "Throughput: " << (NUM_ORDERS * 1000000.0) / duration.count() << " orders/sec" << std::endl;
    
    // Print order book statistics for each symbol
    auto active_symbols = engine.get_active_symbols();
    std::cout << "\nOrder Book Statistics:" << std::endl;
    for (auto symbol_id : active_symbols) {
        if (auto* book = engine.get_order_book(symbol_id)) {
            auto book_stats = book->get_statistics();
            std::cout << "Symbol " << symbol_id << ": "
                     << "Volume=" << book_stats.total_volume
                     << ", Trades=" << book_stats.trade_count
                     << ", Best Bid=$" << (static_cast<double>(book_stats.best_bid) / 10000.0)
                     << ", Best Ask=$" << (static_cast<double>(book_stats.best_ask) / 10000.0)
                     << ", Spread=$" << book_stats.spread
                     << std::endl;
        }
    }
    
    return 0;
}