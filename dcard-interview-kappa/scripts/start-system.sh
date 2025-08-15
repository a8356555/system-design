#!/bin/bash

# Start Dcard Post Tracking System
# This script starts all components in the correct order

set -e

echo "🚀 Starting Dcard Post Tracking System..."

# Function to wait for service to be ready
wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3
    local max_attempts=30
    local attempt=1

    echo "⏳ Waiting for $service_name to be ready..."
    
    while ! nc -z "$host" "$port" >/dev/null 2>&1; do
        if [ $attempt -eq $max_attempts ]; then
            echo "❌ $service_name failed to start after $max_attempts attempts"
            exit 1
        fi
        echo "   Attempt $attempt/$max_attempts - waiting for $service_name..."
        sleep 5
        attempt=$((attempt + 1))
    done
    
    echo "✅ $service_name is ready!"
}

# Start infrastructure services first
echo "📦 Starting infrastructure services..."
docker-compose up -d zookeeper kafka schema-registry clickhouse

# Wait for Kafka to be ready
wait_for_service localhost 9092 "Kafka"

# Wait for ClickHouse to be ready
wait_for_service localhost 8123 "ClickHouse"

# Create Kafka topics
echo "🔧 Creating Kafka topics..."
docker exec dcard-kafka /bin/bash -c "
    kafka-topics --create --bootstrap-server localhost:9092 --topic user-posts --partitions 512 --replication-factor 1 --config compression.type=lz4 --config retention.ms=604800000 --config segment.ms=3600000 || true
    kafka-topics --create --bootstrap-server localhost:9092 --topic user-posts-dlq --partitions 16 --replication-factor 1 --config retention.ms=2592000000 || true
"

# Initialize ClickHouse schema
echo "🗄️  Initializing ClickHouse schema..."
sleep 10  # Give ClickHouse time to fully start

# Build Flink application
echo "🔨 Building Flink application..."
cd flink
if ! mvn clean package -DskipTests; then
    echo "❌ Failed to build Flink application"
    exit 1
fi
cd ..

# Start Flink services
echo "🌊 Starting Flink services..."
docker-compose up -d flink-jobmanager flink-taskmanager

# Wait for Flink JobManager to be ready
wait_for_service localhost 8080 "Flink JobManager"

# Start monitoring services
echo "📊 Starting monitoring services..."
docker-compose up -d prometheus grafana kafka-ui

# Wait for all monitoring services
wait_for_service localhost 9090 "Prometheus"
wait_for_service localhost 3000 "Grafana"
wait_for_service localhost 8090 "Kafka UI"

echo "✅ All services started successfully!"
echo ""
echo "📋 Service URLs:"
echo "   Flink Web UI:     http://localhost:8080"
echo "   Kafka UI:         http://localhost:8090" 
echo "   ClickHouse:       http://localhost:8123"
echo "   Prometheus:       http://localhost:9090"
echo "   Grafana:          http://localhost:3000 (admin/admin)"
echo ""
echo "🔧 To deploy the Flink job, run:"
echo "   ./scripts/deploy-flink-job.sh"
echo ""
echo "📊 To check system status:"
echo "   docker-compose ps"
echo "   docker-compose logs -f [service-name]"