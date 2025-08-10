"""
Kafka source for consuming events in PyFlink
"""
import json
import logging
from typing import List, Optional

from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream.connectors import FlinkKafkaConsumer
from pyflink.common import Configuration
from pyflink.common.typeinfo import Types

from src.models.event import Event

logger = logging.getLogger(__name__)


class EventDeserializationSchema:
    """Custom deserializer for Event objects from JSON"""
    
    def __init__(self):
        pass
    
    def deserialize(self, message: bytes) -> Optional[Event]:
        """Deserialize bytes to Event object"""
        try:
            if not message:
                return None
            
            # Decode bytes to string
            json_str = message.decode('utf-8')
            
            # Parse JSON
            data = json.loads(json_str)
            
            # Handle both direct event format and wrapped format
            if 'event' in data:
                event_data = data['event']
            else:
                event_data = data
            
            # Create Event object
            return Event.from_dict(event_data)
            
        except Exception as e:
            logger.error(f"Failed to deserialize event: {json_str if 'json_str' in locals() else message}")
            logger.error(f"Error: {e}")
            return None  # Return None for malformed events - Flink will skip them
    
    def is_end_of_stream(self, next_element) -> bool:
        """Never end the stream"""
        return False
    
    def get_produced_type(self):
        """Return type information for Event"""
        return Types.PICKLED_BYTE_ARRAY()  # Use pickle for complex Python objects


class KafkaEventSource:
    """Factory for creating Kafka sources that consume events"""
    
    def __init__(self, bootstrap_servers: str, topics: List[str], 
                 group_id: str, value_deserializer: str = 'json'):
        self.bootstrap_servers = bootstrap_servers
        self.topics = topics
        self.group_id = group_id
        self.value_deserializer = value_deserializer
        
        logger.info(f"Creating Kafka source - servers: {bootstrap_servers}, "
                   f"topics: {topics}, group: {group_id}")
    
    def create_source(self) -> FlinkKafkaConsumer:
        """Create Flink Kafka Consumer"""
        
        # Kafka consumer properties
        properties = {
            'bootstrap.servers': self.bootstrap_servers,
            'group.id': self.group_id,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': 'false',  # Flink handles commits
            'session.timeout.ms': '30000',
            'request.timeout.ms': '40000',
            'max.poll.records': '1000',
            'fetch.min.bytes': '1',
            'fetch.max.wait.ms': '500'
        }
        
        if self.value_deserializer == 'json':
            # Use custom Event deserializer
            kafka_consumer = FlinkKafkaConsumer(
                topics=self.topics,
                deserialization_schema=EventDeserializationSchema(),
                properties=properties
            )
        else:
            # Use simple string deserializer
            kafka_consumer = FlinkKafkaConsumer(
                topics=self.topics,
                deserialization_schema=SimpleStringSchema(),
                properties=properties
            )
        
        return kafka_consumer
    
    @staticmethod
    def create_for_replay(bootstrap_servers: str, topics: List[str], 
                         start_timestamp: int) -> FlinkKafkaConsumer:
        """Create Kafka source for replay scenarios"""
        group_id = f"flink-replay-{int(start_timestamp)}"
        
        logger.info(f"Creating Kafka replay source from timestamp: {start_timestamp}")
        
        properties = {
            'bootstrap.servers': bootstrap_servers,
            'group.id': group_id,
            'enable.auto.commit': 'false',
            'session.timeout.ms': '30000',
            'max.poll.records': '5000',  # Higher batch for replay
        }
        
        kafka_consumer = FlinkKafkaConsumer(
            topics=topics,
            deserialization_schema=EventDeserializationSchema(),
            properties=properties
        )
        
        # Set start from specific timestamp
        kafka_consumer.set_start_from_timestamp(start_timestamp)
        
        return kafka_consumer
    
    @staticmethod
    def create_bounded(bootstrap_servers: str, topics: List[str], 
                      start_timestamp: int, end_timestamp: int) -> FlinkKafkaConsumer:
        """Create bounded Kafka source for batch processing"""
        group_id = f"flink-batch-{int(start_timestamp)}"
        
        logger.info(f"Creating bounded Kafka source from {start_timestamp} to {end_timestamp}")
        
        properties = {
            'bootstrap.servers': bootstrap_servers,
            'group.id': group_id,
            'enable.auto.commit': 'false',
            'max.poll.records': '10000',  # Higher batch for batch processing
        }
        
        kafka_consumer = FlinkKafkaConsumer(
            topics=topics,
            deserialization_schema=EventDeserializationSchema(),
            properties=properties
        )
        
        # Set bounded execution
        kafka_consumer.set_start_from_timestamp(start_timestamp)
        # Note: PyFlink doesn't have direct stop_at_timestamp, 
        # would need to implement custom stopping logic
        
        return kafka_consumer


# Alternative implementation using Kafka connector table
def create_kafka_table_source(table_env, bootstrap_servers: str, topic: str, group_id: str):
    """Create Kafka table source for Table API usage"""
    
    table_env.execute_sql(f"""
        CREATE TABLE kafka_events (
            event_id STRING,
            user_id BIGINT,
            session_id STRING,
            event_type STRING,
            event_name STRING,
            url STRING,
            country STRING,
            city STRING,
            event_time TIMESTAMP(3),
            date_partition STRING,
            properties MAP<STRING, STRING>,
            WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND
        ) WITH (
            'connector' = 'kafka',
            'topic' = '{topic}',
            'properties.bootstrap.servers' = '{bootstrap_servers}',
            'properties.group.id' = '{group_id}',
            'properties.auto.offset.reset' = 'latest',
            'format' = 'json',
            'json.fail-on-missing-field' = 'false',
            'json.ignore-parse-errors' = 'true'
        )
    """)
    
    logger.info(f"Created Kafka table source for topic: {topic}")
    
    return table_env.from_path("kafka_events")