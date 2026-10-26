# Core Concepts for System Design Interviews
> 來源：https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts ｜ 分類：in-a-hurry

## 一句話重點
Core concepts 是與技術無關的基礎詞彙（網路、API、資料建模、index、cache、sharding、consistent hashing、CAP、數字感）；面試官假設你懂，並會在你提出時追問。預設選擇：HTTP/REST、normalized relational、cache-aside + Redis、最終一致性，且「不要太早 shard」。

## 核心內容
### Networking Essentials
- 預設 HTTP over TCP（涵蓋約 90% 場景）。
- **SSE vs WebSocket**：SSE 單向（client 發起 HTTP 後 server 持續推送，如比分、通知），較簡單、與標準 HTTP 基礎設施相容；WebSocket 雙向（chat、協作編輯）。兩者都是 stateful connection，不能直接丟在標準 LB 後面；要考慮連線持久性、server 掛掉時成千上萬連線怎麼辦。
- **gRPC**：二進位序列化 + HTTP/2，內部服務間效能關鍵時用；瀏覽器不原生支援（gRPC-Web 需 proxy 且功能不全）。常見做法：對外 REST、對內 gRPC。
- **Load balancing**：L7 看 HTTP 內容可依內容路由（API 與網頁導不同服務）；L4 在 TCP 層，較快但不看內容。WebSocket 通常用 L4（維持持久 TCP 連線）。
- 常見錯誤：只要提到 real-time 就上 WebSocket；long polling 或 SSE 往往已足夠。
- **地理與延遲**：紐約到倫敦光纖光速下限約 80ms；全球低延遲需區域部署、資料依地理 replicate/partition；CDN 從邊緣提供靜態內容。

### API Design
- 90% 用 REST（`/users/{id}`、`POST /events/{id}/bookings`）。
- 別花太多時間：幾分鐘內畫出 4-5 個關鍵 endpoint；10 分鐘後還在設計 API 就太深。
- 順帶提：大結果集用 pagination（cursor-based 適合即時新增資料；offset 多數情況夠用）；認證 user session 用 JWT、服務間用 API key；可能有 bot/濫用就提 rate limiting；除非被問不深入。

### Data Modeling
- **Relational（Postgres）**：結構化資料、明確關聯、強一致、SQL 複雜查詢、transaction、FK。
- **NoSQL（DynamoDB/MongoDB）**：彈性 schema、水平擴展不需複雜 join。
- **Normalization**：拆表避免重複（改一處全更新），代價是 join（大表/多表 join 昂貴）。**Denormalization**：複製資料避免 join、讀更快，代價是更新要改多處；適合讀多、資料少變。
- 面試預設：先 normalized relational，發現讀取熱點再針對性 denormalize；不要沒理由就一開始 denormalize。
- DynamoDB 要依 access pattern 設計 partition key / sort key：例「某 user 所有貼文」用 user_id 當 partition key → 單 partition 查詢快，但「提到 hashtag Y 的貼文」就得全表 scan。必須事先知道查詢。

### Database Indexing
- 無 index 找 email 要全表掃（1000 萬筆就掃 1000 萬）。
- **B-tree**（多數 RDB 預設）：支援精確查詢與範圍查詢。**Hash index**：精確匹配更快但不支援 range。專用：full-text（搜尋）、geospatial（附近餐廳）。
- 面試：依 query pattern 對常查欄位建 index（email 登入、orders.user_id）；複合查詢用 compound index（如 city + date）。
- 超出主 DB 能力 → 外部系統：Elasticsearch（全文）、PostGIS（Postgres 地理）。透過 CDC 從主 DB 同步，因此 index 會略為落後（stale），搜尋場景通常可接受。

### Caching
- 讀取壓垮 DB 時使用。Redis cache hit 約 1ms vs DB 查詢 20-50ms（約 20-50 倍）；同時降低 DB 負載。
- 90% 用 **cache-aside + Redis**：先查 cache → miss 則查 DB、寫入 cache（附 TTL）、回傳。
- **Invalidation 最難**：寫入後立即刪/更新 cache、短 TTL 接受 stale、或兩者結合，取決於新鮮度需求。
- **Cache stampede（thundering herd）**：熱門 key 過期，大量併發同時 miss 壓 DB。對策：locking（只有一個請求重建）、early recomputation、錯開 TTL。
- **Cache 整個掛掉**：請求全打 DB。防禦：小型 in-process fallback cache、circuit breaker 卸載流量、graceful degradation。
- 錯誤：什麼都 cache。只 cache 常讀且不常變的；先 profile。
- CDN caching：靜態資源（圖、影片、JS）。In-process cache：小且少變的值（feature flag、config）。核心應用資料預設用外部 Redis。

