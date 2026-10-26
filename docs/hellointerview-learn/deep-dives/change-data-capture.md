# Change Data Capture
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/change-data-capture ｜ 分類：deep-dives

## 一句話重點
CDC 讀取資料庫 replication log（WAL/binlog）把「資料的變化」串流給下游，避免 dual write 的不一致；適合「下游只需要一份資料副本」，不適合「下游需要知道為什麼變」的業務事件。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：需要讓兩個資料儲存保持同步時（主 DB → search index、OLTP → data warehouse），答案通常是 CDC：讀取 DB 的 replication log 並傳播變更。CDC 常是對的工具，但候選人也常在不適合時濫用。CDC 在消費者只需要資料副本時最好用；當消費者需要知道「為什麼」變動時會出現微妙的正確性問題。文中以 Postgres + Elasticsearch 商品目錄為例，指出 dual write（應用同時寫兩邊）在其中一邊失敗時會不一致。

章節標題（原文）：
- What is CDC（Dual writing / How CDC works）
- When to use CDC：Keeping a derived index in sync / Replicating an OLTP database into a data warehouse / Zero-downtime database migration
- When not to use CDC：Sending an email when an order ships / Invalidating a cache when a row changes / Running cleanup or background jobs after state changes
- Conclusion

## 內容（依大綱逐節）（by agents）
### What is CDC（by agents）
- **Dual write 的問題**：app 先寫 Postgres 再寫 ES，任一步失敗或 crash 即不一致；重試會造成亂序（兩個併發更新，最後寫入 ES 的不一定是最新）；沒有交易涵蓋兩個系統。
- **CDC 作法**：DB 本來就為 crash recovery / replication 寫 log（Postgres WAL via logical decoding、MySQL binlog、MongoDB oplog/change streams）。CDC 工具（Debezium、AWS DMS、Maxwell、Flink CDC）以 replica 身分讀 log，轉成 change event（before/after、op、LSN）發到 Kafka。
- 優點：單一 source of truth、順序與 commit 順序一致（同一 row）、不改 app 程式、at-least-once 加上 idempotent consumer 可得到最終一致。

### How CDC works（by agents）
1. 初次：對來源做 consistent snapshot（backfill），記下 log position（LSN）。
2. 之後：從該 position 持續 tail log，輸出 event 到 Kafka（key = primary key，確保同 row 順序在同 partition）。
3. Consumer 以 upsert / delete（用 PK 與版本號 LSN）套用到目標；offset/position 持久化以便重啟續傳。
- **失效模式**：
  - replication slot 沒被消費 → Postgres WAL 堆積撐爆磁碟（最常見的生產事故）。
  - schema 變更（加欄位/改型別）要和 consumer 同步，需 schema registry。
  - 大交易、批次更新造成 event 洪流與 lag。
  - at-least-once 重複：consumer 必須 idempotent。
  - 刪除需 tombstone；跨表事件沒有全域順序。
  - 只拿到 row 的變化，沒有業務語意（見 When not to use）。

### When to use CDC（by agents）
- **Keeping a derived index in sync**：Postgres → Elasticsearch / Redis / 向量庫。消費者只要「最新狀態的副本」。可接受秒級延遲。見 [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)。
- **Replicating OLTP into a data warehouse**：Postgres → Kafka → Snowflake/BigQuery/ClickHouse；避免分析查詢拖垮主庫；取代每晚全量 dump。
- **Zero-downtime database migration**：snapshot + CDC 追上增量 → 雙向驗證 → 切流量（cutover）；回滾可反向 CDC。

### When not to use CDC（by agents）
共同原因：這些情境需要的是「業務意圖/事件」而不是「欄位變化」。
- **Sending an email when an order ships**：row 的 status 從 'packed' 變 'shipped' 不等於「出貨事件」；也可能是修資料、回填、重放造成誤發信。應該由業務邏輯顯式發出事件（transactional outbox 或直接發 domain event）。
- **Invalidating a cache when a row changes**：可以做，但有 race（cache 先被舊值重填）、延遲、多表衍生 key 難以從 row 變化推導；通常用 write-through / TTL / 在寫入路徑顯式 invalidate 更直接。若用 CDC，需版本號避免舊值覆蓋。
- **Running cleanup or background jobs after state changes**：job 需要明確的觸發與重試語意，用 queue / workflow engine（見 [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)）；CDC 的「所有 row 變化」太雜且容易重放造成重複執行。
- **判斷法則**：下游問的是「現在資料長怎樣」→ CDC；問的是「發生了什麼事、為什麼」→ 顯式事件（outbox）。

### 替代方案與比較（by agents）
| 方案 | 優點 | 缺點 |
|---|---|---|
| Dual write | 簡單 | 不一致、亂序 |
| Transactional outbox | 業務語意明確、同一交易 | 要改 app、需 relay（可用 CDC 讀 outbox 表） |
| Log-based CDC | 不改 app、順序正確 | 無語意、運維（slot、schema） |
| Trigger / polling | 易實作 | 影響效能、漏刪除 |
- 組合：outbox 表 + CDC（Debezium Outbox Event Router）常見，兼得兩者。

### 面試進階點（by agents）
- 說清楚 delivery 語意：CDC 通常 at-least-once；exactly-once 需 idempotent sink 或 Kafka transactions。
- 說明 lag 監控（source LSN vs consumer）、backfill 如何與 stream 銜接不丟不重。
- 資料一致性：目標端是 eventual consistency，read-your-writes 需要另行處理（讀主庫或帶版本）。

## 關鍵數字（by agents，附來源）
- 延遲：log-based CDC 到 Kafka 通常為 sub-second～數秒（視 batch / 負載，經驗量級）。
- Debezium 單 connector 對單一 Postgres 為單執行緒讀 slot，吞吐約數千～數萬 events/s 量級（經驗值，依 payload 而異；請以自身 benchmark 為準）。
- 風險數字：未消費的 replication slot 會讓 WAL 無限成長（PostgreSQL docs 說明），可用 `max_slot_wal_keep_size`（PG13+）設上限。

## 相關題目
- [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)
- [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)（outbox / 對帳）

## 自測問題（by agents）
1. Dual write 為何不可靠？答：兩個系統無共同交易，部分失敗與併發亂序造成不一致。
2. CDC 常見生產事故？答：replication slot 堆積 WAL 撐爆磁碟；schema 變更打壞 consumer。
3. 為何不用 CDC 發「出貨通知」？答：row 變化缺乏業務語意，回填/修資料會誤觸發；應發顯式 domain event（outbox）。
4. 如何做零停機遷移？答：snapshot + CDC 追增量、驗證、切流、保留回滾路徑。
5. CDC 的順序保證？答：同一 PK 的變更依 log 順序（Kafka 以 PK 為 key 同 partition）；跨表/跨 key 無全域順序。

## 參考來源
- Debezium docs: https://debezium.io/documentation/reference/stable/
- PostgreSQL Logical Decoding: https://www.postgresql.org/docs/current/logicaldecoding.html
- Debezium Outbox Event Router: https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
- Kleppmann, *Designing Data-Intensive Applications*, ch.11 (Change Data Capture)
（以上引用自既有知識；2026-10-19 已確認連結可開啟（HTTP 200），內容未逐條比對。）
