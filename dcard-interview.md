# dcard scenario

* build a system to record user's post
* the user can query their total post count in real-time
* millions of users
* millions of posts per day

## Lambda

### 1. Batch Layer (The Source of Truth)
- Purpose: Stores immutable, large-scale historical data; periodically computes accurate, comprehensive batch views.

- Storage: Distributed file system or data lake (e.g., HDFS, S3, or a columnar warehouse like ClickHouse / Apache Iceberg).

- Processing Framework: Distributed batch processing engines (e.g., Apache Spark, Flink in batch mode, Presto).

- Output: Materialized batch views/tables containing pre-aggregated results (e.g., daily user post counts).

Design Tips:

- Use partitioning by date/user to optimize scans.

- Enable reprocessing of entire history for corrections.

- Write batch outputs to append-only storage with versioning or atomic partition swaps.

### 2. Speed Layer (Real-Time Approximate Views)
- Purpose: Provides low-latency, incremental updates to complement batch data; handles recent data until batch job runs.

- Storage: Stream processing state store (e.g., RocksDB in Kafka Streams, Flink state backend, Redis), or a fast OLAP store (e.g., ClickHouse, Druid).

- Processing Framework: Real-time stream processors (e.g., Apache Kafka Streams, Apache Flink, Apache Storm).

- Output: Real-time incremental aggregates reflecting recent events (e.g., posts created in last few hours).

Design Tips:

- Keep windowed aggregations aligned with batch partitions for easy merging.

- Enable exactly-once processing semantics for consistency.

- Implement eviction or TTL for old state no longer needed after batch completes.

### 3. Serving Layer (Unified Query Layer)
- Purpose: Responds to queries by merging batch and speed layer data; ensures high throughput and low latency.

- Storage: An OLAP store capable of fast SQL queries, e.g., ClickHouse, Druid, or Presto querying data lakes.

- Query Pattern:

    ```sql
    SELECT user_id, SUM(count) FROM (
        SELECT user_id, date, count FROM batch_table WHERE date < batch_cutoff_date
        UNION ALL
        SELECT user_id, date, count FROM speed_table WHERE date >= batch_cutoff_date
    )
    GROUP BY user_id;
    Metadata: Store batch_cutoff_date or batch version info in a metadata table, updated atomically with batch job completion.
    ```

Design Tips:

- Use atomic partition swaps in batch table to avoid stale/inconsistent data.

- Dynamically read cutoff date from metadata in queries.

- Cache metadata with short TTL and invalidate on batch completion events.

### Workflow

```
Raw Data (Events)
      |
      |-----------------------------
      |                            |
Batch Ingestion               Streaming Ingestion
      |                            |
      V                            V
Batch Layer (e.g., Spark job)    Speed Layer (e.g., Flink streaming)
- Reads raw historical data      - Processes recent events in real time
- Performs full recomputation    - Computes incremental aggregates
- Writes batch views (e.g.,      - Maintains state in streaming store
  daily aggregates)              - Writes incremental results to speed store
      |                            |
      |                            |
      |                            |
      |-----------------------------
                   |
                   V
           Serving Layer (Query Engine)
- Merges batch + speed layer data on query time
- Uses metadata to determine batch cutoff
- Responds to queries with combined results
```

## Kappa

### Unified Serving Layer

- Purpose: A single pipeline and store handle both recent and historical data without separate batch and speed layers.

- Storage: Append-only log (Kafka or similar) + stream processing state store or OLAP store updated in real time.

- Serving Options:

    - Materialized Views in Stream Processor: e.g., Kafka Streams interactive queries, Flink SQL on streaming data, stateful operators maintaining aggregates.

    - OLAP Store Updated by Stream: Stream processor continuously writes aggregates or event data to an OLAP store like ClickHouse or Druid.

- Query Pattern: Query the single serving store directly, which holds all data up to now, no unions needed.

Design Tips:

- Keep your stream processors capable of exactly-once semantics to maintain correctness.

- Implement watermarking and late data handling to minimize correctness gaps.

- Enable checkpointing and state backups for fault tolerance.

### Workflow

```
Raw Data (Events)
      |
      V
Streaming Ingestion (Kafka / Pub-Sub)
      |
      V
Stream Processing (Flink / Kafka Streams / ksqlDB)
- Processes all data from stream (historical + new)
- Maintains continuously updated state or materialized views
- Writes incremental results to serving store (optional)
      |
      V
Serving Layer (Single Store / State Backend)
- Queries served directly from stream processor state or serving database
- No batch layer, no separate speed layer
- State is continuously updated and queried
```

# Question

### 1. in kappa, can kafka replay all historical message?

- no
- snapshot kafka and replay from snapshot first and then replaying kafka data after snapshot_date
- kafka now support Kafka Tiered Storage, Confluent Tiered Storage

### 2. in kappa, how to store raw historical data

- kafka tiered storage
    - kafka serves as the source of truth for historical raw data.
    - medium cost

- flush kafka data to s3
    - Data lake serves as the source of truth for historical raw data.
    - lowest cost

- OLAP + automatically cold hot seperation (be aware of ingestion rate limit of OLAP)
    - OLAP serves as the source of truth for historical raw data.
    - highest cost


