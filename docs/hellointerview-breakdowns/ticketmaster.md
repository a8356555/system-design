# Ticketmaster
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/ticketmaster ｜ 難度 medium ｜ 類別：Dealing with Contention / Scaling Reads / Real-time Updates（作者 Evan King）

## 一句話核心
Ticketmaster = 讀多寫少的活動瀏覽/搜尋 + 一個「絕不能重複賣票」的強一致訂票流程。核心難點是：結帳期間如何暫時鎖票（reservation + TTL）、熱門場次如何扛住千萬人同時湧入（cache、SSE、Virtual Waiting Queue）、以及搜尋如何低延遲（Elasticsearch + CDC）。

## 需求（Functional / Non-functional / 規模數字）
**Functional（Core）**
- 使用者可以 view events
- 使用者可以 search events
- 使用者可以 book tickets

**Below the line**：查看自己已訂的活動、管理者新增活動、熱門活動動態定價。

**Non-functional（Core）**
- 搜尋/瀏覽優先 availability；訂票優先 consistency（不能 double booking）
- 可擴展，能處理熱門活動高吞吐（10 million users, one event）
- 搜尋低延遲（< 500ms）
- 讀多寫少，讀寫比 100:1

**Below the line**：GDPR、fault tolerant、安全交易、CI/CD 與測試、定期備份。

## Core Entities & API
**Entities**
- Event：日期、描述、類型、表演者/隊伍
- User
- Performer：名稱、簡介、連結（刻意泛化，可為藝人/公司/團體）
- Venue：地址、容量、seat map（JSON 或相關表，含 section/row/seat 與座標，供前端渲染）
- Ticket：eventId、座位（section/row/seat）、價格、狀態；建立活動時依 seat map 為每個座位產生一張 ticket
- Booking：userId、ticketIds、總價、狀態（in-progress / confirmed）。可併進 Ticket，但獨立成 Booking 較適合一次買多張時共用付款狀態與總價

**API**
```
GET  /events/:eventId -> Event & Venue & Performer & Ticket[]   (tickets 用來畫 seat map)
GET  /events/search?keyword=&start=&end=&pageSize=&page= -> Event[]
POST /bookings/:eventId  { ticketIds: string[], paymentDetails } -> bookingId
```
註：訂票 API 之後會演化成「reserve」與「confirm」兩支（見 Deep Dive 1）。原文強調簡單 API 起手、隨設計演進，並口頭告知面試官即可。

## High-Level Design（元件與資料流）
逐條功能往上疊：
```
Client -> (LB) -> API Gateway (auth/rate limit/routing)
                    |-> Event Service  -> Events DB (Postgres: events/performers/venues/tickets/bookings)
                    |-> Search Service -> Events DB (初版: 直接查 DB)
                    |-> Booking Service -> Events DB (txn) + Stripe(Payment Processor)
```
- **View**：Client GET -> API Gateway -> Event Service 查 DB 回傳 event/venue/performer。
- **Search**：初版 Search Service 直接用查詢條件過濾 DB（有問題，留給 deep dive）。
- **Book**：選 PostgreSQL（需要 ACID；MySQL/DynamoDB 也可），加 Bookings / Tickets 兩表（Ticket 有 bookingId 欄位）。Booking Service 在一個 transaction 內：檢查票是否可用 -> 更新為 booked -> 建立 booking；若別人搶先，交易失敗並回報 client。需搭配適當 isolation level 與 row-level lock 或 OCC。
- 多個 service 共用同一個 DB 是刻意決策：資料緊耦合（booking 需要 ticket 需要 event）、需要 ACID，拆庫只增加複雜度。不要死背 "database per service"。
- 此初版的缺陷：使用者填完付款資料才發現票被買走。

## Deep Dives

### 1) 如何用 reservation 改善訂票體驗？（Dealing with Contention）
需求：選位後鎖票；放棄結帳要自動釋放；完成付款轉為 sold。

**爛解：長時間 DB lock（interactive transaction）**
- 用 `SELECT FOR UPDATE` 鎖住 ticket row 直到使用者付款或 timeout。
- 為何爛：DB lock 本來只該用在瞬間 transaction；長時間持有（如 5 分鐘）耗資源、增加 lock contention 與 deadlock 風險；`lock_timeout` 對使用者只會看到錯誤而不是排隊；app crash/網路問題會讓 lock 狀態不明；高負載下無法擴展。

**好解：status + expiration time + cron**
- Ticket 三態：available / reserved / booked。選位時改 reserved 並記錄時間。完成付款 -> booked；逾時 -> cron 掃描把過期的 reserved 改回 available。
- 缺點：cron 與實際過期之間有延遲，熱門場次票在過期後仍不可買；cron 失敗會造成大規模「票看起來都不可用」。

