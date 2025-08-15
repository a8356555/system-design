-- ClickHouse DDL for Dcard Post Tracking System
-- Run this script to create all necessary tables and views

-- Create database
CREATE DATABASE IF NOT EXISTS dcard;
USE dcard;

-- 1. Primary table for user post counts (optimized for real-time queries)
CREATE TABLE IF NOT EXISTS user_post_counts (
    user_id UInt64,
    post_count UInt64,
    last_updated DateTime64(3, 'UTC'),
    date Date MATERIALIZED toDate(last_updated, 'UTC')
) ENGINE = ReplacingMergeTree(last_updated)
PARTITION BY toYYYYMM(date)
ORDER BY (user_id)
SETTINGS index_granularity = 8192;

-- 2. Historical events table for audit and analytics  
CREATE TABLE IF NOT EXISTS post_events (
    user_id UInt64,
    post_id String,
    event_type Enum8('POST_CREATED' = 1, 'POST_DELETED' = 2),
    timestamp DateTime64(3, 'UTC'),
    board_id Nullable(String),
    metadata Nullable(String),
    date Date MATERIALIZED toDate(timestamp, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (user_id, timestamp)
TTL date + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

-- 3. Daily aggregated statistics (materialized view)
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_post_stats
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, board_id)
SETTINGS index_granularity = 8192
AS SELECT
    toDate(timestamp, 'UTC') as date,
    ifNull(board_id, 'unknown') as board_id,
    count() as post_count,
    uniq(user_id) as active_users
FROM post_events
WHERE event_type = 'POST_CREATED'
GROUP BY date, board_id;

-- 4. Real-time metrics view (for monitoring)
CREATE MATERIALIZED VIEW IF NOT EXISTS realtime_metrics
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMMDD(hour)
ORDER BY (hour, event_type)
SETTINGS index_granularity = 1024
AS SELECT
    toStartOfHour(timestamp) as hour,
    event_type,
    count() as event_count,
    uniq(user_id) as unique_users
FROM post_events
GROUP BY hour, event_type;

-- 5. Top users view (for leaderboards)
CREATE MATERIALIZED VIEW IF NOT EXISTS top_users_daily
ENGINE = ReplacingMergeTree(last_updated)
PARTITION BY toYYYYMM(date)
ORDER BY (date, -post_count, user_id)
SETTINGS index_granularity = 8192
AS SELECT
    toDate(last_updated, 'UTC') as date,
    user_id,
    post_count,
    last_updated
FROM user_post_counts
WHERE post_count > 0;

-- Create indexes for better query performance
-- Note: ClickHouse uses sparse indexes, these are just for reference

-- Index for user lookups
ALTER TABLE user_post_counts ADD INDEX IF NOT EXISTS idx_user_id user_id TYPE minmax GRANULARITY 1;

-- Index for time-based queries on events
ALTER TABLE post_events ADD INDEX IF NOT EXISTS idx_timestamp timestamp TYPE minmax GRANULARITY 4;
ALTER TABLE post_events ADD INDEX IF NOT EXISTS idx_board_id board_id TYPE set(100) GRANULARITY 8;