# TimeSeries Tiered Storage Journey: Kafka/Flink Streams to Native Cassandra Cold Reads
> 原文：https://netflixtechblog.com/timeseries-tiered-storage-journey-kafka-flink-streams-to-native-cassandra-cold-reads-e59d597c9d60（作者貼文附的連結卡為 medium 版同一篇：https://netflixtechblog.medium.com/timeseries-tiered-storage-journey-kafka-flink-streams-to-native-cassandra-cold-reads-e59d597c9d60，已確認是同一篇文章；原站 403、Wayback 未存檔，內容仍取自轉載站）｜ Netflix（作者 Oleksii Tkachuk, Rajiv Shringi, Chris Lohfink, Abe Ratnofsky, Kartik Sathyanarayanan） / 日期以轉載站標示為 2026-10-14（早於貼文日期，可能是轉載日，未確認） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/Db5xcCCDnzY（2026-08-11）

> 取得方式備註：netflixtechblog 直連未讀，原文內容來自轉載站 noise.getoto.net 的全文整理與搜尋摘要；細節以轉載內容為準。

## 一句話重點
Netflix 把「歷史 timeseries 資料不可變」這個性質用到底：先用 Kafka + Flink + S3 另建冷層，後來改成讓 Cassandra 自己用 S3 backup 當 cold tier，省掉整套獨立 streaming infra，冷資料規模 15+ PB。

## 作者的解讀（貼文重點）
- 熱/冷資料不該用同樣方式存：recent data 要毫秒級讀取，historical 只需便宜存放；一律放 SSD 等於用 SSD 價格存沒人碰的資料。
- 第一版方案：Kafka + Flink pipeline 把 cold data 從 Cassandra 搬到 S3，加自訂 read layer，P50 約 150ms、P99 約 500ms；功能沒問題，但要維護整套獨立 infrastructure。
- 核心 insight：歷史 timeseries 永遠不變，Cassandra 為 mutable data 設計的機制（compaction、read repair、speculative retry）在資料凍結後全是純 overhead。
- 作者說整個過程「幾乎全部繞著 immutability 轉」。

## 原文重點
### 背景 / 規模
- TimeSeries Abstraction 的資料集達 multiple petabytes；全放 hot storage（為低毫秒延遲調校）成本過高。
- 需求：最近資料留在快儲存、舊的少讀資料移到便宜儲存，同時 API 不變。
- 張力：retention 需求成長 vs 成本；多數 query 打近期事件，但歷史需可供偶爾稽核；hot node 儲存密度高使 scaling、部署、cluster 穩定性變難。

### 方案 1：Kafka / Flink 串流
- 資料同時寫進 Cassandra（hot）與 S3（經 Flink）。
- TimeSeries ID 做 hash partition 成 bucket 以平行化；Flink 依 event hour 把事件批次寫成 Parquet。
- 每日 compaction job 把小檔合成每 namespace 的 daily Parquet。
- Query planner 對 hot/cold 兩層 fan-out 再合併結果。
- Parquet 優化：row group 4-8 MB 以支援 range read；事件依時間排序避免全掃；Bloom filter 快取在 EVCache 做 skip。
- 結果：P50 約 150ms、P99 約 500ms；冷層全球最高約 1,250 reads/s。
- 缺點：串流基礎設施貴、額外資料傳輸成本、維運負擔。

### 方案 2：Cassandra 原生 cold tier
- 重用既有給 DR 用的 Cassandra S3 backup。
- ReadOnlyCompactionStrategy (ROCS)：對 immutable time slice，SSTable 對齊 token range、消除重疊，單一 partition key 不再跨多檔，各層 tail latency 都改善。
- 用 Cassandra 4.1 的 pluggable Memtable（Backup Memtable）把 cold table 的讀取直接導向 S3：index/metadata（不含大的 Data.db）一次下載到本地；跨 request / SSTable / chunk 平行讀 S3；共用 cache 去重與 prefetch；state machine 處理 retry、backoff、partial download。
- 可選擇另起一個讀 hot cluster backup 的獨立 cold-tier Cassandra cluster；Virtual Tables 用來驗證 compaction 完成與 backup 完整性。

### 取捨
- S3 讀比本地讀更吃 CPU，用較便宜硬體的獨立 cold cluster 化解。
- 必須先有 immutability（用 time slice 強制）。
- 對 immutable 資料關閉 read repair 與 speculative retry。
- 用較大的 compression chunk 減少 S3 呼叫次數。

### 結果
- 方案 2 比方案 1 的 p90 改善約 30%，p99 低於約 500ms；每 region 達「thousands of reads per second」。
- 冷層超過 15 PB 壓縮資料；受影響 cluster 的磁碟使用率從 80% 降到 7%（rollout 期間）。
- 省掉獨立 streaming infra、降低資料傳輸成本、架構更簡單。

## 面試怎麼用
- Hot/cold tiering 題（metrics、log、timeseries、order history）：論點是「先確認資料是否 immutable，再決定要不要為冷資料另建 pipeline」。
- 可比較兩種做法：dual-write 串流到 object store（彈性大、維運重）vs 讓原儲存引擎自己支援冷讀（重用 backup、少一套系統）。
- 具體可講的優化：time-sorted Parquet + 小 row group + Bloom filter；token-range 對齊的 compaction；關掉 mutable 才需要的機制。
- 延遲數字（P50 約 150ms / P99 約 500ms）可當冷層合理 SLO 的參照。
- （補充）被問「為什麼不直接用 TTL 刪掉」時，答案是稽核與偶發歷史查詢需求。

## 相關筆記
- [Time series databases](../../hellointerview-learn/deep-dives/time-series-databases.md)
- [Cassandra](../../hellointerview-learn/deep-dives/cassandra.md)
- [Kafka](../../hellointerview-learn/deep-dives/kafka.md)
- [Flink](../../hellointerview-learn/deep-dives/flink.md)
- [Metrics monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