### Sharding
- 觸發：單機儲存上限（單一 Postgres 約到 TB 等級）、寫入吞吐上限（每秒數萬）、replica 也撐不住的讀取。
- **Shard key** 最關鍵：如 Instagram 依 user_id → 同一用戶的 posts/likes/comments 同 shard，user 範圍查詢快；全域查詢（trending）要打所有 shard 再聚合。
- 方式：**Hash-based**（hash key 取 modulo，分布均勻避免 hot spot，最常用）；**Range-based**（access pattern 自然分區如多租戶 SaaS 才適合，易產生 hot spot）；**Directory-based**（查表決定位置，彈性但多一個依賴與每次請求延遲，面試很少值得用）。
- 最大錯誤：太早 shard。調校好的單 DB + read replicas 能做的比多數人想像多。先做容量計算：10K writes/s、100GB 不需要 shard。
- 新問題：跨 shard transaction 幾乎不可行（需 distributed transaction 或 saga，複雜且慢），所以 shard 邊界要避免；hot spot（Taylor Swift 的 shard）；resharding 痛苦要搬大量資料。
- 面試：先證明單 DB 不夠 → 講 shard key → 講 trade-off（對 X 查詢快、對 Y 慢）。

### Consistent Hashing
- 問題：`hash(key) % N` 在增減 server 時 N 變，幾乎所有 key 重新對應。
- 解法：server 與 key 都放在 hash ring，key 歸屬順時針遇到的第一個 server；新增 server 只需搬它與前一個 server 之間的 key；移除則只搬到下一個 server。
- 效果：10 台叢集加一台，modulo 約搬 90%，consistent hashing 約 10%。
- 使用處：Memcached / Redis Cluster、Cassandra / DynamoDB sharding、部分 LB、CDN 路由。
- 面試：通常一句話帶過（"use consistent hashing to distribute data across cache nodes"）；談 elastic scaling（動態增減 cache 節點/shard）時一定提。

### CAP Theorem
- Consistency / Availability / Partition tolerance 三取二；分散式系統 partition 不可避免，實際是 C vs A 的取捨。
- 選 C：partition 時部分節點拒絕服務以免回傳過期資料；選 A：持續服務，但各節點可能暫時不同步。
- 多數系統預設 availability + **eventual consistency**（保證無新更新時最終收斂；不同於 weak consistency 不保證收斂）：社群 feed、推薦、分析 dashboard。
- 強一致用於 stale 會造成實際商業損失：庫存（超賣）、銀行餘額（詐欺）、訂票（重複訂位，如 Ticketmaster）。
- 同一系統可混合：商品描述/評論最終一致；庫存與訂單處理強一致。
- **PACELC**：Partition 時選 A 或 C；Else（正常）選 Latency 或 Consistency——強一致即使網路健康也因節點需協調而增加延遲。
- 面試：被問一致性時安全答案是 eventual，除非涉及金錢、庫存、有限資源預訂。

### Numbers to Know
- 現代硬體比多數人想的強：調校良好 DB 每秒數萬 query；單台 Redis 每秒數十萬 ops。用 2010 年的數字會太早提 shard/cache。
- 延遲階層：記憶體 ns、SSD μs、資料中心內網路 1-10ms、跨洲 數十到數百 ms。
- 容量計算「在需要時」做：例「50K RPS、每台約 5K → 約 10 台加 headroom」。
- 單一 Postgres 可舒適處理數 TB；在 500GB 提 sharding 是白增複雜度。

## 面試怎麼用
- 提出元件時就預期會被追問（為什麼 cache？key 怎麼 invalidate？shard key 選什麼？）。
- 預設值清單：REST、normalized relational、cache-aside Redis、eventual consistency、先單 DB + replicas。
- 陷阱：亂用 WebSocket、太早 shard、什麼都 cache、API 設計花太久、沒量化就說 shard。

## 關鍵數字
| 元件 | 指標 | 擴展觸發 |
|---|---|---|
| Caching | ~1ms 延遲；100k+ ops/s；受記憶體限制（至 1TB） | hit rate < 80%；latency > 1ms；memory > 80%；cache churn/thrashing |
| Databases | 至 50k TPS；快取後讀取 < 5ms；64 TiB+ 儲存 | 寫入 > 10k TPS；uncached 讀取 > 5ms；需地理分布 |
| App Servers | 100k+ 並發連線；8-64 cores @ 2-4GHz；64-512GB RAM（至 2TB） | CPU > 70%；延遲超 SLA；連線近 100k/instance；memory > 80% |
| Message Queues | 每 broker 至 1M msgs/s；端到端 < 5ms；至 50TB | 吞吐近 800k msgs/s；partition 數約 200k/cluster；consumer lag 增長 |
- 其他：Redis hit ~1ms vs DB 20-50ms；NY–London 最低約 80ms；modulo 加機器搬約 90% vs consistent hashing 約 10%。

## 相關題目
[distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)、[ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)、[whatsapp](../../hellointerview-breakdowns/whatsapp.md)、[fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)、[fb-news-feed](../../hellointerview-breakdowns/fb-news-feed.md)

## 自測問題
1. SSE 與 WebSocket 差在哪、何時選哪個？（SSE 單向 server push、簡單；WebSocket 雙向，需 client 頻繁上傳時才用）
2. 什麼時候該 shard？（單 DB 的儲存/寫入/讀取超出上限，經容量計算證明後；例如 10K writes/s、100GB 不需要）
3. Consistent hashing 解決什麼？（增減節點時只搬少量 key，而非 modulo 的幾乎全搬）
4. 何時選強一致？（金錢、庫存、訂位等 stale 會造成實際損失；其餘預設 eventual）
5. Cache stampede 怎麼防？（locking、early recomputation、錯開 TTL）
