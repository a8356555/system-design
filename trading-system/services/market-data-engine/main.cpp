#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include <unordered_map>
#include <atomic>
#include <thread>
#include <chrono>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <immintrin.h>
#include <sys/mman.h>
#include <numa.h>

// High-Frequency Trading Market Data Engine
// Designed for ultra-low latency market data processing

namespace hft {

// Lock-free circular buffer for market data
template<typename T, size_t Size>
class LockFreeRingBuffer {
private:
    static_assert((Size & (Size - 1)) == 0, "Size must be power of 2");
    static constexpr size_t MASK = Size - 1;
    
    alignas(64) std::atomic<size_t> head_{0};
    alignas(64) std::atomic<size_t> tail_{0};
    alignas(64) T buffer_[Size];

public:
    bool push(const T& item) {
        const size_t head = head_.load(std::memory_order_relaxed);
        const size_t next_head = (head + 1) & MASK;
        
        if (next_head == tail_.load(std::memory_order_acquire)) {
            return false; // Buffer full
        }
        
        buffer_[head] = item;
        head_.store(next_head, std::memory_order_release);
        return true;
    }
    
    bool pop(T& item) {
        const size_t tail = tail_.load(std::memory_order_relaxed);
        
        if (tail == head_.load(std::memory_order_acquire)) {
            return false; // Buffer empty
        }
        
        item = buffer_[tail];
        tail_.store((tail + 1) & MASK, std::memory_order_release);
        return true;
    }
    
    size_t size() const {
        const size_t head = head_.load(std::memory_order_acquire);
        const size_t tail = tail_.load(std::memory_order_acquire);
        return (head - tail) & MASK;
    }
};

// Market data structures
struct Price {
    int64_t value;    // Price in fixed-point (multiply by 10000)
    uint32_t size;    // Size/quantity
    
    Price() : value(0), size(0) {}
    Price(int64_t v, uint32_t s) : value(v), size(s) {}
    
    double to_double() const { return static_cast<double>(value) / 10000.0; }
};

struct MarketDataUpdate {
    uint64_t timestamp;     // Nanoseconds since epoch
    uint64_t symbol_id;     // Symbol identifier
    uint8_t  update_type;   // 0=trade, 1=bid, 2=ask, 3=book_update
    uint8_t  level;         // Order book level (0-based)
    Price    price;
    uint32_t quantity;
    uint32_t order_count;   // Number of orders at this level
    uint8_t  flags;         // Additional flags
    
    MarketDataUpdate() = default;
} __attribute__((packed));

struct OrderBookLevel {
    Price price;
    uint32_t quantity;
    uint32_t order_count;
    uint64_t last_update;
    
    OrderBookLevel() : quantity(0), order_count(0), last_update(0) {}
};

// Ultra-fast order book implementation
class OrderBook {
private:
    static constexpr size_t MAX_LEVELS = 10;
    
    alignas(64) OrderBookLevel bids_[MAX_LEVELS];
    alignas(64) OrderBookLevel asks_[MAX_LEVELS];
    alignas(64) std::atomic<uint64_t> sequence_{0};
    alignas(64) std::atomic<uint64_t> last_trade_price_{0};
    alignas(64) std::atomic<uint32_t> last_trade_size_{0};
    
    uint64_t symbol_id_;
    
public:
    explicit OrderBook(uint64_t symbol_id) : symbol_id_(symbol_id) {
        // Initialize order book levels
        for (size_t i = 0; i < MAX_LEVELS; ++i) {
            bids_[i] = OrderBookLevel{};
            asks_[i] = OrderBookLevel{};
        }
    }
    
    // Update bid level (buy orders)
    inline void update_bid(uint8_t level, const Price& price, uint32_t quantity, uint32_t order_count) {
        if (level >= MAX_LEVELS) return;
        
        auto& bid_level = bids_[level];
        bid_level.price = price;
        bid_level.quantity = quantity;
        bid_level.order_count = order_count;
        bid_level.last_update = get_timestamp_ns();
        
        sequence_.fetch_add(1, std::memory_order_release);
    }
    
    // Update ask level (sell orders)
    inline void update_ask(uint8_t level, const Price& price, uint32_t quantity, uint32_t order_count) {
        if (level >= MAX_LEVELS) return;
        
        auto& ask_level = asks_[level];
        ask_level.price = price;
        ask_level.quantity = quantity;
        ask_level.order_count = order_count;
        ask_level.last_update = get_timestamp_ns();
        
        sequence_.fetch_add(1, std::memory_order_release);
    }
    
