"""
ClickHouse sink for storing analytical data
"""
import json
import logging
from typing import Dict, Any, List
from datetime import datetime

from clickhouse_driver import Client
from pyflink.datastream import SinkFunction

logger = logging.getLogger(__name__)


class ClickHouseSinkFunction(SinkFunction):
    """Base ClickHouse sink function"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics', table: str = None):
        self.host = host
        self.port = port
        self.database = database
        self.table = table
        self.client = None
        self.batch = []
        self.batch_size = 1000
        self.batch_timeout = 30  # seconds
        self.last_flush = datetime.now()
    
    def open(self, runtime_context):
        """Initialize ClickHouse connection"""
        try:
            self.client = Client(
                host=self.host,
                port=self.port,
                database=self.database,
                settings={'use_numpy': True}
            )
            
            # Test connection
            self.client.execute('SELECT 1')
            logger.info(f"ClickHouse connection established: {self.host}:{self.port}/{self.database}")
            
            # Ensure table exists
            if self.table:
                self._create_table_if_not_exists()
                
        except Exception as e:
            logger.error(f"Failed to initialize ClickHouse connection: {e}")
            raise
    
    def close(self):
        """Close ClickHouse connection"""
        if self.batch:
            self._flush_batch()
        
        if self.client:
            self.client.disconnect()
    
    def invoke(self, value, context):
        """Store record in ClickHouse"""
        try:
            # Add to batch
            self.batch.append(self._prepare_record(value))
            
            # Check if we should flush
            now = datetime.now()
            should_flush = (
                len(self.batch) >= self.batch_size or
                (now - self.last_flush).total_seconds() >= self.batch_timeout
            )
            
            if should_flush:
                self._flush_batch()
                
        except Exception as e:
            logger.error(f"Error storing record in ClickHouse: {e}")
    
    def _flush_batch(self):
        """Flush batch to ClickHouse"""
        if not self.batch or not self.client:
            return
        
        try:
            self.client.execute(f'INSERT INTO {self.table} VALUES', self.batch)
            logger.debug(f"Flushed {len(self.batch)} records to {self.table}")
            
            self.batch.clear()
            self.last_flush = datetime.now()
            
        except Exception as e:
            logger.error(f"Error flushing batch to ClickHouse: {e}")
            # Keep batch for retry
    
    def _prepare_record(self, value) -> Dict[str, Any]:
        """Prepare record for insertion - override in subclasses"""
        return value
    
    def _create_table_if_not_exists(self):
        """Create table if it doesn't exist - override in subclasses"""
        pass


class SessionsSink(ClickHouseSinkFunction):
    """Sink for user sessions"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics'):
        super().__init__(host, port, database, 'sessions')
    
    def _create_table_if_not_exists(self):
        """Create sessions table"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id String,
            user_id UInt64,
            start_time DateTime,
            end_time DateTime,
            duration_seconds UInt32,
            event_count UInt32,
            page_view_count UInt32,
            unique_urls_count UInt32,
            countries Array(String),
            referrer String,
            landing_page String,
            exit_page String,
            page_view_sequence Array(String),
            is_bounce UInt8,
            device_type String,
            browser String,
            date_partition Date,
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY date_partition
        ORDER BY (user_id, start_time)
        """
        
        self.client.execute(create_table_sql)
    
    def _prepare_record(self, session) -> Dict[str, Any]:
        """Convert UserSession to ClickHouse record"""
        if hasattr(session, 'to_dict'):
            data = session.to_dict()
        else:
            data = session
        
        return (
            data.get('session_id', ''),
            data.get('user_id', 0),
            datetime.fromisoformat(data.get('start_time')) if isinstance(data.get('start_time'), str) else data.get('start_time'),
            datetime.fromisoformat(data.get('end_time')) if isinstance(data.get('end_time'), str) else data.get('end_time'),
            data.get('duration_seconds', 0),
            data.get('event_count', 0),
            data.get('page_view_count', 0),
            data.get('unique_urls_count', 0),
            data.get('countries', []),
            data.get('referrer', ''),
            data.get('landing_page', ''),
            data.get('exit_page', ''),
            data.get('page_view_sequence', []),
            1 if data.get('is_bounce', False) else 0,
            data.get('device_type', ''),
            data.get('browser', ''),
            datetime.strptime(data.get('date_partition'), '%Y-%m-%d').date() if isinstance(data.get('date_partition'), str) else data.get('date_partition')
        )


class HourlyStatsSink(ClickHouseSinkFunction):
    """Sink for hourly statistics"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics'):
        super().__init__(host, port, database, 'hourly_stats')
    
    def _create_table_if_not_exists(self):
        """Create hourly stats table"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS hourly_stats (
            hour_window DateTime,
            event_type String,
            country String,
            event_count UInt64,
            unique_users UInt32,
            unique_sessions UInt32,
            window_end DateTime,
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(hour_window)
        ORDER BY (hour_window, event_type, country)
        """
        
        self.client.execute(create_table_sql)
    
    def _prepare_record(self, stats) -> tuple:
        """Prepare hourly stats record"""
        return (
            datetime.fromisoformat(stats['hour_window'].replace(' ', 'T')),
            stats['event_type'],
            stats['country'],
            stats['event_count'],
            stats['unique_users'], 
            stats['unique_sessions'],
            datetime.fromtimestamp(stats['window_end'] / 1000)
        )


