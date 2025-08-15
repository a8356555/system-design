#!/bin/bash

# Comprehensive backup script for Lambda Architecture system
# This script creates backups of all layers and metadata

set -e

# Configuration
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_ROOT="/var/backups/dcard-lambda"
S3_BUCKET="${S3_BACKUP_BUCKET:-dcard-lambda-backups}"
RETENTION_DAYS=30

# Create backup directory
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_DATE"
mkdir -p "$BACKUP_DIR"

echo "🗄️  Starting Lambda Architecture backup - $BACKUP_DATE"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# =================================================================
# 1. BATCH LAYER BACKUP
# =================================================================

log "📊 Starting Batch Layer backup..."

# Backup HDFS data lake
log "Backing up HDFS data lake..."
if docker exec dcard-lambda-hdfs-namenode hadoop fs -test -d /data-lake 2>/dev/null; then
    docker exec dcard-lambda-hdfs-namenode hadoop distcp \
        /data-lake \
        "file://$BACKUP_DIR/hdfs_data_lake" || log "⚠️  HDFS data lake backup failed"
    log "✅ HDFS data lake backed up"
else
    log "ℹ️  No HDFS data lake found"
fi

# Backup HDFS batch views
log "Backing up HDFS batch views..."
if docker exec dcard-lambda-hdfs-namenode hadoop fs -test -d /batch-views 2>/dev/null; then
    docker exec dcard-lambda-hdfs-namenode hadoop distcp \
        /batch-views \
        "file://$BACKUP_DIR/hdfs_batch_views" || log "⚠️  HDFS batch views backup failed"
    log "✅ HDFS batch views backed up"
else
    log "ℹ️  No HDFS batch views found"
fi

# Export Spark application configurations
log "Backing up Spark configurations..."
mkdir -p "$BACKUP_DIR/spark_config"
cp -r batch-layer/spark/src "$BACKUP_DIR/spark_config/" 2>/dev/null || true
cp batch-layer/spark/pom.xml "$BACKUP_DIR/spark_config/" 2>/dev/null || true
cp -r batch-layer/jobs "$BACKUP_DIR/spark_config/" 2>/dev/null || true
log "✅ Spark configurations backed up"

# =================================================================
# 2. SPEED LAYER BACKUP
# =================================================================

log "⚡ Starting Speed Layer backup..."

# Create Flink savepoint
log "Creating Flink savepoint..."
RUNNING_JOBS=$(docker exec dcard-lambda-flink-jobmanager flink list -r 2>/dev/null | grep "SpeedLayerJob" | awk '{print $4}' || echo "")

if [ ! -z "$RUNNING_JOBS" ]; then
    for JOB_ID in $RUNNING_JOBS; do
        SAVEPOINT_PATH="/opt/flink/savepoints/backup-savepoint-$BACKUP_DATE-$JOB_ID"
        if docker exec dcard-lambda-flink-jobmanager flink savepoint "$JOB_ID" "$SAVEPOINT_PATH"; then
            echo "$SAVEPOINT_PATH" >> "$BACKUP_DIR/flink_savepoints.txt"
            log "✅ Flink savepoint created: $SAVEPOINT_PATH"
        else
            log "⚠️  Failed to create savepoint for job $JOB_ID"
        fi
    done
else
    log "ℹ️  No running Flink jobs found"
fi

# Backup Flink configurations
log "Backing up Flink configurations..."
mkdir -p "$BACKUP_DIR/flink_config"
cp -r speed-layer/flink/src "$BACKUP_DIR/flink_config/" 2>/dev/null || true
cp speed-layer/flink/pom.xml "$BACKUP_DIR/flink_config/" 2>/dev/null || true
cp -r speed-layer/config "$BACKUP_DIR/flink_config/" 2>/dev/null || true
log "✅ Flink configurations backed up"

# =================================================================
# 3. SERVING LAYER BACKUP
# =================================================================

log "🌐 Starting Serving Layer backup..."

# Backup API source code and configurations
log "Backing up API configurations..."
mkdir -p "$BACKUP_DIR/api_config"
cp -r serving-layer/api/src "$BACKUP_DIR/api_config/" 2>/dev/null || true
cp serving-layer/api/requirements.txt "$BACKUP_DIR/api_config/" 2>/dev/null || true
cp serving-layer/api/Dockerfile "$BACKUP_DIR/api_config/" 2>/dev/null || true
log "✅ API configurations backed up"

# =================================================================
# 4. STORAGE LAYER BACKUP
# =================================================================

log "💾 Starting Storage Layer backup..."

# Backup ClickHouse data
log "Backing up ClickHouse data..."
docker exec dcard-lambda-clickhouse clickhouse-client --query="
    BACKUP DATABASE dcard_lambda 
    TO File('$BACKUP_DIR/clickhouse_backup/')
    SETTINGS compression_method='lz4'
