# Online Auction（線上拍賣）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/online-auction ｜ Medium ｜ Dealing with Contention、Real-time Updates（作者 Evan King）

## 一句話核心
每個拍賣的出價必須強一致地序列化（只有高於目前最高價才接受），同時要把「目前最高價」即時推播給所有觀看者，並擴展到 1000 萬同時進行的拍賣。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 使用者可刊登拍賣商品，指定起標價與結束時間。
- 使用者可對商品出價；出價高於目前最高價才被接受。
- 使用者可檢視拍賣，包含目前最高出價。

**Out of scope（原文）**：搜尋商品、依類別篩選、依價格排序、檢視拍賣歷史。

**Non-functional（原文，來自 deep dive 標題）**
- 出價強一致性。
- 容錯與持久性。
- 目前最高價即時顯示。
- 擴展到 **1000 萬同時進行的拍賣**。
- 原文提醒：先向面試官確認規模。具體 NFR 內文被鎖。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`User`、`Auction`（id, itemId, sellerId, startPrice, currentMaxBid, endTime, status）、`Item`、`Bid`（id, auctionId, userId, amount, ts）。
- API：
  - `POST /auctions` `{item, startPrice, endTime}` -> `{auctionId}`
  - `POST /auctions/{id}/bids` `{amount}` -> 202/200（接受）或 409/422（出價過低）
  - `GET /auctions/{id}` -> 含 `currentMaxBid`
  - 即時更新：SSE / WebSocket `/auctions/{id}/stream`。

## High-Level Design
原文大綱：(1) 刊登拍賣 (2) 出價（需高於目前最高價）(3) 檢視拍賣與最高價。

（補充，非原文 — 原文為 Premium）
- **刊登**：Auction Service 寫 `Auction` 表（含 endTime）；圖片走 blob store。
- **出價**：Bid Service 驗證 `auction.status=open`、`now < endTime`、`amount > currentMaxBid`，通過後寫入 Bid 並更新 `currentMaxBid`；此「檢查+更新」必須原子。
- **檢視**：Read 路徑查 Auction，最高價可快取；即時更新見 deep dive 3。
- **拍賣結束**：endTime 到期由 scheduler / delay queue 觸發結算（決定得標者、通知），拒絕之後的出價。

## Deep Dives（依原文大綱逐條）
### 1) How can we ensure strong consistency for bids?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：讀 `currentMaxBid` -> app 比較 -> 寫入；兩個併發出價都通過 -> 較低的蓋掉較高的。
- 好解：DB 條件更新（CAS）：`UPDATE auction SET max=:amt WHERE id=:id AND max < :amt AND status='open'`，成功才寫入 Bid；或 optimistic locking（version）；或 `SELECT ... FOR UPDATE` row lock（熱點拍賣鎖競爭高）。
- 最佳解：**以 auctionId 為分區鍵，將同一拍賣的出價序列化給單一 writer**（Kafka partition 單消費者 / Redis Lua 原子比較並設定 / 單一 actor）；其他拍賣平行。這樣熱門拍賣的競爭轉成佇列，不產生鎖爭用重試風暴。取捨：單一拍賣吞吐上限（單分區），通常足夠（一場拍賣每秒出價數有限）。

### 2) How can we ensure that the system is fault tolerant and durable?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：僅存在記憶體/單機 DB -> 掛了就丟出價。
- 好解：DB 多 AZ 同步複製；出價先寫 durable log 再 ack。
- 最佳解：**出價先 append 到 Kafka（replication 3, acks=all），Bid Processor 消費後更新 DB（Bid 表 append-only 為 source of truth，currentMaxBid 為其衍生）**；consumer 崩潰從 offset 重放，處理需 idempotent（bidId 去重）；Redis 之類快取可由 Bid 重建；跨區容災 + 備份。取捨：多一層 log 增加幾十 ms 延遲，換取不丟。

### 3) How can we ensure that the system displays the current highest bid in real-time?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：前端每秒 polling -> 大量無效請求。
- 好解：Long polling / SSE，從 DB 讀取變化。
- 最佳解：Bid Processor 在新最高價確立後，發布事件到 **Pub/Sub（Redis Pub/Sub / Kafka topic）**，WebSocket/SSE Gateway 依 auctionId 訂閱並推給正在看該拍賣的連線；新連線進入時先 `GET` 目前狀態再訂閱（避免遺漏）。熱門拍賣數十萬觀眾 -> 多層 fan-out（Gateway 層分擔）；可合併/節流更新（每 100-200ms 一次）。是 AP 體驗但寫入端維持強一致：顯示稍晚可接受，**接受與否必須以強一致寫入端為準**。

### 4) How can we ensure that the system scales to support 10M concurrent auctions?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 DB 單一服務。
- 好解：Auction/Bid 以 auctionId 分片；Bid Service 無狀態水平擴展；讀取走快取 + 副本。
- 最佳解：Kafka 依 auctionId 分區，分區數足夠使單一 processor 負責一批拍賣（記憶體持有狀態可進一步優化）；WebSocket 層按 auctionId consistent hash；已結束拍賣資料冷儲存；長尾拍賣（多數無人出價）零成本——狀態僅在有活動時佔資源。
- 計算：1000 萬拍賣中絕大多數冷門；假設平均每拍賣每小時 1 次出價 ≈ 2,800 bids/s；最後幾分鐘（sniping）的熱門拍賣才是尖峰。

### Some additional deep dives you might consider（原文標題，內容鎖住）
（補充，非原文）拍賣延長規則（anti-sniping）、代理出價（proxy/auto-bid）、拍賣結束精準觸發、詐騙/惡意出價、付款與得標履約。

## 關鍵數字與 back-of-envelope
（補充，非原文，除 1000 萬為原文）
- 1000 萬並行拍賣；若總出價 ~3k-10k/s，Kafka 與分片 DB 完全能承受，難點在單一熱門拍賣的序列化與 fan-out，而非總量。
- Auction 記錄 ~1KB，1000 萬 ≈ 10GB；Bid 記錄 ~100 bytes，很小。

## 可遷移的 pattern
1. **按實體 key 分區 + 單一 writer 序列化**（處理 contention，而非鎖）。
2. **條件更新（CAS / optimistic lock）作為最終防線**。
3. **先 append durable log 再處理，狀態由 log 衍生**（event sourcing 精神）。
4. **Pub/Sub + SSE/WebSocket 做即時推播**，連線時先拉再訂閱。
5. **寫入強一致、讀取最終一致**的分離。

## 常見追問
- **兩人同一毫秒出相同金額？** 比較用嚴格大於，先進入序列的勝；或比較 (amount, timestamp) tie-break。
- **拍賣結束時間怎麼精準執行？** 序列化器本身在處理每筆出價時以 server 時間檢查 endTime；結算由 delay queue 觸發，並以條件更新關閉狀態。
- **如何防最後一秒狙擊？** 結束前 N 分鐘內有人出價就延長 endTime（需放在同一個原子操作內）。
- **Kafka 分區熱點？** 單一拍賣已是最小單位；可限制出價頻率或用 Redis 原子操作取代 Kafka 做單拍賣熱點。
- **得標後付款失敗？** 順延給第二高出價者或重新拍賣，需保留完整 Bid 歷史（所以 Bid 表 append-only）。