class UserMetricsSink(ClickHouseSinkFunction):
    """Sink for user metrics"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics'):
        super().__init__(host, port, database, 'user_metrics')
    
    def _create_table_if_not_exists(self):
        """Create user metrics table"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS user_metrics (
            date_partition Date,
            user_id UInt64,
            total_events UInt32,
            page_views UInt32,
            purchases UInt32,
            sessions UInt32,
            unique_pages_visited UInt32,
            first_event_time DateTime,
            last_event_time DateTime,
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY date_partition
        ORDER BY (date_partition, user_id)
        """
        
        self.client.execute(create_table_sql)
    
    def _prepare_record(self, metrics) -> tuple:
        """Prepare user metrics record"""
        return (
            datetime.strptime(metrics['date_partition'], '%Y-%m-%d').date(),
            metrics['user_id'],
            metrics['total_events'],
            metrics['page_views'],
            metrics['purchases'],
            metrics['sessions'],
            metrics['unique_pages_visited'],
            datetime.fromisoformat(metrics['first_event_time']),
            datetime.fromisoformat(metrics['last_event_time'])
        )


class ConversionFunnelSink(ClickHouseSinkFunction):
    """Sink for conversion funnel data"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics'):
        super().__init__(host, port, database, 'conversion_funnel')
    
    def _create_table_if_not_exists(self):
        """Create conversion funnel table"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS conversion_funnel (
            date_partition Date,
            total_users UInt32,
            users_viewed_product UInt32,
            users_added_to_cart UInt32,
            users_started_checkout UInt32,
            users_completed_purchase UInt32,
            product_to_cart_rate Float64,
            cart_to_checkout_rate Float64,
            checkout_to_purchase_rate Float64,
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY date_partition
        ORDER BY date_partition
        """
        
        self.client.execute(create_table_sql)
    
    def _prepare_record(self, funnel) -> tuple:
        """Prepare conversion funnel record"""
        return (
            datetime.strptime(funnel['date_partition'], '%Y-%m-%d').date(),
            funnel['total_users'],
            funnel['users_viewed_product'],
            funnel['users_added_to_cart'],
            funnel['users_started_checkout'],
            funnel['users_completed_purchase'],
            funnel['product_to_cart_rate'],
            funnel['cart_to_checkout_rate'],
            funnel['checkout_to_purchase_rate']
        )


class ClickHouseSink:
    """Factory for creating ClickHouse sinks"""
    
    def __init__(self, host: str, port: int = 9000, database: str = 'analytics'):
        self.host = host
        self.port = port
        self.database = database
    
    def create_sessions_sink(self):
        """Create sessions sink"""
        return SessionsSink(self.host, self.port, self.database)
    
    def create_hourly_stats_sink(self):
        """Create hourly stats sink"""
        return HourlyStatsSink(self.host, self.port, self.database)
    
    def create_user_metrics_sink(self):
        """Create user metrics sink"""
        return UserMetricsSink(self.host, self.port, self.database)
    
    def create_pageview_stats_sink(self):
        """Create pageview stats sink"""
        return HourlyStatsSink(self.host, self.port, self.database)  # Reuse hourly stats
    
    def create_cohort_stats_sink(self):
        """Create cohort stats sink"""
        return HourlyStatsSink(self.host, self.port, self.database)  # Reuse hourly stats
    
    def create_user_journeys_sink(self):
        """Create user journeys sink"""
        return SessionsSink(self.host, self.port, self.database)  # Reuse sessions
    
    def create_conversion_funnel_sink(self):
        """Create conversion funnel sink"""
        return ConversionFunnelSink(self.host, self.port, self.database)
    
    def create_geo_analytics_sink(self):
        """Create geo analytics sink"""
        return HourlyStatsSink(self.host, self.port, self.database)  # Reuse hourly stats