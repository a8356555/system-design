# Kafka
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/kafka ｜ 分類：deep-dives

## 一句話重點
Kafka 是分散式 event streaming 平台，可當 message queue 或 stream；以 partition（有序、不可變的 append-only log）達成 scale 與同 key 有序，consumer group 達成並行消費。面試重點：partition key 選擇 / hot partition、acks 與 replication 的 durability、offset commit 時機與 retry / DLQ。

## 它是什麼 / 核心機制
- 原文動機例：World Cup 即時比分。同一場比賽的事件必須有序 -> 依 game 分 partition；consumer 跟不上 -> consumer group；多種運動 -> topic。
- **Broker**：叢集中的單一伺服器，儲存資料並服務 client。**Partition**：有序、不可變、持續 append 的 log，是 Kafka scale 的單位（可平行消費）。**Topic**：partition 的邏輯分組（Topic 是邏輯分組，partition 是實體分組）；topic 永遠 multi-producer。
- **Message（record）**：value、key、timestamp、headers，皆為可選。key 決定 partition；partition 內的順序由 offset 決定，不是 timestamp。
- **Partition 選擇**：hash(key) 決定 partition（預設 murmur2，`hash(key) % num_partitions`），同 key 必在同 partition，故 partition 層級有序。沒 key 時現代 client 用 sticky partitioner（批次送同一 partition 再輪轉）。再由 controller 維護的 metadata 找出 partition 所在 broker，producer 直送。
- **Append-only log 的好處**：immutability（只經 retention 或 log compaction 移除，簡化 replication 與復原）、減少 disk seek、易於水平擴展。
- **Offset**：partition 內的循序位置；consumer 定期 commit offset，重啟後從上次 commit 處續讀。預設 **at-least-once**：處理後、commit 前當機則會重處理。Exactly-once 需額外設定（idempotent producer + transactional APIs）。
- **Replication**：leader-follower。leader 處理所有寫入與（預設）讀取（Kafka 2.4+ 支援從 follower 讀以優化延遲）；follower 被動複製；controller 監控 broker 健康，leader 掛掉時從 in-sync follower 提升新 leader。
- **Consumer 是 pull-based**：consumer 自己控制消費速率、利於 batching、不會壓垮慢 consumer、簡化失效處理。
- **Consumer group**：每個 partition 只分配給組內一個 consumer，正常情況每個事件只交付給一個 consumer。
- Queue vs stream 差異很小，關鍵是消費模式：queue 時每則訊息由組內一個 consumer 處理後視為 consumed；stream 時 log 保留可重播，多個 consumer group 可獨立讀取同一份資料。

## 何時用 / 何時不用
**當 message queue**：
- 可非同步處理（YouTube 上傳後，標清先可用，轉碼丟 Kafka 慢慢做）。
- 需要有序處理（Ticketmaster 的 virtual waiting queue，依到達順序放行）。
- 解耦 producer / consumer 讓兩者獨立擴展（producer 比 consumer 快時；避免一個服務拖垮另一個）。

**當 stream**：
- 需要持續、即時處理（Ad Click Aggregator 即時聚合點擊）。
- 多個 consumer 同時消費同一訊息（FB Live Comments 當 pub/sub）。

**不要**：把大 blob 放進 Kafka。Kafka 不是資料庫。YouTube 例：影片存 S3，Kafka 只放 S3 位置的指標。

## 面試常考的進階點
（原文註明：junior/mid 通常不需以下內容；senior 要熟一部分；staff 以上多數要懂。）

### Scalability
- 先估吞吐與訊息量，判斷需不需要談 scaling。單一 broker 在好硬體上約可存 ~1TB、處理 ~1M messages/sec（原文標註很粗略，依訊息大小與硬體而異）。不超過就不必討論 scale。
- 訊息大小無硬上限（`message.max.bytes`），但建議 < 1MB。
- 水平擴展：加 broker，**但 topic 必須有足夠 partition**，否則 under-partitioned 用不到新 broker。
- **Partition strategy 才是主戰場**：key 選差了會有 hot partition；好 key 要在 partition space 均勻分佈。擴展通常以 topic 為單位（不同 topic 需求不同）；增加 partition 數以利用更多 broker。託管服務（Confluent Cloud、AWS MSK）會代為處理許多 scaling，但仍要懂概念。

