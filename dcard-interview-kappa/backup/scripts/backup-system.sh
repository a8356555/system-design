#!/bin/bash

# Backup script for Dcard Post Tracking System
# This script creates backups of ClickHouse data and Kafka topics

set -e

# Configuration
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_ROOT="/var/backups/dcard"
S3_BUCKET="${S3_BACKUP_BUCKET:-dcard-backups}"
RETENTION_DAYS=30

# Create backup directory
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_DATE"
mkdir -p "$BACKUP_DIR"

echo "🗄️  Starting backup process - $BACKUP_DATE"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 1. Backup ClickHouse data
log "Starting ClickHouse backup..."

# Create ClickHouse backup using native BACKUP command
docker exec dcard-clickhouse clickhouse-client --query="
    BACKUP DATABASE dcard 
    TO File('$BACKUP_DIR/clickhouse_backup/')
    SETTINGS compression_method='lz4'
"

if [ $? -eq 0 ]; then
    log "✅ ClickHouse backup completed"
else
    log "❌ ClickHouse backup failed"
    exit 1
fi

# 2. Export Kafka topics metadata and recent data
log "Starting Kafka metadata backup..."

# Export topic configurations
docker exec dcard-kafka kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --describe > "$BACKUP_DIR/kafka_topics.txt"

# Export consumer group offsets
docker exec dcard-kafka kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --list > "$BACKUP_DIR/kafka_consumer_groups.txt"

# For each consumer group, export offsets
while IFS= read -r group; do
    if [ ! -z "$group" ]; then
        docker exec dcard-kafka kafka-consumer-groups.sh \
            --bootstrap-server localhost:9092 \
            --group "$group" \
            --describe > "$BACKUP_DIR/kafka_offsets_$group.txt"
    fi
done < "$BACKUP_DIR/kafka_consumer_groups.txt"

log "✅ Kafka metadata backup completed"

# 3. Create Flink savepoint
log "Creating Flink savepoint..."

# Get running job ID
JOB_ID=$(docker exec dcard-flink-jobmanager flink list -r | grep "PostCountStreamingJob" | awk '{print $4}' | head -1)

if [ ! -z "$JOB_ID" ]; then
    SAVEPOINT_PATH="/opt/flink/savepoints/savepoint-$BACKUP_DATE"
    docker exec dcard-flink-jobmanager flink savepoint "$JOB_ID" "$SAVEPOINT_PATH"
    
    if [ $? -eq 0 ]; then
        log "✅ Flink savepoint created: $SAVEPOINT_PATH"
        echo "$SAVEPOINT_PATH" > "$BACKUP_DIR/flink_savepoint_path.txt"
    else
        log "⚠️  Failed to create Flink savepoint"
    fi
else
    log "⚠️  No running Flink job found"
fi

# 4. System metadata backup
log "Creating system metadata backup..."

# Docker Compose configuration
cp docker-compose.yml "$BACKUP_DIR/"

# Configuration files
cp -r kafka/config "$BACKUP_DIR/kafka_config"
cp -r clickhouse/ddl "$BACKUP_DIR/clickhouse_ddl"
cp -r monitoring "$BACKUP_DIR/monitoring_config"

# Create backup manifest
cat > "$BACKUP_DIR/backup_manifest.json" << EOF
{
  "backup_date": "$BACKUP_DATE",
  "backup_type": "full",
  "components": {
    "clickhouse": {
      "status": "completed",
      "path": "clickhouse_backup/",
      "compression": "lz4"
    },
    "kafka_metadata": {
      "status": "completed",
      "files": ["kafka_topics.txt", "kafka_consumer_groups.txt"]
    },
    "flink_savepoint": {
      "status": "$([ -f "$BACKUP_DIR/flink_savepoint_path.txt" ] && echo "completed" || echo "skipped")",
      "path": "$([ -f "$BACKUP_DIR/flink_savepoint_path.txt" ] && cat "$BACKUP_DIR/flink_savepoint_path.txt" || echo "none")"
    },
    "system_config": {
      "status": "completed",
      "files": ["docker-compose.yml", "kafka_config/", "clickhouse_ddl/", "monitoring_config/"]
    }
  },
  "retention_days": $RETENTION_DAYS
}
EOF

log "✅ System metadata backup completed"

# 5. Compress backup
log "Compressing backup..."
cd "$BACKUP_ROOT"
tar -czf "dcard_backup_$BACKUP_DATE.tar.gz" "$BACKUP_DATE/"

if [ $? -eq 0 ]; then
    log "✅ Backup compressed: dcard_backup_$BACKUP_DATE.tar.gz"
    rm -rf "$BACKUP_DATE"
else
    log "❌ Backup compression failed"
    exit 1
fi

# 6. Upload to S3 (if configured)
if [ ! -z "$AWS_ACCESS_KEY_ID" ] && [ ! -z "$S3_BUCKET" ]; then
    log "Uploading backup to S3..."
    
    aws s3 cp "dcard_backup_$BACKUP_DATE.tar.gz" "s3://$S3_BUCKET/backups/"
    
    if [ $? -eq 0 ]; then
        log "✅ Backup uploaded to S3: s3://$S3_BUCKET/backups/dcard_backup_$BACKUP_DATE.tar.gz"
    else
        log "❌ S3 upload failed"
    fi
else
    log "⚠️  S3 upload skipped (AWS credentials not configured)"
fi

# 7. Cleanup old backups
log "Cleaning up old backups..."
find "$BACKUP_ROOT" -name "dcard_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete
log "✅ Old backups cleaned up (retention: $RETENTION_DAYS days)"

# 8. Generate backup report
BACKUP_SIZE=$(du -sh "$BACKUP_ROOT/dcard_backup_$BACKUP_DATE.tar.gz" | cut -f1)
BACKUP_END_TIME=$(date '+%Y-%m-%d %H:%M:%S')

cat > "$BACKUP_ROOT/backup_report_$BACKUP_DATE.txt" << EOF
Dcard Post Tracking System Backup Report
========================================
Backup Date: $BACKUP_DATE
Backup Size: $BACKUP_SIZE
Backup Location: $BACKUP_ROOT/dcard_backup_$BACKUP_DATE.tar.gz
Start Time: $(date '+%Y-%m-%d %H:%M:%S')
End Time: $BACKUP_END_TIME

Components Backed Up:
- ✅ ClickHouse database (dcard)
- ✅ Kafka topics metadata
- ✅ Kafka consumer group offsets
- $([ -f "$BACKUP_DIR/flink_savepoint_path.txt" ] && echo "✅" || echo "⚠️ ") Flink savepoint
- ✅ System configurations
- ✅ Docker Compose setup

S3 Upload: $([ ! -z "$AWS_ACCESS_KEY_ID" ] && echo "✅ Completed" || echo "⚠️  Skipped")
EOF

log "📊 Backup completed successfully!"
log "📄 Report: $BACKUP_ROOT/backup_report_$BACKUP_DATE.txt"
log "📦 Archive: $BACKUP_ROOT/dcard_backup_$BACKUP_DATE.tar.gz ($BACKUP_SIZE)"