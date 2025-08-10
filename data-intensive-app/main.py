import asyncio
import signal
import sys
from typing import List
from contextlib import asynccontextmanager

import uvicorn
import structlog
from prometheus_client import start_http_server

from app.streaming.async_consumer import AsyncKafkaConsumerPool, setup_signal_handlers
from app.streaming.event_stream_processor import (
    RealtimeMetricsProcessor,
    SessionProcessor, 
    AggregationProcessor,
    SearchIndexProcessor
)
from app.storage.multi_tier_storage import MultiTierStorage

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

class DataIntensiveApplication:
    """Main application orchestrator"""
    
    def __init__(self):
        self.storage: MultiTierStorage = None
        self.consumer_pools: List[AsyncKafkaConsumerPool] = []
        self.shutdown_event = asyncio.Event()
        
    async def initialize_storage(self):
        """Initialize multi-tier storage"""
        logger.info("Initializing storage layers...")
        
        self.storage = MultiTierStorage()
        
        # Storage configuration
        storage_config = {
            'hot_storage': {
                'cluster_nodes': ['localhost:7000', 'localhost:7001', 'localhost:7002']
            },
            'warm_storage': {
                'hosts': ['localhost:9000', 'localhost:9001'],
                'database': 'analytics'
            },
            'cold_storage': {
                'endpoint': 'http://localhost:9100',
                'access_key': 'minioadmin',
                'secret_key': 'minioadmin123',
                'bucket': 'analytics-cold-storage'
            },
            'search_storage': {
                'hosts': ['http://localhost:9200']
            }
        }
        
        await self.storage.initialize(storage_config)
        logger.info("Storage layers initialized successfully")
    
    async def setup_stream_processors(self):
        """Setup stream processing consumers"""
        logger.info("Setting up stream processors...")
        
        kafka_bootstrap_servers = ['localhost:9092']
        
        # Real-time metrics processor
        realtime_processor = RealtimeMetricsProcessor(self.storage)
        realtime_consumer = AsyncKafkaConsumerPool(
            bootstrap_servers=kafka_bootstrap_servers,
            topics=['raw-events'],
            group_id='realtime-metrics-processor',
            event_processor=realtime_processor,
            consumer_count=2,
            batch_size=100,
            max_poll_records=500
        )
        
        # Session tracking processor
        session_processor = SessionProcessor(self.storage, session_timeout_minutes=30)
        session_consumer = AsyncKafkaConsumerPool(
            bootstrap_servers=kafka_bootstrap_servers,
            topics=['raw-events'],
            group_id='session-processor',
            event_processor=session_processor,
            consumer_count=1,
            batch_size=200,
            max_poll_records=1000
        )
        
        # Aggregation processor (for ClickHouse)
        aggregation_processor = AggregationProcessor(self.storage)
        aggregation_consumer = AsyncKafkaConsumerPool(
            bootstrap_servers=kafka_bootstrap_servers,
            topics=['raw-events'],
            group_id='aggregation-processor',
            event_processor=aggregation_processor,
            consumer_count=3,
            batch_size=1000,
            max_poll_records=2000
        )
        
        # Search indexing processor
        search_processor = SearchIndexProcessor(self.storage)
        search_consumer = AsyncKafkaConsumerPool(
            bootstrap_servers=kafka_bootstrap_servers,
            topics=['raw-events'],
            group_id='search-processor',
            event_processor=search_processor,
            consumer_count=1,
            batch_size=500,
            max_poll_records=1000
        )
        
        self.consumer_pools = [
            realtime_consumer,
            session_consumer,
            aggregation_consumer,
            search_consumer
        ]
        
        # Start all consumer pools
        for i, consumer_pool in enumerate(self.consumer_pools):
            await consumer_pool.start()
            logger.info(f"Started consumer pool {i+1}/{len(self.consumer_pools)}")
        
        logger.info("All stream processors started successfully")
    
    async def start(self):
        """Start the application"""
        logger.info("Starting Data-Intensive Application...")
        
        try:
            # Start Prometheus metrics server
            start_http_server(9090)
            logger.info("Prometheus metrics server started on port 9090")
            
            # Initialize storage
            await self.initialize_storage()
            
            # Setup stream processors
            await self.setup_stream_processors()
            
            # Setup signal handlers
            for consumer_pool in self.consumer_pools:
                setup_signal_handlers(consumer_pool)
            
            logger.info("Application started successfully")
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
        except Exception as e:
            logger.error("Failed to start application", error=str(e))
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the application gracefully"""
        logger.info("Stopping application...")
        
        # Stop all consumer pools
        for i, consumer_pool in enumerate(self.consumer_pools):
            try:
                await consumer_pool.stop()
                logger.info(f"Stopped consumer pool {i+1}/{len(self.consumer_pools)}")
            except Exception as e:
                logger.error(f"Error stopping consumer pool {i+1}", error=str(e))
        
        logger.info("Application stopped")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_event.set()

async def run_api_server():
    """Run the FastAPI server"""
    config = uvicorn.Config(
        "app.api.events:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        loop="uvloop",
        http="httptools",
        log_config=None,  # Use structured logging
        access_log=False  # Disable uvicorn access logs
    )
    
    server = uvicorn.Server(config)
    await server.serve()

async def run_stream_processors():
    """Run the stream processing components"""
    app = DataIntensiveApplication()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, app.signal_handler)
    signal.signal(signal.SIGTERM, app.signal_handler)
    
    await app.start()

async def main():
    """Main entry point - runs both API server and stream processors"""
    
    # Determine run mode from command line arguments
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        mode = "all"  # Default: run everything
    
    logger.info("Starting application", mode=mode)
    
    if mode == "api":
        # Run only API server
        await run_api_server()
        
    elif mode == "processors":
        # Run only stream processors
        await run_stream_processors()
        
    elif mode == "all":
        # Run both API server and stream processors
        tasks = [
            asyncio.create_task(run_api_server()),
            asyncio.create_task(run_stream_processors())
        ]
        
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
            for task in tasks:
                task.cancel()
            
            # Wait for tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)
    
    else:
        logger.error("Invalid mode. Use: api, processors, or all", mode=mode)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted")
    except Exception as e:
        logger.error("Application failed", error=str(e))
        sys.exit(1)