package com.dcard.lambda.batch;

import org.apache.spark.sql.*;
import org.apache.spark.sql.types.*;
import static org.apache.spark.sql.functions.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Batch Layer Processing Job for Dcard Lambda Architecture
 * 
 * This job processes historical post data stored in the data lake and computes
 * accurate, comprehensive batch views for user post counts.
 */
public class BatchProcessingJob {
    
    private static final Logger logger = LoggerFactory.getLogger(BatchProcessingJob.class);
    
    private final SparkSession spark;
    private final String dataLakePath;
    private final String batchOutputPath;
    private final String clickHouseUrl;
    
    public BatchProcessingJob(String dataLakePath, String batchOutputPath, String clickHouseUrl) {
        this.dataLakePath = dataLakePath;
        this.batchOutputPath = batchOutputPath;
        this.clickHouseUrl = clickHouseUrl;
        
        // Initialize Spark with Delta Lake support
        this.spark = SparkSession.builder()
            .appName("Dcard-Batch-Processing")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.sql.adaptive.enabled", "true")
            .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
            .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
            .getOrCreate();
            
        spark.sparkContext().setLogLevel("WARN");
    }
    
    public static void main(String[] args) {
        if (args.length < 3) {
            System.err.println("Usage: BatchProcessingJob <dataLakePath> <batchOutputPath> <clickHouseUrl> [processingDate]");
            System.exit(1);
        }
        
        String dataLakePath = args[0];
        String batchOutputPath = args[1]; 
        String clickHouseUrl = args[2];
        String processingDate = args.length > 3 ? args[3] : getCurrentDate();
        
        BatchProcessingJob job = new BatchProcessingJob(dataLakePath, batchOutputPath, clickHouseUrl);
        
        try {
            logger.info("Starting batch processing for date: {}", processingDate);
            job.processBatchData(processingDate);
            logger.info("Batch processing completed successfully");
        } catch (Exception e) {
            logger.error("Batch processing failed", e);
            System.exit(1);
        } finally {
            job.spark.stop();
        }
    }
    
    /**
     * Main batch processing logic
     */
    public void processBatchData(String processingDate) {
        logger.info("Processing batch data for date: {}", processingDate);
        
        // 1. Read raw events from data lake
        Dataset<Row> rawEvents = readRawEvents(processingDate);
        
        // 2. Clean and validate data
        Dataset<Row> cleanEvents = cleanAndValidateEvents(rawEvents);
        
        // 3. Compute batch views
        Dataset<Row> dailyUserCounts = computeDailyUserPostCounts(cleanEvents, processingDate);
        Dataset<Row> cumulativeUserCounts = computeCumulativeUserPostCounts(processingDate);
        Dataset<Row> boardStatistics = computeBoardStatistics(cleanEvents, processingDate);
        
        // 4. Write batch views to storage
        writeBatchViews(dailyUserCounts, cumulativeUserCounts, boardStatistics, processingDate);
        
        // 5. Update metadata
        updateBatchMetadata(processingDate);
        
        logger.info("Batch processing completed for date: {}", processingDate);
    }
    
    /**
     * Read raw events from data lake (partitioned by date)
     */
    private Dataset<Row> readRawEvents(String processingDate) {
        logger.info("Reading raw events for date: {}", processingDate);
        
        String eventPath = dataLakePath + "/events/date=" + processingDate;
        
        StructType eventSchema = new StructType()
            .add("user_id", DataTypes.LongType, false)
            .add("post_id", DataTypes.StringType, false)
            .add("event_type", DataTypes.StringType, false)
            .add("timestamp", DataTypes.TimestampType, false)
            .add("board_id", DataTypes.StringType, true)
            .add("metadata", DataTypes.StringType, true);
            
        Dataset<Row> events = spark.read()
            .format("delta")
            .schema(eventSchema)
            .load(eventPath);
            
        logger.info("Read {} events from {}", events.count(), eventPath);
        return events;
    }
    
    /**
     * Clean and validate events data
     */
    private Dataset<Row> cleanAndValidateEvents(Dataset<Row> rawEvents) {
        logger.info("Cleaning and validating events");
        
        Dataset<Row> cleanEvents = rawEvents
            // Remove null or invalid user_ids
            .filter(col("user_id").isNotNull().and(col("user_id").gt(0)))
            // Remove null or empty post_ids
            .filter(col("post_id").isNotNull().and(col("post_id").notEqual("")))
            // Only process valid event types
            .filter(col("event_type").isin("POST_CREATED", "POST_DELETED"))
            // Remove duplicate events (same user_id, post_id, event_type, timestamp)
            .dropDuplicates("user_id", "post_id", "event_type", "timestamp")
            // Add derived columns
            .withColumn("date", to_date(col("timestamp")))
            .withColumn("hour", hour(col("timestamp")))
            .withColumn("event_value", 
                when(col("event_type").equalTo("POST_CREATED"), 1)
                .when(col("event_type").equalTo("POST_DELETED"), -1)
                .otherwise(0));
                
        long originalCount = rawEvents.count();
        long cleanCount = cleanEvents.count();
        logger.info("Cleaned events: {} -> {} (removed {} invalid events)", 
                   originalCount, cleanCount, originalCount - cleanCount);
                   
        return cleanEvents;
    }
    
