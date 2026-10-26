# Scaling Writes
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/scaling-writes ｜ 分類：patterns

## 一句話重點
寫入擴展有四招組合：垂直擴展與選對 DB → 分片／分區 → 用 queue 吸收尖峰與 load shedding → 批次與階層式聚合。難題是 resharding 與連單一 shard 都扛不住的 hot key。

## 原文大綱（原文）
- 介紹（原文）：Scaling Writes addresses the challenge of handling high-volume write operations when a single database or single server becomes the bottleneck. 寫入量從數百增長到數百萬/秒時，個別元件會遇到 disk I/O、CPU、網路頻寬的硬上限，面試官喜歡探測這些瓶頸。
- The Challenge（原文重點）：讀端有 read replica、cache 等工具，但寫端通常困難得多；突發、高吞吐、高競爭的寫入很難設計。
- 原文列出的相關題目：YouTube Top K、Strava、Rate Limiter、Job Scheduler、Ad Click Aggregator、FB Post Search、Metrics Monitoring、Notification System、Flash Sale
- The Solution（原文）：四策略——Vertical Scaling and Database Choices / Sharding and Partitioning / Handling Bursts with Queues and Load Shedding / Batching and Hierarchical Aggregation
- 章節：Vertical Scaling and Write Optimization（Vertical Scaling、Database Choices）；Sharding and Partitioning（Horizontal Sharding、Vertical Partitioning）；Handling Bursts（Write Queues for Burst Handling、Load Shedding Strategies）；Batching and Hierarchical Aggregation（Batching、Hierarchical Aggregation）
- When to Use in Interviews：Common Interview Scenarios / When NOT to Use in Interviews
- Common Deep Dives：「How do you handle resharding when you need to add more shards?」「What happens when you have a hot key that's too popular for even a single shard?」（Split All Keys、Split Hot Keys Dynamically）
- Conclusion

## 內容（by agents）
### 1. Vertical Scaling and Write Optimization
- **Vertical Scaling**：更大機器、更快 NVMe、更多 RAM。現代單機 Postgres 可達數萬 TPS；成本線性以上、有天花板、單點。面試中先估算，常常單機就夠，別一開始就 shard。
- **Database Choices**：寫入模型決定引擎。LSM-tree（Cassandra、RocksDB、HBase、ScyllaDB）把隨機寫轉為順序寫，寫吞吐高；B-tree（Postgres/MySQL）讀友善但寫放大較高。時序 DB（TimescaleDB、InfluxDB）、append-only log（Kafka）適合事件流。其他優化：減少 index 數量、關閉不必要的同步（權衡 durability）、WAL 調校、批次 COMMIT、使用 COPY／bulk insert。

### 2. Sharding and Partitioning
- **Horizontal Sharding**：把同一張表依 shard key 切到多台。Hash sharding 均勻但範圍查詢差；range sharding 範圍查詢好但易熱點（遞增 ID／時間）。好的 shard key：高基數、分佈均勻、與主要 query pattern 對齊（避免 scatter-gather）。
- **Vertical Partitioning**：按功能／欄位拆資料（用戶資料 vs 活動記錄 vs 大 blob 各自一個 DB 或表），不同資料用最合適的儲存與擴展策略；也可把熱欄位與冷欄位分開。

### 3. Handling Bursts with Queues and Load Shedding
- **Write Queues**：Kafka／SQS 先接住寫入，consumer 以 DB 能承受的速度消化，削峰填谷。代價：寫入變非同步、最終一致，讀取暫時看不到新資料；須處理 queue 無限堆積（背壓）、消費者冪等、重試與 DLQ。
- **Load Shedding**：超載時主動丟棄／降級以保護核心：依優先級丟（廣告點擊保留、分析事件採樣）、取樣（只寫 10%）、rate limit／429、回傳可重試錯誤、合併重複更新（只保留最新值，例如位置更新）。要定義哪些寫入可丟，哪些絕不可丟（付款）。

### 4. Batching and Hierarchical Aggregation
- **Batching**：把多筆小寫入合成一筆（client 端、queue consumer、DB bulk insert），降低 per-request 開銷與 fsync 次數；代價是增加延遲與批次失敗處理（部分成功）。以「大小或時間」雙門檻 flush。
- **Hierarchical Aggregation**：先在靠近來源處聚合再往上合併——本機 counter → 區域聚合器 → 中央儲存（如 metrics agent、Ad click 的 stream aggregation、view count 計數）。把每個事件一次寫入變成每個視窗一次寫入。適合可交換／可結合的聚合（sum、count、max、HyperLogLog 等）。精確性與延遲換吞吐。

## 常見深入題（by agents）
- **如何 resharding？** 預先分更多邏輯分片（virtual shard／slot），再映射到實體節點，新增節點只搬 slot（Redis Cluster 16384 slots）；consistent hashing 減少搬動；線上遷移：雙寫 + 回填 + 切讀 + 驗證 + 停舊；或使用能自動 rebalance 的 DB（DynamoDB、Cassandra、Vitess、CockroachDB）。
- **Hot key 連單一 shard 都扛不住？**
  - **Split All Keys**：所有 key 加後綴（`key#0..N-1`）寫入隨機/輪流分散，讀時 scatter-gather 合併；簡單但讀放大且對所有 key 都付成本。
  - **Split Hot Keys Dynamically**：偵測熱 key（計數、取樣、heavy hitters），只對熱 key 啟用分裂與 salting，其餘維持單 key；需維護「哪些 key 是熱的」的元資料，並在讀端知道要聚合幾份。也可搭配本地聚合後再寫入。

## 面試怎麼用（by agents）
- 訊號：「每秒百萬事件」「點擊流」「IoT／metrics」「計數器」「尖峰搶購」「寫多讀少」。
- 步驟：先估算寫入 QPS 與資料量 → 判斷單機是否足夠 → 選 DB → shard key → 緩衝與批次 → 熱點處理。
- 不要用：寫入量小（< 數千 TPS）時別 shard；讀為瓶頸的題目看 [scaling-reads](./scaling-reads.md)；需強一致同步回應的寫入不要硬塞 async queue。
- 加分：談一致性代價（queue 後的 read-your-writes）、重複與冪等、取樣的精確度。

## 相關題目
- [top-k](../../hellointerview-breakdowns/top-k.md)
- [strava](../../hellointerview-breakdowns/strava.md)
- [distributed-rate-limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)
- [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)
- [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
- [notification-system](../../hellointerview-breakdowns/notification-system.md)
- [flash-sale](../../hellointerview-breakdowns/flash-sale.md)

## 自測問題（by agents）
1. 為什麼 LSM-tree 適合高寫入？答：把隨機寫轉為 memtable + 順序 flush/compaction，寫放大低於 B-tree 的隨機頁寫。
2. 好的 shard key 條件？答：高基數、均勻、貼合 query pattern；避免單調遞增 key 造成熱點。
3. Queue 削峰有什麼代價？答：最終一致、讀不到新資料、需處理背壓與冪等。
4. 如何處理 hot key？答：分裂 key（salting）並在讀時聚合，最好只對偵測到的熱 key 動態啟用。
5. 如何在不停機下 resharding？答：虛擬分片/slot、雙寫回填、切流量、驗證後下線舊分片。

## 參考來源
- https://www.cs.umb.edu/~poneil/lsmtree.pdf （The Log-Structured Merge-Tree）
- https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf （Dynamo）
- https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/ （Redis Cluster hash slots）
- https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
