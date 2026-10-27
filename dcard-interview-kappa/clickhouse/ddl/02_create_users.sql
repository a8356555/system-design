-- ClickHouse User Management for Dcard Post Tracking System

-- Create application user for Flink streaming job
CREATE USER IF NOT EXISTS flink_user 
IDENTIFIED WITH plaintext_password BY 'flink_password_2024';

-- Grant necessary permissions to flink user
GRANT INSERT, SELECT ON dcard.user_post_counts TO flink_user;
GRANT INSERT, SELECT ON dcard.post_events TO flink_user;
GRANT SELECT ON dcard.daily_post_stats TO flink_user;
GRANT SELECT ON dcard.realtime_metrics TO flink_user;

-- Create read-only user for analytics and monitoring
CREATE USER IF NOT EXISTS analytics_user
IDENTIFIED WITH plaintext_password BY 'analytics_readonly_2024';

-- Grant read-only permissions
GRANT SELECT ON dcard.* TO analytics_user;

-- Create admin user for maintenance
CREATE USER IF NOT EXISTS dcard_admin
IDENTIFIED WITH plaintext_password BY 'admin_secure_password_2024';

-- Grant admin permissions
GRANT ALL ON dcard.* TO dcard_admin;
GRANT CREATE, DROP, ALTER ON dcard.* TO dcard_admin;

-- Create backup user for backup operations
CREATE USER IF NOT EXISTS backup_user
IDENTIFIED WITH plaintext_password BY 'backup_secure_password_2024';

-- Grant backup permissions
GRANT SELECT ON dcard.* TO backup_user;
GRANT BACKUP ON dcard.* TO backup_user;

-- Set quotas and limits
CREATE QUOTA IF NOT EXISTS flink_quota 
KEYED BY user_name 
FOR INTERVAL 1 hour MAX queries = 100000, MAX result_rows = 10000000;

CREATE QUOTA IF NOT EXISTS analytics_quota
KEYED BY user_name
FOR INTERVAL 1 hour MAX queries = 1000, MAX result_rows = 1000000;

-- Assign quotas
ALTER QUOTA flink_quota TO flink_user;
ALTER QUOTA analytics_quota TO analytics_user;

-- Create settings profiles for different use cases
CREATE SETTINGS PROFILE IF NOT EXISTS flink_profile SETTINGS
    max_memory_usage = 4000000000,
    max_execution_time = 300,
    max_result_rows = 10000000,
    max_result_bytes = 1000000000,
    readonly = 0;

CREATE SETTINGS PROFILE IF NOT EXISTS analytics_profile SETTINGS
    max_memory_usage = 8000000000,
    max_execution_time = 600,
    max_result_rows = 1000000,
    max_result_bytes = 500000000,
    readonly = 1;

-- Apply profiles to users
ALTER USER flink_user SETTINGS PROFILE 'flink_profile';
ALTER USER analytics_user SETTINGS PROFILE 'analytics_profile';