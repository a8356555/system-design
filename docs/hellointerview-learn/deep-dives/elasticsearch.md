# Elasticsearch
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/elasticsearch ｜ 分類：deep-dives

## 一句話重點
Elasticsearch 是建構在 Apache Lucene 之上的分散式搜尋引擎（索引 -> shard -> Lucene index -> immutable segment，核心是 inverted index + doc values）。面試中通常透過 CDC 掛在 Postgres / DynamoDB 等權威資料庫旁，當作 read-heavy、最終一致的搜尋層，而不是主資料庫。

## 它是什麼 / 核心機制
### 基本概念
- **Document**：任何 JSON 物件。**Index**：documents 的集合（類似 table；注意與「輔助資料結構的 index」同名）。**Mapping**：index 的 schema，定義欄位型別與處理方式；決定哪些欄位可搜尋。
- 型別範例：`keyword`（整值，適合 id / 精確比對、排序）vs `text`（會 tokenize，走 inverted index）；另有 nested、geo_point、geo_shape、自訂 analyzer、embeddings。
- Mapping 影響效能：把不搜尋的欄位也映射進去會增加每個 index 的記憶體開銷（例：10 欄只搜 2 欄，就別全映射）。
- 建 index 可設 shards 與 replicas 數（建好後可更新部分參數）。nested（如 reviews）vs 分開 index 取決於更新與查詢模式：很少更新、常查詢可內嵌；否則獨立 index（類似正規化 / 反正規化取捨）。

### 寫入與更新
- 新增 `POST /books/_doc`，回傳含 `_version`、`_seq_no`、`_primary_term`；`_version` 用於 optimistic concurrency control。
- 整份覆寫 PUT 有風險（併發會覆蓋）；可帶 `?version=` 只在版本符合時更新，否則報錯，由 client 處理衝突重試。`POST _update` 可只更新部分欄位。系統是分散、非同步、併發的，請求可能亂序，明確的更新語意很重要。

### 搜尋
- JSON 查詢語法：`match`、`bool`（must）、`range`、`nested` 查詢。回應含 hits、`_score`（相關性）、`_source`。
- **Geospatial**：`geo_point`（單一經緯度）、`geo_shape`（多邊形等）；`geo_distance` 查半徑內。底層使用 geohash、BKD tree（為 block storage 優化的 k-d tree 變體）、R-tree 類結構；geo_point 用 BKD tree，可在兩個維度縮小搜尋空間。可與其他 filter、sort 結合（如 2 英里內的義大利餐廳按評分排序）。
- **Sort**：欄位排序（可多欄位）、script 排序（Painless）、nested 欄位需用 nested sort。未指定時按相關性 `_score`，預設演算法與 TF-IDF 相關。
- **分頁**：
  - `from/size`：簡單，但深分頁（約超過 10,000 筆）要排序並抓取之前所有文件，成本高。
  - `search_after`：用上一頁最後一筆的 sort 值當邊界，只能往前翻，client 要保存；若期間資料有變動可能漏看或重複。
  - Cursor 式：PIT (point in time) + search_after，取得一致視圖但成本更高，用完要關閉 PIT。

### 內部架構
- Elasticsearch = 分散式協調層（叢集、API、aggregations）+ Lucene（搜尋核心）。
- **5 種 node**：Master（叢集協調、增刪 node、建刪 index，只有它能做 cluster-level 操作）、Data（存資料）、Coordinating（接 client 搜尋請求並分發 / 合併）、Ingest（轉換資料）、Machine Learning。一個實例可兼具多種角色；大型部署可專用主機。Data node 可分 hot / warm / cold / frozen。啟動時 seed nodes（master-eligible）選出單一 active master，其餘待命。
- **Data node**：將 raw `_source` 與 Lucene index 分開存放；請求分 **query phase**（用索引找出文件）與 **fetch phase**（取回文件）。理想查詢不碰 source 文件。Index 由 shard 及其 replica 組成，shard 1:1 對應 Lucene index，Lucene index 由 segments 組成。
- **Shard**：把資料與索引分散到多主機；搜尋並行打所有相關 shard，由 coordinating node 合併排序。**Replica**：shard 的完整拷貝，用於高可用與提高吞吐（shard 能處理 X TPS，Y 個 replica 約 X*Y TPS）；coordinating node 可把搜尋分散到 primary 與 replica。

