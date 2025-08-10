import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
import structlog

from app.streaming.async_consumer import AsyncEventProcessor, ProcessingResult
from app.storage.multi_tier_storage import MultiTierStorage
from prometheus_client import Counter, Histogram, Gauge

logger = structlog.get_logger(__name__)

# Metrics
STREAM_EVENTS_PROCESSED = Counter('stream_events_processed_total', 'Events processed by stream processor', ['processor_type'])
STREAM_PROCESSING_DURATION = Histogram('stream_processing_duration_seconds', 'Stream processing duration', ['operation'])
REALTIME_METRICS_UPDATED = Counter('realtime_metrics_updated_total', 'Real-time metrics updates')
SESSION_EVENTS = Gauge('active_session_events', 'Active session events being tracked')

class RealtimeMetricsProcessor(AsyncEventProcessor):
    """Processes events for real-time metrics and dashboards"""
    
    def __init__(self, storage: MultiTierStorage):
        self.storage = storage
        self.metrics_buffer = defaultdict(lambda: defaultdict(int))
        self.last_flush = time.time()
        self.flush_interval = 10  # seconds
        
    async def process_event(self, event: Dict[str, Any]) -> ProcessingResult:
        """Process single event for real-time metrics"""
        start_time = time.time()
        
        try:
            event_data = event.get('value', {})
            
            if not event_data:
                return ProcessingResult(success=False, error="Empty event data")
            
            # Extract timing information
            current_minute = datetime.utcnow().strftime('%Y-%m-%d-%H-%M')
            current_hour = datetime.utcnow().strftime('%Y-%m-%d-%H')
            
            # Update real-time counters in hot storage
            if self.storage.hot_storage:
                await self._update_hot_metrics(event_data, current_minute, current_hour)
            
            processing_time = time.time() - start_time
            
            STREAM_EVENTS_PROCESSED.labels(processor_type='realtime_metrics').inc()
            
            return ProcessingResult(
                success=True,
                processing_time=processing_time
            )
            
        except Exception as e:
            logger.error("Error processing event for real-time metrics", error=str(e))
            return ProcessingResult(success=False, error=str(e))
    
    async def _update_hot_metrics(self, event: Dict[str, Any], current_minute: str, current_hour: str):
        """Update hot storage with real-time metrics"""
        hot_storage = self.storage.hot_storage
        
        # Basic event counters
        await hot_storage.increment_counter(f"events:count:{current_minute}", ttl=3600)
        await hot_storage.increment_counter(f"events:count:hour:{current_hour}", ttl=7200)
        
        # Event type counters
        event_type = event.get('event_type', 'unknown')
        await hot_storage.increment_counter(f"events:type:{event_type}:{current_minute}", ttl=3600)
        
        # User counters
        user_id = event.get('user_id')
        if user_id:
            await hot_storage.increment_counter(f"events:user:{user_id}:{current_minute}", ttl=3600)
            
            # Add to unique users set (HyperLogLog would be better for scale)
            await hot_storage.add_to_sorted_set(
                f"unique_users:{current_minute}",
                score=time.time(),
                member=str(user_id),
                ttl=3600
            )
        
        # Geographic counters
        country = event.get('country')
        if country:
            await hot_storage.increment_counter(f"events:country:{country}:{current_minute}", ttl=3600)
        
        # URL counters (for page views)
        if event_type == 'page_view':
            url = event.get('url')
            if url:
                # Store top URLs in sorted set
                await hot_storage.add_to_sorted_set(
                    f"top_urls:{current_hour}",
                    score=1,  # This would need proper incrementing logic
                    member=url,
                    ttl=7200
                )
        
        REALTIME_METRICS_UPDATED.inc()

