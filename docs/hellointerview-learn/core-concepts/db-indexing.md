# Database Indexing
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/db-indexing ｜ 分類：core-concepts

## 一句話重點
Index = 為了「少讀 page」而額外維護的搜尋結構；用寫入成本與空間換讀取速度。預設選 B-tree，寫入密集選 LSM，純等值查詢可用 hash，地理用 geohash/quadtree/R-tree，全文用 inverted index，多欄查詢靠 composite / covering index 的欄位順序。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：在百萬筆資料的表中用 email 找 user，沒有 index 就得逐 row 全表掃描；index 是獨立維護、為搜尋最佳化的資料結構。何時加 index、加在哪些欄位、用哪種 index 是面試常考重點；mid-level 要懂基本策略，staff-level 要精通各類 index 與 trade-off。原文並提到 indexing / data organization 在 infrastructure 類面試比重較高。

章節標題（原文）：
- How Database Indexes Work
  - Physical Storage and Access Patterns
  - Cost
- Types of indexes
  - B-Tree Indexes（The Structure of B-trees / Real-World Examples / Why B-trees are the default choice）
  - LSM Trees（How LSM Trees Work / Negative Impact on Reads / Real-World Examples）
  - Hash Indexes（How Hash Indexes Work / Real-World Usage / When to Choose Hash Indexes）
  - Geospatial Indexes（The Challenge with Location Data / Core Approaches / Geohash / Quadtree / R-Tree）
  - Inverted Indexes
- Index Optimization Patterns
  - Composite Indexes（The Order Matters）
  - Covering Indexes
- Wrapping Up

## 內容（by agents）
### How Database Indexes Work（by agents）
- **機制**：table 以 heap file 儲存（無序 row，分成固定大小 page，PostgreSQL 預設 8KB）。DB 只能處理記憶體中的 page，所以成本單位是「讀了幾個 page」。無 index → seq scan，讀 N 個 page；有 index → 沿樹走 3-4 層就到目標 page。
- **Physical storage**：即使是 SSD，random IO 仍比 sequential 慢且有 IOPS 上限；index 把「讀全表」變成「少量 random read」。buffer pool 會把熱的 index 上層節點留在記憶體，所以實際磁碟讀更少。
- **Cost**：每個 index 佔空間（有時接近表本身）；每次 INSERT/UPDATE/DELETE 都要更新所有相關 index（write amplification）；UPDATE 到被索引欄位無法走 HOT update（PostgreSQL）。
- **何時不用**：寫多讀少的 log 表、低選擇度（selectivity）欄位（如 boolean，planner 反而選 seq scan）、小表。
- **進階點**：index 太多會拖慢寫入、拉長 vacuum / replication lag；要用 `EXPLAIN (ANALYZE)` 驗證有走到；定期查 unused index（`pg_stat_user_indexes`）。

### B-Tree Indexes（by agents）
- **結構**：多叉平衡樹，節點大小 = 一個 page，fan-out 數百；所有 leaf 同深度。實務多為 B+tree（資料/指標在 leaf，leaf 以鏈結串列相連 → range scan 很快）。10 億筆資料通常也只有 3-4 層。
- **能力**：等值、範圍、ORDER BY、prefix（LIKE 'abc%'）、MIN/MAX。
- **實例**：PostgreSQL PK / UNIQUE 皆為 B-tree；MySQL InnoDB 的 PK 是 clustered index（leaf 存整列），secondary index leaf 存 PK 值（回表需再查一次）；MongoDB 用 B-tree 類結構。
- **失效模式**：隨機 key（UUIDv4）作 PK 造成 page split 與 cache 不友善 → 偏好 time-ordered ID（UUIDv7/ULID/snowflake）；對欄位套函式（`WHERE lower(email)=...`）會讓 index 失效，需 expression index。

### LSM Trees（by agents）
- **機制**：寫入先進記憶體 memtable（同時寫 WAL），滿了 flush 成不可變 sorted 檔（SSTable）；背景 compaction 合併多層。寫入全為 sequential append → 寫吞吐極高。
- **對讀的負面影響**：一次 read 可能要查 memtable + 多個 SSTable（read amplification）；用 Bloom filter 跳過不含 key 的檔、用 block cache 緩解。Compaction 帶來 write amplification 與 latency spike。
- **實例**：Cassandra、RocksDB、LevelDB、HBase、ScyllaDB、DynamoDB（儲存層普遍認為屬 LSM 風格，AWS 未完整公開）。
- **何時用**：metrics / log / time-series / 事件寫入密集（呼應 metrics-monitoring）。**何時不用**：讀多、需要大量 secondary index 與 range 掃描的 OLTP。
- **進階點**：compaction 策略（size-tiered 偏寫、leveled 偏讀與空間）；tombstone 堆積導致讀變慢（Cassandra 經典坑）。

### Hash Indexes（by agents）
- **機制**：key → hash → bucket，等值查詢 O(1)；不保序，無法 range / ORDER BY / prefix。
- **實例**：PostgreSQL hash index（10+ 起有 WAL，可用但少用）；Redis / memcached 本質是 hash table；Bitcask 風格 log-structured hash（記憶體 keydir）。
- **何時選**：僅等值 lookup 且想省空間/CPU；多數情況 B-tree 等值已夠快，所以面試中「預設 B-tree」較安全。
- **失效**：hash collision、resize（rehash）成本、無法 range。

