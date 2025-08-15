-- ClickHouse DDL for Dcard Lambda Architecture Serving Layer
-- This script creates tables for both batch and speed layer data

-- Create database
CREATE DATABASE IF NOT EXISTS dcard_lambda;
USE dcard_lambda;

-- =================================================================
-- BATCH LAYER TABLES (Source of Truth)
-- =================================================================

-- 1. Batch layer user post counts (pre-computed from historical data)
CREATE TABLE IF NOT EXISTS user_post_counts_batch (
    user_id UInt64,
    total_post_count UInt64,
    total_event_count UInt64,
    last_updated DateTime64(3, 'UTC'),
    first_event_timestamp DateTime64(3, 'UTC'),
    processing_date Date,
    batch_version UInt32 DEFAULT 1,
    date Date MATERIALIZED toDate(processing_date)
) ENGINE = ReplacingMergeTree(batch_version, last_updated)
PARTITION BY toYYYYMM(date)
ORDER BY (user_id, processing_date)
SETTINGS index_granularity = 8192;

-- 2. Batch layer board statistics
CREATE TABLE IF NOT EXISTS board_statistics_batch (
    board_id String,
    processing_date Date,
    posts_created UInt64,
    active_users UInt64,
    unique_posts UInt64,
    avg_posts_per_user Float64,
    batch_version UInt32 DEFAULT 1
) ENGINE = ReplacingMergeTree(batch_version)
PARTITION BY toYYYYMM(processing_date)
ORDER BY (board_id, processing_date)
SETTINGS index_granularity = 8192;

-- =================================================================
-- SPEED LAYER TABLES (Real-time Increments)
-- =================================================================