**很好解：Implicit status（status + expiration 組合判斷）**
- 不用長 transaction，也不靠 cron 釋放。可用狀態 = AVAILABLE，或 RESERVED 但已過期。
- Transaction（很短）：begin -> 檢查 ticket 是 AVAILABLE 或（RESERVED 且已過期）-> 更新為 RESERVED、expiration = now + 10 分 -> commit。
- 保證只有一人能 reserve/book，且能直接搶到過期的預留。
- 取捨：讀取要多過濾兩個條件（可用 materialized view + compound index 緩解）；表格對其他讀者較不直觀（有「實質已過期」的 reserved），可用 cron 清掃，關鍵差別是清掃延遲**不影響系統行為**。

**很好解（原文最終採用）：Redis distributed lock + TTL**
- 為何需要 Redis：Postgres 沒有 row-level TTL；Redis 內建 key 過期、in-memory、鎖操作快。
- 流程：選位時 `SET key value NX EX seconds`（atomic）以 ticketId 為 key、userId 為 value、TTL 例如 10 分鐘；付款完成後更新 DB 為 booked 並主動釋放 lock；TTL 到期自動釋放。Ticket 表只剩 available / booked 兩態。
- 多張票：依序取鎖，任一失敗就釋放已取得的；若票落在同一 Redis node 可用 Lua script 做原子取鎖。
- Challenges：
  - Read-path 複雜度：seat map 需顯示 Redis 中的保留座位。直接用 Redis Set 會留下幽靈成員（key 過期但 set member 不過期）；改用 sorted set，score = 過期時間（`ZADD event:{eventId}:reserved <expiresAt> ticketId`），讀取時只算 score 在未來的，並用 `ZREMRANGEBYSCORE` 惰性清除。替代方案：取鎖時 write-through 一個 reserved 狀態到 DB，並定期清掃。
  - Failure handling：Redis 掛了只是體驗降級（使用者可能付款後才發現被搶），因 DB 仍用 OCC/row lock，**不會 double booking**；原文認為這比 cron 失效導致全部票不可買好。
  - TTL 在付款中過期：A 的 lock 第 10 分鐘過期、第 11 分鐘才付款完成，B 可能已拿到鎖。DB transaction 以 OCC 保證只有一人成功，失敗者由 Stripe 自動退款。對策：TTL 設寬鬆、付款開始時延長 lock。
- 最終 Booking Flow：
  1. 選位 -> POST /bookings (ticketId)
  2. Gateway -> Booking Service
  3. Booking Service 在 Redis 加鎖（TTL 10 分）
  4. 同時在 DB 寫 booking（status = in-progress）
  5. 回傳 bookingId，導到付款頁；不付款則 10 分後鎖自動釋放
  6. 前端用 Stripe.js tokenize 卡片（server 不接觸原始卡號，PCI compliance），server 建 PaymentIntent，Stripe 以 webhook 通知成功
  7. webhook 從 metadata 取 bookingId，開 DB transaction 同時把 ticket 設 sold、booking 設 confirmed。Webhook handler 要 idempotent（Stripe 會重送），以 bookingId 為 idempotency key 並先檢查 booking 狀態。

### 2) View API 如何擴展到千萬級並發？（Scaling Reads）
- **Caching**：事件詳情、表演者簡介、場館資訊讀多更新少 -> 以 `eventId:eventObject` 存 Redis/Memcached，read-through（miss 就讀 DB 回填）。失效：DB trigger 通知 cache 失效 + TTL（靜態資料如場館 TTL 長，常變的如可用性 TTL 短）。
- **Load balancing**：Round Robin 或 Least Connections。
- **Horizontal scaling**：Event Service 無狀態，加實例即可。
- 挑戰：cache 與 DB 一致性（但活動資料預期不常更新）；大量實例的部署與 rollback 複雜度。

### 3) 熱門活動百萬人同時搶票的體驗（Real-time Updates）
**好解：SSE 即時推送座位變化**
- 單向 server -> client，座位被預留/售出就即時更新 seat map。
- 缺點：Taylor Swift 等級的活動，座位圖瞬間被搶光，使用者面對一堆座位秒消失，體驗仍很差。

**很好解：Virtual Waiting Queue（admin 可啟用）**
- 使用者先進虛擬隊列，才能看到選位頁；隊列位於 Booking Service 前面做流量閘門。
- 實作：建立持久連線（SSE 或 WebSocket；SSE 較簡單因只需 server -> client 推送位置），隊列用 Redis sorted set（timestamp 排序）；定期或依已售量從隊首 dequeue 並通知可進入；同時在 Redis `admitted:{eventId}` set（附 TTL）標記該 session，Booking Service 預約前檢查，未經隊列者拒絕。
- 取捨：等待太久使用者會挫折，靠即時推送隊列位置與預估等待時間緩解。
- 原文觀點：有時最佳解不是技術更難，而是跳出限制、解決商業問題，這是 senior 與 staff 的常見差異。

