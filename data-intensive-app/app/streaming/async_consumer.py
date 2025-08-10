import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Set
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
import orjson
from prometheus_client import Counter, Histogram, Gauge
import structlog
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import signal

logger = structlog.get_logger(__name__)

# Prometheus metrics
EVENTS_CONSUMED_TOTAL = Counter('events_consumed_total', 'Total events consumed from Kafka', ['topic', 'partition'])
EVENTS_PROCESSED_TOTAL = Counter('events_processed_total', 'Total events processed successfully', ['processor'])
PROCESSING_DURATION = Histogram('event_processing_duration_seconds', 'Time spent processing events')
CONSUMER_LAG = Gauge('kafka_consumer_lag', 'Consumer lag by topic/partition', ['topic', 'partition'])
PROCESSING_ERRORS = Counter('event_processing_errors_total', 'Processing errors', ['error_type'])
ACTIVE_CONSUMERS = Gauge('active_kafka_consumers', 'Number of active consumers')

@dataclass
class ProcessingResult:
    """Result of event processing"""
    success: bool
    error: Optional[str] = None
    processing_time: float = 0.0
    metadata: Dict[str, Any] = None

class AsyncEventProcessor:
    """Base class for event processors"""
    
    async def process_event(self, event: Dict[str, Any]) -> ProcessingResult:
        """Process a single event - override this method"""
        raise NotImplementedError
    
    async def process_batch(self, events: List[Dict[str, Any]]) -> List[ProcessingResult]:
        """Process a batch of events - can be overridden for batch optimization"""
        results = []
        for event in events:
            result = await self.process_event(event)
            results.append(result)
        return results

