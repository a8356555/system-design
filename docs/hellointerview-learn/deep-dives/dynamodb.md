# DynamoDB
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/dynamodb ｜ 分類：deep-dives

## 一句話重點
DynamoDB 是 AWS 全託管、可自動擴展的 key-value / document 服務，支援 transactions、per-request 可選的強一致讀、GSI/LSI、DAX、Streams；面試中幾乎可以拿來當任何 persistence layer，但要先問面試官能不能用，並清楚講出 partition key / sort key 與其限制。

## 它是什麼 / 核心機制
- Fully-managed（AWS 處理硬體、設定、patch、擴展）、highly scalable（無停機自動調整）、key-value（NoSQL）。
- 非 open source，內部細節來自 AWS 文件與 DynamoDB Paper。
- 資料模型：Table（必有 primary key）> Item（相當於 row，最大 400KB）> Attribute（scalar、set、可巢狀）。Schema-less：同表 item 屬性可不同，驗證要在 application 層做。
- Primary key：Partition Key（hash 後決定 partition）+ 可選 Sort Key（同 partition 內排序，支援 range query）。
- 範例：群組聊天用 `chat_id` 為 partition key、`message_id` 為 sort key。sort key 用單調遞增 ID 而非 timestamp（timestamp 可能重複）；產生方式：per-partition auto-increment、UUID v7（優於 v1）、Snowflake ID、ULID。
- 內部：hash partitioning + request router 查詢 partition metadata service（集中式 partition map，不同於 Dynamo 2007 paper 的 P2P hash ring）；服務負責 partition 自動 split/merge。Partition 內以 B-tree 按 sort key 索引。

### Secondary indexes
| | GSI | LSI |
|---|---|---|
| 定義 | partition key 與主表不同 | partition key 相同、sort key 不同 |
| 儲存 | 獨立 partition 與 replica（本質是另一張表） | 與主表同 partition 共置 |
| 更新 | 非同步（eventually consistent） | 與主表寫入同步 |
| 一致性 | 僅 eventually consistent | 支援 eventual（預設）與 strong |
| 容量 | 獨立 R/W capacity，item 大小無限制 | 共用主表 capacity，每個 partition key 限 10GB |
| 建立 | 隨時可增刪 | 只能在建表時定義，無法移除 |
| 數量上限 | 每表 20 個 | 每表 5 個 |

- 例：GSI 用 `user_id` + `message_id` 查某使用者跨所有 chat 的訊息；LSI 例如在 chat 內依 `num_attachments` 查。

### Accessing data
- Scan：讀整張表/索引，分頁，低效，盡量避免。Query：依 primary key 或索引 key 取資料，可對 sort key 做 range。
- 主介面是 SDK / console；也支援 PartiQL（SQL 相容語法，底層轉成同樣操作）。
- ProjectionExpression 只減少網路傳輸，仍讀整個 item 並按整個 item 大小收 RCU。大 item 要拆表（例：Yelp 的 reviews 獨立成表，以 business_id 查詢）。

## 何時用 / 何時不用
- 用：幾乎任何 persistence 需求——可擴展、durable、支援 transactions、個位數毫秒延遲（搭 DAX 為微秒級）。
- 不用的理由：
  - 成本：每秒數十萬寫入時可能太貴。
  - 複雜查詢：JOIN、ad-hoc aggregation 不適合（雖支援跨表 transaction，最多 100 items）。
  - Data modeling 限制：若一直需要大量 GSI/LSI，PostgreSQL 可能更合適。
  - Vendor lock-in：有些面試官要求 vendor-neutral。

## 面試常考的進階點
### 一致性（CAP）
- 一致性模型是 **per-request**（`ConsistentRead=true`），不是 table 層級設定。預設 eventually consistent，整體偏 AP、BASE。
- Strong read 成本 2 倍（1 RCU/4KB vs 0.5 RCU），延遲稍高；只支援 base table 與 LSI，**GSI 不支援**。
- 內部：每個 partition 3 個 replica（1 leader + 2 follower），Multi-Paxos；leader 處理所有寫入、產生 WAL entry，quorum（3 取 2）持久化後才 ack。強一致讀路由到 leader；最終一致讀可由任一 replica 服務，可能讀到舊值。
- 支援 ACID transactions：TransactWriteItems / TransactGetItems，serializable isolation，最多 100 items、可跨表。因此「NoSQL 沒有 transaction」已過時。

