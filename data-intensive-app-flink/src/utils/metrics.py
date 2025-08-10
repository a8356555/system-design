"""
Prometheus metrics collection for PyFlink jobs
"""
import time
import threading
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import structlog

logger = structlog.get_logger(__name__)


class MetricsCollector:
    """Collect and expose Prometheus metrics for PyFlink jobs"""
    
    def __init__(self, port=8000, job_name="pyflink-job"):
        self.port = port
        self.job_name = job_name
        self.server_started = False
        
        # Define metrics
        self.events_processed = Counter(
            'pyflink_events_processed_total',
            'Total number of events processed',
            ['job_name', 'processor_type']
        )
        
        self.processing_duration = Histogram(
            'pyflink_processing_duration_seconds',
            'Time spent processing events',
            ['job_name', 'operation']
        )
        
        self.events_per_second = Gauge(
            'pyflink_events_per_second',
            'Current events per second rate',
            ['job_name', 'processor_type']
        )
        
        self.checkpoint_duration = Histogram(
            'pyflink_checkpoint_duration_seconds',
            'Checkpoint duration',
            ['job_name']
        )
        
        self.errors_total = Counter(
            'pyflink_errors_total',
            'Total number of errors',
            ['job_name', 'error_type']
        )
        
        self.state_size = Gauge(
            'pyflink_state_size_bytes',
            'State size in bytes',
            ['job_name', 'operator']
        )
        
        # Start metrics server
        self._start_metrics_server()
    
    def _start_metrics_server(self):
        """Start Prometheus metrics HTTP server"""
        try:
            start_http_server(self.port)
            self.server_started = True
            logger.info(f"Metrics server started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
    
    def record_event_processed(self, processor_type: str, count: int = 1):
        """Record processed events"""
        self.events_processed.labels(
            job_name=self.job_name,
            processor_type=processor_type
        ).inc(count)
    
    def record_processing_time(self, operation: str, duration: float):
        """Record processing time"""
        self.processing_duration.labels(
            job_name=self.job_name,
            operation=operation
        ).observe(duration)
    
    def set_events_per_second(self, processor_type: str, rate: float):
        """Set current events per second rate"""
        self.events_per_second.labels(
            job_name=self.job_name,
            processor_type=processor_type
        ).set(rate)
    
    def record_checkpoint_time(self, duration: float):
        """Record checkpoint duration"""
        self.checkpoint_duration.labels(job_name=self.job_name).observe(duration)
    
    def record_error(self, error_type: str):
        """Record an error"""
        self.errors_total.labels(
            job_name=self.job_name,
            error_type=error_type
        ).inc()
    
    def set_state_size(self, operator: str, size_bytes: int):
        """Set state size for an operator"""
        self.state_size.labels(
            job_name=self.job_name,
            operator=operator
        ).set(size_bytes)


class ProcessingTimer:
    """Context manager for timing operations"""
    
    def __init__(self, metrics_collector: MetricsCollector, operation: str):
        self.metrics_collector = metrics_collector
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            self.metrics_collector.record_processing_time(self.operation, duration)


class EventRateTracker:
    """Track and report events per second"""
    
    def __init__(self, metrics_collector: MetricsCollector, processor_type: str, window_seconds: int = 60):
        self.metrics_collector = metrics_collector
        self.processor_type = processor_type
        self.window_seconds = window_seconds
        self.events = []
        self.lock = threading.Lock()
        
        # Start background thread to calculate rate
        self.running = True
        self.thread = threading.Thread(target=self._calculate_rate)
        self.thread.daemon = True
        self.thread.start()
    
    def record_event(self):
        """Record a single event"""
        current_time = time.time()
        with self.lock:
            self.events.append(current_time)
            
            # Remove old events outside window
            cutoff_time = current_time - self.window_seconds
            self.events = [t for t in self.events if t > cutoff_time]
    
    def record_events(self, count: int):
        """Record multiple events"""
        current_time = time.time()
        with self.lock:
            self.events.extend([current_time] * count)
            
            # Remove old events outside window
            cutoff_time = current_time - self.window_seconds
            self.events = [t for t in self.events if t > cutoff_time]
    
    def _calculate_rate(self):
        """Background thread to calculate and report rate"""
        while self.running:
            try:
                time.sleep(5)  # Update every 5 seconds
                
                current_time = time.time()
                cutoff_time = current_time - self.window_seconds
                
                with self.lock:
                    # Remove old events
                    self.events = [t for t in self.events if t > cutoff_time]
                    event_count = len(self.events)
                
                # Calculate rate
                rate = event_count / self.window_seconds
                
                # Report to metrics
                self.metrics_collector.set_events_per_second(self.processor_type, rate)
                
            except Exception as e:
                logger.error(f"Error calculating event rate: {e}")
    
    def stop(self):
        """Stop the rate tracker"""
        self.running = False
        if self.thread.is_alive():
            self.thread.join()


# Global metrics collector instance
_global_metrics_collector = None


def get_metrics_collector(job_name: str = "pyflink-job", port: int = 8000) -> MetricsCollector:
    """Get global metrics collector instance"""
    global _global_metrics_collector
    
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector(port=port, job_name=job_name)
    
    return _global_metrics_collector