class AsyncKafkaConsumerPool:
    """High-performance async Kafka consumer with parallel processing"""
    
    def __init__(
        self,
        bootstrap_servers: List[str],
        topics: List[str],
        group_id: str,
        event_processor: AsyncEventProcessor,
        consumer_count: int = 3,
        batch_size: int = 500,
        max_poll_records: int = 1000,
        session_timeout_ms: int = 30000,
        enable_auto_commit: bool = False,
        auto_offset_reset: str = 'latest'
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topics = topics
        self.group_id = group_id
        self.event_processor = event_processor
        self.consumer_count = consumer_count
        self.batch_size = batch_size
        self.max_poll_records = max_poll_records
        self.session_timeout_ms = session_timeout_ms
        self.enable_auto_commit = enable_auto_commit
        self.auto_offset_reset = auto_offset_reset
        
        self.consumers: List[AIOKafkaConsumer] = []
        self.consumer_tasks: List[asyncio.Task] = []
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
        # Processing pool for CPU-intensive tasks
        self.thread_pool = ThreadPoolExecutor(max_workers=consumer_count * 2)
        
        # Metrics tracking
        self.messages_processed = 0
        self.messages_failed = 0
        self.last_commit_time = time.time()
        
        logger.info("Initialized AsyncKafkaConsumerPool",
                   topics=topics, group_id=group_id, consumer_count=consumer_count)
    
    async def start(self):
        """Start the consumer pool"""
        try:
            self.is_running = True
            self.shutdown_event.clear()
            
            # Create consumers
            for i in range(self.consumer_count):
                consumer = AIOKafkaConsumer(
                    *self.topics,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=f"{self.group_id}-{i}",
                    value_deserializer=self._deserialize_value,
                    key_deserializer=self._deserialize_key,
                    max_poll_records=self.max_poll_records,
                    session_timeout_ms=self.session_timeout_ms,
                    enable_auto_commit=self.enable_auto_commit,
                    auto_offset_reset=self.auto_offset_reset,
                    consumer_timeout_ms=10000,
                    fetch_max_wait_ms=500,
                    fetch_min_bytes=1024
                )
                
                await consumer.start()
                self.consumers.append(consumer)
                ACTIVE_CONSUMERS.inc()
                
                # Start consumer task
                task = asyncio.create_task(
                    self._consumer_loop(consumer, i)
                )
                self.consumer_tasks.append(task)
                
                logger.info("Started Kafka consumer", consumer_id=i)
            
            # Start health monitoring task
            monitor_task = asyncio.create_task(self._monitor_health())
            self.consumer_tasks.append(monitor_task)
            
            logger.info("AsyncKafkaConsumerPool started successfully",
                       active_consumers=len(self.consumers))
            
        except Exception as e:
            logger.error("Failed to start AsyncKafkaConsumerPool", error=str(e))
            await self.stop()
            raise
    
    async def stop(self):
        """Gracefully stop the consumer pool"""
        logger.info("Stopping AsyncKafkaConsumerPool...")
        
        self.is_running = False
        self.shutdown_event.set()
        
        # Cancel all consumer tasks
        for task in self.consumer_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to complete
        if self.consumer_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.consumer_tasks, return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("Consumer tasks didn't stop within timeout")
        
        # Stop consumers
        for consumer in self.consumers:
            try:
                await consumer.stop()
                ACTIVE_CONSUMERS.dec()
            except Exception as e:
                logger.warning("Error stopping consumer", error=str(e))
        
        # Shutdown thread pool
        self.thread_pool.shutdown(wait=True)
        
        self.consumers.clear()
        self.consumer_tasks.clear()
        
        logger.info("AsyncKafkaConsumerPool stopped")
    
    async def _consumer_loop(self, consumer: AIOKafkaConsumer, consumer_id: int):
        """Main consumer loop for processing events"""
        logger.info("Starting consumer loop", consumer_id=consumer_id)
        
        batch = []
        last_commit = time.time()
        
        try:
            async for msg in consumer:
                if not self.is_running:
                    break
                
                # Parse message
                try:
                    event = {
                        'value': msg.value,
                        'key': msg.key,
                        'topic': msg.topic,
                        'partition': msg.partition,
                        'offset': msg.offset,
                        'timestamp': msg.timestamp,
                        'consumer_id': consumer_id,
                        'received_at': time.time()
                    }
                    
                    batch.append((msg, event))
                    
                    EVENTS_CONSUMED_TOTAL.labels(
                        topic=msg.topic,
                        partition=msg.partition
                    ).inc()
                    
                except Exception as e:
                    logger.error("Error parsing message", error=str(e))
                    PROCESSING_ERRORS.labels(error_type='parse_error').inc()
                    continue
                
                # Process batch when full or timeout
                current_time = time.time()
                should_process = (
                    len(batch) >= self.batch_size or
                    current_time - last_commit > 5.0  # 5 second timeout
                )
                
                if should_process and batch:
                    await self._process_batch(consumer, batch, consumer_id)
                    batch.clear()
                    last_commit = current_time
        
        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled", consumer_id=consumer_id)
        except Exception as e:
            logger.error("Error in consumer loop", consumer_id=consumer_id, error=str(e))
        finally:
            # Process remaining batch
            if batch:
                await self._process_batch(consumer, batch, consumer_id)
            
            logger.info("Consumer loop stopped", consumer_id=consumer_id)
    
    async def _process_batch(
        self, 
        consumer: AIOKafkaConsumer, 
        batch: List[tuple], 
        consumer_id: int
    ):
        """Process a batch of events"""
        if not batch:
            return
        
        start_time = time.time()
        
        try:
            # Extract events for processing
            events = [event for _, event in batch]
            
            # Process events (can be CPU intensive, so use thread pool if needed)
            with PROCESSING_DURATION.time():
                results = await self.event_processor.process_batch(events)
            
            # Handle results and commit offsets
            successful_offsets = []
            failed_count = 0
            
            for (msg, event), result in zip(batch, results):
                if result.success:
                    successful_offsets.append(msg)
                    EVENTS_PROCESSED_TOTAL.labels(
                        processor=self.event_processor.__class__.__name__
                    ).inc()
                else:
                    failed_count += 1
                    PROCESSING_ERRORS.labels(
                        error_type='processing_failed'
                    ).inc()
                    
                    logger.warning("Event processing failed",
                                 topic=msg.topic, offset=msg.offset,
                                 error=result.error)
            
            # Commit successful offsets
            if successful_offsets and not self.enable_auto_commit:
                await self._commit_offsets(consumer, successful_offsets)
            
            processing_time = time.time() - start_time
            
            logger.debug("Processed batch",
                        consumer_id=consumer_id, batch_size=len(batch),
                        successful=len(successful_offsets), failed=failed_count,
                        processing_time=processing_time)
            
            # Update metrics
            self.messages_processed += len(successful_offsets)
            self.messages_failed += failed_count
            
        except Exception as e:
            logger.error("Error processing batch", error=str(e))
            PROCESSING_ERRORS.labels(error_type='batch_error').inc()
    
    async def _commit_offsets(self, consumer: AIOKafkaConsumer, messages: List):
        """Commit offsets for successfully processed messages"""
        try:
            # Group by topic/partition and get highest offset
            offsets_to_commit = {}
            
            for msg in messages:
                key = (msg.topic, msg.partition)
                if key not in offsets_to_commit or msg.offset > offsets_to_commit[key].offset:
                    offsets_to_commit[key] = msg
            
            # Commit offsets
            await consumer.commit({
                msg.topic: {
                    msg.partition: msg.offset + 1
                } for msg in offsets_to_commit.values()
            })
            
            self.last_commit_time = time.time()
            
        except Exception as e:
            logger.error("Error committing offsets", error=str(e))
    
    async def _monitor_health(self):
        """Monitor consumer health and lag"""
        while self.is_running:
            try:
                for consumer in self.consumers:
                    # Get consumer lag
                    partitions = consumer.assignment()
                    for tp in partitions:
                        try:
                            # Get high water mark
                            high_water_mark = await consumer.highwater(tp)
                            # Get current position
                            position = await consumer.position(tp)
                            
                            lag = high_water_mark - position if high_water_mark and position else 0
                            
                            CONSUMER_LAG.labels(
                                topic=tp.topic,
                                partition=tp.partition
                            ).set(lag)
                            
                        except Exception as e:
                            logger.debug("Error getting lag for partition", 
                                       topic=tp.topic, partition=tp.partition, error=str(e))
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in health monitoring", error=str(e))
                await asyncio.sleep(60)
    
    def _deserialize_value(self, value: bytes) -> Any:
        """Deserialize message value"""
        if value is None:
            return None
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return value.decode('utf-8')
        except Exception:
            return value
    
    def _deserialize_key(self, key: bytes) -> Optional[str]:
        """Deserialize message key"""
        if key is None:
            return None
        try:
            return key.decode('utf-8')
        except Exception:
            return str(key)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of consumer pool"""
        return {
            'is_running': self.is_running,
            'active_consumers': len(self.consumers),
            'messages_processed': self.messages_processed,
            'messages_failed': self.messages_failed,
            'last_commit_time': self.last_commit_time,
            'consumer_tasks_running': sum(1 for task in self.consumer_tasks if not task.done())
        }

def setup_signal_handlers(consumer_pool: AsyncKafkaConsumerPool):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(consumer_pool.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)