### Scalability / 可用性
- 自動 sharding：partition 達到容量（大小或吞吐）自動 split；hash 分佈均勻。
- 資料自動複製到同一 region 的 3 個 AZ（不可設定）；跨 region 用 Global Tables（面試提到即可）。

### 定價與 back-of-the-envelope
- 兩種模式：on-demand（按請求，適合不可預測負載）與 provisioned（指定 RCU/WCU，按小時計，適合可預測負載）。
- 1 RCU = 每秒 1 次強一致讀（4KB）或 2 次最終一致讀；1 WCU = 每秒 1 次 1KB 寫入，寫入小於 1KB 也向上取整。
- 每 partition 上限 3,000 RCU、1,000 WCU（約 12MB/s 讀、1MB/s 寫）。
- 原文範例：YouTube views 每秒 1,000 萬次寫入 -> 約 10,000 partitions；provisioned 約 $0.00065 / WCU-hour，估計約 $156,000 / 天，on-demand 更貴。用於 sanity check 負載是否現實。

### 進階功能
- **DAX**：內建 in-memory cache（microsecond）。read-through + write-through；需改用 DAX client SDK（非完全透明）。只對經 DAX 的寫入自動 invalidate，直接寫 DynamoDB 會讓 cache 過期資料殘留到 TTL/eviction。有 item cache 與 query cache，皆啟用；**不快取 strongly consistent reads**。可省去額外引入 Redis / Memcached。
- **Streams**：內建 CDC。可觸發 Lambda、同步 Elasticsearch index、維護其他系統的 replica。即時分析：啟用 Kinesis Data Streams，再接 Firehose 到 S3 / Redshift / OpenSearch（Firehose 不能直接讀 DynamoDB Streams）。
- 安全：預設 at-rest 加密、TLS 傳輸、IAM 細粒度權限、VPC endpoints；面試提一句即可。
- 熱 partition（補充）：partition key 分佈不均會撞到單 partition 1,000 WCU / 3,000 RCU 的上限，要選高基數 key 或加 shard suffix。

## 關鍵數字
- Item 最大 400KB。
- 1 RCU = 4KB 讀；1 WCU = 1KB 寫；strong read 2 倍成本。
- 每 partition：3,000 RCU / 1,000 WCU。
- RCU $1.12 / 百萬次讀（4KB）；WCU $5.62 / 百萬次寫（1KB）。
- GSI 上限 20、LSI 上限 5；LSI 每 partition key 10GB。
- Transaction 最多 100 items。
- 3 replicas，3 AZ，quorum 2/3。

## 相關題目
- [Yelp](../../hellointerview-breakdowns/yelp.md)
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [WhatsApp](../../hellointerview-breakdowns/whatsapp.md)
- [Bitly](../../hellointerview-breakdowns/bitly.md)
- [Dropbox](../../hellointerview-breakdowns/dropbox.md)

## 自測問題
1. DynamoDB 的一致性如何選擇？
   - 每次讀取以 ConsistentRead 指定；strong read 成本 2 倍且不支援 GSI。
2. GSI 與 LSI 的差別？
   - GSI：不同 partition key、獨立儲存、非同步更新、隨時可建、僅最終一致；LSI：同 partition key 不同 sort key、同步更新、需建表時定義、10GB 限制。
3. 為什麼 ProjectionExpression 不能省 RCU？
   - 仍然讀取整個 item 並按整個大小計費，只省網路頻寬；大 item 應拆表。
4. DAX 的限制？
   - 需換 client SDK；繞過 DAX 的寫入不會 invalidate；不快取 strong read。
5. 如何用 DynamoDB 做 CDC / 同步搜尋索引？
   - DynamoDB Streams 觸發 Lambda / 消費者，更新 Elasticsearch。
