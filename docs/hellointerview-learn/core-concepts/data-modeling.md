# Data Modeling
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/data-modeling ｜ 分類：core-concepts

## 一句話重點
面試的 data modeling 門檻遠低於專門的 data modeling 面試：預設 PostgreSQL，由 requirements/API 推導 entities、keys、indexes，先 normalize 再視需要 denormalize，並選與主要 access pattern 相符的 shard key。

## 核心內容

### 在 Delivery framework 出現兩次
1. 需求階段：識別 core entities（通常 1:1 對應 table / collection）。
2. High-Level Design：在 DB 元件旁畫基本 schema：關鍵欄位、關係，以及為主要 query pattern 做的 index / partition 備註。
- 不需要完全 normalize 或完整 schema 圖，只要清楚、可用、符合需求。壞的 model 日後痛，好的「夠用」model 讓討論聚焦。

### Database Model Options
面試誘惑是選冷門 DB 炫技，要抵抗。**關係型 DB 是預設**，除非需求明確指向特殊模型；除非有很強意見，就選 PostgreSQL。

| 類型 | 特性 | 何時優於 SQL | 對 data modeling 的影響 | 技術 |
|---|---|---|---|---|
| Relational (SQL) | 固定 schema 的 table、foreign key、ACID | 預設；強一致需求（付款不重複扣款、庫存不超賣）；複雜 query 與 join | 正規化、FK 約束 | PostgreSQL, MySQL, SQLite |
| Document | JSON-like 文件、彈性 schema | schema 常變、深層巢狀資料、各筆結構差異大（有人工作經歷很多、有人很少）。面試通常需求固定，沒有「schema 演進」，所以很少需要；除非面試官明說資料結構快速變動 | 積極 denormalize、內嵌關聯資料；省 join 但更新要改整份文件，犧牲儲存空間與更新複雜度換讀取效能 | MongoDB, Firestore, CouchDB |
| Key-Value | 以精確 key 查詢，極快但 query 能力有限 | cache、session、feature flags、只用單一 ID 查、高寫入場景。實務常與 SQL 並用：SQL 當 source of truth，Redis 在前面放熱資料 | schema 很扁平，大量 denormalize、為不同 access pattern 複製多份；讀快但資料變動時一致性很差 | Redis, DynamoDB, Memcached |
| Wide-Column | column family，列可有不同欄位；針對大量寫入、time-series 最佳化 | 巨量寫入、時序、append + aggregation 的分析（telemetry、event logging、IoT）。新貼文：新增 row，key = (user_id, timestamp)；同 partition key 存在一起，寫入只是 append、讀取為連續範圍掃描 | 比 SQL 更依 query pattern 設計，常跨 column family 複製資料；時間是一等公民 | Cassandra, HBase |
| Graph | nodes 與 edges，最佳化關係遍歷 | 「老實說？面試幾乎不用」。Facebook 社交圖用 MySQL，LinkedIn、Twitter 核心關係也用 SQL | — | Neo4j, Amazon Neptune |

- 原文警告：graph DB 是面試常見錯誤，聽起來高級但增加不必要的複雜度。
- SQL 擅長複雜 query（如「我追蹤的人的貼文依時間排序」靠 join），但多表 join 在規模大時是效能陷阱；面試中提到報表式複雜 query 可能引起效能疑慮，要想 denormalized view、cache 或預先計算。
- 「SQL 不能擴展」常被誇大：read replicas、sharding、connection pooling、caching；Facebook、Airbnb 都建在關係型基礎上。

### Schema Design Fundamentals
**從需求出發：三個因素**
- **Data volume**：決定資料能放哪；資料需分散到多個 store 時，schema 要考慮彼此如何引用。
- **Access patterns（最重要）**：由 API 自然導出——問「每個 endpoint 要支援什麼 query？」。news feed「追蹤對象的最新貼文」暗示 denormalized 資料或精心設計的 index；分析 dashboard 的時間聚合需要不同表結構。
- **Consistency requirements**：金融交易需強一致（同一 DB + ACID）；activity feed 可最終一致，可分散到不同系統與 schema。
- 話術：「因為 feed 要快速載入且 like 可最終一致，我把 like count denormalize 進 posts 表。」展現推理，不是背模式。後面所有技術（entities、keys、normalization、indexes、sharding）都是解決這三個因素的工具。

