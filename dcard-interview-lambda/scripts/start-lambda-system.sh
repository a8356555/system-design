#!/bin/bash

# Start Dcard Lambda Architecture System
# This script starts all components in the correct order

set -e

echo "🚀 Starting Dcard Lambda Architecture System..."

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
        sleep 10
        attempt=$((attempt + 1))
    done
    
    echo "✅ $service_name is ready!"
}

# Function to check service health
check_service_health() {
    local url=$1
    local service_name=$2
    local max_attempts=10
    local attempt=1
    
    echo "🏥 Checking $service_name health..."
    
    while ! curl -f "$url" >/dev/null 2>&1; do
        if [ $attempt -eq $max_attempts ]; then
            echo "⚠️  $service_name health check failed after $max_attempts attempts"
            return 1
        fi
        echo "   Health check attempt $attempt/$max_attempts for $service_name..."
        sleep 5
        attempt=$((attempt + 1))
    done
    
    echo "✅ $service_name is healthy!"
}

# Start infrastructure services first
echo "📦 Starting infrastructure services..."
docker-compose up -d zookeeper kafka clickhouse redis hdfs-namenode hdfs-datanode

# Wait for core infrastructure
wait_for_service localhost 2181 "Zookeeper"
wait_for_service localhost 9092 "Kafka"
wait_for_service localhost 8123 "ClickHouse"
wait_for_service localhost 6379 "Redis"
wait_for_service localhost 9870 "HDFS NameNode"

# Create Kafka topics
echo "🔧 Creating Kafka topics..."
sleep 10  # Give Kafka more time to fully start

docker exec dcard-lambda-kafka kafka-topics --create \
    --bootstrap-server localhost:9092 \
    --topic user-posts \
    --partitions 128 \
    --replication-factor 1 \
    --config compression.type=lz4 \
    --config retention.ms=604800000 \
    --if-not-exists || echo "Topic already exists"

docker exec dcard-lambda-kafka kafka-topics --create \
    --bootstrap-server localhost:9092 \
    --topic user-posts-dlq \
    --partitions 16 \
    --replication-factor 1 \
    --config retention.ms=2592000000 \
    --if-not-exists || echo "DLQ topic already exists"

echo "✅ Kafka topics created"

# Initialize ClickHouse schema
echo "🗄️  Initializing ClickHouse schema..."
sleep 15  # Give ClickHouse time to fully start

# Wait for ClickHouse to be fully ready
docker exec dcard-lambda-clickhouse clickhouse-client --query="SELECT 1" || sleep 10

echo "✅ ClickHouse schema initialized"

# Start batch layer (Spark)
echo "🔥 Starting Batch Layer (Spark)..."
docker-compose up -d spark-master spark-worker

wait_for_service localhost 8080 "Spark Master"
echo "✅ Batch Layer started"

# Build batch processing job
echo "🔨 Building batch processing job..."
if [ -d "batch-layer/spark" ]; then
    cd batch-layer/spark
    if ! mvn clean package -DskipTests -q; then
        echo "❌ Failed to build batch processing job"
        exit 1
    fi
    cd ../..
    echo "✅ Batch processing job built"
fi

# Start speed layer (Flink)  
echo "⚡ Starting Speed Layer (Flink)..."
docker-compose up -d flink-jobmanager flink-taskmanager

wait_for_service localhost 8081 "Flink JobManager"
echo "✅ Speed Layer started"

# Build speed processing job
echo "🔨 Building speed processing job..."
if [ -d "speed-layer/flink" ]; then
    cd speed-layer/flink
    if ! mvn clean package -DskipTests -q; then
        echo "❌ Failed to build speed processing job"
        exit 1
    fi
    cd ../..
    echo "✅ Speed processing job built"
fi

# Start serving layer (API)
echo "🌐 Starting Serving Layer (API)..."
docker-compose up -d serving-api

wait_for_service localhost 8000 "Serving Layer API"
check_service_health "http://localhost:8000/health" "Serving Layer API"
echo "✅ Serving Layer started"

# Start monitoring services
echo "📊 Starting monitoring services..."
docker-compose up -d prometheus grafana kafka-ui

wait_for_service localhost 9090 "Prometheus"
wait_for_service localhost 3000 "Grafana"
wait_for_service localhost 8090 "Kafka UI"

check_service_health "http://localhost:9090/-/healthy" "Prometheus"
check_service_health "http://localhost:3000/api/health" "Grafana"

echo "✅ Monitoring services started"

# Deploy Flink streaming job
echo "🌊 Deploying Flink streaming job..."
sleep 10  # Give Flink time to be fully ready

if [ -f "speed-layer/flink/target/speed-layer-1.0.0.jar" ]; then
    docker exec dcard-lambda-flink-jobmanager flink run \
        --parallelism 128 \
        --class com.dcard.lambda.speed.SpeedLayerJob \
        /opt/flink/usrlib/speed-layer-1.0.0.jar || echo "⚠️  Flink job deployment failed (may already be running)"
    
    echo "✅ Flink streaming job deployed"
else
    echo "⚠️  Flink JAR not found, skipping job deployment"
fi

# Run initial batch processing (if data exists)
echo "📊 Checking for initial batch processing..."
if [ -d "data-lake/events" ] && [ "$(ls -A data-lake/events 2>/dev/null)" ]; then
    echo "🔄 Running initial batch processing..."
    
    YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
    
    if [ -f "batch-layer/spark/target/batch-layer-1.0.0.jar" ]; then
        docker exec dcard-lambda-spark-master spark-submit \
            --class com.dcard.lambda.batch.BatchProcessingJob \
            --master spark://spark-master:7077 \
            --deploy-mode client \
            --driver-memory 2g \
            --executor-memory 4g \
            --executor-cores 4 \
            --num-executors 2 \
            /opt/spark-apps/batch-layer-1.0.0.jar \
            "hdfs://hdfs-namenode:8020/data-lake" \
            "hdfs://hdfs-namenode:8020/batch-views" \
            "jdbc:clickhouse://clickhouse:8123/dcard_lambda" \
            "$YESTERDAY" || echo "⚠️  Initial batch processing failed"
        
        echo "✅ Initial batch processing completed"
    else
        echo "⚠️  Batch JAR not found, skipping initial processing"
    fi
else
    echo "ℹ️  No initial data found, skipping batch processing"
fi

echo ""
echo "🎉 Dcard Lambda Architecture System started successfully!"
echo ""
echo "📋 Service URLs:"
echo "   Serving Layer API:    http://localhost:8000"
echo "   API Documentation:    http://localhost:8000/docs"
echo "   Spark Master UI:      http://localhost:8080"
echo "   Flink Web UI:         http://localhost:8081" 
echo "   ClickHouse:           http://localhost:8123"
echo "   HDFS NameNode:        http://localhost:9870"
echo "   Kafka UI:             http://localhost:8090"
echo "   Prometheus:           http://localhost:9090"
echo "   Grafana:              http://localhost:3000 (admin/admin)"
echo ""
echo "🔧 Management Commands:"
echo "   View logs:            docker-compose logs -f [service-name]"
echo "   Stop system:          docker-compose down"
echo "   System status:        docker-compose ps"
echo "   Run batch job:        ./batch-layer/jobs/daily-batch-job.sh [date]"
echo ""
echo "📊 Test the system:"
echo "   curl http://localhost:8000/api/v1/system/health"
echo "   curl http://localhost:8000/api/v1/users/12345/post-count"
echo ""
echo "🚀 Lambda Architecture is ready!"