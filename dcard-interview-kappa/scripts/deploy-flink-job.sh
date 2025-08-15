#!/bin/bash

# Deploy Flink Streaming Job to the cluster

set -e

echo "🚀 Deploying Flink streaming job..."

# Check if Flink JobManager is running
if ! nc -z localhost 8080 >/dev/null 2>&1; then
    echo "❌ Flink JobManager is not running. Please start it first with ./start-system.sh"
    exit 1
fi

# Check if JAR file exists
JAR_PATH="./flink/target/post-count-streaming-1.0.0.jar"
if [ ! -f "$JAR_PATH" ]; then
    echo "❌ Flink JAR not found. Building..."
    cd flink
    mvn clean package -DskipTests
    cd ..
fi

if [ ! -f "$JAR_PATH" ]; then
    echo "❌ Failed to build Flink JAR"
    exit 1
fi

# Deploy the job using Flink CLI
echo "📦 Submitting job to Flink cluster..."

# Submit the job with proper configuration
docker exec dcard-flink-jobmanager flink run \
    --parallelism 512 \
    --class com.dcard.PostCountStreamingJob \
    /opt/flink/usrlib/post-count-streaming-1.0.0.jar

if [ $? -eq 0 ]; then
    echo "✅ Flink job deployed successfully!"
    echo ""
    echo "📊 You can monitor the job at: http://localhost:8080"
    echo ""
    echo "🔍 To check job status:"
    echo "   docker exec dcard-flink-jobmanager flink list"
    echo ""
    echo "📝 To view logs:"
    echo "   docker-compose logs -f flink-jobmanager"
    echo "   docker-compose logs -f flink-taskmanager"
else
    echo "❌ Failed to deploy Flink job"
    echo "📝 Check logs for details:"
    echo "   docker-compose logs flink-jobmanager"
    exit 1
fi