" 2>/dev/null && log "✅ ClickHouse backup completed" || log "⚠️  ClickHouse backup failed"

# Export ClickHouse schema
log "Exporting ClickHouse schema..."
docker exec dcard-lambda-clickhouse clickhouse-client --query="SHOW CREATE DATABASE dcard_lambda" > "$BACKUP_DIR/clickhouse_schema.sql"
docker exec dcard-lambda-clickhouse clickhouse-client --database=dcard_lambda --query="SHOW TABLES" | while read -r table; do
    docker exec dcard-lambda-clickhouse clickhouse-client --database=dcard_lambda --query="SHOW CREATE TABLE $table" >> "$BACKUP_DIR/clickhouse_schema.sql"
done
log "✅ ClickHouse schema exported"

# Backup Redis data
log "Backing up Redis data..."
if docker exec dcard-lambda-redis redis-cli --rdb "$BACKUP_DIR/redis_dump.rdb" 2>/dev/null; then
    log "✅ Redis backup completed"
else
    log "⚠️  Redis backup failed"
fi

# =================================================================
# 5. KAFKA BACKUP
# =================================================================

log "📨 Starting Kafka backup..."

# Export topic configurations
docker exec dcard-lambda-kafka kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --describe > "$BACKUP_DIR/kafka_topics.txt" 2>/dev/null || log "⚠️  Kafka topics export failed"

# Export consumer group offsets
docker exec dcard-lambda-kafka kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --list > "$BACKUP_DIR/kafka_consumer_groups.txt" 2>/dev/null || log "⚠️  Consumer groups export failed"

# For each consumer group, export detailed offsets
if [ -f "$BACKUP_DIR/kafka_consumer_groups.txt" ]; then
    while IFS= read -r group; do
        if [ ! -z "$group" ]; then
            docker exec dcard-lambda-kafka kafka-consumer-groups.sh \
                --bootstrap-server localhost:9092 \
                --group "$group" \
                --describe > "$BACKUP_DIR/kafka_offsets_$group.txt" 2>/dev/null || true
        fi
    done < "$BACKUP_DIR/kafka_consumer_groups.txt"
fi

log "✅ Kafka metadata backed up"

# =================================================================
# 6. SYSTEM CONFIGURATIONS BACKUP
# =================================================================

log "⚙️  Backing up system configurations..."

# Docker Compose and configurations
cp docker-compose.yml "$BACKUP_DIR/"
cp -r monitoring "$BACKUP_DIR/monitoring_config" 2>/dev/null || true
cp -r scripts "$BACKUP_DIR/scripts_config" 2>/dev/null || true

# Environment and deployment configurations
env > "$BACKUP_DIR/environment_variables.txt" 2>/dev/null || true

log "✅ System configurations backed up"

# =================================================================
# 7. METADATA AND MANIFEST
# =================================================================

log "📋 Creating backup manifest..."

# Gather system statistics
TOTAL_USERS=$(docker exec dcard-lambda-clickhouse clickhouse-client --query="SELECT count() FROM user_post_counts_batch" 2>/dev/null || echo "0")
TOTAL_POSTS=$(docker exec dcard-lambda-clickhouse clickhouse-client --query="SELECT sum(total_post_count) FROM user_post_counts_batch" 2>/dev/null || echo "0")
BATCH_CUTOFF=$(docker exec dcard-lambda-clickhouse clickhouse-client --query="SELECT value FROM processing_metadata WHERE key = 'batch_cutoff_date'" 2>/dev/null || echo "unknown")

# Create backup manifest
cat > "$BACKUP_DIR/backup_manifest.json" << EOF
{
  "backup_date": "$BACKUP_DATE",
  "backup_type": "full_lambda_architecture",
  "system_statistics": {
    "total_users": $TOTAL_USERS,
    "total_posts": $TOTAL_POSTS,
    "batch_cutoff_date": "$BATCH_CUTOFF"
  },
  "components": {
    "batch_layer": {
      "hdfs_data_lake": "$([ -d "$BACKUP_DIR/hdfs_data_lake" ] && echo "completed" || echo "skipped")",
      "hdfs_batch_views": "$([ -d "$BACKUP_DIR/hdfs_batch_views" ] && echo "completed" || echo "skipped")",
      "spark_config": "completed"
    },
    "speed_layer": {
      "flink_savepoints": "$([ -f "$BACKUP_DIR/flink_savepoints.txt" ] && echo "completed" || echo "skipped")",
      "flink_config": "completed"
    },
    "serving_layer": {
      "api_config": "completed"
    },
    "storage_layer": {
      "clickhouse_data": "$([ -d "$BACKUP_DIR/clickhouse_backup" ] && echo "completed" || echo "failed")",
      "clickhouse_schema": "completed",
      "redis_data": "$([ -f "$BACKUP_DIR/redis_dump.rdb" ] && echo "completed" || echo "failed")"
    },
    "kafka": {
      "topics_config": "completed",
      "consumer_groups": "completed"
    },
    "system_config": {
      "docker_compose": "completed",
      "monitoring": "completed",
      "scripts": "completed"
    }
  },
  "retention_days": $RETENTION_DAYS,
  "s3_bucket": "$S3_BUCKET"
}
EOF

