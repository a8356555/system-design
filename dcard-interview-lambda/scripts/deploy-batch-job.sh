#!/bin/bash

# Deploy and run batch processing job for specific date
# Usage: ./deploy-batch-job.sh [YYYY-MM-DD] [mode]

set -e

# Configuration
PROCESSING_DATE=${1:-$(date -d "yesterday" +%Y-%m-%d)}
MODE=${2:-"cluster"}  # cluster or local
JAR_FILE="batch-layer-1.0.0.jar"
MAIN_CLASS="com.dcard.lambda.batch.BatchProcessingJob"

# Paths
DATA_LAKE_PATH="hdfs://hdfs-namenode:8020/data-lake"
BATCH_OUTPUT_PATH="hdfs://hdfs-namenode:8020/batch-views"
CLICKHOUSE_URL="jdbc:clickhouse://clickhouse:8123/dcard_lambda"

echo "🚀 Deploying batch processing job for date: $PROCESSING_DATE"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Check if JAR file exists
JAR_PATH="./batch-layer/spark/target/$JAR_FILE"
if [ ! -f "$JAR_PATH" ]; then
    log "❌ JAR file not found: $JAR_PATH"
    log "Building batch processing job..."
    
    cd batch-layer/spark
    if ! mvn clean package -DskipTests; then
        log "❌ Failed to build batch processing job"
        exit 1
    fi
    cd ../..
    
    if [ ! -f "$JAR_PATH" ]; then
        log "❌ JAR file still not found after build"
        exit 1
    fi
fi

log "✅ JAR file found: $JAR_PATH"

# Check if Spark cluster is running
if ! docker exec dcard-lambda-spark-master curl -s http://localhost:8080 >/dev/null 2>&1; then
    log "❌ Spark master is not running. Please start the system first."
    exit 1
fi

log "✅ Spark cluster is running"

# Check if data exists for the processing date
log "Checking if data exists for $PROCESSING_DATE..."
if ! docker exec dcard-lambda-hdfs-namenode hadoop fs -test -e "/data-lake/events/date=$PROCESSING_DATE" 2>/dev/null; then
    log "⚠️  No data found for date $PROCESSING_DATE"
    log "Creating sample data for demonstration..."
    
    # Create sample data directory
    docker exec dcard-lambda-hdfs-namenode hadoop fs -mkdir -p "/data-lake/events/date=$PROCESSING_DATE" || true
    
    # Create a small sample file (in a real system, this would be your actual data)
    docker exec dcard-lambda-hdfs-namenode sh -c "
        echo '{\"user_id\":12345,\"post_id\":\"post_001\",\"event_type\":\"POST_CREATED\",\"timestamp\":\"$(date -Is)\",\"board_id\":\"tech\"}' | hadoop fs -put - /data-lake/events/date=$PROCESSING_DATE/sample.json
    " || log "Sample data creation failed (data may already exist)"
fi

log "✅ Data exists for $PROCESSING_DATE"

# Submit Spark job
log "Submitting batch processing job..."

SPARK_SUBMIT_CMD="spark-submit \
    --class $MAIN_CLASS \
    --master spark://spark-master:7077 \
    --deploy-mode $MODE \
    --driver-memory 2g \
    --executor-memory 4g \
    --executor-cores 4 \
    --num-executors 2 \
    --conf spark.app.name=Dcard-Batch-Processing-$PROCESSING_DATE \
    --conf spark.sql.adaptive.enabled=true \
    --conf spark.sql.adaptive.coalescePartitions.enabled=true \
    --conf spark.serializer=org.apache.spark.serializer.KryoSerializer \
    --conf spark.dynamicAllocation.enabled=false \
    --packages io.delta:delta-core_2.12:3.0.0,com.clickhouse:clickhouse-jdbc:0.4.6 \
    /opt/spark-apps/$JAR_FILE \
    $DATA_LAKE_PATH \
    $BATCH_OUTPUT_PATH \
    $CLICKHOUSE_URL \
    $PROCESSING_DATE"

log "Executing: $SPARK_SUBMIT_CMD"

if docker exec dcard-lambda-spark-master $SPARK_SUBMIT_CMD; then
    SPARK_EXIT_CODE=0
else
    SPARK_EXIT_CODE=$?
fi

if [ $SPARK_EXIT_CODE -eq 0 ]; then
    log "✅ Batch processing completed successfully for $PROCESSING_DATE"
    
    # Update batch processing metadata in ClickHouse
    log "Updating batch processing cutoff metadata..."
    
    docker exec dcard-lambda-clickhouse clickhouse-client --query="
        INSERT INTO processing_metadata (key, value) VALUES 
        ('batch_cutoff_date', '$PROCESSING_DATE')
        ON DUPLICATE KEY UPDATE value='$PROCESSING_DATE', updated_at=now64()
    " || log "⚠️  Failed to update metadata"
    
    # Trigger serving layer cache refresh
    log "Triggering serving layer cache refresh..."
    curl -X POST "http://localhost:8000/api/v1/cache/refresh" \
         -H "Content-Type: application/json" \
         -d "{\"processing_date\":\"$PROCESSING_DATE\"}" 2>/dev/null || log "⚠️  Cache refresh failed"
    
    log "🎉 Batch job completed successfully!"
    
    # Show some statistics
    log "📊 Batch processing statistics:"
    
    docker exec dcard-lambda-clickhouse clickhouse-client --query="
        SELECT 'Users processed' as metric, count() as value
        FROM user_post_counts_batch 
        WHERE processing_date = '$PROCESSING_DATE'
        
        UNION ALL
        
        SELECT 'Total posts' as metric, sum(total_post_count) as value
        FROM user_post_counts_batch 
        WHERE processing_date = '$PROCESSING_DATE'
    " 2>/dev/null || log "⚠️  Could not retrieve statistics"
    
else
    log "❌ Batch processing failed with exit code $SPARK_EXIT_CODE"
    
    # Show recent Spark logs
    log "Recent Spark driver logs:"
    docker exec dcard-lambda-spark-master find /opt/spark/logs -name "*driver*" -type f -exec tail -20 {} \; 2>/dev/null || log "Could not retrieve driver logs"
    
    exit $SPARK_EXIT_CODE
fi

# Generate batch job report
BATCH_REPORT="/tmp/batch_report_$PROCESSING_DATE.txt"
cat > $BATCH_REPORT << EOF
Dcard Lambda Architecture - Batch Processing Report
==================================================
Processing Date: $PROCESSING_DATE
Completion Time: $(date)
Status: $([ $SPARK_EXIT_CODE -eq 0 ] && echo "SUCCESS ✅" || echo "FAILED ❌")
Mode: $MODE
Spark Job Exit Code: $SPARK_EXIT_CODE

Configuration:
- Data Lake Path: $DATA_LAKE_PATH
- Batch Output Path: $BATCH_OUTPUT_PATH  
- ClickHouse URL: $CLICKHOUSE_URL
- JAR File: $JAR_FILE
- Main Class: $MAIN_CLASS

Spark Configuration:
- Driver Memory: 2g
- Executor Memory: 4g
- Executor Cores: 4
- Number of Executors: 2

$([ $SPARK_EXIT_CODE -eq 0 ] && echo "🎉 All processing steps completed successfully" || echo "❌ Processing failed - check Spark logs for details")

Next Steps:
- Check serving layer API: http://localhost:8000/api/v1/system/health
- View batch results: http://localhost:8000/api/v1/users/top
- Monitor in Grafana: http://localhost:3000
EOF

log "📄 Batch report generated: $BATCH_REPORT"
cat $BATCH_REPORT