### Lucene segments
- Segment 是**不可變**的索引資料容器。寫入先批次累積再 flush 成 segment；segments 太多時 merge（建新 segment、移除舊的）。
- 刪除：每個 segment 有 deleted-ID 集合，查詢時假裝不存在，merge 時才真正清除。
- 更新：舊文件 soft delete + 插入新文件，merge 時清理。所以更新比插入更貴，**不適合頻繁更新的資料**。
- 不可變的好處：寫入快、可安全快取、並行讀取簡單、易於復原、壓縮好、搜尋快；代價是需要週期性 merge 與暫時增加的儲存。
- **Inverted index**：token -> 含該 token 的文件列表；把 O(n) 掃描變 O(1) 查找（透過「重新組織資料」或「複製並重新組織」）。
- **Doc values**：欄位的 columnar、連續記憶體表示，用於排序 / 聚合（避免像 row store 讀整列），與 inverted index 互補。

### Coordinating node 與 query planning
- 解析查詢、決定哪些 node 負責、合併結果。Query planner 依統計資訊（欄位類型、熱門關鍵字、文件長度）選執行順序。例如搜 "bill nye"，"bill" 有百萬筆、"nye" 只有幾百筆，先從短的 posting list 下手，效能可差數個數量級。

## 何時用 / 何時不用
- 用：複雜搜尋（排序、過濾、排名、faceting、geo）。多數情況是透過 CDC 接到權威資料庫（Postgres、DynamoDB）。
- 不用 / 注意：
  - 通常不該當資料庫：它是 search engine；早期版本有一致性與耐久性問題（類似 CouchDB 的痛點）。要持久化的資料放別處。
  - 為 read-heavy 設計；寫入重的場景要考慮其他方案或 write buffer。像在文件裡放按讚數 / impression 計數這種頻繁更新，會讓 ES 吃力。
  - 要接受 eventual consistency，結果可能過期（有時很久）。
  - 不是關聯式 DB：盡量 denormalize，目標是 1~2 個 query 拿到結果，寫入端可能需要額外轉換邏輯。
  - 不是所有搜尋都需要它：資料量小（< 100k documents）或很少變動，直接查主資料庫通常夠用（Postgres full-text index 對許多問題已足夠）。
  - 與底層資料同步失敗會導致 drift，是常見 bug 來源。

## 面試常考的進階點
- 為何更新比插入貴、為何不適合高頻更新（immutable segment + soft delete + merge）。
- Query phase / fetch phase；shard 並行搜尋再由 coordinating node merge。
- Replica 的兩個目的：HA 與讀取吞吐。
- 深分頁策略：from/size -> search_after -> PIT。
- 同步策略：CDC（如 DynamoDB Streams）+ 如何處理 drift / 重新索引（補充）。
- Mapping 設計：只映射要搜尋的欄位、nested vs 分開 index 的取捨。
- 面試官可能要求「假設沒有 Elasticsearch，自己解釋」：能講 inverted index、segment 不可變、shard / replica、query planning 就夠（常見於 infra 偏重的職位、雲端公司）。
- 可借用的設計教訓：在對的層級用 immutability（利於快取、壓縮、免同步）；分離查詢執行與資料儲存；依存取模式選索引結構；分散式帶來 CAP 取捨；用專用資料結構（如 skip lists、finite state transducers）。

## 關鍵數字
- 預設建 index 示例：1 shard、1 replica。
- 深分頁（from/size）約 10,000 筆以上變貴。
- 資料量 < 100k documents 通常不需要 Elasticsearch。
- 其餘原文沒有給吞吐或容量數字。

## 相關題目
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)
- [Yelp](../../hellointerview-breakdowns/yelp.md)
- [Uber](../../hellointerview-breakdowns/uber.md)
- [Google News](../../hellointerview-breakdowns/google-news.md)
- [GoPuff](../../hellointerview-breakdowns/gopuff.md)（補充：地理搜尋相關）

## 自測問題
1. 為什麼更新文件比插入慢？
   - Segment 不可變，更新是 soft delete 舊文件並插入新文件，merge 時才清理。
2. Inverted index 與 doc values 各負責什麼？
   - Inverted index：term -> 文件，用於快速找出匹配；doc values：columnar 欄位值，用於排序 / 聚合。
3. 深分頁怎麼處理？
   - 避免 from/size；用 search_after，需要一致性時搭配 PIT。
4. 為什麼不該把 Elasticsearch 當主資料庫？
   - Search engine 優先、最終一致、歷史上有耐久性 / 一致性問題；應以 CDC 從權威資料庫同步。
5. 搜尋如何在叢集中執行？
   - Coordinating node 解析並規劃查詢，分發到相關 shard（primary 或 replica）並行執行 query phase，合併排序後再 fetch 文件。