    // Process trade
    inline void process_trade(const Price& price, uint32_t size) {
        last_trade_price_.store(price.value, std::memory_order_release);
        last_trade_size_.store(size, std::memory_order_release);
        sequence_.fetch_add(1, std::memory_order_release);
    }
    
    // Get best bid/ask (Level 1)
    inline Price get_best_bid() const {
        return bids_[0].price;
    }
    
    inline Price get_best_ask() const {
        return asks_[0].price;
    }
    
    inline double get_mid_price() const {
        const auto bid = get_best_bid();
        const auto ask = get_best_ask();
        if (bid.value > 0 && ask.value > 0) {
            return (bid.to_double() + ask.to_double()) / 2.0;
        }
        return 0.0;
    }
    
    inline uint64_t get_sequence() const {
        return sequence_.load(std::memory_order_acquire);
    }
    
private:
    static inline uint64_t get_timestamp_ns() {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
    }
};

// Memory pool for zero-allocation message handling
template<typename T, size_t PoolSize>
class MemoryPool {
private:
    alignas(64) T pool_[PoolSize];
    alignas(64) std::atomic<size_t> head_{0};
    alignas(64) std::atomic<size_t> tail_{0};
    static constexpr size_t MASK = PoolSize - 1;
    
    static_assert((PoolSize & (PoolSize - 1)) == 0, "PoolSize must be power of 2");

public:
    MemoryPool() {
        // Initialize pool indices
        for (size_t i = 0; i < PoolSize; ++i) {
            pool_[i] = T{};
        }
    }
    
    T* acquire() {
        const size_t tail = tail_.load(std::memory_order_relaxed);
        const size_t next_tail = (tail + 1) & MASK;
        
        if (next_tail == head_.load(std::memory_order_acquire)) {
            return nullptr; // Pool exhausted
        }
        
        T* item = &pool_[tail];
        tail_.store(next_tail, std::memory_order_release);
        return item;
    }
    
    void release(T* item) {
        if (!item) return;
        
        const size_t head = head_.load(std::memory_order_relaxed);
        const size_t index = item - pool_;
        
        if (index < PoolSize) {
            head_.store((head + 1) & MASK, std::memory_order_release);
        }
    }
};

// Market data feed handler
class MarketDataFeedHandler {
private:
    static constexpr size_t BUFFER_SIZE = 65536;
    static constexpr size_t MAX_SYMBOLS = 10000;
    
    LockFreeRingBuffer<MarketDataUpdate, BUFFER_SIZE> update_buffer_;
    MemoryPool<MarketDataUpdate, BUFFER_SIZE> memory_pool_;
    
    // Order books for each symbol
    std::unordered_map<uint64_t, std::unique_ptr<OrderBook>> order_books_;
    
    // Thread management
    std::atomic<bool> running_{false};
    std::vector<std::thread> worker_threads_;
    
    // Statistics
    alignas(64) std::atomic<uint64_t> updates_processed_{0};
    alignas(64) std::atomic<uint64_t> messages_dropped_{0};
    alignas(64) std::atomic<uint64_t> total_latency_ns_{0};
    
public:
    MarketDataFeedHandler() {
        // Pre-allocate order books for common symbols
        for (uint64_t symbol_id = 1; symbol_id <= 1000; ++symbol_id) {
            order_books_[symbol_id] = std::make_unique<OrderBook>(symbol_id);
        }
    }
    
    ~MarketDataFeedHandler() {
        stop();
    }
    
    void start(size_t num_threads = 4) {
        running_.store(true, std::memory_order_release);
        
        // Start worker threads
        for (size_t i = 0; i < num_threads; ++i) {
            worker_threads_.emplace_back([this, i]() {
                this->worker_thread(i);
            });
            
            // Set CPU affinity for each thread
            cpu_set_t cpuset;
            CPU_ZERO(&cpuset);
            CPU_SET(i, &cpuset);
            pthread_setaffinity_np(worker_threads_.back().native_handle(), 
                                 sizeof(cpu_set_t), &cpuset);
        }
        
        std::cout << "Market data feed handler started with " << num_threads << " threads" << std::endl;
    }
    
    void stop() {
        running_.store(false, std::memory_order_release);
        
        for (auto& thread : worker_threads_) {
            if (thread.joinable()) {
                thread.join();
            }
        }
        worker_threads_.clear();
    }
    
