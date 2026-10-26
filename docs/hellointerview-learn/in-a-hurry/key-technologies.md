# Key Technologies
> 來源：https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies ｜ 分類：in-a-hurry

## 一句話重點
面試要懂的是涵蓋 90% 題目的「元件類別」（DB、blob storage、search、API gateway、LB、queue、stream、distributed lock、cache、CDN），每類至少會一種；先廣度再深度，且別做 SQL vs NoSQL 的籠統比較。

## 核心內容
面試官探測的深度與你的 level 成正比：mid-level 能說 Elasticsearch 是 search index 即可；senior 說不出 inverted index 與其 scaling 就是 yellow flag。

### Core Database
- 選一種就好：product design 為主 → relational（Postgres）；infrastructure design 為主 → NoSQL（DynamoDB）。
- 陷阱：硬插入 SQL vs NoSQL 比較。「因為有關聯所以用 relational」「因為要 scale 所以用 NoSQL」都是 yellow flag（兩者高度重疊）。好的說法：「用 Postgres 因為 ACID 可維持資料完整性」，談你選的 DB 的具體特性如何解題。

**Relational（Postgres / MySQL；無偏好選 Postgres）**
- 表/列/欄、SQL；product design 的預設選擇，常用於交易型資料。
- 必知：**Joins**（可任意 join，但常是效能瓶頸，盡量減少）、**Indexes**（B-Tree / Hash，可建任意多個、多欄與特殊 index 如 geospatial、full-text）、**Transactions**（多操作原子化，如建立 user 與 post 同時成功或失敗）。

**NoSQL（DynamoDB、Cassandra、MongoDB）**
- 資料模型：key-value、document、column-family、graph；多半 schema-less、易水平擴展。適合：資料模型常變、需水平擴展、大量/即時資料。
- 但 relational 也能有 JSON 欄位、也能水平擴展——不要做籠統宣稱。
- 必知：data model、consistency model（strong 到 eventual）、indexing、scalability（consistent hashing / sharding）。
- DynamoDB 是原文偏好之一（功能廣、被廣泛接受）；Cassandra 適合 write-heavy（append-only storage model），但功能有取捨。

### Blob Storage
- 圖片、影片、檔案等大型非結構化資料：不要放傳統 DB（貴且低效），用 S3 / GCS / Azure Blob，並常搭配 CDN（blob 為 origin，CDN 在邊緣快取）。
- 不要把 S3 當主資料庫；標準做法：核心 DB（Postgres/DynamoDB）存指向 blob 的 URL/metadata，利於低延遲查詢與索引。例：YouTube、Instagram、Dropbox 皆「blob 存檔案、DB 存 metadata」。
- **上傳流程**：client 向 server 要 presigned URL → server 回傳並記錄到 DB → client 直傳 blob storage → storage 觸發通知給 server，更新狀態。**下載**：client 向 server 要檔案 → 得到 presigned URL → 經 CDN（代理到 blob storage）下載。
- 必知：Durability（replication + erasure coding）、Scalability（視為無限，不必在面試特別考慮）、Cost、Security（加密、存取控制）、client 直傳直下載（presigned URL）、Chunking（大檔分塊，可續傳、可平行；S3 multipart upload API）。
- 成本例：S3 $0.023/GB/月（前 50TB）vs DynamoDB $1.25/GB/月（前 10TB）。不熟就選 S3（最被面試官理解，其他平台也常有 S3 相容 API）。

### Search Optimized Database
- 全文搜尋若用 `LIKE '%term%'` 需全表掃描，不 scale。
- 搜尋型 DB 建 **inverted index**（word → documents 對應），搭配 tokenization（切詞）、stemming（還原詞根，running/runs → run）、fuzzy search（edit distance 容忍拼字錯）；透過加節點 + sharding 擴展。
- 例：Ticketmaster 搜活動、Twitter 搜推文。領導者 **Elasticsearch**（分散式、REST、建於 Lucene；Netflix、Uber、Yelp 使用）。替代：Postgres GIN index 做 full-text、Redis 的 full-text（原文評價「quite immature and bad」）；用現有 DB 可縮小 footprint。

### API Gateway
- 微服務前的入口：路由請求到對應服務，處理 auth、rate limiting、logging 等 cross-cutting concerns。
- 幾乎所有 product design 面試都建議畫在 client 第一接觸點；面試官很少深挖。常見：AWS API Gateway、Kong、Apigee；nginx/Apache 也可。

### Load Balancer
- 水平擴展時分散流量。面試中視為黑盒；不需在每個服務前都畫，只畫在最前面或口頭說明服務已水平擴展。
- 有時需 sticky sessions / persistent connections。**L4 vs L7 rule of thumb**：有 WebSocket 等持久連線 → L4；否則 L7（彈性路由、減少下游連線負擔）。
- 常見：AWS ELB、NGINX、HAProxy；極高流量時專用硬體 LB 勝過軟體。

