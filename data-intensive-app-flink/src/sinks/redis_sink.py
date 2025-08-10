"""
Redis sink for storing real-time metrics
"""
import json
import logging
from typing import List, Dict, Any
from datetime import datetime

import redis
from redis.cluster import RedisCluster
from pyflink.datastream import SinkFunction

logger = logging.getLogger(__name__)


class RedisMetricsSink(SinkFunction):
    """Base Redis sink for metrics storage"""
    
    def __init__(self, cluster_nodes: List[str], metric_type: str):
        self.cluster_nodes = cluster_nodes
        self.metric_type = metric_type
        self.redis_client = None
    
    def open(self, runtime_context):
        """Initialize Redis connection"""
        try:
            # Parse cluster nodes
            startup_nodes = []
            for node in self.cluster_nodes:
                host, port = node.split(':')
                startup_nodes.append({"host": host, "port": int(port)})
            
            # Create Redis cluster client
            self.redis_client = RedisCluster(
                startup_nodes=startup_nodes,
                decode_responses=True,
                skip_full_coverage_check=True,
                health_check_interval=30,
                socket_keepalive=True,
                retry_on_timeout=True
            )
            
            # Test connection
            self.redis_client.ping()
            logger.info(f"Redis cluster connection established for {self.metric_type}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis cluster: {e}")
            raise
    
    def close(self):
        """Close Redis connection"""
        if self.redis_client:
            self.redis_client.close()
    
    def invoke(self, value, context):
        """Store metric in Redis"""
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return
            
            self._store_metric(value)
            
        except Exception as e:
            logger.error(f"Error storing {self.metric_type} metric: {e}")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Override in subclasses to implement specific storage logic"""
        raise NotImplementedError


class GlobalMetricsSink(RedisMetricsSink):
    """Sink for global metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "global_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store global metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        
        # Store current metrics
        key = f"events:global:{window_minute}"
        self.redis_client.hset(key, mapping={
            'event_count': metric['event_count'],
            'error_count': metric['error_count'],
            'page_view_count': metric['page_view_count'],
            'purchase_count': metric['purchase_count'],
            'rate_change_percent': metric['rate_change_percent'],
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)  # 1 hour TTL
        
        # Store in time series for dashboards
        ts_key = f"events:count:timeseries"
        self.redis_client.zadd(ts_key, {window_minute: metric['event_count']})
        self.redis_client.expire(ts_key, 7200)  # 2 hour TTL


class EventTypeMetricsSink(RedisMetricsSink):
    """Sink for event type metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "event_type_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store event type metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        event_type = metric['event_type']
        
        # Store event type metrics
        key = f"events:type:{event_type}:{window_minute}"
        self.redis_client.hset(key, mapping={
            'event_count': metric['event_count'],
            'unique_users': metric['unique_users'],
            'unique_countries': metric['unique_countries'],
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)  # 1 hour TTL
        
        # Update event type rankings
        ranking_key = f"events:type:ranking:{window_minute}"
        self.redis_client.zadd(ranking_key, {event_type: metric['event_count']})
        self.redis_client.expire(ranking_key, 3600)


class CountryMetricsSink(RedisMetricsSink):
    """Sink for country metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "country_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store country metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        country = metric['country']
        
        # Store country metrics
        key = f"events:country:{country}:{window_minute}"
        self.redis_client.hset(key, mapping={
            'event_count': metric['event_count'],
            'unique_users': metric['unique_users'],
            'event_type_breakdown': json.dumps(metric['event_type_breakdown']),
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)
        
        # Update country rankings
        ranking_key = f"events:country:ranking:{window_minute}"
        self.redis_client.zadd(ranking_key, {country: metric['event_count']})
        self.redis_client.expire(ranking_key, 3600)


class ActiveUsersSink(RedisMetricsSink):
    """Sink for active users metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "active_users_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store active users metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        
        # Store active users metrics
        key = f"users:active:{window_minute}"
        self.redis_client.hset(key, mapping={
            'active_users': metric['active_users'],
            'active_sessions': metric['active_sessions'],
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)
        
        # Store in time series
        ts_key = f"users:active:timeseries"
        self.redis_client.zadd(ts_key, {window_minute: metric['active_users']})
        self.redis_client.expire(ts_key, 7200)


class PageViewMetricsSink(RedisMetricsSink):
    """Sink for page view metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "page_view_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store page view metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        
        # Store page view metrics
        key = f"pageviews:metrics:{window_minute}"
        self.redis_client.hset(key, mapping={
            'total_page_views': metric['total_page_views'],
            'unique_viewers': metric['unique_viewers'],
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)
        
        # Store top URLs
        top_urls_key = f"pageviews:top_urls:{window_minute}"
        if metric['top_urls']:
            self.redis_client.zadd(top_urls_key, metric['top_urls'])
            self.redis_client.expire(top_urls_key, 3600)


class ErrorMetricsSink(RedisMetricsSink):
    """Sink for error metrics"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "error_metrics")
    
    def _store_metric(self, metric: Dict[str, Any]):
        """Store error metrics in Redis"""
        window_start = metric['window_start']
        window_minute = datetime.fromtimestamp(window_start / 1000).strftime('%Y-%m-%d-%H-%M')
        
        # Store error metrics
        key = f"errors:metrics:{window_minute}"
        self.redis_client.hset(key, mapping={
            'error_count': metric['error_count'],
            'affected_users': metric['affected_users'],
            'error_types': json.dumps(metric['error_types']),
            'processing_time': metric['processing_time']
        })
        self.redis_client.expire(key, 3600)
        
        # Store in time series for alerting
        ts_key = f"errors:count:timeseries"
        self.redis_client.zadd(ts_key, {window_minute: metric['error_count']})
        self.redis_client.expire(ts_key, 7200)
        
        # Alert if error count is high
        if metric['error_count'] > 100:  # Threshold
            alert_key = f"alerts:high_error_rate:{window_minute}"
            self.redis_client.setex(alert_key, 300, json.dumps({  # 5 min TTL
                'alert_type': 'HIGH_ERROR_RATE',
                'error_count': metric['error_count'],
                'affected_users': metric['affected_users'],
                'window_minute': window_minute,
                'created_at': datetime.now().isoformat()
            }))


class SessionSummaryS3Sink(RedisMetricsSink):
    """Sink for session summaries (stored for quick lookup)"""
    
    def __init__(self, cluster_nodes: List[str]):
        super().__init__(cluster_nodes, "session_summary")
    
    def _store_metric(self, session: Dict[str, Any]):
        """Store session summary in Redis"""
        session_id = session['session_id']
        user_id = session['user_id']
        
        # Store session summary for quick lookup
        key = f"session:{session_id}"
        self.redis_client.hset(key, mapping={
            'user_id': user_id,
            'duration_seconds': session['duration_seconds'],
            'page_view_count': session['page_view_count'],
            'is_bounce': str(session['is_bounce']).lower(),
            'landing_page': session.get('landing_page', ''),
            'exit_page': session.get('exit_page', ''),
            'countries': json.dumps(session.get('countries', [])),
            'date_partition': session['date_partition']
        })
        self.redis_client.expire(key, 3600)  # 1 hour TTL
        
        # Update user session count
        user_sessions_key = f"user:{user_id}:sessions:{session['date_partition']}"
        self.redis_client.incr(user_sessions_key)
        self.redis_client.expire(user_sessions_key, 86400)  # 1 day TTL


class RedisSink:
    """Factory for creating Redis sinks"""
    
    def __init__(self, cluster_nodes: List[str]):
        self.cluster_nodes = cluster_nodes
    
    def create_global_metrics_sink(self):
        """Create sink for global metrics"""
        return GlobalMetricsSink(self.cluster_nodes)
    
    def create_event_type_metrics_sink(self):
        """Create sink for event type metrics"""
        return EventTypeMetricsSink(self.cluster_nodes)
    
    def create_country_metrics_sink(self):
        """Create sink for country metrics"""
        return CountryMetricsSink(self.cluster_nodes)
    
    def create_active_users_sink(self):
        """Create sink for active users metrics"""
        return ActiveUsersSink(self.cluster_nodes)
    
    def create_page_view_metrics_sink(self):
        """Create sink for page view metrics"""
        return PageViewMetricsSink(self.cluster_nodes)
    
    def create_error_metrics_sink(self):
        """Create sink for error metrics"""
        return ErrorMetricsSink(self.cluster_nodes)
    
    def create_session_summary_sink(self):
        """Create sink for session summaries"""
        return SessionSummaryS3Sink(self.cluster_nodes)