-- 3. Speed layer user post counts (incremental from recent events)
CREATE TABLE IF NOT EXISTS user_post_counts_speed (
    user_id UInt64,
    post_count_delta Int64,
    event_count UInt64,
    last_updated DateTime64(3, 'UTC'),
    window_start DateTime64(3, 'UTC'),
    window_end DateTime64(3, 'UTC'),
    processing_timestamp DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(window_start)
ORDER BY (user_id, window_start)
TTL window_start + INTERVAL 7 DAY
SETTINGS index_granularity = 4096;

-- 4. Speed layer board statistics (real-time board metrics)
CREATE TABLE IF NOT EXISTS board_stats_speed (
    board_id String,
    window_start DateTime64(3, 'UTC'),
    window_end DateTime64(3, 'UTC'),
    event_count UInt64,
    active_users UInt64,
    posts_created UInt64,
    processing_timestamp DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(window_start)
ORDER BY (board_id, window_start)
TTL window_start + INTERVAL 3 DAY
SETTINGS index_granularity = 4096;

-- 5. Real-time metrics for monitoring
CREATE TABLE IF NOT EXISTS realtime_metrics (
    metric_time DateTime64(3, 'UTC'),
    events_per_minute UInt64,
    active_users_per_minute UInt64,
    posts_created_per_minute UInt64,
    posts_deleted_per_minute UInt64,
    processing_timestamp DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(metric_time)
ORDER BY metric_time
TTL metric_time + INTERVAL 1 DAY
SETTINGS index_granularity = 1024;

-- =================================================================
-- SERVING LAYER VIEWS (Lambda Architecture Query Layer)
-- =================================================================

-- 6. Metadata table to track batch processing cutoff
CREATE TABLE IF NOT EXISTS processing_metadata (
    key String,
    value String,
    updated_at DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY key
SETTINGS index_granularity = 8192;

-- Insert initial metadata
INSERT INTO processing_metadata (key, value) VALUES 
    ('batch_cutoff_date', '1970-01-01'),
    ('speed_layer_enabled', 'true'),
    ('serving_layer_version', '1.0.0');

-- 7. Unified view combining batch and speed layer data
CREATE VIEW IF NOT EXISTS user_post_counts_unified AS
SELECT 
    user_id,
    SUM(post_count) as total_post_count,
    MAX(last_updated) as last_updated,
    'unified' as source_layer
FROM (
    -- Batch layer data (historical, accurate)
    SELECT 
        user_id,
        total_post_count as post_count,
        last_updated,
        'batch' as layer_type
    FROM user_post_counts_batch b
    WHERE processing_date = (
        SELECT toDate(value) 
        FROM processing_metadata 
        WHERE key = 'batch_cutoff_date'
    )
    
    UNION ALL
    
    -- Speed layer data (recent, incremental)
    SELECT 
        user_id,
        SUM(post_count_delta) as post_count,
        MAX(last_updated) as last_updated,
        'speed' as layer_type
    FROM user_post_counts_speed s
    WHERE window_start > (
        SELECT toDateTime64(value || ' 00:00:00', 3, 'UTC')
        FROM processing_metadata 
        WHERE key = 'batch_cutoff_date'
    )
    GROUP BY user_id
)
GROUP BY user_id;

-- 8. Board statistics unified view
CREATE VIEW IF NOT EXISTS board_statistics_unified AS
SELECT 
    board_id,
    SUM(posts_created) as total_posts_created,
    SUM(active_users) as total_active_users,
    MAX(last_updated) as last_updated
FROM (
    -- Batch layer board stats
    SELECT 
        board_id,
        posts_created,
        active_users,
        toDateTime64(toString(processing_date) || ' 23:59:59', 3, 'UTC') as last_updated
    FROM board_statistics_batch
    WHERE processing_date = (
        SELECT toDate(value)
        FROM processing_metadata 
        WHERE key = 'batch_cutoff_date'
    )
    
    UNION ALL
    
    -- Speed layer board stats
    SELECT 
        board_id,
        posts_created,
        active_users,
        window_end as last_updated
    FROM board_stats_speed
    WHERE window_start > (
        SELECT toDateTime64(value || ' 00:00:00', 3, 'UTC')
        FROM processing_metadata 
        WHERE key = 'batch_cutoff_date'
    )
)
GROUP BY board_id;

-- =================================================================
-- PERFORMANCE OPTIMIZATION
-- =================================================================

-- Indexes for better query performance
ALTER TABLE user_post_counts_batch ADD INDEX IF NOT EXISTS idx_user_id user_id TYPE minmax GRANULARITY 1;
ALTER TABLE user_post_counts_batch ADD INDEX IF NOT EXISTS idx_processing_date processing_date TYPE minmax GRANULARITY 4;

ALTER TABLE user_post_counts_speed ADD INDEX IF NOT EXISTS idx_user_id user_id TYPE minmax GRANULARITY 1;
ALTER TABLE user_post_counts_speed ADD INDEX IF NOT EXISTS idx_window_start window_start TYPE minmax GRANULARITY 2;

ALTER TABLE board_statistics_batch ADD INDEX IF NOT EXISTS idx_board_id board_id TYPE set(1000) GRANULARITY 8;
ALTER TABLE board_stats_speed ADD INDEX IF NOT EXISTS idx_board_id board_id TYPE set(1000) GRANULARITY 4;

-- =================================================================
-- MATERIALIZED VIEWS FOR FAST QUERIES
-- =================================================================

-- 9. Top users materialized view (updated from unified view)
CREATE MATERIALIZED VIEW IF NOT EXISTS top_users_mv
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY (-total_post_count, user_id)
SETTINGS index_granularity = 8192
AS SELECT
    user_id,
    total_post_count,
    last_updated,
    now64() as materialized_at
FROM user_post_counts_unified
WHERE total_post_count > 0;

-- 10. System health materialized view
CREATE MATERIALIZED VIEW IF NOT EXISTS system_health_mv
ENGINE = ReplacingMergeTree(update_time)
ORDER BY metric_name
SETTINGS index_granularity = 1024
AS SELECT
    'total_users' as metric_name,
    toString(count()) as metric_value,
    now64() as update_time
FROM user_post_counts_unified
WHERE total_post_count > 0

UNION ALL

SELECT
    'total_posts' as metric_name,
    toString(sum(total_post_count)) as metric_value,
    now64() as update_time
FROM user_post_counts_unified

UNION ALL

SELECT
    'active_boards' as metric_name,
    toString(count()) as metric_value,
    now64() as update_time
FROM board_statistics_unified
WHERE total_posts_created > 0;

-- =================================================================
-- SAMPLE DATA FOR TESTING
-- =================================================================

-- Insert sample batch cutoff date
INSERT INTO processing_metadata (key, value) VALUES 
    ('batch_cutoff_date', toString(today() - 1))
ON DUPLICATE KEY UPDATE value = toString(today() - 1), updated_at = now64();