**Entities, Keys & Relationships**
- 用**系統產生的 ID**（user_id、post_id）當 primary key，而非 email 等業務資料（業務規則變動時 ID 仍穩定）。
- 社群 app 範例：`users(id PK, username, email)`、`posts(id PK, user_id FK, content, created_at)`、`comments(id PK, post_id FK, user_id FK, content)`、`likes(user_id FK, post_id FK)`。
- 關係：1:N（user→posts）、N:M（users↔liked posts）、1:1（少見，常是兩表該合併的訊號）。
- SQL 用 FK 強制；NoSQL 靠應用層。FK 保證 referential integrity（防孤兒資料），但每次 insert/update 要驗證；極大規模時有公司會拿掉 FK、在應用層保證完整性。面試提到取捨是加分。
- 再加 NOT NULL / UNIQUE / CHECK 等 constraint，保護資料品質但增加寫入開銷。
- Schema 要貼近問題領域（users、tweets、follows），不要用抽象的 "entities"。

**Indexing for Access Patterns**
- Index 像書後的索引，避免全表掃描。面試要點名哪些欄位有 index、為什麼。
- 社群 app 例：`posts.user_id`（某使用者的貼文）、`posts.created_at`（時間序）、composite `(user_id, created_at)`（某使用者最近貼文）。
- 將 index 對應到 API：「`GET /users/{id}/posts` 需要 `posts.user_id` index」。細節見 Database Indexing。

**Normalization vs Denormalization**
- Normalization：每項資訊只存一處，避免更新異常。Denormalized 版本中，使用者改名需更新其所有貼文，漏一筆就不一致。
- 面試：**先給乾淨的 normalized model，需要時才 denormalize**；重複資料造成的一致性問題比你想解的效能問題更難處理。
- 可 denormalize 的例外：分析/報表系統（聚合不常變的資料）、event log 與 audit trail（記錄當下快照）、重讀取優化系統如 search engine（速度優先於一致性）。
- 替代做法：source of truth 維持 normalized，在前面放 cache 存 denormalized 表示（預先 join / 聚合）。

**Scaling and Sharding**
- 資料量超過單機就 shard；目標是讓相關資料在一起。
- **依主要 access pattern shard**：主要查「某使用者的貼文」→ 以 user_id shard，避免跨 shard query。
- **小心 time-range sharding**：看似適合「最近貼文」，但所有新寫入打在同一個最新區間→ hot shard，寫入重的系統通常是 anti-pattern；較適合寫入分散、近期資料讀取多的 archival / analytics。
- 避免 cross-shard query：若依 user_id shard，時間軸要看多個被追蹤者貼文就得查多個 shard 再合併，昂貴複雜。
- shard key 選擇通常是永久的，影響每個 query。

### 結論清單（上 DB 元件時）
1. 決定 DB 類型
2. 列出滿足功能需求的各 entity 欄位
3. 指定 PK / FK 與關係
4. 決定哪些欄位需要 index
5. 判斷是否需要 denormalize
6. 判斷是否需要 sharding；需要則選與主要 access pattern 匹配的 shard key

## 面試怎麼用
- 何時：需求階段列 entities；HLD 畫 DB 時附 schema。
- 怎麼說：「用 PostgreSQL；post_id 是 PK 方便 comments / likes 引用；`GET /users/{id}/posts` 需要 user_id index；likes 可最終一致，所以 count denormalize 進 posts。」
- 陷阱：選 graph / document DB 炫技；一上來就 denormalize；時間範圍 shard 造成 hot shard；忘了 index 與 API 的對應；花太多時間畫完整 schema；用 email 當 PK。

## 關鍵數字
原文無具體數字。

## 相關題目
- [instagram](../../hellointerview-breakdowns/instagram.md)
- [fb-news-feed](../../hellointerview-breakdowns/fb-news-feed.md)
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)

## 自測問題
1. 為何預設選 PostgreSQL / SQL？答：多數題目的 entity 有明確關係，需要 ACID 與 join；SQL 也能靠 replica、sharding、cache 擴展。
2. 什麼情況才考慮 document DB？答：面試官明說 schema 常變、深層巢狀、各筆結構差異大。
3. 決定 schema 的三個因素？答：data volume、access patterns（最重要）、consistency requirements。
4. 何時 denormalize？答：先 normalize；分析/報表、audit log、search 等讀取優先系統才 denormalize；或用 cache 持有 denormalized 副本。
5. 為何 time-range sharding 常是壞主意？答：新寫入全落在最新區間，形成 hot shard。
