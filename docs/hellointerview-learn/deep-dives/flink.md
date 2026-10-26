# Flink
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/flink ｜ 分類：deep-dives

## 一句話重點
Flink 是有狀態（stateful）串流處理引擎：用 keyed state + watermark/window + checkpoint 解決「狀態遺失、擴縮容 re-shard、亂序/遲到資料」三大難題；但先問「真的需要即時嗎」，很多問題用 batch（Spark）就夠。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：許多系統設計題需要串流處理，但串流既難又貴，許多看似串流的問題其實可化為 batch（Spark / Hadoop）。先問「我真的需要即時延遲嗎？」。最簡單例子是從 Kafka 讀 click、做無狀態轉換、寫入 DB；一旦加入「每個 user 最近 5 分鐘 click 數」就引入 state，產生三個問題：(1) 服務 crash 後 state 遺失，重讀整個 Kafka topic 又慢又貴；(2) 擴容時 state 重新分配是複雜且多故障情境的過程；(3) 事件亂序或遲到影響計數準確性。Flink 解決這些問題。文章從「如何使用」與「底層如何運作」兩個角度說明。

章節標題（原文）：
- Basic Concepts：Sources/Sinks / Streams / Operators / State / Watermarks / Windows
- Basic Use：Defining a Job / Submitting a Job / Sample Jobs（Basic Dashboard Using Redis、Fraud Detection System）
- How Flink Works：Cluster Architecture（Job Manager and Task Managers、Task Slots and Parallelism）/ State Management（State Backends、Checkpointing and Exactly-Once Processing）
- In Your Interview：Using Flink / Lessons from Flink
- Conclusion / References

## 內容（by agents）
### Basic Concepts（by agents）
- **Sources/Sinks**：Source 讀 Kafka/Kinesis/檔案/CDC；Sink 寫 Kafka/JDBC/ES/Redis/S3。exactly-once 端到端需要 source 可重放（offset）＋ sink 支援 idempotent 或 two-phase commit。
- **Streams**：無界（unbounded）事件序列，DataStream API（亦有 Table/SQL API，batch 視為有界 stream）。
- **Operators**：map/filter/flatMap（無狀態）、keyBy（依 key hash 重分區 shuffle）、window、join、process function（可用 timer 與 state）。
- **State**：keyed state（ValueState、ListState、MapState）綁定在 key 上，隨 key 分區分佈；operator state 用於 source offset 等。這就是「每 user 5 分鐘計數」的存放處。
- **Watermarks**：以 event time 推進的「時間進度」宣告：watermark(t) 表示「t 之前的事件應該都到了」；通常 = 最大 event time − 允許亂序延遲。決定何時關閉 window。遲到資料可 allowedLateness 或送 side output。
- **Windows**：tumbling（固定不重疊）、sliding（滑動，重疊）、session（以 inactivity gap 切）、global。event time vs processing time 取捨：event time 正確但需 watermark；processing time 簡單但結果不可重現。

### Basic Use（by agents）
- **Defining a Job**：以 Java/Scala/Python/SQL 寫 dataflow DAG：source → keyBy → window/process → sink。
- **Submitting a Job**：打包 JAR 提交到 cluster（session / application mode，K8s operator、YARN、managed 如 AWS Managed Flink、Confluent）；可從 savepoint 升級/重啟。
- **Sample: Basic Dashboard Using Redis**：Kafka click → keyBy(page) → 1 分鐘 tumbling window count → sink 寫 Redis，前端讀 Redis。見 [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)、[top-k](../../hellointerview-breakdowns/top-k.md)。
- **Sample: Fraud Detection**：keyBy(card) + state 存最近交易 + timer；規則（短時間多地點刷卡）或呼叫模型打分，異常寫入 alert topic。重點：低延遲 + 有狀態 + 事件時間。見 [payment-system](../../hellointerview-breakdowns/payment-system.md)。