### 4) 如何讓搜尋達到低延遲？
問題：`LIKE '%Taylor%'` 造成 full table scan。
- **好解：索引 + SQL 優化**：對 event name/date、performer name、venue location 建索引；用 EXPLAIN、避免 `SELECT *`、加 LIMIT、用 UNION 取代 OR。缺點：對部分字串匹配效果有限、索引增加儲存與寫入成本、要平衡索引數量。
- **很好解：DB 內建 full-text index**：Postgres 的 tsvector + GIN，MySQL 也有 full-text（原文特別註明兩者都不是 Lucene）。缺點：額外儲存、維護較複雜、查詢可能比一般索引慢。
- **很好解：Elasticsearch**：inverted index；用 CDC 從 Postgres 近即時同步 insert/update/delete；支援 fuzzy search（"Tayler Swift" 容錯），SQL 很難做到。缺點：同步一致性複雜、叢集維運成本。

### 5) 如何加速重複搜尋、降低搜尋層負載？
- **好解：Redis/Memcached 快取查詢結果**：key 包含所有影響結果的參數，如 `search:keyword=Taylor Swift&start=2021-01-01&end=2021-12-31`，TTL 例如 24 小時。難點：失效管理（尤其 fuzzy 結果），可用 TTL + 以 cache tag 為基礎的失效；cache miss 多時負載仍高。
- **很好解：ES 內建 cache + CDN 邊緣快取**：ES 有 shard-level query cache（filter 結果）與 request cache（完整回應，對 aggregation 有用），可做 adaptive caching；CDN（如 CloudFront）把搜尋結果放近使用者，**僅限結果不個人化**。難點：新活動公布時要讓 cache 失效，但搜尋查詢與結果間沒有明確關聯，很難；基礎設施更複雜。

## 關鍵數字與 back-of-envelope
- 原文給的數字：10 million users 同時搶一個 event；讀寫比 100:1；搜尋延遲 < 500ms；預留 TTL 10 分鐘（範例）。
- 搜尋 cache TTL 範例 24 小時。
- 原文沒有做 QPS/儲存量的詳細估算。（補充）自己估算可用：座位數 x 活動數 = ticket 列數，量級不大，瓶頸在熱點 contention 而非儲存。

## 面試官期待（Mid / Senior / Staff）
- **Mid（E4）**：約 80% breadth / 20% depth。定義清楚 API 與 data model，HLD 至少能 view + book；用「好解」（status + timeout + cron）解決 no double booking；更深的 deep dive 屬加分。
- **Senior（E5）**：約 60/40。快速帶過基本 HLD，把時間花在搜尋優化（Elasticsearch）、no double booking（distributed lock 或同等級方案）、熱門活動處理；需能講 sharding / replication 等擴展策略（有提示也可）。
- **Staff+**：約 40/60。主動性極高，深入 2-3 個領域並帶出創新想法；衡量標準之一是面試官聽完有學到新觀點。

## 可遷移的 pattern
1. **Reservation with TTL（兩階段預留）**：先暫時佔位（Redis `SET NX EX` 或 DB 過期時間欄位），付款成功才轉確認；適用 booking、庫存、飯店/機票、搶購。
2. **Implicit expiry（過期是狀態的一部分）**：用「狀態 + 過期時間」在讀/寫時判斷，而非依賴 cron 去改狀態，讓清掃延遲不影響正確性。
3. **最終一致性守門員 = DB 的 OCC / 短 transaction**：快取/鎖只做體驗優化，真正防重複的最後防線仍在 DB。
4. **Virtual Waiting Queue + admitted set**：用 Redis sorted set 做排隊，admission token 讓下游只服務被放行者；適用任何極端尖峰（演唱會、球鞋、搶購）。
5. **Search = DB 為真相 + Elasticsearch（CDC 同步）+ 多層 cache**：全文/模糊搜尋用倒排索引，結果可 Redis/CDN 快取。

## 常見追問
1. **Redis 掛了會 double booking 嗎？** 不會，DB 仍用 OCC/row lock 保證唯一；只是使用者可能付款後才發現被搶，體驗降級。
2. **付款時 lock 過期怎麼辦？** DB transaction 只會讓一人成功，失敗者由 Stripe 自動退款；TTL 設寬鬆，付款開始時延長 lock。
3. **Stripe webhook 重送怎麼辦？** Handler idempotent：用 bookingId 作 idempotency key，更新前先檢查 booking 狀態。
4. **為何不用 SELECT FOR UPDATE 鎖到付款完成？** 長 transaction 耗資源、易 deadlock、crash 時鎖狀態不明、無法擴展。
5. **seat map 如何顯示 Redis 裡的保留座位？** 用 sorted set（score = 過期時間）只計未過期者，惰性清除；或取鎖時 write-through 狀態到 DB。
