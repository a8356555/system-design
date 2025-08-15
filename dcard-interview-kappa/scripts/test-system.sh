#!/bin/bash

# Test script for Dcard Post Tracking System
# This script generates test data and validates the system

set -e

echo "🧪 Testing Dcard Post Tracking System..."

# Configuration
KAFKA_HOST="localhost:9092"
CLICKHOUSE_HOST="localhost:8123"
NUM_USERS=1000
POSTS_PER_USER=10

# Function to generate random user ID
random_user_id() {
    echo $((RANDOM % NUM_USERS + 1))
}

# Function to generate random post ID
random_post_id() {
    echo "post_$(date +%s%N | cut -b1-13)"
}

# Function to wait and check
wait_and_check() {
    local seconds=$1
    local message=$2
    echo "⏳ Waiting ${seconds}s for $message..."
    sleep $seconds
}

# 1. Test Kafka connectivity
echo "🔗 Testing Kafka connectivity..."
if docker exec dcard-kafka kafka-topics --bootstrap-server $KAFKA_HOST --list | grep -q "user-posts"; then
    echo "✅ Kafka is accessible and topic exists"
else
    echo "❌ Kafka connectivity failed"
    exit 1
fi

# 2. Test ClickHouse connectivity
echo "🔗 Testing ClickHouse connectivity..."
if docker exec dcard-clickhouse clickhouse-client --host $CLICKHOUSE_HOST --query="SELECT 1" >/dev/null 2>&1; then
    echo "✅ ClickHouse is accessible"
else
    echo "❌ ClickHouse connectivity failed"
    exit 1
fi

# 3. Check Flink job status
echo "🌊 Checking Flink job status..."
JOB_STATUS=$(docker exec dcard-flink-jobmanager flink list -r 2>/dev/null | grep "PostCountStreamingJob" | wc -l)
if [ "$JOB_STATUS" -gt 0 ]; then
    echo "✅ Flink job is running"
else
    echo "⚠️  Flink job is not running - starting it..."
    ./scripts/deploy-flink-job.sh
    wait_and_check 30 "Flink job to start"
fi

# 4. Generate test data
echo "📊 Generating test data..."

# Create temporary file for test events
TEST_EVENTS_FILE="/tmp/dcard_test_events.json"
> $TEST_EVENTS_FILE

# Generate POST_CREATED events
for i in $(seq 1 $((NUM_USERS * POSTS_PER_USER / 2))); do
    USER_ID=$(random_user_id)
    POST_ID=$(random_post_id)
    TIMESTAMP=$(date +%s000)
    BOARD_ID="board_$((RANDOM % 10 + 1))"
    
    cat >> $TEST_EVENTS_FILE << EOF
{"user_id": $USER_ID, "post_id": "$POST_ID", "event_type": "POST_CREATED", "timestamp": $TIMESTAMP, "board_id": "$BOARD_ID"}
EOF
done

# Send events to Kafka
echo "📤 Sending $(wc -l < $TEST_EVENTS_FILE) events to Kafka..."
docker exec -i dcard-kafka kafka-console-producer \
    --bootstrap-server $KAFKA_HOST \
    --topic user-posts < $TEST_EVENTS_FILE

echo "✅ Test events sent successfully"

# 5. Wait for processing and validate results
wait_and_check 60 "stream processing to complete"

# 6. Query and validate results
echo "📋 Validating results..."