| Step                                           | Description                                                                                               |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **1. Ingest raw events into Kafka**            | Kafka stores the live, ordered stream with retention policy (days to months).                             |
| **2. Periodically export Kafka to Data Lake**  | Use tools like Kafka Connect, Flink, or Spark Streaming to write compacted Parquet files in S3/GCS.       |
| **3. Stream processing consumes Kafka**        | Streaming job reads Kafka to update real-time aggregates & materialized views.                            |
| **4. OLAP queries aggregate data + data lake** | Query aggregated tables in OLAP; for deep historical or ad hoc queries, query data lake with SQL engines. |


### 3. in kappa, how to partition kafka topic?

- partition by user_id 

- use user_shard = user_id % N to prevent millions of partition

- hundreds to low-thousands partitions

### 4. when to use lambda?

- need very high data accuracy and correctness guarantees

- batch processing is complex or very resource-intensive

- correct or reprocess historical data easily

- separation of concerns in architecture

- tolerate slight query latency in exchange for accuracy


| Application Type                               | Why Lambda fits well                                                 |
| ---------------------------------------------- | -------------------------------------------------------------------- |
| Financial risk and fraud systems               | Need absolute correctness, reprocessing events, complex batch models |
| Large-scale analytics/reporting                | Heavy aggregations on petabytes of data                              |
| ML model training pipelines                    | Batch retraining on full historical data                             |
| ETL pipelines with data cleansing              | Batch jobs clean and fix historical data                             |
| Systems with event corrections or delayed data | Need reprocessing and merging corrected data                         |

### 5. When to avoid Lambda and prefer Kappa instead

- Your data pipeline is simpler, mostly append-only, and can be fully handled by streaming processing.

- You want to avoid maintaining two separate codebases and data stores (batch + speed).

- Your latency needs are very low and you want a simpler architecture.

- Your use cases do not require reprocessing or complex batch aggregations.

### 6. Why Kappa struggles with absolute correctness

- streaming assumes data flows forward and doesn’t easily handle late-arriving, corrected, or out-of-order data.

- Reprocessing or replay in Kappa is complex and costly

- state management and consistency challenges: If a bug or operator failure happens, recomputing state from partial history may be trick

- Correctness depends heavily on upstream data quality and ordering

    - If data arrives late or out of order, or needs correction, the streaming pipeline must be carefully designed to handle that (watermarks, event-time windows).

    - Even then, perfect correctness may require complex watermarking or retries that increase latency and complexity.

### 7. in lambda arch,  how to prevent consistency gap window (batch 還沒更新完成但是要 query)

- atomic swap. Record swap time metadata, then query batch / speed layer using threshold according to the recorded swap time metadata.


    ```sql
    INSERT INTO post_counts_daily_batch_staging
    SELECT * FROM post_counts_live WHERE date = '2025-08-09'

    ALTER TABLE post_counts_daily_batch
    REPLACE PARTITION '2025-08-09'
    FROM post_counts_daily_batch_staging;

    ALTER TABLE post_counts_live
    DROP PARTITION '2025-08-09';

    -- old recent_threshold is '2025-08-09'
    ALTER TABLE processing_metadata
    UPDATE value = '2025-08-10'
    WHERE key = 'recent_threshold';
    ```

    ```
    -- query
    WITH (SELECT value FROM processing_metadata WHERE key = 'recent_threshold') AS recent_threshold
    SELECT sum(count)
    FROM (
        SELECT user_id, date, count 
        FROM post_counts_daily_batch
        WHERE ...

        UNION ALL

        SELECT user_id, date, count 
        FROM post_counts_live
        WHERE date >= recent_threshold
    )
    GROUP BY user_id;
    ```

- versioned data and query filter. Record version time metadata, then query batch / speed layer using version time metadata

- double buffering (blue/green). use 2 batch table, record which table is good metadata, query from correct batch table using this metadata

### 8. Why Kappa becomes attractive at very large scale

1. Simpler pipeline — easier to scale

- One unified streaming pipeline handles all data (historical + real-time), instead of maintaining separate batch and speed layers.

- Managing and scaling a single, horizontally scalable stream processor (e.g., Flink, Kafka Streams) is operationally simpler than coordinating batch jobs + streaming jobs + merging logic.

- At massive scale, coordinating complex batch workflows (e.g., multi-hour Spark jobs) becomes fragile and expensive.

2. Better real-time freshness

- Kappa processes all data as a stream, so queries reflect up-to-the-millisecond freshness across entire dataset.

- No waiting for batch jobs to complete or managing "cutoff" timestamps for merging speed and batch views.

3. Lower data duplication and storage overhead

- Batch layer typically stores a separate copy of full historical data optimized for batch processing.

- Kappa pipelines store raw data once (e.g., in Kafka + OLAP), reducing storage duplication.

- Some OLAP systems support tiered storage so cold data moves to cheaper storage transparently.

4. Fault tolerance & reprocessing via Kafka

- Kafka’s log retention means you can replay the entire data stream if needed for fixing bugs or recalculation.

- No need to manage separate batch data snapshots and reconciliations.

5. Better integration with event-driven microservices

- Streaming pipelines often integrate nicely with event-driven architectures.

- Enables real-time analytics, alerting, and operational insights all within the same system.

But…

- Kappa requires more advanced stream processing expertise — managing state, scaling state backends, handling late/out-of-order data can be complex.

- Absolute correctness guarantees (exactly-once semantics) depend on your streaming framework and connectors.

- For some use cases, batch reprocessing remains simpler and more reliable.