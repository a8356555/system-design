# Common Patterns
> 來源：https://www.hellointerview.com/learn/system-design/in-a-hurry/patterns ｜ 分類：in-a-hurry

## 一句話重點
把 Key Technologies 與 Core Concepts 組合成可重用的 pattern；能辨識題目需要哪些 pattern，就能套 best practice、省時間、知道哪裡有趣——這是 senior 與 junior 的分水嶺。原則：從簡單做法開始（polling、單機 orchestration），有具體需求才加複雜度。

## 核心內容
### Pushing Realtime Updates
- 同步 API 回傳即可；chat、通知、live dashboard 需要主動推送。
- 協定：HTTP polling（最簡單但效率差）→ SSE / WebSocket（專為 realtime，但基礎設施難做對）。**建議先 polling，不夠再升級**。
- Server 端：Pub/Sub 解耦 publisher / subscriber（WhatsApp breakdown 用）；處理較重時用 consistent hash ring 上的 stateful servers（Google Docs 用）。

### Managing Long-Running Tasks
- 影片編碼、報表、批次操作等超過數秒的任務：立即 ack + 背景處理。
- Web server 驗證請求 → 推 job 到 queue（Redis/Kafka）→ 數毫秒內回 job ID；worker 持續拉取執行。好處：回應快、web 與 worker 獨立擴展、故障隔離。
- 警告：很多人太快上 queue，常是壞決定。短任務同步回傳狀態可大幅簡化架構，back-pressure 更清楚、UX 更好。
- 需處理：job 狀態追蹤、retry、失敗情境如 dead letter queue（poison message）。

### Dealing with Contention
- 多人同時搶同一資源（最後一張票、拍賣出價）→ 防 race condition、保證一致。
- 方案由 DB 層（pessimistic locking、optimistic concurrency control、atomicity/transactions）到分散式協調（distributed lock、two-phase commit、queue 序列化）。
- Trade-off：效能 vs 一致性、簡單 DB 方案 vs 複雜分散式協調。**先單 DB 解，再考慮分散式**。
- DB 本來就是為 contention 設計；把資料拆到多個 DB 等於自己承擔這些問題——面試官會追問你放棄了什麼。

### Scaling Reads
- 讀流量通常先成為瓶頸。read:write 常從 10:1 到 100:1 以上（Instagram：打開 app 看數十張照片需數百次 query，但一天只發一篇）。
- 自然演進：DB 內優化（index、denormalization）→ read replicas 水平擴展 → 外部 cache（Redis）與 CDN。
- 注意：cache invalidation、replication lag、hot key（百萬人同時讀同一熱門內容）。

### Scaling Writes
- 寫入達單機極限（每秒數百到百萬等級成長）→ sharding、batching、負載管理。
- 策略：horizontal sharding、vertical partitioning（按資料類型拆）、突發寫入用 queue 緩衝或 load shedding 優先處理重要寫入；batching 降低 per-operation 開銷。
- 關鍵：挑能均勻分散負載、又讓相關資料在一起的 partition key（有 good/bad partition key 圖示）。

### Handling Large Blobs
- 大檔不要經過 app server：用 **presigned URL** 讓 client 直傳 blob storage（S3），下載走 CDN + signed URL 控權限。好處：server 不成為瓶頸、可續傳、進度追蹤、全球分發。
- 挑戰：DB metadata 與 blob storage 的狀態同步、上傳失敗、生命週期管理；用 storage 事件通知保持一致。

### Multi-Step Processes
- 跨多服務、長時間、需耐受失敗/重試/外部依賴的流程（訂單履行、onboarding、付款）。
- 方案：簡單單機 orchestration → workflow engine / durable execution（Temporal、AWS Step Functions 自動處理 state、failure recovery、retry）；event sourcing 是分散式做法（每步發 event 觸發下一步）。
- 重點：從散落的狀態管理與手動錯誤處理，轉為宣告式 workflow 定義，並有完整 audit trail（原文稱保證 exactly-once execution）。

### Proximity-Based Services
- Uber、Gopuff 等要依位置搜尋 → geospatial index。實作：PostgreSQL + PostGIS、Redis geospatial type、Elasticsearch geo-queries。
- 架構：把地理區域分成小區域並索引，快速排除大片無關區域。
- 只在需要索引「數十萬到數百萬」項目時才需要；1,000 個項目直接 scan 比專用 index 更划算。多數系統並非全球查詢，而是找本地實體。

### Pattern Selection
- Pattern 常組合：影片平台 = Large Blobs（上傳）+ Long-Running Tasks（轉碼）+ Realtime Updates（進度通知）+ Multi-Step Processes（協調整個 workflow）。
- 先簡單（polling、單機 orchestration），有具體需求才加複雜度。

## 面試怎麼用
- 讀題後先問「這題需要哪些 pattern？」，主動點名；用 pattern 決定 deep dive 方向。
- 陷阱：太早上 queue / WebSocket / sharding / geospatial index；過早把資料拆多 DB；忽略 hot key 與 replication lag。

## 關鍵數字
- 讀寫比：起始約 10:1，常達 100:1 以上。
- Geospatial index 值得用的規模：數十萬至數百萬項目；約 1,000 項不需要。

## 相關題目
[whatsapp](../../hellointerview-breakdowns/whatsapp.md)、[google-docs](../../hellointerview-breakdowns/google-docs.md)、[ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)、[online-auction](../../hellointerview-breakdowns/online-auction.md)、[youtube](../../hellointerview-breakdowns/youtube.md)、[dropbox](../../hellointerview-breakdowns/dropbox.md)、[uber](../../hellointerview-breakdowns/uber.md)、[gopuff](../../hellointerview-breakdowns/gopuff.md)、[payment-system](../../hellointerview-breakdowns/payment-system.md)、[job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)

## 自測問題
1. Realtime 更新的升級路徑？（HTTP polling → SSE/WebSocket；server 端 Pub/Sub 或 consistent hash ring 的 stateful servers）
2. 何時不該把任務丟 queue？（短任務；同步回傳更簡單、back-pressure 更清楚）
3. Scaling Reads 的演進順序？（index/denormalization → read replicas → Redis/CDN cache）
4. 大檔上傳為何用 presigned URL？（client 直傳 S3，不經 app server 避免瓶頸；並用事件通知同步 metadata）
5. 何時需要 geospatial index？（索引數十萬到數百萬項目；1,000 項直接 scan）