### How Flink Works（by agents）
- **Cluster Architecture**：JobManager（調度、協調 checkpoint、故障恢復；可 HA，用 ZooKeeper 或 K8s 做 leader election）＋ 多個 TaskManager（執行 task）。
- **Task Slots and Parallelism**：每個 TaskManager 有若干 slot（資源切分單位）；operator parallelism = 並行 subtask 數；keyBy 後同一 key 一定在同一 subtask。parallelism 上限受 key group 數（max parallelism，預設 128 起）限制，影響 rescale。Source parallelism 不應超過 Kafka partition 數。
- **State Backends**：HashMapStateBackend（state 在 JVM heap，快但受記憶體限制）、EmbeddedRocksDB（本機 LSM on disk，容量大、支援 incremental checkpoint，但每次存取要序列化，較慢）。
- **Checkpointing and Exactly-Once**：JobManager 定期注入 barrier（Chandy-Lamport 變體）隨資料流傳遞；operator 收到 barrier 就對 state 做 snapshot 寫到 durable storage（S3/HDFS）；source 記錄 offset。失敗 → 回到最近 checkpoint、重放 Kafka。端到端 exactly-once 需 sink 用 two-phase commit（如 Kafka sink transactions）或 idempotent upsert。
- **失效模式**：state 無限增長（沒設 TTL）；data skew/hot key 讓單一 subtask 成為瓶頸；backpressure 沿 DAG 回推；checkpoint 太久（state 過大）或 barrier 對齊逾時；watermark 因某 idle partition 停滯導致 window 不關閉；changing parallelism 需 savepoint 與 key group 重分配。

### In Your Interview（by agents）
- **Using Flink**：出現「窗口聚合、join 多串流、有狀態偵測、需要 exactly-once 與低延遲」時才提；先明說為何不用 batch/Spark、為何不只用 Kafka consumer。說明 source（Kafka）、key、window 型態、watermark 延遲、state 規模、sink 與一致性。
- **Lessons from Flink**：即使不用 Flink 也能借鏡：state 與運算同分區（共置）、定期 snapshot + 可重放 log 做恢復、用 event time + watermark 處理亂序、以 key 分區做水平擴展。
- 備案：Kafka Streams（嵌入式、無獨立 cluster）、Spark Structured Streaming（micro-batch，延遲較高）。

## 關鍵數字（by agents，附來源）
- Checkpoint interval 常見 數秒～數分鐘（官方文件建議視 state 大小調整；經驗量級）。
- Flink 官方預設 max parallelism：未設定時依 parallelism 推算，最小 128（Flink 文件 key group 說明）。
- 延遲：Flink 可達毫秒～秒級端到端；Spark micro-batch 通常秒級以上（量級比較，非 benchmark）。

## 相關題目
- [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [top-k](../../hellointerview-breakdowns/top-k.md)
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)

## 自測問題（by agents）
1. 為何有狀態串流比無狀態難？答：state 需容錯（crash 恢復）、擴縮時重分配、且要處理亂序/遲到。
2. Watermark 是什麼？答：event time 進度宣告，表示此時間之前的事件預期已到齊，用來觸發 window。
3. Flink 如何達成 exactly-once？答：barrier 對齊的分散式 snapshot + 可重放 source + 2PC/idempotent sink。
4. RocksDB vs HashMap state backend？答：後者快但受 heap 限制；前者容量大且支援 incremental checkpoint，但較慢。
5. 何時不用 Flink？答：不需即時、可 batch；或僅無狀態轉換，簡單 consumer 即可。

## 參考來源
- Apache Flink docs (Stateful Stream Processing / Checkpointing / State Backends): https://nightlies.apache.org/flink/flink-docs-stable/
- Carbone et al., Lightweight Asynchronous Snapshots for Distributed Dataflows (2015)
- Akidau et al., The Dataflow Model (VLDB 2015)
（以上引用自既有知識；2026-10-19 已確認連結可開啟（HTTP 200），內容未逐條比對。）
