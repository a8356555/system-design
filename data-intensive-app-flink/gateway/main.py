"""
FastAPI Event Gateway for PyFlink Analytics Platform
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaProducer
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# Metrics
event_ingestion_counter = Counter('events_ingested_total', 'Total events ingested', ['event_type'])
ingestion_duration = Histogram('event_ingestion_duration_seconds', 'Event ingestion duration')
batch_size_histogram = Histogram('batch_size', 'Batch size distribution')

# Create FastAPI app
app = FastAPI(
    title="PyFlink Analytics Event Gateway",
    description="High-performance event ingestion gateway for PyFlink analytics platform",
    version="3.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(',')
KAFKA_TOPIC = os.getenv('KAFKA_TOPIC', 'raw-events')
REDIS_CLUSTER_NODES = os.getenv('REDIS_CLUSTER_NODES', 'localhost:7000').split(',')

# Global connections
kafka_producer = None
redis_client = None


class Event(BaseModel):
    """Event model matching PyFlink Event class"""
    user_id: Optional[int] = None
    event_id: Optional[str] = None
    session_id: Optional[str] = None
    event_type: str = "unknown"
    event_name: Optional[str] = None
    properties: Optional[Dict[str, Any]] = Field(default_factory=dict)
    url: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    timestamp: Optional[str] = None
    date_partition: Optional[str] = None
    
    def dict_for_kafka(self) -> Dict[str, Any]:
        """Convert to dict for Kafka serialization"""
        data = self.dict()
        
        # Generate event_id if not provided
        if not data.get('event_id'):
            data['event_id'] = f"evt_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:8]}"
        
        # Set timestamp if not provided
        if not data.get('timestamp'):
            data['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        # Set date partition
        if not data.get('date_partition'):
            data['date_partition'] = datetime.utcnow().strftime('%Y-%m-%d')
        
        return data


class EventBatch(BaseModel):
    """Batch of events"""
    events: List[Event]


@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup"""
    global kafka_producer, redis_client
    
    # Initialize Kafka producer
    try:
        kafka_producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: str(k).encode('utf-8'),
            batch_size=16384,
            linger_ms=50,
            compression_type='snappy',
            retries=3,
            acks='all'
        )
        print(f"✅ Kafka producer initialized: {KAFKA_BOOTSTRAP_SERVERS}")
    except Exception as e:
        print(f"❌ Failed to initialize Kafka producer: {e}")
        raise
    
    # Initialize Redis client
    try:
        # For simplicity, connect to first Redis node
        redis_host, redis_port = REDIS_CLUSTER_NODES[0].split(':')
        redis_client = aioredis.Redis(
            host=redis_host,
            port=int(redis_port),
            decode_responses=True
        )
        await redis_client.ping()
        print(f"✅ Redis client initialized: {REDIS_CLUSTER_NODES[0]}")
    except Exception as e:
        print(f"❌ Failed to initialize Redis client: {e}")
        # Continue without Redis
        redis_client = None


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup connections on shutdown"""
    global kafka_producer, redis_client
    
    if kafka_producer:
        kafka_producer.flush()
        kafka_producer.close()
    
    if redis_client:
        await redis_client.close()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "PyFlink Analytics Event Gateway",
        "version": "3.0.0",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    health_status = {
        "service": "healthy",
        "kafka": "unknown",
        "redis": "unknown",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Check Kafka
    try:
        if kafka_producer:
            health_status["kafka"] = "healthy"
        else:
            health_status["kafka"] = "unhealthy"
    except:
        health_status["kafka"] = "unhealthy"
    
    # Check Redis
    try:
        if redis_client:
            await redis_client.ping()
            health_status["redis"] = "healthy"
        else:
            health_status["redis"] = "unavailable"
    except:
        health_status["redis"] = "unhealthy"
    
    return health_status


@app.post("/events")
async def ingest_single_event(event: Event, background_tasks: BackgroundTasks):
    """Ingest a single event"""
    with ingestion_duration.time():
        try:
            # Convert to dict for Kafka
            event_data = event.dict_for_kafka()
            
            # Send to Kafka
            partition_key = str(event_data.get('user_id', event_data.get('event_id')))
            
            future = kafka_producer.send(
                topic=KAFKA_TOPIC,
                value=event_data,
                key=partition_key
            )
            
            # Don't wait for Kafka acknowledgment to maintain low latency
            background_tasks.add_task(wait_for_kafka_ack, future, event_data)
            
            # Update metrics
            event_ingestion_counter.labels(event_type=event.event_type).inc()
            
            # Optional: Update real-time counters in Redis
            if redis_client:
                background_tasks.add_task(update_redis_counters, event_data)
            
            return {
                "status": "accepted",
                "event_id": event_data["event_id"],
                "timestamp": event_data["timestamp"]
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to ingest event: {str(e)}")


@app.post("/events/batch")
async def ingest_batch_events(batch: EventBatch, background_tasks: BackgroundTasks):
    """Ingest a batch of events"""
    with ingestion_duration.time():
        try:
            batch_size = len(batch.events)
            batch_size_histogram.observe(batch_size)
            
            futures = []
            event_data_list = []
            
            for event in batch.events:
                # Convert to dict for Kafka
                event_data = event.dict_for_kafka()
                event_data_list.append(event_data)
                
                # Send to Kafka
                partition_key = str(event_data.get('user_id', event_data.get('event_id')))
                
                future = kafka_producer.send(
                    topic=KAFKA_TOPIC,
                    value=event_data,
                    key=partition_key
                )
                futures.append(future)
                
                # Update metrics
                event_ingestion_counter.labels(event_type=event.event_type).inc()
            
            # Handle Kafka acknowledgments in background
            background_tasks.add_task(wait_for_batch_kafka_acks, futures, event_data_list)
            
            # Optional: Update Redis counters for the batch
            if redis_client:
                background_tasks.add_task(update_redis_batch_counters, event_data_list)
            
            return {
                "status": "accepted",
                "batch_size": batch_size,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to ingest batch: {str(e)}")


@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/realtime/metrics")
async def get_realtime_metrics(time_window: str = "1m"):
    """Get real-time metrics from Redis"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    try:
        current_time = datetime.utcnow()
        
        if time_window == "1m":
            key = current_time.strftime('%Y-%m-%d-%H-%M')
            events_count = await redis_client.get(f"events:count:{key}") or 0
            
            return {
                "time_window": time_window,
                "events_count": int(events_count),
                "timestamp": current_time.isoformat()
            }
        
        return {"error": "Unsupported time window"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


# Background tasks
async def wait_for_kafka_ack(future, event_data):
    """Wait for Kafka acknowledgment"""
    try:
        record_metadata = future.get(timeout=10)
        print(f"Event sent to {record_metadata.topic}:{record_metadata.partition}:{record_metadata.offset}")
    except Exception as e:
        print(f"Failed to send event to Kafka: {e}")


async def wait_for_batch_kafka_acks(futures, event_data_list):
    """Wait for batch Kafka acknowledgments"""
    try:
        for future, event_data in zip(futures, event_data_list):
            record_metadata = future.get(timeout=10)
            print(f"Batch event sent to {record_metadata.topic}:{record_metadata.partition}:{record_metadata.offset}")
    except Exception as e:
        print(f"Failed to send batch to Kafka: {e}")


async def update_redis_counters(event_data):
    """Update Redis counters for real-time metrics"""
    if not redis_client:
        return
    
    try:
        current_minute = datetime.utcnow().strftime('%Y-%m-%d-%H-%M')
        
        # Increment global counter
        await redis_client.incr(f"events:count:{current_minute}")
        await redis_client.expire(f"events:count:{current_minute}", 3600)
        
        # Increment event type counter
        event_type = event_data.get('event_type', 'unknown')
        await redis_client.incr(f"events:type:{event_type}:{current_minute}")
        await redis_client.expire(f"events:type:{event_type}:{current_minute}", 3600)
        
    except Exception as e:
        print(f"Failed to update Redis counters: {e}")


async def update_redis_batch_counters(event_data_list):
    """Update Redis counters for batch of events"""
    if not redis_client:
        return
    
    try:
        current_minute = datetime.utcnow().strftime('%Y-%m-%d-%H-%M')
        batch_size = len(event_data_list)
        
        # Increment global counter
        await redis_client.incrby(f"events:count:{current_minute}", batch_size)
        await redis_client.expire(f"events:count:{current_minute}", 3600)
        
        # Count event types
        event_type_counts = {}
        for event_data in event_data_list:
            event_type = event_data.get('event_type', 'unknown')
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        
        # Update event type counters
        for event_type, count in event_type_counts.items():
            await redis_client.incrby(f"events:type:{event_type}:{current_minute}", count)
            await redis_client.expire(f"events:type:{event_type}:{current_minute}", 3600)
        
    except Exception as e:
        print(f"Failed to update Redis batch counters: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)