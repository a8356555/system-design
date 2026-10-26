# Ad Click Aggregator
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/ad-click-aggregator ｜ 難度：hard ｜ 類別：Scaling Writes

## 一句話核心
這是一道「寫入量遠大於讀取量」的資料處理題：click 先進 Kafka/Kinesis 緩衝，由 Flink 即時按 AdId + 分鐘聚合後寫入 OLAP DB，再用 S3 + Spark 批次對帳（Lambda architecture）保證正確；idempotency 靠「Ad Placement Service 簽名的 impression ID + 寫入 stream 前先用 cache 去重」。

## 需求
**Functional（Core）**
- 使用者點擊廣告後被導向廣告主網站
- 廣告主可查詢 ad click metrics，最小粒度 1 分鐘

**Out of scope**：ad targeting、ad serving、cross device tracking、離線行銷通路整合

**Non-functional（Core）**
- 可擴展至 peak 10k clicks/sec
- 廣告主分析查詢低延遲（sub-second）
- Fault tolerant、資料準確，不能掉 click
- 盡可能 realtime（click 後越快查得到越好）
- Idempotent click tracking（同一個 click 不重複計算）

**Out of scope**：fraud/spam detection、demographic/geo profiling、conversion tracking

**規模數字**：10M active ads；peak 10k clicks/s；平均約 1k clicks/s（heuristic：peak ≈ 10x average）→ 約 100M clicks/day。

## Core Entities & API
原文未列出獨立的 Entities/API 段落，改以 System Interface 與 Data Flow 起手（適用於 data processing 題）：
- Input：使用者的 ad click 資料
- Output：給廣告主的 click metrics
- Data Flow：user 點廣告 → click 被追蹤並儲存 → user 被導向廣告主網站 → 廣告主查詢聚合後的 metrics

（補充）可用的介面形狀：`GET /click?impressionId=...&sig=...` 回 302；`GET /metrics?adId=&from=&to=&granularity=` 查 OLAP。這是我補的示意，原文只明確提到 `/click` endpoint。

## High-Level Design
元件：Ad Placement Service（黑盒，決定投放哪個廣告並附 redirect URL）、Click Processor Service、Stream（Kafka/Kinesis）、Stream Processor（Flink）、OLAP DB。

```
Browser --click--> LB --> Click Processor --(dedup cache)--> Kafka/Kinesis --> Flink --> OLAP DB <-- Advertiser query
       <--302-----                                              |
                                                                +--> S3 (raw) --> Spark (daily reconcile) --> OLAP 修正
```

### 1) Redirect 怎麼做
- **Good：Client side redirect**。ad 附帶 redirect URL，點擊時瀏覽器直接跳轉，同時平行 POST `/click`。缺點：使用者可直接拿 URL 繞過追蹤（例如瀏覽器 extension），造成數據落差。
- **Great：Server side redirect**。click 先打到我們 server，記錄後回 302 導向廣告主。確保每個 click 都被追蹤，還能在 URL 附加追蹤參數。代價：多一跳、可能拖慢體驗，server 要夠快、夠能擴展。

### 2) 廣告主查詢 metrics（演進三階）
- **Bad：同一個 DB 存 raw event 並直接 GROUP BY**（`COUNT(*)`、`COUNT(DISTINCT UserId)`）。10k/s 下 DB 成為瓶頸，查詢慢，違反低延遲 NFR。
- **Good：獨立分析 DB + Batch processing**。raw event 寫進 event DB（Cassandra：LSM tree，commit log + memtable → SSTable，寫入優化但不適合 range/aggregation），Spark 每 N 分鐘批次聚合（map-reduce：按 adId + minute 聚合）寫入 OLAP（Redshift/Snowflake/BigQuery，columnar）。Schema：`AdId | MinuteTimestamp | UniqueClicks`。
  - 缺點：資料永遠落後數分鐘；流量尖峰時下一批要處理更多資料，可能跑得比 batch interval 還久，延遲連鎖惡化。只加 queue 能吸收寫入尖峰但解不了延遲。