### Queue
- 用途：緩衝突發流量、分散工作；producer 丟了就忘，worker pool 依自己速度處理。例：1,000 請求突發、每秒只能處理 200 → 800 排隊而非丟失。解耦、獨立擴展。
- 警告：同步且延遲要求嚴格（如 < 500ms）的流程加 queue 幾乎一定破壞延遲限制。
- 例：Uber 尖峰叫車緩衝；照片處理分配給 worker nodes。
- 必知：Message ordering（多為 FIFO；Kafka 有更複雜排序保證）、Retry 機制、**Dead Letter Queue**（無法處理的訊息，供除錯稽核）、Partitioning（需 partition key 讓相關訊息在同一 partition）、**Backpressure**（系統 200/s 但進來 300/s，queue 只是掩蓋容量不足；queue 滿時拒絕或減速並回錯誤）。
- 常見：Kafka、SQS（AWS 全託管）。

### Streams / Event Sourcing
- 與 queue 不同：stream 可保留資料一段時間，consumer 可從某位置或過去時間重讀。
- 適用：(1) 即時處理大量資料（社群互動 analytics，用 Flink / Spark Streaming）；(2) event sourcing（銀行每筆交易為 event，可 replay、稽核、回滾、重建任意時間點狀態）；(3) 多 consumer 讀同一 stream（chat room pub/sub）。
- 必知：Partitioning 擴展、Multiple consumer groups（同一資料不同處理，如一組更新 dashboard 另一組入庫）、Replication、Windowing（依時間/次數分組，如過去 24 小時各區平均送達時間）。
- 常見：Kafka、Flink、Kinesis。

### Distributed Lock
- 需要跨系統/行程、較長時間鎖資源（如 Ticketmaster 鎖票約 10 分鐘）；傳統 DB transaction lock 不是為長時間鎖設計。
- 實作：Redis 或 ZooKeeper 等 KV store，用原子性確保單一持有者；可設 expiry 避免 process crash 後鎖卡死。
- 例：電商 checkout 保留限量商品、叫車媒合鎖司機、分散式 cron 只由一台執行、拍賣最後時刻處理出價。
- 必知：機制（Redis 上的 Redlock，用多個 Redis 實例）、Lock expiry、Granularity（單一資源或一組，如單張票 vs 整區）、**Deadlocks**（兩 process 互等；避免鎖散落在遠處基礎設施/程式碼中使其難以辨識與預防）。

### Distributed Cache
- 用途：存昂貴計算/查詢結果。例：預先算好的聚合 metrics（背景 job 每小時算）、user session 降低 DB 負載、加速複雜查詢（Twitter 追蹤者貼文 list 的 join，跑一次後存 cache）。
- 必知：**Eviction**（LRU、FIFO、LFU）；**Invalidation strategy**（如 Ticketmaster 活動場地變更需 invalidate）；**Write strategy**：Write-Through（同寫 cache 與 datastore，一致但寫較慢）、Write-Around（直寫 datastore 繞過 cache，減少 cache pollution 但後續讀較慢）、Write-Back（先寫 cache 再非同步寫 datastore，寫快但 cache 掛掉會丟資料）。
- 要明說 cache 存什麼、用什麼資料結構（例：活動列表用 sorted set 取熱門），別只說「存進 cache」。
- Redis（strings、hashes、lists、sets、sorted sets、bitmaps、hyperloglogs）vs Memcached（簡單 KV）。

### CDN
- 以地理位置就近提供內容的分散式快取；請求→最近邊緣；miss 則向 origin 取、快取、回傳。
- 最常見：快取靜態媒體（Instagram 頭像）。也可快取動態內容（一天更新一次的 blog）與 API 回應。有 TTL / invalidation。
- 常見：Cloudflare、Akamai、CloudFront（亦有 DDoS 防護、WAF）。

## 面試怎麼用
- 每類至少備一個熟悉的技術，講「它的哪個特性解決眼前問題」；被問比較時只比你熟的那些。
- 快速決策：product→Postgres；infra→DynamoDB；大檔→S3+presigned URL+CDN；搜尋→Elasticsearch；WebSocket→L4；需要耐久可重讀→Kafka stream；長時間鎖→Redis lock with TTL。
- 陷阱：SQL vs NoSQL 籠統宣稱；S3 當主 DB；同步低延遲流程加 queue；queue 掩蓋容量不足（要 backpressure）；cache 只說「存 cache」不講結構/invalidation。

## 關鍵數字
- S3 $0.023/GB/月（前 50TB）vs DynamoDB $1.25/GB/月（前 10TB）。
- 鎖票例：約 10 分鐘 lock expiry。
- Queue 例：突發 1,000 req、處理能力 200/s。

## 相關題目
[ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)、[youtube](../../hellointerview-breakdowns/youtube.md)、[dropbox](../../hellointerview-breakdowns/dropbox.md)、[fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)、[distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)、[online-auction](../../hellointerview-breakdowns/online-auction.md)、[ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)、[uber](../../hellointerview-breakdowns/uber.md)

## 自測問題
1. 為何不要在面試中籠統比較 SQL 與 NoSQL？（兩者高度重疊，籠統宣稱是 yellow flag；應談所選 DB 的具體特性）
2. 大檔上傳流程？（要 presigned URL → client 直傳 S3 → storage 通知 server 更新狀態；下載經 CDN；DB 只存 metadata）
3. Queue 與 stream 的差異？（stream 保留資料、可重讀、多 consumer group；queue 處理完即消費）
4. 何時用 L4 vs L7 LB？（持久連線如 WebSocket 用 L4；否則 L7）
5. Distributed lock 為何需要 expiry？（避免 process crash 導致鎖永遠卡住，如鎖票 10 分鐘後釋放）
