# Dcard Post Tracking System - Kappa Architecture

A real-time post counting system built with Kappa architecture, designed to handle millions of users and posts per day with sub-second query latency.

## 🏗️ Architecture Overview

```
Posts Events → Kafka → Flink Streaming → ClickHouse
                ↓
            S3 Backup
```

### Components

- **Kafka**: Event streaming platform for post creation/deletion events
- **Flink**: Stream processing for real-time aggregations  
- **ClickHouse**: OLAP database for serving queries
- **Prometheus + Grafana**: Monitoring and alerting
- **S3**: Long-term backup storage

## 📊 System Specifications

- **Throughput**: 10K+ posts/sec capacity
- **Latency**: <100ms end-to-end
- **Storage**: Hot/cold data separation with TTL
- **Availability**: 99.9% with replication
- **Scalability**: Horizontal scaling via partitions

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Maven 3.6+
- Java 11+
- 8GB+ RAM recommended

### 1. Start the System

```bash
# Clone and navigate to the project
git clone <repository-url>
cd dcard-interview-kappa

# Start all services
./scripts/start-system.sh
```

This will start:
- Zookeeper (coordination)
- Kafka (event streaming)  
- Schema Registry (Avro schemas)
- ClickHouse (data storage)
- Flink (stream processing)
- Prometheus (metrics)
- Grafana (dashboards)
- Kafka UI (monitoring)

### 2. Deploy the Streaming Job

```bash
# Deploy Flink streaming job
./scripts/deploy-flink-job.sh
```

### 3. Verify the System

Visit the web interfaces:

- **Flink Web UI**: http://localhost:8080
- **Kafka UI**: http://localhost:8090
- **ClickHouse**: http://localhost:8123
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

## 🔧 Configuration

### Kafka Configuration

- **Topic**: `user-posts` (512 partitions)
- **Replication Factor**: 3
- **Retention**: 7 days + S3 tiered storage
- **Compression**: LZ4

### Flink Configuration

- **Parallelism**: 512 (matches Kafka partitions)
- **Checkpointing**: Every 60s, exactly-once
- **State Backend**: RocksDB with incremental checkpoints
- **Memory**: 4GB per TaskManager

### ClickHouse Configuration

- **Engine**: ReplacingMergeTree for user counts
- **Partitioning**: By month (`toYYYYMM(date)`)
- **TTL**: 1 year for events, no TTL for aggregates
- **Compression**: LZ4

## 📈 Usage Examples

### Send Test Events

```bash
# Create a post (via Kafka producer)
docker exec -i dcard-kafka kafka-console-producer \
  --bootstrap-server localhost:9092 \
  --topic user-posts << EOF
{"user_id": 12345, "post_id": "post_001", "event_type": "POST_CREATED", "timestamp": $(date +%s000), "board_id": "tech"}
EOF
```

### Query User Post Count

```bash
# Connect to ClickHouse and query
docker exec -i dcard-clickhouse clickhouse-client --query="
SELECT post_count, last_updated 
FROM dcard.user_post_counts 
WHERE user_id = 12345
"
```

### Monitor System Health

```bash
# Check all services
docker-compose ps

# View Flink job status
docker exec dcard-flink-jobmanager flink list

# Check ClickHouse tables
docker exec dcard-clickhouse clickhouse-client --query="
SELECT table, sum(rows) as total_rows, formatReadableSize(sum(bytes)) as size
FROM system.parts 
WHERE database = 'dcard' AND active = 1
GROUP BY table
"
```

## 📊 Sample Queries

Common query patterns are provided in `clickhouse/queries/sample_queries.sql`:

```sql
-- Get user's post count
SELECT post_count FROM user_post_counts WHERE user_id = ?;

-- Top users by post count  
SELECT user_id, post_count FROM user_post_counts 
ORDER BY post_count DESC LIMIT 100;

-- Daily statistics
SELECT date, sum(post_count) as total_posts 
FROM daily_post_stats 
WHERE date >= today() - 30 
GROUP BY date;
```

## 🔄 Backup & Recovery

### Automated Backup

```bash
# Run backup (stores in /var/backups/dcard)
./backup/scripts/backup-system.sh

# With S3 upload (set AWS credentials first)
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret  
export S3_BACKUP_BUCKET=your-backup-bucket
./backup/scripts/backup-system.sh
```

### Recovery Process

1. **ClickHouse**: Restore from backup using `RESTORE DATABASE`
2. **Kafka**: Replay from S3 or use consumer group offsets
3. **Flink**: Restart job from savepoint

## 📊 Monitoring

### Key Metrics

- **Kafka**: Message throughput, consumer lag, partition health
- **Flink**: Checkpoint duration, backpressure, memory usage
- **ClickHouse**: Query performance, memory usage, data freshness

### Alerts

Pre-configured alerts for:
- High consumer lag (>100K messages)
- Failed checkpoints
- Slow queries (>5s)
- Data freshness issues (>5min delay)

### Dashboards

Import Grafana dashboards from `monitoring/grafana/dashboards/`:
- System Overview
- Kafka Metrics
- Flink Job Performance  
- ClickHouse Performance

## 🛠️ Development

### Project Structure

```
├── kafka/                 # Kafka configuration and schemas
├── flink/                 # Stream processing job
├── clickhouse/            # Database DDL and queries
├── monitoring/            # Prometheus and Grafana config
├── backup/                # Backup scripts and configuration
├── scripts/               # Utility scripts
└── docker-compose.yml     # Service orchestration
```

### Building the Flink Job

```bash
cd flink
mvn clean package -DskipTests
```

### Running Tests

```bash
# Unit tests
cd flink
mvn test

# Integration tests (requires running services)
mvn verify -Pit
```

## 🔧 Troubleshooting

### Common Issues

**Flink Job Won't Start**
```bash
# Check logs
docker-compose logs flink-jobmanager
docker-compose logs flink-taskmanager

# Verify Kafka connectivity
docker exec dcard-kafka kafka-topics --list --bootstrap-server localhost:9092
```

**ClickHouse Connection Issues**
```bash
# Test connection
docker exec dcard-clickhouse clickhouse-client --query="SELECT 1"

# Check table creation
docker exec dcard-clickhouse clickhouse-client --query="SHOW TABLES FROM dcard"
```

**High Memory Usage**
```bash
# Scale TaskManagers
docker-compose up -d --scale flink-taskmanager=4

# Adjust parallelism in flink-conf.yaml
```

### Performance Tuning

1. **Increase Parallelism**: Match your CPU cores
2. **Tune Checkpointing**: Balance frequency vs performance  
3. **Optimize ClickHouse**: Adjust `max_memory_usage` and `max_threads`
4. **Scale Kafka**: Add brokers and increase partitions

## 📚 Additional Resources

- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [Apache Flink Documentation](https://flink.apache.org/docs/stable/)
- [ClickHouse Documentation](https://clickhouse.com/docs/)
- [Kappa Architecture Guide](https://hazelcast.com/glossary/kappa-architecture/)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License.