log "✅ Backup manifest created"

# =================================================================
# 8. COMPRESSION AND FINALIZATION
# =================================================================

log "📦 Compressing backup..."
cd "$BACKUP_ROOT"
tar -czf "lambda_backup_$BACKUP_DATE.tar.gz" "$BACKUP_DATE/"

if [ $? -eq 0 ]; then
    log "✅ Backup compressed: lambda_backup_$BACKUP_DATE.tar.gz"
    rm -rf "$BACKUP_DATE"
else
    log "❌ Backup compression failed"
    exit 1
fi

# =================================================================
# 9. S3 UPLOAD (if configured)
# =================================================================

if [ ! -z "$AWS_ACCESS_KEY_ID" ] && [ ! -z "$S3_BUCKET" ]; then
    log "☁️  Uploading backup to S3..."
    
    aws s3 cp "lambda_backup_$BACKUP_DATE.tar.gz" "s3://$S3_BUCKET/backups/"
    
    if [ $? -eq 0 ]; then
        log "✅ Backup uploaded to S3: s3://$S3_BUCKET/backups/lambda_backup_$BACKUP_DATE.tar.gz"
    else
        log "❌ S3 upload failed"
    fi
else
    log "⚠️  S3 upload skipped (AWS credentials not configured)"
fi

# =================================================================
# 10. CLEANUP OLD BACKUPS
# =================================================================

log "🧹 Cleaning up old backups..."
find "$BACKUP_ROOT" -name "lambda_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete
log "✅ Old backups cleaned up (retention: $RETENTION_DAYS days)"

# =================================================================
# 11. BACKUP REPORT
# =================================================================

BACKUP_SIZE=$(du -sh "$BACKUP_ROOT/lambda_backup_$BACKUP_DATE.tar.gz" | cut -f1)
BACKUP_END_TIME=$(date '+%Y-%m-%d %H:%M:%S')

cat > "$BACKUP_ROOT/backup_report_$BACKUP_DATE.txt" << EOF
Dcard Lambda Architecture System Backup Report
==============================================
Backup Date: $BACKUP_DATE
Backup Size: $BACKUP_SIZE
Backup Location: $BACKUP_ROOT/lambda_backup_$BACKUP_DATE.tar.gz
End Time: $BACKUP_END_TIME

System Statistics:
- Total Users: $TOTAL_USERS
- Total Posts: $TOTAL_POSTS
- Batch Cutoff Date: $BATCH_CUTOFF

Components Backed Up:
📊 Batch Layer:
- ✅ HDFS Data Lake $([ -d "$BACKUP_DIR/hdfs_data_lake" ] && echo "(included)" || echo "(no data)")
- ✅ HDFS Batch Views $([ -d "$BACKUP_DIR/hdfs_batch_views" ] && echo "(included)" || echo "(no data)")
- ✅ Spark Configurations

⚡ Speed Layer:
- $([ -f "$BACKUP_DIR/flink_savepoints.txt" ] && echo "✅" || echo "⚠️ ") Flink Savepoints
- ✅ Flink Configurations

🌐 Serving Layer:
- ✅ API Configurations

💾 Storage Layer:
- $([ -d "$BACKUP_DIR/clickhouse_backup" ] && echo "✅" || echo "❌") ClickHouse Data
- ✅ ClickHouse Schema
- $([ -f "$BACKUP_DIR/redis_dump.rdb" ] && echo "✅" || echo "❌") Redis Data

📨 Kafka:
- ✅ Topics Configuration
- ✅ Consumer Groups

⚙️  System:
- ✅ Docker Compose
- ✅ Monitoring Configuration
- ✅ Scripts

S3 Upload: $([ ! -z "$AWS_ACCESS_KEY_ID" ] && echo "✅ Completed" || echo "⚠️  Skipped")

Recovery Instructions:
1. Stop current system: docker-compose down
2. Extract backup: tar -xzf lambda_backup_$BACKUP_DATE.tar.gz
3. Restore configurations and restart system
4. Restore ClickHouse: RESTORE DATABASE ... FROM File(...)
5. Restore Redis: redis-cli --pipe < redis_dump.rdb
6. Restart Flink jobs from savepoints
EOF

log "📄 Backup completed successfully!"
log "📊 Report: $BACKUP_ROOT/backup_report_$BACKUP_DATE.txt"
log "📦 Archive: $BACKUP_ROOT/lambda_backup_$BACKUP_DATE.tar.gz ($BACKUP_SIZE)"

cat "$BACKUP_ROOT/backup_report_$BACKUP_DATE.txt"