- **Great：Stream processing（Kafka/Kinesis + Flink）**。click processor 立刻寫入 stream，Flink 在記憶體維護 running count，用 event time（不是 processing time）+ watermark 處理亂序/late event，window 結束時 flush 到 OLAP。
  - 為什麼不用普通 Kafka consumer 記憶體計數？Mid-level 可以；但 Flink 內建 event-time windowing、watermarks、exactly-once、狀態恢復，自己做易錯。
  - 延遲槓桿：minute window 但可每幾秒 flush，當前分鐘資料先不完整，到邊界才完整（符合預期）。Spark job 不可能每幾秒跑一次。
  - 為何 OLAP 不用 TSDB（InfluxDB/TimescaleDB）：ad ID 數百萬（高 cardinality）且之後要多維度切（device、geo、campaign），OLAP 較合適；若只需單一 metric 的簡單時間範圍查詢，TSDB 也合理，要能講取捨。

## Deep Dives

### 1) 如何撐到 10k clicks/s？逐層看瓶頸
- **Click Processor**：水平擴展 + load balancer，雲端 autoscaling。
- **Stream**：Kafka/Kinesis 分散式但需配置。Kinesis 每 shard 上限 1MB/s 或 1000 records/s，要加 shard。以 **AdId 當 partition key**：同一 ad 的事件在同一 shard，stream processor 可平行讀不同 shard，彼此獨立。
- **Stream Processor**：水平擴展，每個 shard 對應一個 Flink job 聚合該 shard 的 AdIds。
- **OLAP**：Snowflake/BigQuery 自動擴展；自管如 ClickHouse 可按 **AdvertiserId** shard，讓同一廣告主的資料在同一節點（預期廣告主會一次查自己所有 active ads）。要監控查詢效能是否達 SLA。

**Hot shard 問題**：Nike 新出 LeBron 廣告，所有 click 打到同一 shard → 延遲上升甚至資料遺失。
- 解法：partition key 加隨機後綴，`AdId:0..N`，只對熱門 ad（依 ad spend 或歷史 click 量判斷）啟用。
- Flink 寫 OLAP 前剝掉後綴，用原 AdId 做 upsert + SUM，多 partition 的寫入可正確相加。替代方案：保留 sub-key 在 query time 再聚合，但前者查詢效能較好。

### 2) 如何確保不掉 click？
- Kafka 跨 broker 複製，Kinesis 跨 AZ 複製；啟用 retention（例如 7 天），Flink 掛掉重啟可從 stream 重讀。
- **Flink checkpointing**（定期把 state 寫到 S3）：對大 window（天/週）有用，但本題 window 只有 1 分鐘，最多損失一分鐘聚合，stream 有保留就能從已知 timestamp replay 重算。原文強調：面試中主動質疑「checkpoint 在這裡真的必要嗎」是展現 seniority 的方式。
- **Reconciliation（對帳）**：click 等於錢，正確性與低延遲常衝突，所以加週期性對帳。stream 尾端同時把 raw events dump 到 S3（Kafka Connect S3 Sink / Kinesis Data Firehose，不增加 Flink 負擔），每日 Spark 重新聚合，與 stream 結果比對，不一致就追根因並修正 OLAP。
- 這個「speed layer（Flink）+ batch layer（Spark）作為 source of truth」就是 **Lambda architecture**。