    // Process incoming market data update
    bool process_update(const MarketDataUpdate& update) {
        const uint64_t start_time = get_timestamp_ns();
        
        if (!update_buffer_.push(update)) {
            messages_dropped_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        
        const uint64_t end_time = get_timestamp_ns();
        total_latency_ns_.fetch_add(end_time - start_time, std::memory_order_relaxed);
        
        return true;
    }
    
    // Get order book for symbol
    OrderBook* get_order_book(uint64_t symbol_id) {
        auto it = order_books_.find(symbol_id);
        if (it != order_books_.end()) {
            return it->second.get();
        }
        
        // Create new order book for unknown symbol
        order_books_[symbol_id] = std::make_unique<OrderBook>(symbol_id);
        return order_books_[symbol_id].get();
    }
    
    // Statistics
    struct Statistics {
        uint64_t updates_processed;
        uint64_t messages_dropped;
        double average_latency_us;
        double throughput_updates_per_sec;
    };
    
    Statistics get_statistics() const {
        const uint64_t processed = updates_processed_.load(std::memory_order_acquire);
        const uint64_t dropped = messages_dropped_.load(std::memory_order_acquire);
        const uint64_t total_latency = total_latency_ns_.load(std::memory_order_acquire);
        
        Statistics stats{};
        stats.updates_processed = processed;
        stats.messages_dropped = dropped;
        stats.average_latency_us = processed > 0 ? 
            static_cast<double>(total_latency) / (processed * 1000.0) : 0.0;
        
        // Calculate throughput (simplified)
        static auto start_time = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::seconds>(now - start_time);
        
        if (duration.count() > 0) {
            stats.throughput_updates_per_sec = static_cast<double>(processed) / duration.count();
        }
        
        return stats;
    }
    
private:
    void worker_thread(size_t thread_id) {
        // Set thread priority to maximum
        struct sched_param param;
        param.sched_priority = sched_get_priority_max(SCHED_FIFO);
        sched_setscheduler(0, SCHED_FIFO, &param);
        
        std::cout << "Worker thread " << thread_id << " started" << std::endl;
        
        MarketDataUpdate update;
        while (running_.load(std::memory_order_acquire)) {
            if (update_buffer_.pop(update)) {
                process_market_data_update(update);
                updates_processed_.fetch_add(1, std::memory_order_relaxed);
            } else {
                // Busy wait with CPU pause
                _mm_pause();
            }
        }
        
        std::cout << "Worker thread " << thread_id << " stopped" << std::endl;
    }
    
    void process_market_data_update(const MarketDataUpdate& update) {
        OrderBook* book = get_order_book(update.symbol_id);
        if (!book) return;
        
        switch (update.update_type) {
            case 0: // Trade
                book->process_trade(update.price, update.quantity);
                break;
                
            case 1: // Bid update
                book->update_bid(update.level, update.price, update.quantity, update.order_count);
                break;
                
            case 2: // Ask update
                book->update_ask(update.level, update.price, update.quantity, update.order_count);
                break;
                
            case 3: // Full book update
                // Handle full order book refresh
                break;
                
            default:
                // Unknown update type
                break;
        }
    }
    
    static inline uint64_t get_timestamp_ns() {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
    }
};

// FIX protocol message parser for market data feeds
class FIXMessageParser {
private:
    static constexpr char SOH = '\x01'; // Start of Header
    
public:
    struct FIXMessage {
        std::unordered_map<int, std::string> fields;
        std::string raw_message;
        
        std::string get_field(int tag) const {
            auto it = fields.find(tag);
            return it != fields.end() ? it->second : "";
        }
        
        int get_int_field(int tag) const {
            auto value = get_field(tag);
            return value.empty() ? 0 : std::stoi(value);
        }
        
        double get_double_field(int tag) const {
            auto value = get_field(tag);
            return value.empty() ? 0.0 : std::stod(value);
        }
    };
    
    // Parse FIX message from buffer
    static bool parse_message(const char* buffer, size_t length, FIXMessage& message) {
        message.fields.clear();
        message.raw_message.assign(buffer, length);
        
        const char* ptr = buffer;
        const char* end = buffer + length;
        
        while (ptr < end) {
            // Find tag
            const char* tag_start = ptr;
            while (ptr < end && *ptr != '=') ++ptr;
            if (ptr >= end) break;
            
            int tag = std::atoi(std::string(tag_start, ptr - tag_start).c_str());
            ++ptr; // Skip '='
            
            // Find value
            const char* value_start = ptr;
            while (ptr < end && *ptr != SOH) ++ptr;
            
            std::string value(value_start, ptr - value_start);
            message.fields[tag] = value;
            
            if (ptr < end && *ptr == SOH) ++ptr; // Skip SOH
        }
        
        return !message.fields.empty();
    }
    
