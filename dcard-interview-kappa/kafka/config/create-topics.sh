#!/bin/bash

# Create Kafka topics for Dcard post tracking system

KAFKA_HOME=${KAFKA_HOME:-/opt/kafka}
BOOTSTRAP_SERVERS=${BOOTSTRAP_SERVERS:-localhost:9092}

echo "Creating user-posts topic..."
$KAFKA_HOME/bin/kafka-topics.sh --create \
    --bootstrap-server $BOOTSTRAP_SERVERS \
    --topic user-posts \
    --partitions 512 \
    --replication-factor 3 \
    --config compression.type=lz4 \
    --config min.insync.replicas=2 \
    --config retention.ms=604800000 \
    --config segment.ms=3600000 \
    --config cleanup.policy=delete

echo "Creating dead letter queue topic..."
$KAFKA_HOME/bin/kafka-topics.sh --create \
    --bootstrap-server $BOOTSTRAP_SERVERS \
    --topic user-posts-dlq \
    --partitions 16 \
    --replication-factor 3 \
    --config retention.ms=2592000000

echo "Listing topics..."
$KAFKA_HOME/bin/kafka-topics.sh --list \
    --bootstrap-server $BOOTSTRAP_SERVERS

echo "Topic creation completed!"