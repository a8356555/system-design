-- Sample queries for Dcard Post Tracking System
-- These queries demonstrate common use cases and access patterns

USE dcard;

-- 1. Get individual user's post count (most common query)
SELECT post_count, last_updated
FROM user_post_counts
WHERE user_id = 12345;

-- 2. Get top 100 users by post count
SELECT user_id, post_count, last_updated
FROM user_post_counts
ORDER BY post_count DESC, user_id ASC
LIMIT 100;

-- 3. Get users with post count in a specific range
SELECT count() as user_count, avg(post_count) as avg_posts
FROM user_post_counts
WHERE post_count BETWEEN 10 AND 100;

-- 4. Daily active users and post statistics
SELECT 
    date,
    sum(post_count) as total_posts,
    sum(active_users) as total_active_users,
    sum(post_count) / sum(active_users) as avg_posts_per_user
FROM daily_post_stats
WHERE date >= today() - 30
GROUP BY date
ORDER BY date DESC;

-- 5. Real-time metrics for monitoring (last 24 hours)
SELECT 
    hour,
    event_type,
    sum(event_count) as total_events,
    sum(unique_users) as unique_users
FROM realtime_metrics
WHERE hour >= now() - INTERVAL 24 HOUR
GROUP BY hour, event_type
ORDER BY hour DESC, event_type;

-- 6. Board-wise statistics
SELECT 
    board_id,
    sum(post_count) as total_posts,
    sum(active_users) as total_users,
    sum(post_count) / sum(active_users) as posts_per_user
FROM daily_post_stats
WHERE date >= today() - 7  -- Last 7 days
GROUP BY board_id
ORDER BY total_posts DESC
LIMIT 20;

-- 7. User activity timeline (for specific user)
SELECT 
    toDate(timestamp) as date,
    event_type,
    count() as event_count
FROM post_events
WHERE user_id = 12345
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY date, event_type
ORDER BY date DESC;

-- 8. System health check queries
SELECT 
    'Total Users' as metric,
    toString(count()) as value
FROM user_post_counts
WHERE post_count > 0

UNION ALL

SELECT 
    'Total Posts' as metric,
    toString(sum(post_count)) as value
FROM user_post_counts

UNION ALL

SELECT
    'Events Last Hour' as metric,
    toString(sum(event_count)) as value
FROM realtime_metrics
WHERE hour = toStartOfHour(now());

-- 9. Data freshness check
SELECT 
    'Last Event Timestamp' as metric,
    toString(max(last_updated)) as value,
    toString(dateDiff('second', max(last_updated), now())) as seconds_ago
FROM user_post_counts;

-- 10. Performance monitoring queries
-- Check table sizes
SELECT 
    table,
    formatReadableSize(sum(bytes)) as size,
    sum(rows) as rows,
    count() as parts
FROM system.parts
WHERE database = 'dcard'
  AND active = 1
GROUP BY table
ORDER BY sum(bytes) DESC;

-- Check query performance
SELECT 
    query_kind,
    type,
    count() as query_count,
    avg(query_duration_ms) as avg_duration_ms,
    quantile(0.95)(query_duration_ms) as p95_duration_ms
FROM system.query_log
WHERE event_date = today()
  AND databases LIKE '%dcard%'
GROUP BY query_kind, type
ORDER BY avg_duration_ms DESC;

-- 11. Data quality checks
-- Check for negative post counts (should not happen)
SELECT count() as negative_count_users
FROM user_post_counts
WHERE post_count < 0;

-- Check for very old data without updates
SELECT count() as stale_users
FROM user_post_counts
WHERE last_updated < now() - INTERVAL 7 DAY;

-- 12. Export queries for analytics
-- Export daily summary for external analytics
SELECT 
    date,
    sum(post_count) as total_posts,
    sum(active_users) as total_active_users,
    count(distinct board_id) as active_boards
FROM daily_post_stats
WHERE date >= '2024-01-01'
GROUP BY date
ORDER BY date
FORMAT CSV;