# Check total number of users with posts
TOTAL_USERS=$(docker exec dcard-clickhouse clickhouse-client --query="
    SELECT count() 
    FROM dcard.user_post_counts 
    WHERE post_count > 0
" 2>/dev/null || echo "0")

echo "📊 Users with posts: $TOTAL_USERS"

# Check total post count
TOTAL_POSTS=$(docker exec dcard-clickhouse clickhouse-client --query="
    SELECT sum(post_count) 
    FROM dcard.user_post_counts
" 2>/dev/null || echo "0")

echo "📊 Total posts: $TOTAL_POSTS"

# Check data freshness (last event processed)
LAST_UPDATE=$(docker exec dcard-clickhouse clickhouse-client --query="
    SELECT max(last_updated) 
    FROM dcard.user_post_counts
" 2>/dev/null || echo "1970-01-01 00:00:00")

echo "📊 Last update: $LAST_UPDATE"

# 7. Test individual user queries
echo "🔍 Testing individual user queries..."

# Get a random user with posts
SAMPLE_USER=$(docker exec dcard-clickhouse clickhouse-client --query="
    SELECT user_id 
    FROM dcard.user_post_counts 
    WHERE post_count > 0 
    LIMIT 1
" 2>/dev/null || echo "")

if [ ! -z "$SAMPLE_USER" ]; then
    USER_POST_COUNT=$(docker exec dcard-clickhouse clickhouse-client --query="
        SELECT post_count 
        FROM dcard.user_post_counts 
        WHERE user_id = $SAMPLE_USER
    " 2>/dev/null || echo "0")
    
    echo "📊 User $SAMPLE_USER has $USER_POST_COUNT posts"
else
    echo "⚠️  No users found with posts"
fi

# 8. Test query performance
echo "⚡ Testing query performance..."

# Time a simple query
QUERY_TIME=$(docker exec dcard-clickhouse clickhouse-client --time --query="
    SELECT user_id, post_count 
    FROM dcard.user_post_counts 
    ORDER BY post_count DESC 
    LIMIT 100
" 2>&1 | grep "Elapsed:" | awk '{print $2}' || echo "unknown")

echo "📊 Top 100 users query time: $QUERY_TIME"

# 9. Test system health endpoints
echo "🏥 Checking system health..."

# Check Flink metrics
FLINK_HEALTH=$(curl -s "http://localhost:8080/overview" | jq -r '.state // "UNKNOWN"' 2>/dev/null || echo "UNKNOWN")
echo "📊 Flink cluster state: $FLINK_HEALTH"

# Check ClickHouse system metrics
CH_QUERIES_RUNNING=$(docker exec dcard-clickhouse clickhouse-client --query="
    SELECT count() 
    FROM system.processes
" 2>/dev/null || echo "0")

echo "📊 ClickHouse running queries: $CH_QUERIES_RUNNING"

# 10. Generate test report
echo "📄 Generating test report..."

TEST_REPORT="/tmp/dcard_test_report_$(date +%Y%m%d_%H%M%S).txt"

cat > $TEST_REPORT << EOF
Dcard Post Tracking System Test Report
=====================================
Date: $(date)
Test Events Sent: $(wc -l < $TEST_EVENTS_FILE)
Processing Time: 60 seconds

Results:
- Users with posts: $TOTAL_USERS
- Total posts: $TOTAL_POSTS  
- Last update: $LAST_UPDATE
- Sample user ($SAMPLE_USER): $USER_POST_COUNT posts
- Query performance: $QUERY_TIME
- Flink state: $FLINK_HEALTH
- ClickHouse queries: $CH_QUERIES_RUNNING

Status: $( [ "$TOTAL_POSTS" -gt 0 ] && echo "✅ PASS" || echo "❌ FAIL" )
EOF

echo "📄 Test report saved: $TEST_REPORT"
cat $TEST_REPORT

# 11. Cleanup
rm -f $TEST_EVENTS_FILE

# 12. Final validation
if [ "$TOTAL_POSTS" -gt 0 ] && [ "$TOTAL_USERS" -gt 0 ]; then
    echo ""
    echo "✅ All tests passed! The system is working correctly."
    echo "🎉 Events are being processed and stored successfully."
    exit 0
else
    echo ""
    echo "❌ Tests failed! Check the logs for issues:"
    echo "   docker-compose logs flink-jobmanager"
    echo "   docker-compose logs flink-taskmanager" 
    echo "   docker-compose logs clickhouse"
    exit 1
fi