    // Convert FIX market data message to internal format
    static bool convert_to_market_data(const FIXMessage& fix_msg, MarketDataUpdate& update) {
        // FIX tags for market data
        const int MSG_TYPE = 35;
        const int SYMBOL = 55;
        const int MD_ENTRY_TYPE = 269;
        const int MD_ENTRY_PX = 270;
        const int MD_ENTRY_SIZE = 271;
        const int MD_ENTRY_POSITION_NO = 290;
        
        std::string msg_type = fix_msg.get_field(MSG_TYPE);
        if (msg_type != "W") return false; // Not a market data snapshot
        
        // Extract symbol and convert to ID (simplified)
        std::string symbol = fix_msg.get_field(SYMBOL);
        update.symbol_id = std::hash<std::string>{}(symbol);
        
        // Extract price and size
        double price_dbl = fix_msg.get_double_field(MD_ENTRY_PX);
        update.price = Price(static_cast<int64_t>(price_dbl * 10000), 0);
        update.quantity = fix_msg.get_int_field(MD_ENTRY_SIZE);
        
        // Determine update type
        char entry_type = fix_msg.get_field(MD_ENTRY_TYPE)[0];
        switch (entry_type) {
            case '0': update.update_type = 1; break; // Bid
            case '1': update.update_type = 2; break; // Ask
            case '2': update.update_type = 0; break; // Trade
            default: return false;
        }
        
        update.level = fix_msg.get_int_field(MD_ENTRY_POSITION_NO);
        update.timestamp = get_timestamp_ns();
        
        return true;
    }
    
private:
    static inline uint64_t get_timestamp_ns() {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
    }
};

} // namespace hft

// Main application
int main() {
    std::cout << "High-Frequency Trading Market Data Engine" << std::endl;
    std::cout << "=========================================" << std::endl;
    
    // Initialize NUMA if available
    if (numa_available() >= 0) {
        numa_set_localalloc();
        std::cout << "NUMA optimization enabled" << std::endl;
    }
    
    // Create market data handler
    hft::MarketDataFeedHandler handler;
    
    // Start processing threads
    const size_t num_threads = std::thread::hardware_concurrency();
    handler.start(num_threads);
    
    // Simulate market data feed
    std::thread simulator([&handler]() {
        std::cout << "Starting market data simulation..." << std::endl;
        
        uint64_t message_count = 0;
        const uint64_t target_rate = 1000000; // 1M updates per second
        auto start_time = std::chrono::high_resolution_clock::now();
        
        while (message_count < target_rate * 10) { // Run for 10 seconds
            hft::MarketDataUpdate update{};
            update.timestamp = hft::get_timestamp_ns();
            update.symbol_id = (message_count % 1000) + 1; // Rotate through 1000 symbols
            update.update_type = message_count % 3; // Rotate update types
            update.level = message_count % 5; // Rotate through 5 levels
            update.price = hft::Price(1000000 + (message_count % 10000), 0); // Price range
            update.quantity = (message_count % 1000) + 1;
            update.order_count = (message_count % 10) + 1;
            
            if (!handler.process_update(update)) {
                std::cerr << "Failed to process update " << message_count << std::endl;
            }
            
            ++message_count;
            
            // Rate limiting (simple)
            if (message_count % 100000 == 0) {
                auto stats = handler.get_statistics();
                std::cout << "Processed: " << stats.updates_processed 
                         << ", Dropped: " << stats.messages_dropped
                         << ", Avg Latency: " << stats.average_latency_us << "us"
                         << ", Throughput: " << stats.throughput_updates_per_sec << " ups"
                         << std::endl;
            }
        }
        
        auto end_time = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::microseconds>(end_time - start_time);
        
        std::cout << "Simulation completed in " << duration.count() << " microseconds" << std::endl;
        std::cout << "Average rate: " << (message_count * 1000000.0) / duration.count() << " messages/sec" << std::endl;
    });
    
    // Run for a while then shutdown
    std::this_thread::sleep_for(std::chrono::seconds(15));
    
    // Stop simulation
    simulator.join();
    
    // Print final statistics
    auto final_stats = handler.get_statistics();
    std::cout << "\nFinal Statistics:" << std::endl;
    std::cout << "Updates Processed: " << final_stats.updates_processed << std::endl;
    std::cout << "Messages Dropped: " << final_stats.messages_dropped << std::endl;
    std::cout << "Average Latency: " << final_stats.average_latency_us << " microseconds" << std::endl;
    std::cout << "Throughput: " << final_stats.throughput_updates_per_sec << " updates/sec" << std::endl;
    
    // Shutdown
    handler.stop();
    
    return 0;
}