### Hot partition（面試官愛問）
範例：Ad Click Aggregator 以 ad id 分 partition，Nike 發 Lebron James 廣告時該 partition 爆量。
1. **不帶 key**：用預設 partitioner 平均分散；代價是失去相關訊息的順序保證，若順序不重要是好選項。
2. **Random salting**：在 ad ID 加隨機數或 timestamp 當 key；分散負載，但 consumer 端聚合變複雜。
3. **Compound key**：ad ID + 地區 / user ID segment 等獨立變動的屬性。
4. **Back pressure**：放慢 producer；自建叢集可檢查 partition lag 過高時降速，託管服務可能內建。

### Durability / Fault tolerance
- Replication factor 通常 3（1 leader + 2 followers）。`acks=all` 代表所有 in-sync replicas (ISR) 收到才 ack，最強的 durability。
- 「Kafka always available, sometimes consistent」：「Kafka 掛了怎麼辦」不太現實，可溫和反問；更現實的是 consumer 掛掉。
- Consumer 掛掉：靠 committed offset 續讀（可能重處理，at-least-once）；consumer group **rebalancing** 把 partition 重新分配給剩下的 consumer。
- **何時 commit offset 是取捨**：例如 Web Crawler 要等 raw HTML 存進 blob storage 後才 commit。Consumer 工作越多，失敗後重做越多 -> 讓 consumer 工作越小越好（Web Crawler 拆成下載 HTML 與解析兩階段）。

### Retries and errors
- **Producer retries**：自動重試（如 retries 5、initialRetryTime 100ms），務必開 **idempotent producer** 避免重試造成重複訊息。
- **Consumer retries**：Kafka 不內建 consumer retry（AWS SQS 有）。常見做法：把失敗訊息移到另一個 retry topic 由獨立 consumer 處理，重試過多次後移到 **dead letter queue (DLQ)** 供後續調查。Web Crawler 題因此選 SQS 以取得內建 retry 與 DLQ。

### Performance
- Producer 批次送（單次 send 多則；sendBatch 跨 topic）；壓縮（GZIP、Snappy、LZ4）。
- 影響最大的仍是 partition key 的選擇：最大化並行、均勻分佈。面試中討論 partition 策略通常是起點。

### Retention
- 由 `retention.ms`、`retention.bytes` 控制，預設保留 7 天。需要更久可調長，注意儲存成本與效能。

### 其他
- （補充）Exactly-once 的完整保證需要 idempotent producer + transaction + consumer 端 read-committed，且對外部 side effect 仍需 consumer 端冪等。
- （補充）增加 partition 數會改變 hash(key) % N 的映射，破壞既有 key 的順序語意，預先規劃足夠 partition 數。

## 關鍵數字
- 單 broker：~1TB 儲存、~1M msg/s（粗估）。
- 訊息建議 < 1MB。
- 預設 retention 7 天。
- Replication factor 常見 3。
- 原文引述：80% 的 Fortune 100 使用 Kafka。

## 相關題目
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [FB Live Comments](../../hellointerview-breakdowns/fb-live-comments.md)
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [Web Crawler](../../hellointerview-breakdowns/web-crawler.md)
- [YouTube](../../hellointerview-breakdowns/youtube.md)
- [Top-K](../../hellointerview-breakdowns/top-k.md)

## 自測問題
1. Kafka 如何保證同一實體的事件有序？
   - 用 entity ID 當 key，hash 後固定到同一 partition；順序保證只在 partition 內，由 offset 決定。
2. 熱門 key 造成 hot partition 怎麼辦？
   - 不帶 key、random salting、compound key、back pressure；各有 ordering / 聚合複雜度的取捨。
3. 想盡量不丟訊息要怎麼設定？
   - replication factor 3 + `acks=all` (ISR)，producer 開 idempotent；consumer 處理完成後才 commit offset。
4. Consumer 失敗後的重試怎麼做？
   - Kafka 不內建；用 retry topic + 獨立 consumer，超過次數進 DLQ；或改用 SQS。
5. 為何不把影片丟進 Kafka？
   - Kafka 適合小訊息（建議 < 1MB）；影片放 S3，Kafka 只送位置指標。
