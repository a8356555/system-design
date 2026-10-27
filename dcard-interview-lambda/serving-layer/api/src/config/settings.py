"""
Configuration settings for the Serving Layer API
"""

from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Application settings
    app_name: str = "Dcard Lambda Architecture - Serving Layer"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    
    # ClickHouse settings
    clickhouse_url: str = "clickhouse://default@clickhouse:9000/dcard_lambda"
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 9000
    clickhouse_database: str = "dcard_lambda"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_max_connections: int = 10
    
    # Redis settings
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_max_connections: int = 20
    
    # Caching settings
    cache_ttl_user_count: int = 300  # 5 minutes
    cache_ttl_top_users: int = 60    # 1 minute
    cache_ttl_system_health: int = 60  # 1 minute
    
    # Performance settings
    query_timeout: int = 30
    max_batch_size: int = 1000
    max_top_users: int = 1000
    
    # Lambda Architecture settings
    batch_cutoff_buffer_hours: int = 1  # Hours to overlap batch/speed layers
    data_freshness_threshold: int = 3600  # Seconds for healthy data freshness
    
    # Monitoring settings
    enable_metrics: bool = True
    metrics_port: int = 9090
    log_level: str = "INFO"
    
    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 1000
    rate_limit_period: int = 60  # seconds
    
    # Health check settings
    health_check_timeout: int = 10
    
    class Config:
        env_file = ".env"
        env_prefix = "SERVING_"
        case_sensitive = False


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get settings singleton"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Environment-specific configurations
class DevelopmentSettings(Settings):
    debug: bool = True
    log_level: str = "DEBUG"
    workers: int = 1


class ProductionSettings(Settings):
    debug: bool = False
    log_level: str = "INFO"
    workers: int = 8
    
    # Production-specific overrides
    clickhouse_max_connections: int = 20
    redis_max_connections: int = 50
    
    # Stricter rate limiting in production
    rate_limit_requests: int = 500


class TestingSettings(Settings):
    debug: bool = True
    log_level: str = "DEBUG"
    
    # Test database settings
    clickhouse_database: str = "dcard_lambda_test"
    redis_db: int = 1
    
    # Faster cache expiration for testing
    cache_ttl_user_count: int = 5
    cache_ttl_top_users: int = 5
    cache_ttl_system_health: int = 5


def get_settings_for_environment(env: str = None) -> Settings:
    """Get settings based on environment"""
    if env is None:
        env = os.getenv("ENVIRONMENT", "development").lower()
    
    if env == "production":
        return ProductionSettings()
    elif env == "testing":
        return TestingSettings()
    else:
        return DevelopmentSettings()