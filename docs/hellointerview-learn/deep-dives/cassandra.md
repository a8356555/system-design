# Cassandra
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/cassandra ｜ 分類：deep-dives

## 一句話重點
Cassandra 是 partitioned wide-column、eventually consistent、LSM-tree 的 NoSQL，強項是高寫入吞吐與 availability；用它的關鍵是 query-driven data modeling（先列 access patterns，再決定 partition key / clustering key，並接受 denormalization）。

## 它是什麼 / 核心機制
Facebook 為 inbox search 打造；結合 Dynamo 與 Bigtable 的元素，用 commodity hardware 水平擴展。Discord、Netflix、Apple、Bloomberg 都在用。

### 資料模型
- Keyspace（相當於 database，定義 replication 策略與 UDT）> Table（schema + primary key）> Row > Column。
- Wide-column：同表各 row 的欄位可不同，不必填 NULL。每個 column 有 write timestamp，replica 衝突時 **last write wins**。
- Primary key = partition key（決定 partition）+ 可選 clustering key（決定 partition 內排序）。與 DynamoDB 的 primary key 概念 1:1 對應。
- 範例 CQL：`PRIMARY KEY ((a, b), c)` 表示 composite partition key (a,b)、clustering key c。

### Partitioning
- Consistent hashing：hash(value) % N 在節點數變動時大量重新映射且可能不均；ring 上順時針找第一個節點，節點加入/離開只影響相鄰節點。
- 用 vnodes（virtual nodes）讓一個 physical node 擁有多個 ring 位置，負載更平均，且大機器可擁有更多 vnode。

### Replication
- 從 hash 到的 vnode 順時針掃描找 replica，跳過同一 physical node 的 vnode。
- SimpleStrategy：只順時針掃描，適合測試與簡單部署。
- NetworkTopologyStrategy：production 建議，可感知 data center / rack，如 `{'dc1': 3, 'dc2': 2}`。

### Consistency
- 受 CAP 約束，可調（tunable）。每次讀寫指定 consistency level：ONE 到 ALL。
- QUORUM = n/2 + 1；讀寫都用 QUORUM 則讀寫集合必有交集，讀得到最新寫入（3 副本需 2 個）。
- 沒有 transaction / ACID；只保證單一 partition 內 row 層級的 atomic 與 isolated write。最終是 eventual consistency。

### Query routing
任何節點都可當 coordinator；靠 gossip 知道存活節點、靠 consistent hashing 與 replication 設定找出 replica，由 coordinator 向 replica 發查詢。

### Storage model（LSM tree）
- 寫入多為 append：create/update/delete 都是新 entry，delete 寫 tombstone。偏向寫入速度而非讀取。
- Commit log（WAL，durability）-> Memtable（記憶體中按 primary key 排序）-> flush 成不可變 SSTable；flush 後對應 commit log 可刪。
- 讀取：先看 Memtable，再用 bloom filter 判斷哪些 SSTable 可能有資料，由新到舊讀取。
- Compaction：合併 SSTable、清掉 tombstone（因為已排序，效率高）。SSTable index 記錄 key 到 byte offset。

### Gossip
- P2P 傳播叢集資訊，無 SPOF。每個節點維護 generation（bootstrap timestamp）與 version（約每秒遞增的 logical clock），形成 vector clock 以忽略過期資訊。
- 偏向挑 seed nodes 溝通，避免形成分裂的子叢集。

### Fault tolerance
- Phi Accrual Failure Detector：各節點獨立判斷，「convict」無回應節點並停止送寫入；但節點仍留在 ring，直到管理員改拓樸，避免短暫故障觸發 rebalancing。
- Hinted handoff：節點離線時 coordinator 暫存寫入（hint），上線後補送；hint 壽命短，長時間離線要靠 rebuild 或 read repair。

## 何時用 / 何時不用
- 用：availability 優先於 consistency、高擴展需求；高寫入吞吐（LSM tree）；彈性/稀疏 schema（wide-column）；有明確且固定的 access patterns。
- 不用：需要嚴格一致性；需要進階查詢（multi-table JOIN、ad-hoc aggregation）。