### Geospatial Indexes（by agents）
- **挑戰**：經緯度是二維，B-tree 只能對一維排序，「附近 5km」無法有效用兩個獨立 B-tree 解。
- **Geohash**：把二維座標交錯編碼成 base32 字串，前綴相同 = 同一格；可用字串 prefix 的 B-tree 查。缺點：格子邊界問題（相鄰兩點前綴可能完全不同），需查周圍 8 格；格子大小固定，密度不均。
- **Quadtree**：遞迴把平面切四塊，格內點數超過閾值再切；適應密度不均（市中心深、郊區淺）；通常在記憶體中維護，更新/重平衡要處理。
- **R-tree**：用 bounding box 包住鄰近物件的階層結構，支援矩形/多邊形，PostGIS（GiST）、MySQL spatial、Elasticsearch BKD 類結構採用。適合有範圍的物件（餐廳區域、配送範圍）。
- **選擇**：點資料 + 簡單 → geohash（Redis GEO、DynamoDB 常見）；密度極不均、記憶體內 → quadtree；需複雜幾何 → R-tree/PostGIS。呼應 yelp、uber 類題目。

### Inverted Indexes（by agents）
- **機制**：term → posting list（含 doc id、位置、頻率）；查詢時對多個 term 的 posting list 做 intersect / union，再用 BM25 排序。
- **實例**：Elasticsearch / Lucene、PostgreSQL GIN（`tsvector`）、MySQL FULLTEXT。
- **進階點**：index 建立需 analyzer（tokenize、stemming、stop words）；更新是 segment 不可變 + 背景 merge，因此「近即時」非即時；與 OLTP 通常透過 CDC 同步（見 change-data-capture）。

### Composite Indexes（by agents）
- 多欄 index `(a, b, c)` 依 **leftmost prefix** 生效：可支援 `a`、`a,b`、`a,b,c` 的查詢，不支援單獨 `b`。
- **欄位順序**：等值條件欄位在前、範圍條件欄位在後；選擇度高者通常在前；若要同時避免 sort，順序需與 ORDER BY 對齊。例：`(user_id, created_at)` 可高效處理「某使用者最新 20 篇貼文」。
- **失效**：範圍條件之後的欄位無法再縮小掃描範圍；OR 條件、函式包欄位。

### Covering Indexes（by agents）
- **機制**：index 已含查詢所需的全部欄位 → index-only scan，不回表（PostgreSQL `INCLUDE`、MySQL 把欄位放入 composite）。
- **取捨**：index 變胖、寫入變慢；適合高頻、欄位少且固定的查詢（如 feed 列表）。PostgreSQL 還受 visibility map 影響，需 vacuum 才能真正 index-only。

### Wrapping Up（by agents）
面試回答模板：先說「查詢 pattern 是什麼」→ 選 index 類型 → 說明欄位順序 → 說出寫入成本與監控方式。不要「每個欄位都加 index」。

## 關鍵數字（by agents，附來源）
| 項目 | 量級 | 條件/來源 |
|---|---|---|
| PostgreSQL page 大小 | 8 KB（預設） | PostgreSQL 官方文件 Database Page Layout |
| B-tree 深度 | 10^9 筆通常 3-4 層 | fan-out 數百的估算（by agents 推算） |
| SSD random read 4KB | ~150 µs（2012 舊表）；現代 NVMe 約 ~10-100 µs | Jeff Dean / Colin Scott latency numbers（gist，約 2012，估算用） |
| 記憶體存取 | ~100 ns | 同上 |
| 磁碟 seek | ~10 ms（HDD） | 同上 |

## 相關題目
- [yelp](../../hellointerview-breakdowns/yelp.md)（geospatial index、composite index）
- [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)（inverted index）
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)（LSM / time-series 寫入）
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（unique / composite index 防重複）

## 自測問題（by agents）
1. 為何 B-tree 比 binary tree 更適合 DB？答：fan-out 大、節點對齊 page，樹高低、IO 次數少；leaf 鏈結支援 range。
2. 有 index `(a,b,c)`，`WHERE b=1` 會用到嗎？答：通常不會（違反 leftmost prefix），除非 planner 做 skip scan（部分 DB 支援）。
3. 寫入密集 metrics 系統選 B-tree 還是 LSM？答：LSM，sequential 寫 + compaction；代價是讀放大，用 Bloom filter 緩解。
4. 「附近的餐廳」為何不能對 lat、lng 各建 B-tree？答：兩個一維 index 各自回傳大量候選再交集，無法有效剪枝；需 geohash / quadtree / R-tree。
5. 何謂 covering index，代價？答：index 含全部查詢欄位，免回表；代價是 index 更大、寫更慢。

## 參考來源
- PostgreSQL docs, Indexes: https://www.postgresql.org/docs/current/indexes.html
- PostgreSQL docs, Index-Only Scans and Covering Indexes: https://www.postgresql.org/docs/current/indexes-index-only-scans.html
- Latency Numbers Every Programmer Should Know (gist, 約 2012): https://gist.github.com/jboner/2841832（已實際擷取）
- Kleppmann, *Designing Data-Intensive Applications*, ch.3 Storage and Retrieval（B-tree vs LSM）
