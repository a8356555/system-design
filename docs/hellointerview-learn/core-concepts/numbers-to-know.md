# Numbers to Know
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/numbers-to-know ｜ 分類：core-concepts

## 一句話重點
硬體進步很快，用 2015 年的數字估算會低估現代單機能力，進而「過早 sharding、過度 cache、過度設計」。面試時應記住量級（order of magnitude），而不是精確值。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：產業變動快，書本上的數字可能差好幾個數量級；用過時的硬體限制做規模計算，是「只有書本知識、缺乏實務經驗」的一大訊號。文章列出「2026 年真正重要的數字」。

公開的 Modern Hardware Limits 段（原文大意）：
- AWS M6i.32xlarge：512 GiB 記憶體、128 vCPU；X1e.32xlarge：4 TB RAM；U-24tb1.metal：24 TB RAM。
- 儲存：i3en.24xlarge 有 60 TB 本機 SSD；D3en.12xlarge 有 336 TB HDD；S3 等 object storage 實質無上限。
- 網路：datacenter 內 25 Gbps 常見，高階 50-100 Gbps 以上；跨 AZ 頻寬受限於 instance 網卡，延遲可預期。
- 結論（原文大意）：教科書「資料庫 100GB 就要切」、「避免把大物件放記憶體」等限制已過時。

章節標題（原文）：
- Modern Hardware Limits
- Applying These Numbers in System Design Interviews：Caching / Databases / Application Servers / Message Queues
- Cheat Sheet
- Common Mistakes In Interviews：Premature sharding / Overestimating latency / Over-engineering given a high write throughput
- What about costs?
- Conclusion

## 內容（by agents）
> 以下數字為「量級」，非保證值；實際依 instance、payload、設定而異。不確定處已標「約」。

### Applying These Numbers — Caching（by agents）
- Redis 單節點（單執行緒處理命令）：官方 redis-benchmark 文件示例，無 pipeline、50 clients、3 byte payload 約 7 萬 req/s（該文件中的舊機器範例）；pipeline 16 在 MacBook Air 範例達 150 萬+ req/s。生產環境常用量級：單節點 ~10^5 ops/s、延遲 p50 < 1 ms（同 AZ 內網）。
- 記憶體：單機可放 TB 級；快取容量不再是「幾十 GB」的問題 → 一個 cache node 可放得下多數中型服務的熱資料。
- **何時要 shard cache**：單節點 QPS 超過 ~10^5、或資料 > 單機 RAM、或需要高可用/跨 AZ。見 [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)。
- 失效模式：hot key（單 key QPS 超過單 shard 容量）、big key（MB 級 value 阻塞單執行緒）。

### Databases（by agents）
- 單台現代 PostgreSQL/MySQL：資料量可到 數 TB～數十 TB（受備份/還原時間限制多於硬體）；讀 QPS 約 10^4～10^5（簡單 PK 查詢、資料在記憶體），寫 TPS 約 10^3～10^4（取決於 fsync、index 數、replica 同步方式）。這是經驗量級，非官方保證。
- 因此「100GB 就切」是過時說法；先問：資料量 / QPS / 可用性是否真的超過單機＋read replica 能力。
- 切分動機通常是：寫入吞吐、資料量 > 單機、地理分佈、故障爆炸半徑。
- 延遲：同機房 RTT ~0.5 ms；DB 簡單 PK 查詢（in buffer pool）~ 0.1-1 ms；需 disk 讀 ~ 0.1-10 ms。

### Application Servers（by agents）
- 單台 8-64 core 的 stateless server：HTTP 輕量請求約 10^3～10^4 RPS/core 級的量級取決於框架與 IO 比例；連線數可達 10^5（epoll/async）。
- 面試中常見估算：單台 ~1k-10k RPS（含業務邏輯與 DB 呼叫），需要時水平擴展；瓶頸多在 DB/下游而非 app server CPU。
- 記憶體：數十～數百 GB 常見，可放大物件與 in-process cache。

### Message Queues（by agents）
- Kafka：LinkedIn 2014 benchmark，3 台廉價機器約 200 萬 writes/s（每筆 100 bytes，batch、無 replication 同步 ack 的條件，見來源）；現代單 broker 常見 10^5～10^6 msg/s，吞吐常受網路/磁碟頻寬限制。
- Kafka 預設單訊息上限 ~1 MB（`message.max.bytes`），大 payload 應放 S3 傳 reference。
- 端到端延遲：低至個位數～數十 ms（取決於 `linger.ms`、acks）。
- 單 partition 內有序、一個 consumer group 內同一 partition 同時只被一個 consumer 消費 → partition 數 = 並行度上限。