    /**
     * Compute daily user post counts
     */
    private Dataset<Row> computeDailyUserPostCounts(Dataset<Row> events, String processingDate) {
        logger.info("Computing daily user post counts for {}", processingDate);
        
        Dataset<Row> dailyCounts = events
            .groupBy("user_id", "date")
            .agg(
                sum("event_value").alias("daily_post_delta"),
                count("*").alias("daily_event_count"),
                max("timestamp").alias("last_event_timestamp")
            )
            .filter(col("date").equalTo(lit(processingDate)));
            
        logger.info("Computed daily counts for {} users", dailyCounts.count());
        return dailyCounts;
    }
    
    /**
     * Compute cumulative user post counts (including historical data)
     */
    private Dataset<Row> computeCumulativeUserPostCounts(String processingDate) {
        logger.info("Computing cumulative user post counts up to {}", processingDate);
        
        // Read all historical events up to processing date
        Dataset<Row> historicalEvents = spark.read()
            .format("delta")
            .load(dataLakePath + "/events")
            .filter(col("date").leq(lit(processingDate)));
            
        Dataset<Row> cumulativeCounts = historicalEvents
            .filter(col("event_type").isin("POST_CREATED", "POST_DELETED"))
            .withColumn("event_value", 
                when(col("event_type").equalTo("POST_CREATED"), 1)
                .when(col("event_type").equalTo("POST_DELETED"), -1)
                .otherwise(0))
            .groupBy("user_id")
            .agg(
                sum("event_value").alias("total_post_count"),
                count("*").alias("total_event_count"),
                max("timestamp").alias("last_updated"),
                min("timestamp").alias("first_event_timestamp")
            )
            // Ensure post count is not negative
            .withColumn("total_post_count", greatest(col("total_post_count"), lit(0)))
            .withColumn("processing_date", lit(processingDate));
            
        logger.info("Computed cumulative counts for {} users", cumulativeCounts.count());
        return cumulativeCounts;
    }
    
    /**
     * Compute board-level statistics
     */
    private Dataset<Row> computeBoardStatistics(Dataset<Row> events, String processingDate) {
        logger.info("Computing board statistics for {}", processingDate);
        
        Dataset<Row> boardStats = events
            .filter(col("event_type").equalTo("POST_CREATED"))
            .groupBy("board_id", "date")
            .agg(
                count("*").alias("posts_created"),
                countDistinct("user_id").alias("active_users"),
                countDistinct("post_id").alias("unique_posts")
            )
            .withColumn("avg_posts_per_user", 
                round(col("posts_created").divide(col("active_users")), 2))
            .filter(col("date").equalTo(lit(processingDate)));
            
        logger.info("Computed board statistics for {} boards", boardStats.count());
        return boardStats;
    }
    
    /**
     * Write batch views to storage (Delta Lake + ClickHouse)
     */
    private void writeBatchViews(Dataset<Row> dailyCounts, Dataset<Row> cumulativeCounts, 
                                Dataset<Row> boardStats, String processingDate) {
        logger.info("Writing batch views for {}", processingDate);
        
        // Write to Delta Lake (for batch layer storage)
        String batchDate = processingDate.replace("-", "");
        
        // Daily user counts
        dailyCounts.coalesce(10)
            .write()
            .format("delta")
            .mode(SaveMode.Overwrite)
            .option("replaceWhere", "date = '" + processingDate + "'")
            .save(batchOutputPath + "/daily_user_counts");
            
        // Cumulative user counts 
        cumulativeCounts.coalesce(50)
            .write()
            .format("delta") 
            .mode(SaveMode.Overwrite)
            .save(batchOutputPath + "/cumulative_user_counts_" + batchDate);
            
        // Board statistics
        boardStats.coalesce(1)
            .write()
            .format("delta")
            .mode(SaveMode.Overwrite)
            .option("replaceWhere", "date = '" + processingDate + "'")
            .save(batchOutputPath + "/board_statistics");
            
        // Write to ClickHouse (for serving layer)
        writeToClickHouse(cumulativeCounts, "user_post_counts_batch", processingDate);
        writeToClickHouse(boardStats, "board_statistics_batch", processingDate);
        
        logger.info("Batch views written successfully");
    }
    
    /**
     * Write data to ClickHouse
     */
    private void writeToClickHouse(Dataset<Row> data, String tableName, String processingDate) {
        try {
            logger.info("Writing {} rows to ClickHouse table: {}", data.count(), tableName);
            
            data.write()
                .format("jdbc")
                .option("url", clickHouseUrl)
                .option("dbtable", tableName)
                .option("user", "default")
                .option("driver", "com.clickhouse.jdbc.ClickHouseDriver")
                .option("batchsize", "10000")
                .option("isolationLevel", "NONE")
                .mode(SaveMode.Append)
                .save();
                
        } catch (Exception e) {
            logger.error("Failed to write to ClickHouse table: {}", tableName, e);
            throw e;
        }
    }
    
    /**
     * Update batch processing metadata
     */
    private void updateBatchMetadata(String processingDate) {
        logger.info("Updating batch metadata for {}", processingDate);
        
        Dataset<Row> metadata = spark.createDataFrame(
            java.util.Arrays.asList(
                RowFactory.create(processingDate, java.sql.Timestamp.valueOf(java.time.LocalDateTime.now()), "SUCCESS")
            ),
            new StructType()
                .add("processing_date", DataTypes.StringType)
                .add("completion_time", DataTypes.TimestampType) 
                .add("status", DataTypes.StringType)
        );
        
        metadata.write()
            .format("delta")
            .mode(SaveMode.Append)
            .save(batchOutputPath + "/processing_metadata");
    }
    
    /**
     * Get current date in YYYY-MM-DD format
     */
    private static String getCurrentDate() {
        return java.time.LocalDate.now().toString();
    }
}