### 3) 如何防止重複點擊（idempotency）？
- **Bad：payload 加 userId**，用 userId + adId 去重。問題：要求使用者必須登入；而且語意錯誤——retargeting 會刻意對同一人多次展示同一廣告，我們要的是「每個 ad instance 一次 click」。去重還必須在進 stream 之前做，因為跨 window 邊界的重複在 Flink 內無法去重。
- **Great：unique impression ID**。Ad Placement Service 為每次「展示給某使用者的 ad instance」產生唯一 impression ID，點擊時帶回，當 idempotency key。
  - 去重位置：進 stream 前。查 cache，存在即重複丟棄；不存在則寫 stream，**先寫 stream 再寫 cache**（cache 失敗頂多多一筆重複，由 reconciliation 抓；掉 click 則無法恢復）。
  - 防偽造：Ad Placement 用 secret key 對 impressionId + adId 做 **HMAC 簽名**，click processor 驗簽（微秒級，無非對稱加密），避免攻擊者偽造 impression ID 或把有效簽名重放到別的 ad。
  - Cache 規模：100M/day × 16 bytes = 1.6GB，很小；用 Redis Cluster + replica + persistence（RDB/AOF）。
  - 代價：複雜度增加、cache 可能成瓶頸需擴展。

### 4) 如何保證低延遲查詢？
- 大部分已被預聚合解決（OLAP 中已是聚合後資料）。
- 大時間範圍（天/週/年）仍可能慢：在 OLAP 建更粗粒度的表（daily/weekly），夜間 cron 聚合；查詢先查粗粒度，需要時 drill down。這是用儲存空間換查詢效能，類似 cache。

## 關鍵數字與 back-of-envelope
- Peak 10k clicks/s、平均 ~1k/s、~100M clicks/day（1k × 86,400）
- Batch 例：每 5 分鐘 → 10k × 300s = 3M events/batch；每筆 ≤ ~100 bytes → ~300MB/batch（原文指出單機就能處理，Spark 是為了未來成長與好講的 MapReduce 模型）
- Kinesis shard 上限：1MB/s 或 1000 records/s
- Dedup cache：100M × 16 bytes = 1.6GB
- Stream retention 範例：7 天

## 面試官期待
- **Mid-level**（廣度 80% / 深度 20%）：理解需要預聚合，至少提出 batch 方案；被問 idempotency 或 DB 選擇時能解題。
- **Senior**（60/40）：快速帶過 HLD，把時間花在 scaling、降低 click-to-query 延遲、fault tolerance；對比 batch 與 real-time；知道 map reduce 與 Flink 運作；選幾個 deep dive 講深即可。
- **Staff+**（40/60）：清楚權衡 batch vs real-time 與各自影響，提出 fault-tolerant 方案、談 DB 選擇與儲存策略對效能/擴展的影響；主動發現問題，面試官只需聚焦不需引導；理想情況能教面試官新東西。

## 可遷移的 pattern
1. **Stream buffer + pre-aggregation**：高寫入量先進 Kafka/Kinesis 緩衝，再用 stream processor 預聚合，讀路徑只查聚合結果（適用任何 metrics/counter/leaderboard 題）。
2. **Partition key 選擇 + hot key salting**：按實體 ID shard，熱門 key 加隨機後綴分散，寫下游前剝除後綴再 upsert/SUM。
3. **Lambda 對帳**：speed layer 求快，batch layer（raw log in S3 + 定期重算）求準，兩者比對修正。
4. **Idempotency key + 簽名 + 先寫再標記**：由上游產生唯一 key、HMAC 防偽造、dedup 在進 stream 前，且「先寫持久層、後寫 cache」寧可重複不可遺失。
5. **質疑不必要的機制**（如小 window 不需 checkpoint）：依場景判斷而非背誦技術。

## 常見追問
- **為什麼不直接用 Kafka consumer 在記憶體計數？** 可行（mid-level 可接受），但亂序、watermark、exactly-once、state recovery 要自己做，Flink 現成提供。
- **Stream 重放後會不會重複計算？** 以 window 重新聚合並對 OLAP 做 upsert（覆蓋該 window 結果）較安全；（補充）原文未細述 upsert 冪等細節。
- **Cache 掛了怎麼辦？** 用 replica 接手並開啟 Redis persistence；偶發重複由 reconciliation 修正。
- **Hot ad 怎麼辦？** 對熱門 ad 的 partition key 加 `:0..N` 後綴，寫 OLAP 前剝除後綴。
- **查一年資料怎麼保持快？** 夜間 cron 建 daily/weekly 預聚合表，必要時 drill down。