### Cheat Sheet（by agents）
| 項目 | 量級 | 備註／來源 |
|---|---|---|
| L1 cache ref | ~0.5 ns | Jeff Dean 數字（約 2012） |
| Main memory ref | ~100 ns | 同上 |
| 1MB 循序讀 memory | ~250 µs | 同上（舊） |
| SSD random read 4K | ~150 µs（舊）；現代 NVMe 約 10-100 µs | 同上，現代值為經驗量級 |
| 1MB 循序讀 SSD | ~1 ms | 同上 |
| 1MB 循序讀 HDD | ~20 ms | 同上 |
| HDD seek | ~10 ms | 同上 |
| 同 datacenter RTT | ~500 µs | 同上 |
| CA → NL → CA | ~150 ms | 同上 |
| Redis 單節點 | 10^5 ops/s（無 pipeline），pipeline 可 10^6 | redis.io benchmark 文件 |
| S3 單 prefix | 至少 3,500 PUT/COPY/POST/DELETE、5,500 GET/HEAD 每秒 | AWS S3 官方文件 |
| DynamoDB 單 item | 上限 400 KB | AWS 官方文件 |
| DynamoDB 單 partition | 約 3,000 RCU / 1,000 WCU | AWS 官方文件（adaptive capacity 可緩解） |
| Kafka 單訊息 | 預設 ~1 MB | Kafka 官方文件 |
| 機器上限（原文） | RAM 到 24 TB、本機 SSD 60 TB | 見上方原文段 |

### Common Mistakes In Interviews（by agents）
- **Premature sharding**：「資料 500 GB 所以要 shard」→ 多半單機＋replica 足夠。先算 QPS、資料量、成長率，再決定。
- **Overestimating latency**：把 DB 讀寫說成「很慢要 cache」。實際同 AZ 內單次 DB 查詢是毫秒級；cache 的價值在於降低 DB 負載與尾端延遲，而非每次都必要。反過來也別低估跨區（~100+ ms）。
- **Over-engineering given high write throughput**：看到 10k writes/s 就上 Kafka + 分片。許多單機 DB 可承受；真正要拆的是 >10^5 writes/s 或需要 buffer / 削峰時。見 [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（先 batch，再 stream）。

### What about costs?（by agents）
- 面試可補一句成本：RAM 約是 SSD 的 10 倍以上單價、跨 AZ/跨 region 流量要收費、S3 便宜但 request 計費。量大時 egress 與 cross-AZ replication 可能比算力更貴。具體單價隨年份與地區變動，請以官方定價頁為準。

### 面試使用方式（by agents）
1. 先換算：DAU × 動作數 ÷ 86,400 ≈ 平均 QPS，峰值 ×2~10。
2. 把結果對照單機能力，決定是否需要 shard / cache / queue。
3. 說明假設與數字來源（「約」「量級」），並指出瓶頸最可能出現的位置。

## 關鍵數字（by agents，附來源）
見上方 Cheat Sheet。年份：Jeff Dean 數字約 2012；LinkedIn Kafka benchmark 2014；Redis benchmark 文件為持續更新的官方頁面；S3 request rate 為 2018 年起的 AWS 公告值。

## 相關題目
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)
- [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [top-k](../../hellointerview-breakdowns/top-k.md)
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)

## 自測問題（by agents）
1. 一個 1 TB、5k QPS 的服務需要 shard 嗎？答：多半不需要；單機＋read replica 可處理，先確認寫入與可用性需求。
2. Redis 單節點大約能撐多少 ops/s？答：10^5 量級（無 pipeline），pipeline 可到 10^6；瓶頸常在網路。
3. 為何 Kafka 不適合傳 50 MB 影片？答：預設單訊息約 1MB 上限、會拖慢 broker；改存 S3 傳 reference。
4. 同 AZ 與跨 region 延遲差多少？答：約 0.5 ms vs 數十～150 ms，差 2-3 個數量級。
5. 為何「過時的數字」是紅旗？答：會導致過早切分、過度複雜架構，表示缺乏實務。

## 參考來源
- Latency Numbers Every Programmer Should Know: https://gist.github.com/jboner/2841832（已實際擷取）
- Redis benchmark: https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/（已實際擷取）
- Kreps, Benchmarking Apache Kafka: 2 Million Writes Per Second (LinkedIn, 2014): https://engineering.linkedin.com/kafka/benchmarking-apache-kafka-2-million-writes-second-three-cheap-machines
- AWS S3 performance guidelines: https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html
- DynamoDB quotas: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ServiceQuotas.html
- Kafka broker configs: https://kafka.apache.org/documentation/#brokerconfigs
（後三項引用自既有知識；2026-10-19 已確認連結可開啟，數值使用前請核對最新版本。）