## 面試常考的進階點
### Data modeling（query-driven，非 entity-relationship-driven）
- 沒有 FK、JOIN，只服務單表查詢 -> 先看 access patterns，再決定 partition key、partition size、clustering key，並 denormalize。
- **範例 Discord messages**：初版 `PRIMARY KEY (channel_id, message_id) ORDER BY message_id DESC`，單一 partition 就能取一個 channel 的訊息，避免 scatter-gather。用 Snowflake ID 而非 created_at，避免 key 衝突。
- 問題：熱門 channel partition 過大、且 partition 無限成長 -> 效能下降。解法：partition key 加 bucket（10 天一個 window，以 DISCORD_EPOCH 2015-01-01 對齊）：`PRIMARY KEY ((channel_id, bucket), message_id)`。最近訊息通常在同一個 bucket；例外是剛換 bucket 或不活躍 channel（少數）。
- **範例 Ticketmaster 瀏覽座位**：不需要強一致（真正結帳時再去 consistent DB 檢查）。初版 `PRIMARY KEY (event_id, seat_id)`，萬張票以上的活動每次查詢需聚合，熱門活動負擔大。改成 `PRIMARY KEY ((event_id, section_id), seat_id)`，每個 section 一個 partition，分散到多節點且單 partition 更小。另建 `event_sections(event_id, section_id, num_tickets, price_floor)` 做 denormalization，讓總覽查詢只打單一 partition（活動 section 通常 < 100）；數量不必精確（Ticketmaster 顯示 "100+"）。
- 重點：Partition key 選擇、partition 大小上限（會不會無限成長）、用 time bucket 切 partition、denormalize 預先聚合。

### 其他進階點
- Large partition 會出現效能問題 -> 必須設計邊界（bucketing）。
- Tunable consistency：QUORUM 讀 + QUORUM 寫的交集保證；ONE 換取低延遲與高可用。
- Tombstone + compaction：delete 不是立即移除；LWW 靠 timestamp 解衝突。
- 失效處理：failure detector、hinted handoff（短期）、read repair/rebuild（長期離線）。
- 進階功能：Storage Attached Indexes（SAI，global secondary index，效能比 partition key 查詢差但可接受，適合低頻查詢以避免多餘 denormalize）；Materialized Views（由 Cassandra 自動 denormalize）；Search Indexing（透過 plugin 接 Elasticsearch / Solr，如 Stratio Lucene Index）。
- （補充）LWW 依賴時鐘，時鐘偏移可能導致寫入被覆蓋；不要拿 Cassandra 做需要 read-modify-write 的計數/庫存扣減。

## 關鍵數字
- QUORUM = n/2 + 1（RF=3 時為 2）。
- Discord bucket = 10 天；Ticketmaster 每活動 section 通常 < 100。
- 原文未給 partition 大小的具體上限數字。

## 相關題目
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [WhatsApp](../../hellointerview-breakdowns/whatsapp.md)（訊息儲存，同 Discord 模式）
- [FB Live Comments](../../hellointerview-breakdowns/fb-live-comments.md)
- [Metrics Monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)（補充：高寫入時序類）

## 自測問題
1. 為什麼 Cassandra 寫入快？
   - LSM tree：commit log + Memtable 的 append-only 寫入，之後 flush 成不可變 SSTable，再 compaction。
2. QUORUM 讀寫為何能讀到最新值？
   - 讀寫各需多數節點（n/2+1），兩個多數集合必有交集。
3. Discord 為何在 partition key 加 bucket？
   - 熱門 channel partition 過大且無限成長；以 10 天 window 限制 partition 大小，且最近訊息通常只需讀一個 partition。
4. 節點暫時掛掉時寫入怎麼辦？
   - Hinted handoff：coordinator 暫存 hint，節點恢復後補送；長時間離線靠 rebuild / read repair。
5. 什麼情況不選 Cassandra？
   - 要嚴格一致性、transaction，或 JOIN / ad-hoc aggregation 等複雜查詢。
