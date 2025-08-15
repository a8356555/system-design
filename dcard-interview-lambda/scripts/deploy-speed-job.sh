#!/bin/bash

# Deploy Flink streaming job for speed layer
# Usage: ./deploy-speed-job.sh [restart]

set -e

RESTART_FLAG=${1:-"false"}
JAR_FILE="speed-layer-1.0.0.jar"
MAIN_CLASS="com.dcard.lambda.speed.SpeedLayerJob"

echo "🌊 Deploying Flink speed layer job..."

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Check if Flink cluster is running
if ! docker exec dcard-lambda-flink-jobmanager curl -s http://localhost:8081 >/dev/null 2>&1; then
    log "❌ Flink JobManager is not running. Please start the system first."
    exit 1
fi

log "✅ Flink cluster is running"

# Check if JAR file exists
JAR_PATH="./speed-layer/flink/target/$JAR_FILE"
if [ ! -f "$JAR_PATH" ]; then
    log "❌ JAR file not found: $JAR_PATH"
    log "Building speed layer job..."
    
    cd speed-layer/flink
    if ! mvn clean package -DskipTests; then
        log "❌ Failed to build speed layer job"
        exit 1
    fi
    cd ../..
    
    if [ ! -f "$JAR_PATH" ]; then
        log "❌ JAR file still not found after build"
        exit 1
    fi
fi

log "✅ JAR file found: $JAR_PATH"

# Check if job is already running
EXISTING_JOB=$(docker exec dcard-lambda-flink-jobmanager flink list -r 2>/dev/null | grep "SpeedLayerJob" | awk '{print $4}' | head -1 || echo "")

if [ ! -z "$EXISTING_JOB" ]; then
    log "⚠️  Speed layer job is already running with ID: $EXISTING_JOB"
    
    if [ "$RESTART_FLAG" = "restart" ]; then
        log "🔄 Restarting existing job..."
        
        # Create savepoint first
        SAVEPOINT_PATH="/opt/flink/savepoints/manual-savepoint-$(date +%s)"
        log "Creating savepoint: $SAVEPOINT_PATH"
        
        if docker exec dcard-lambda-flink-jobmanager flink savepoint "$EXISTING_JOB" "$SAVEPOINT_PATH"; then
            log "✅ Savepoint created: $SAVEPOINT_PATH"
            
            # Cancel the job
            log "Cancelling existing job..."
            docker exec dcard-lambda-flink-jobmanager flink cancel "$EXISTING_JOB"
            sleep 10
            
            # Deploy new job from savepoint
            log "Deploying new job from savepoint..."
            docker exec dcard-lambda-flink-jobmanager flink run \
                --parallelism 128 \
                --fromSavepoint "$SAVEPOINT_PATH" \
                --class $MAIN_CLASS \
                /opt/flink/usrlib/$JAR_FILE
                
        else
            log "⚠️  Failed to create savepoint, cancelling without savepoint..."
            docker exec dcard-lambda-flink-jobmanager flink cancel "$EXISTING_JOB"
            sleep 10
        fi
    else
        log "ℹ️  Job is already running. Use './deploy-speed-job.sh restart' to restart it."
        exit 0
    fi
else
    log "📦 No existing job found, deploying new job..."
    
    # Deploy the job with proper configuration
    docker exec dcard-lambda-flink-jobmanager flink run \
        --parallelism 128 \
        --class $MAIN_CLASS \
        /opt/flink/usrlib/$JAR_FILE
fi

# Check if deployment was successful
sleep 5
NEW_JOB=$(docker exec dcard-lambda-flink-jobmanager flink list -r 2>/dev/null | grep "SpeedLayerJob" | awk '{print $4}' | head -1 || echo "")

if [ ! -z "$NEW_JOB" ]; then
    log "✅ Speed layer job deployed successfully!"
    log "📊 Job ID: $NEW_JOB"
    log "🌐 Monitor at: http://localhost:8081"
    
    # Show job details
    log "📋 Job details:"
    docker exec dcard-lambda-flink-jobmanager flink list -r 2>/dev/null | grep -A2 -B2 "SpeedLayerJob" || true
    
    # Wait a bit and check job status
    sleep 10
    JOB_STATUS=$(docker exec dcard-lambda-flink-jobmanager flink list -r 2>/dev/null | grep "SpeedLayerJob" | awk '{print $5}' | head -1 || echo "UNKNOWN")
    
    if [ "$JOB_STATUS" = "RUNNING" ]; then
        log "✅ Job is running successfully"
        
        # Test the speed layer by checking if it's processing events
        log "🧪 Testing speed layer processing..."
        
        # Send a test event to Kafka
        docker exec dcard-lambda-kafka kafka-console-producer --bootstrap-server localhost:9092 --topic user-posts << EOF
{"user_id": 99999, "post_id": "test_post_$(date +%s)", "event_type": "POST_CREATED", "timestamp": "$(date -Is)", "board_id": "test"}
EOF
        
        log "📤 Test event sent to Kafka"
        
        # Wait and check if speed layer processed it
        sleep 30
        
        SPEED_RECORDS=$(docker exec dcard-lambda-clickhouse clickhouse-client --query="
            SELECT count() 
            FROM user_post_counts_speed 
            WHERE window_start > now() - INTERVAL 1 HOUR
        " 2>/dev/null || echo "0")
        
        if [ "$SPEED_RECORDS" -gt "0" ]; then
            log "✅ Speed layer is processing events successfully ($SPEED_RECORDS recent records)"
        else
            log "⚠️  No recent speed layer records found - may need more time to process"
        fi
        
    else
        log "⚠️  Job status: $JOB_STATUS"
        log "Check logs: docker-compose logs flink-jobmanager"
    fi
    
else
    log "❌ Failed to deploy speed layer job"
    log "Check Flink logs:"
    docker exec dcard-lambda-flink-jobmanager find /opt/flink/log -name "*.log" -exec tail -20 {} \; 2>/dev/null || log "Could not retrieve logs"
    exit 1
fi

# Generate deployment report
SPEED_REPORT="/tmp/speed_deployment_report_$(date +%s).txt"
cat > $SPEED_REPORT << EOF
Dcard Lambda Architecture - Speed Layer Deployment Report
=========================================================
Deployment Time: $(date)
Job ID: $NEW_JOB
Job Status: $JOB_STATUS
JAR File: $JAR_FILE
Main Class: $MAIN_CLASS

Configuration:
- Parallelism: 128
- Checkpointing: Every 30s (EXACTLY_ONCE)
- State Backend: RocksDB
- State TTL: 7 days

Flink Cluster:
- JobManager: http://localhost:8081
- TaskManagers: 2 instances
- Task Slots: 4 per TaskManager

Kafka Integration:
- Bootstrap Servers: kafka:29092
- Topic: user-posts
- Consumer Group: speed-layer-consumer

ClickHouse Integration:
- URL: jdbc:clickhouse://clickhouse:8123/dcard_lambda
- Target Tables: user_post_counts_speed, realtime_metrics

Status: $([ ! -z "$NEW_JOB" ] && echo "SUCCESS ✅" || echo "FAILED ❌")

Next Steps:
- Monitor job: http://localhost:8081/#/job/$NEW_JOB
- Check metrics: http://localhost:9090
- View dashboards: http://localhost:3000
- Test API: curl http://localhost:8000/api/v1/system/health
EOF

log "📄 Deployment report generated: $SPEED_REPORT"
cat $SPEED_REPORT

log "🎉 Speed layer deployment completed!"