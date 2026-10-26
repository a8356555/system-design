# PostgreSQL
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/postgres ｜ 分類：deep-dives

## 一句話重點
面試中講 PostgreSQL 重點是「能力與限制」：ACID 與關聯、B-tree/GIN 等 index、單主寫入、read replica 擴讀、必要時 partition/shard；不要陷入 MVCC/WAL 內部細節，也不要空泛地說「Postgres 擴展不了」。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：PostgreSQL 在 Stack Overflow 調查中屢居最受喜愛資料庫，被 Reddit、Instagram 等使用。面試官不是找 DBA，而是看你能否做架構決策。常見錯誤：過度深入內部（MVCC、WAL），或做過度籠統的陳述。以社群平台為 Motivating Example：user 發文、留言、追蹤、對貼文與留言按讚、DM；需求包含 DM thread 建立需原子性、留言/追蹤需參照完整性、按讚數可最終一致、profile 要高效取最近貼文與 follower 數、搜尋貼文與使用者、未來擴展。
原文另有：預設 B-tree 適用等值、範圍、排序；反例「為每個欄位加 index」會拖慢寫入、佔空間、planner 不一定採用；範例 `CREATE INDEX idx_posts_user_date ON posts(user_id, created_at)`。

章節標題（原文）：
- A Motivating Example
- Core Capabilities & Limitations：Read Performance（Basic Indexing / Beyond Basic Indexes / Query Optimization Essentials）、Write Performance（Throughput Limitations / Write Performance Optimizations）、Replication（Scaling reads / High Availability）、Data Consistency（Transactions）
- When to Use PostgreSQL (and When Not To)：When to Consider Alternatives
- Summary
- Appendix: Basic SQL Concepts：Relational Database Principles / ACID（Atomicity、Consistency、Isolation、Durability）/ Why ACID Matters / SQL Language（SQL Command Types）

## 內容（by agents）
### A Motivating Example（by agents）
- 資料模型：users、posts、comments、follows(follower_id, followee_id)、likes、dm_threads/participants/messages。
- 對應需求：DM 建立用 transaction；FK 保證參照完整；like count 可由 counter 欄位/Redis 非同步更新；profile 查詢靠 `(user_id, created_at DESC)` index；搜尋用 GIN + tsvector 或外接 Elasticsearch。

### Read Performance（by agents）
- **Basic Indexing**：B-tree 預設；composite index 遵守 leftmost prefix；partial index（`WHERE deleted=false`）縮小 index；expression index。詳見 [db-indexing](../core-concepts/db-indexing.md)。
- **Beyond Basic Indexes**：GIN（JSONB、陣列、全文 tsvector）、GiST/SP-GiST（PostGIS 地理、範圍）、BRIN（超大、自然排序的時間序列表，極小）、pg_trgm（模糊 LIKE）、pgvector（向量搜尋）。
- **Query Optimization Essentials**：`EXPLAIN ANALYZE` 看 seq scan vs index scan；避免 `SELECT *`；N+1 改 join / batch；keyset pagination 取代大 OFFSET；covering index（INCLUDE）達成 index-only scan；統計資訊過舊需 ANALYZE；連線太多用 PgBouncer 連線池（每連線是一個 process）。

### Write Performance（by agents）
- **Throughput Limitations**：單一 primary 負責寫；寫入受 WAL fsync、index 數量、鎖與 vacuum 影響。單機通常 10^3~10^4 TPS 量級（依硬體與批次）。
- **Optimizations**：批次 insert / COPY；減少不必要 index；`synchronous_commit=off` 換取延遲（可能丟最後幾筆）；group commit；table partitioning（依時間/範圍）讓舊資料 detach；HOT update、調整 fillfactor；寫放大時考慮 queue 緩衝。
- **擴展寫**：application-level sharding 或用 Citus 等；跨 shard transaction 變困難 —— 面試要主動提及這個代價。
- **失效模式**：長交易阻擋 vacuum → table/index bloat；XID wraparound；hot row（計數器、庫存）鎖競爭 → 改用 optimistic locking / `SELECT FOR UPDATE SKIP LOCKED`。見 [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)。

