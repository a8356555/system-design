#!/bin/bash

# Daily Batch Processing Job for Dcard Lambda Architecture
# This script runs the daily batch processing job

set -e

# Configuration
SPARK_HOME=${SPARK_HOME:-/opt/spark}
DATA_LAKE_PATH=${DATA_LAKE_PATH:-"s3a://dcard-data-lake"}
BATCH_OUTPUT_PATH=${BATCH_OUTPUT_PATH:-"s3a://dcard-batch-views"}
CLICKHOUSE_URL=${CLICKHOUSE_URL:-"jdbc:clickhouse://clickhouse:8123/default"}
PROCESSING_DATE=${1:-$(date -d "yesterday" +%Y-%m-%d)}

# Spark configuration
SPARK_DRIVER_MEMORY="4g"
SPARK_EXECUTOR_MEMORY="8g"
SPARK_EXECUTOR_CORES="4"
SPARK_NUM_EXECUTORS="10"
SPARK_MAX_ATTEMPTS="3"

# JAR file location
BATCH_JAR="/opt/batch-layer/batch-layer-1.0.0.jar"

echo "🚀 Starting daily batch processing job for date: $PROCESSING_DATE"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Check if data exists for the processing date
log "Checking if data exists for $PROCESSING_DATE..."
if ! hadoop fs -test -e "$DATA_LAKE_PATH/events/date=$PROCESSING_DATE" 2>/dev/null; then
    log "❌ No data found for date $PROCESSING_DATE in $DATA_LAKE_PATH/events/"
    exit 1
fi

log "✅ Data found for $PROCESSING_DATE"

# Submit Spark job
log "Submitting Spark batch processing job..."

$SPARK_HOME/bin/spark-submit \
    --class com.dcard.lambda.batch.BatchProcessingJob \
    --master yarn \
    --deploy-mode cluster \
    --driver-memory $SPARK_DRIVER_MEMORY \
    --executor-memory $SPARK_EXECUTOR_MEMORY \
    --executor-cores $SPARK_EXECUTOR_CORES \
    --num-executors $SPARK_NUM_EXECUTORS \
    --conf spark.app.name="Dcard-Batch-Processing-$PROCESSING_DATE" \
    --conf spark.sql.adaptive.enabled=true \
    --conf spark.sql.adaptive.coalescePartitions.enabled=true \
    --conf spark.sql.adaptive.skewJoin.enabled=true \
    --conf spark.serializer=org.apache.spark.serializer.KryoSerializer \
    --conf spark.sql.execution.arrow.pyspark.enabled=true \
    --conf spark.sql.parquet.compression.codec=snappy \
    --conf spark.sql.shuffle.partitions=400 \
    --conf spark.dynamicAllocation.enabled=true \
    --conf spark.dynamicAllocation.minExecutors=5 \
    --conf spark.dynamicAllocation.maxExecutors=20 \
    --conf spark.dynamicAllocation.executorIdleTimeout=60s \
    --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
    --conf spark.hadoop.fs.s3a.aws.credentials.provider=org.apache.hadoop.fs.s3a.DefaultAWSCredentialsProviderChain \
    --conf spark.hadoop.fs.s3a.fast.upload=true \
    --conf spark.hadoop.fs.s3a.block.size=128M \
    --conf spark.hadoop.fs.s3a.multipart.size=104857600 \
    --conf spark.hadoop.mapreduce.fileoutputcommitter.algorithm.version=2 \
    --conf spark.speculation=true \
    --conf spark.speculation.multiplier=2 \
    --conf spark.speculation.quantile=0.75 \
    --packages io.delta:delta-core_2.12:3.0.0,com.clickhouse:clickhouse-jdbc:0.4.6 \
    $BATCH_JAR \
    "$DATA_LAKE_PATH" \
    "$BATCH_OUTPUT_PATH" \
    "$CLICKHOUSE_URL" \
    "$PROCESSING_DATE"

SPARK_EXIT_CODE=$?

if [ $SPARK_EXIT_CODE -eq 0 ]; then
    log "✅ Batch processing completed successfully for $PROCESSING_DATE"
    
    # Update batch processing metadata in ClickHouse
    log "Updating batch processing cutoff metadata..."
    
    # Connect to ClickHouse and update metadata
    clickhouse-client --host clickhouse --query="
        INSERT INTO processing_metadata (key, value, updated_at) VALUES 
        ('batch_cutoff_date', '$PROCESSING_DATE', now())
        ON DUPLICATE KEY UPDATE value='$PROCESSING_DATE', updated_at=now()
    "
    
    if [ $? -eq 0 ]; then
        log "✅ Batch processing metadata updated"
    else
        log "⚠️  Failed to update batch processing metadata"
    fi
    
    # Optional: Trigger serving layer cache refresh
    log "Triggering serving layer cache refresh..."
    curl -X POST "http://serving-layer-api:8080/api/cache/refresh" \
         -H "Content-Type: application/json" \
         -d "{\"processing_date\":\"$PROCESSING_DATE\"}" || true
    
    # Cleanup old batch views (keep last 30 days)
    log "Cleaning up old batch views..."
    CLEANUP_DATE=$(date -d "$PROCESSING_DATE - 30 days" +%Y%m%d)
    hadoop fs -rm -r -f "$BATCH_OUTPUT_PATH/cumulative_user_counts_$CLEANUP_DATE" 2>/dev/null || true
    
    log "🎉 Daily batch job completed successfully!"
    
else
    log "❌ Batch processing failed with exit code $SPARK_EXIT_CODE"
    
    # Send alert notification (if configured)
    if [ ! -z "$ALERT_WEBHOOK_URL" ]; then
        curl -X POST "$ALERT_WEBHOOK_URL" \
             -H "Content-Type: application/json" \
             -d "{\"text\":\"❌ Dcard batch processing failed for $PROCESSING_DATE\"}" || true
    fi
    
    exit $SPARK_EXIT_CODE
fi

# Generate batch job report
BATCH_REPORT="/tmp/batch_report_$PROCESSING_DATE.txt"
cat > $BATCH_REPORT << EOF
Dcard Batch Processing Report
============================
Processing Date: $PROCESSING_DATE
Completion Time: $(date)
Status: $([ $SPARK_EXIT_CODE -eq 0 ] && echo "SUCCESS" || echo "FAILED")
Spark Job Exit Code: $SPARK_EXIT_CODE

Configuration:
- Data Lake Path: $DATA_LAKE_PATH
- Batch Output Path: $BATCH_OUTPUT_PATH
- ClickHouse URL: $CLICKHOUSE_URL
- Driver Memory: $SPARK_DRIVER_MEMORY
- Executor Memory: $SPARK_EXECUTOR_MEMORY
- Number of Executors: $SPARK_NUM_EXECUTORS

$([ $SPARK_EXIT_CODE -eq 0 ] && echo "✅ All processing steps completed successfully" || echo "❌ Processing failed - check Spark logs for details")
EOF

log "📄 Batch report generated: $BATCH_REPORT"
cat $BATCH_REPORT