class SessionProcessor(AsyncEventProcessor):
    """Processes events to track user sessions and behavior"""
    
    def __init__(self, storage: MultiTierStorage, session_timeout_minutes: int = 30):
        self.storage = storage
        self.session_timeout_minutes = session_timeout_minutes
        self.active_sessions = {}  # session_id -> session_data
        self.session_cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
        
    async def process_event(self, event: Dict[str, Any]) -> ProcessingResult:
        """Process event for session tracking"""
        start_time = time.time()
        
        try:
            event_data = event.get('value', {})
            
            if not event_data:
                return ProcessingResult(success=False, error="Empty event data")
            
            session_id = event_data.get('session_id')
            user_id = event_data.get('user_id')
            
            if not session_id:
                return ProcessingResult(success=True, processing_time=0)  # Skip events without session
            
            # Update or create session
            await self._update_session(session_id, user_id, event_data)
            
            # Periodic cleanup of old sessions
            if time.time() - self.last_cleanup > self.session_cleanup_interval:
                await self._cleanup_old_sessions()
                self.last_cleanup = time.time()
            
            processing_time = time.time() - start_time
            
            STREAM_EVENTS_PROCESSED.labels(processor_type='session_tracking').inc()
            SESSION_EVENTS.set(len(self.active_sessions))
            
            return ProcessingResult(success=True, processing_time=processing_time)
            
        except Exception as e:
            logger.error("Error processing event for session tracking", error=str(e))
            return ProcessingResult(success=False, error=str(e))
    
    async def _update_session(self, session_id: str, user_id: Optional[int], event: Dict[str, Any]):
        """Update session with new event"""
        current_time = time.time()
        
        if session_id not in self.active_sessions:
            # Create new session
            self.active_sessions[session_id] = {
                'session_id': session_id,
                'user_id': user_id,
                'start_time': current_time,
                'last_activity': current_time,
                'event_count': 0,
                'page_views': 0,
                'unique_urls': set(),
                'countries': set(),
                'device_info': {}
            }
        
        session = self.active_sessions[session_id]
        
        # Update session data
        session['last_activity'] = current_time
        session['event_count'] += 1
        
        event_type = event.get('event_type', '')
        
        if event_type == 'page_view':
            session['page_views'] += 1
            url = event.get('url')
            if url:
                session['unique_urls'].add(url)
        
        country = event.get('country')
        if country:
            session['countries'].add(country)
        
        # Extract device info
        user_agent = event.get('user_agent')
        if user_agent and not session['device_info']:
            session['device_info'] = self._extract_device_info(user_agent)
        
        # Check if session should be closed
        session_duration = current_time - session['start_time']
        timeout_seconds = self.session_timeout_minutes * 60
        
        if (event_type == 'session_end' or 
            session_duration > timeout_seconds or
            (current_time - session['last_activity']) > timeout_seconds):
            
            await self._close_session(session_id, session)
    
    async def _close_session(self, session_id: str, session: Dict[str, Any]):
        """Close session and store summary"""
        try:
            session_duration = session['last_activity'] - session['start_time']
            
            session_summary = {
                'session_id': session_id,
                'user_id': session['user_id'],
                'start_time': session['start_time'],
                'end_time': session['last_activity'],
                'duration_seconds': int(session_duration),
                'event_count': session['event_count'],
                'page_views': session['page_views'],
                'unique_urls_count': len(session['unique_urls']),
                'countries_visited': list(session['countries']),
                'device_info': session['device_info'],
                'is_bounce': session['page_views'] <= 1,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Store session summary in warm storage
            if self.storage.warm_storage:
                # You would insert this into a sessions table
                logger.info("Session closed", **session_summary)
            
            # Store in hot storage for real-time access
            if self.storage.hot_storage:
                await self.storage.hot_storage.put(
                    f"session_summary:{session_id}",
                    session_summary,
                    ttl=3600
                )
            
            # Remove from active sessions
            del self.active_sessions[session_id]
            
        except Exception as e:
            logger.error("Error closing session", session_id=session_id, error=str(e))
    
    async def _cleanup_old_sessions(self):
        """Clean up old inactive sessions"""
        current_time = time.time()
        timeout_seconds = self.session_timeout_minutes * 60
        
        sessions_to_close = []
        
        for session_id, session in self.active_sessions.items():
            if (current_time - session['last_activity']) > timeout_seconds:
                sessions_to_close.append((session_id, session))
        
        for session_id, session in sessions_to_close:
            await self._close_session(session_id, session)
        
        if sessions_to_close:
            logger.info("Cleaned up old sessions", count=len(sessions_to_close))
    
    def _extract_device_info(self, user_agent: str) -> Dict[str, str]:
        """Extract device information from user agent"""
        # Simple device detection - in production use a proper library
        ua_lower = user_agent.lower()
        
        device_type = 'desktop'
        if 'mobile' in ua_lower or 'android' in ua_lower or 'iphone' in ua_lower:
            device_type = 'mobile'
        elif 'tablet' in ua_lower or 'ipad' in ua_lower:
            device_type = 'tablet'
        
        browser = 'other'
        if 'chrome' in ua_lower:
            browser = 'chrome'
        elif 'firefox' in ua_lower:
            browser = 'firefox'
        elif 'safari' in ua_lower:
            browser = 'safari'
        elif 'edge' in ua_lower:
            browser = 'edge'
        
        return {
            'device_type': device_type,
            'browser': browser,
            'user_agent': user_agent[:200]  # Truncate for storage
        }

class AggregationProcessor(AsyncEventProcessor):
    """Processes events for batch aggregation (pre-aggregation for ClickHouse)"""
    
    def __init__(self, storage: MultiTierStorage):
        self.storage = storage
        self.aggregation_buffer = []
        self.buffer_max_size = 1000
        self.buffer_max_age = 30  # seconds
        self.last_flush = time.time()
        
    async def process_batch(self, events: List[Dict[str, Any]]) -> List[ProcessingResult]:
        """Process batch of events for aggregation"""
        start_time = time.time()
        
        try:
            # Extract event data
            event_list = []
            for event_msg in events:
                event_data = event_msg.get('value', {})
                if event_data:
                    event_list.append(event_data)
            
            # Add to aggregation buffer
            self.aggregation_buffer.extend(event_list)
            
            # Check if we should flush to warm storage
            current_time = time.time()
            should_flush = (
                len(self.aggregation_buffer) >= self.buffer_max_size or
                current_time - self.last_flush >= self.buffer_max_age
            )
            
            if should_flush and self.aggregation_buffer:
                await self._flush_to_warm_storage()
            
            processing_time = time.time() - start_time
            
            STREAM_EVENTS_PROCESSED.labels(processor_type='aggregation').inc()
            
            # Return success for all events
            return [
                ProcessingResult(success=True, processing_time=processing_time / len(events))
                for _ in events
            ]
            
        except Exception as e:
            logger.error("Error processing batch for aggregation", error=str(e))
            return [
                ProcessingResult(success=False, error=str(e))
                for _ in events
            ]
    
    async def _flush_to_warm_storage(self):
        """Flush aggregated events to ClickHouse"""
        try:
            if not self.storage.warm_storage or not self.aggregation_buffer:
                return
            
            with STREAM_PROCESSING_DURATION.labels(operation='warm_storage_insert').time():
                success = await self.storage.warm_storage.insert_events(
                    self.aggregation_buffer
                )
                
                if success:
                    logger.info("Flushed events to warm storage", count=len(self.aggregation_buffer))
                else:
                    logger.error("Failed to flush events to warm storage")
            
            # Clear buffer
            self.aggregation_buffer.clear()
            self.last_flush = time.time()
            
        except Exception as e:
            logger.error("Error flushing to warm storage", error=str(e))

class SearchIndexProcessor(AsyncEventProcessor):
    """Processes events for search indexing"""
    
    def __init__(self, storage: MultiTierStorage):
        self.storage = storage
        self.index_buffer = []
        self.buffer_max_size = 500
        self.buffer_max_age = 15  # seconds
        self.last_flush = time.time()
        
    async def process_batch(self, events: List[Dict[str, Any]]) -> List[ProcessingResult]:
        """Process batch for search indexing"""
        start_time = time.time()
        
        try:
            # Extract and prepare events for indexing
            searchable_events = []
            
            for event_msg in events:
                event_data = event_msg.get('value', {})
                if event_data and self._should_index_event(event_data):
                    # Prepare event for search (add searchable fields, clean data, etc.)
                    searchable_event = self._prepare_for_search(event_data)
                    searchable_events.append(searchable_event)
            
            if searchable_events:
                self.index_buffer.extend(searchable_events)
            
            # Check if we should flush to search storage
            current_time = time.time()
            should_flush = (
                len(self.index_buffer) >= self.buffer_max_size or
                current_time - self.last_flush >= self.buffer_max_age
            )
            
            if should_flush and self.index_buffer:
                await self._flush_to_search_storage()
            
            processing_time = time.time() - start_time
            
            STREAM_EVENTS_PROCESSED.labels(processor_type='search_indexing').inc()
            
            return [
                ProcessingResult(success=True, processing_time=processing_time / len(events))
                for _ in events
            ]
            
        except Exception as e:
            logger.error("Error processing batch for search indexing", error=str(e))
            return [
                ProcessingResult(success=False, error=str(e))
                for _ in events
            ]
    
    def _should_index_event(self, event: Dict[str, Any]) -> bool:
        """Determine if event should be indexed for search"""
        # Index events that have searchable content
        event_type = event.get('event_type', '')
        
        # Index page views, searches, errors, and custom events
        indexable_types = {'page_view', 'search', 'error', 'custom_event'}
        
        return (
            event_type in indexable_types or
            event.get('url') or
            event.get('properties', {}).get('search_query') or
            len(str(event.get('properties', {}))) > 10  # Has substantial properties
        )
    
    def _prepare_for_search(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare event data for search indexing"""
        searchable_event = event.copy()
        
        # Add computed fields for better search
        properties = event.get('properties', {})
        
        # Create searchable text field
        searchable_text_parts = [
            event.get('event_type', ''),
            event.get('event_name', ''),
            event.get('url', ''),
            str(properties.get('search_query', '')),
            str(properties.get('page_title', '')),
            str(properties.get('error_message', ''))
        ]
        
        searchable_event['searchable_text'] = ' '.join(
            part for part in searchable_text_parts if part
        )
        
        # Add timestamp for time-based queries
        if 'timestamp' in event:
            try:
                timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                searchable_event['@timestamp'] = timestamp.isoformat()
            except (ValueError, AttributeError):
                searchable_event['@timestamp'] = datetime.utcnow().isoformat()
        
        return searchable_event
    
    async def _flush_to_search_storage(self):
        """Flush events to search storage"""
        try:
            if not self.storage.search_storage or not self.index_buffer:
                return
            
            with STREAM_PROCESSING_DURATION.labels(operation='search_indexing').time():
                indexed_count = await self.storage.search_storage.index_events(
                    self.index_buffer
                )
                
                logger.info("Indexed events for search", 
                           total=len(self.index_buffer), indexed=indexed_count)
            
            # Clear buffer
            self.index_buffer.clear()
            self.last_flush = time.time()
            
        except Exception as e:
            logger.error("Error flushing to search storage", error=str(e))