### Replication（by agents）
- **Scaling reads**：streaming replication（WAL 傳到 hot standby）→ read replica 分流讀；非同步 → replica lag，read-your-writes 需路由到 primary 或帶 LSN 等待。
- **High Availability**：同步／非同步 standby、自動 failover（Patroni、RDS Multi-AZ、Aurora）；failover 時 RPO/RTO 取捨：同步複製 RPO≈0 但寫延遲增加。Logical replication 可供 CDC/跨版本遷移（見 [change-data-capture](change-data-capture.md)）。

### Data Consistency（by agents）
- **Transactions**：預設 Read Committed；Repeatable Read 為 snapshot isolation（PG 的 RR 能防 phantom 但有 write skew）；Serializable 使用 SSI，衝突時 abort，需 retry。可用 `SELECT ... FOR UPDATE`、advisory lock、unique constraint 作並發控制。
- 跨服務一致性不由 DB 負責 → saga / outbox。見 [payment-system](../../hellointerview-breakdowns/payment-system.md)。

### When to Use PostgreSQL (and When Not To)（by agents）
- **適用**：預設選擇——關聯資料、需要交易、複雜查詢、中等規模（單機＋replica 常可撐到相當大）。
- **When to Consider Alternatives**：
  - 極高寫入／水平擴展為核心（>10^5 writes/s、多區）→ Cassandra / DynamoDB。
  - 大規模全文/相關性搜尋 → Elasticsearch（搭配 CDC 同步）。
  - 時序／metrics 大量 append → TimescaleDB / ClickHouse / TSDB。
  - 巨量分析（OLAP）→ 列式倉儲。
  - 簡單 KV、極低延遲 → Redis / DynamoDB。
  - 但別過早：先確認單機＋replica＋partition 真不夠。

### Summary（by agents）
Postgres 是強預設；面試要點是點出 index 設計、replica lag、單主寫入上限、何時及如何走向 partition/shard/專用引擎。

### Appendix: Basic SQL Concepts（by agents）
- **ACID**：Atomicity（全做或全不做，靠 WAL/undo）、Consistency（約束、FK 維持不變式）、Isolation（並發交易互不干擾，視 isolation level）、Durability（commit 後經 WAL fsync 不丟）。
- **SQL 類型**：DDL（CREATE/ALTER）、DML（INSERT/UPDATE/DELETE）、DQL（SELECT）、DCL（GRANT）、TCL（COMMIT/ROLLBACK）。
- **為何重要**：金流、庫存、預訂等需要正確性的領域。

## 關鍵數字（by agents，附來源）
- Page 預設 8 KB（PostgreSQL 官方文件）。
- 單機寫入 10^3~10^4 TPS、讀 10^4~10^5 QPS：經驗量級，依硬體/schema，非官方保證。
- 每個連線是一個 OS process，建議以連線池控制在數百內（PostgreSQL wiki / PgBouncer 文件的一般建議）。
- XID 為 32-bit，約 20 億交易需 vacuum freeze 避免 wraparound（PostgreSQL 官方文件 Routine Vacuuming）。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)
- [yelp](../../hellointerview-breakdowns/yelp.md)
- [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)
- [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)

## 自測問題（by agents）
1. 如何擴展 Postgres 讀取？答：read replica（接受 lag）、cache、index/查詢優化；需 read-your-writes 時回主庫。
2. 單主寫入瓶頸如何處理？答：批次、減 index、partition、queue 緩衝，最後 sharding（犧牲跨 shard 交易）。
3. 何時 Postgres 不是好選擇？答：極高寫入水平擴展、全文相關性搜尋、巨量 OLAP、簡單 KV。
4. 為何不為每欄加 index？答：寫入變慢、佔空間、planner 可能不用。
5. 長交易的危害？答：阻擋 vacuum 造成 bloat，甚至 XID wraparound 風險。

## 參考來源
- PostgreSQL docs: https://www.postgresql.org/docs/current/
  - Indexes: .../indexes.html；Routine Vacuuming: .../routine-vacuuming.html；High Availability / Replication: .../high-availability.html；Transaction Isolation: .../transaction-iso.html
- PgBouncer: https://www.pgbouncer.org/
- Citus: https://www.citusdata.com/
（以上引用自既有知識；2026-10-19 已確認連結可開啟（HTTP 200），內容未逐條比對。）
