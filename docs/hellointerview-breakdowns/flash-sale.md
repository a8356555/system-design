# Flash Sale（限量搶購）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/flash-sale ｜ Hard ｜ Real-time Updates、Dealing with Contention、Scaling Writes（作者 Evan King）

## 一句話核心
不是設計整個電商，而是「極端競爭下賣有限庫存且絕不超賣」：用 **reservation（保留 + 逾時釋放）** 把慢速付款與庫存扣減分離，用 Redis 原子操作扛熱點，用 waiting room / 排隊保證公平與流量削峰。

## 需求（Functional / Non-functional / 規模數字）
**情境（原文）**：Nike 中午開賣 10,000 雙限量鞋，數千萬使用者幾秒內湧入；需讓大家公平競爭、完成購買、**永不超賣**。

**Functional（原文）**
- 使用者可檢視 flash sale 商品。
- 使用者可在銷售期間**保留（secure/reserve）**一個可用單位，限時。
- 取得保留的使用者可完成付款購買。
- 原文強調：第二點最常被漏掉。付款走第三方、需要數秒，不能在整段付款期間占著 DB transaction；reservation 讓庫存立即被拿下，之後再結算金流。

**Out of scope（原文）**：瀏覽/搜尋完整商品目錄、運送/退貨/退款/訂單歷史、管理者建立與設定活動。

**Non-functional**：原文內文被鎖。（補充）推定：不超賣（強一致的庫存扣減）、公平、高可用、能承受數千萬同時到達的瞬間流量、低延遲回應。
**規模（原文）**：10,000 件庫存、數千萬使用者在幾秒內嘗試購買。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`Item/Sale`（id, totalStock, start, end）、`Reservation`（id, itemId, userId, status, expiresAt）、`Order`（id, reservationId, paymentId, status）、`User`。
- API：
  - `GET /sales/{id}`（商品資訊、剩餘狀態；可大量快取）
  - `POST /sales/{id}/reserve` -> `{reservationId, expiresAt}` 或 409 sold out
  - `POST /orders` `{reservationId, paymentToken}`（帶 idempotency key）
  - 付款結果由 payment provider webhook 回呼。

## High-Level Design
原文大綱：(1) 檢視商品 (2) 保留單位 (3) 付款。

（補充，非原文 — 原文為 Premium）
- **檢視**：靜態內容走 CDN；剩餘庫存顯示用快取（可稍微 stale）。
- **保留**：Reservation Service 以原子操作扣減可用庫存並建立 `Reservation(status=held, expiresAt=now+10min)`；一人限 1 單位（userId unique）。
- **付款**：user 在 reservation 有效期內付款；成功 -> `Reservation=confirmed`、建 Order；失敗/逾時 -> 釋放庫存。付款需 idempotency key，避免重複扣款；webhook 驗證簽章。

## Deep Dives（依原文大綱逐條）
### 1) How do we maintain consistency under extreme contention?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：先 `SELECT stock` 再 `UPDATE` -> race condition 超賣。
- 好解：DB 原子條件更新 `UPDATE inventory SET stock = stock - 1 WHERE id=? AND stock > 0`；或 row lock / optimistic locking（version）。缺點：所有請求搶同一 row，鎖競爭導致吞吐崩潰。
- 最佳解：**Redis 單線程原子操作**（Lua script：`DECR` 若 > 0 並寫 reservation key，帶 TTL），Redis 擋掉絕大多數失敗請求，只有成功的（~10,000 個）才寫 DB 持久化。更進一步：庫存分段（shard 成多個 counter，每段分配 N 件，需處理最後少量庫存的再平衡）。取捨：Redis 與 DB 一致性（用 reservation 事件非同步落地 + 對帳；Redis 掛了時以 DB 為準重建）。

### 2) How do we efficiently release expired reservations?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：cron 每分鐘掃全表找 `expiresAt < now` -> 延遲高、全表掃。
- 好解：Redis key TTL + keyspace notification 觸發釋放（但通知不保證送達）。
- 最佳解：**Redis sorted set（score = expiresAt）** 或 delay queue，worker 輪詢 `ZRANGEBYSCORE` 取到期的並以 Lua 原子釋放庫存；DB 層另有 reconciliation job 作保險。付款成功與逾時釋放之間要有競態處理（以 reservation 狀態 CAS：僅 `held -> confirmed` 或 `held -> expired` 其一成功）。

### 3) How do we handle millions of users arriving at once?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：全部請求直達 app/DB -> 全面崩潰。
- 好解：CDN 吸收靜態、API gateway 限流、auto scale。
- 最佳解：**Virtual waiting room / 排隊**：開賣前使用者進入佇列（Redis 計數 + 簽名 token），只放行與庫存相匹配的流量（如 10 萬人進入購買流程）；其餘即時回覆「已售完/排隊中」。使用 WebSocket/SSE 或 long polling 推播排隊進度（Real-time Updates）。早期過濾（edge 上檢查 sold-out flag）讓售完後的請求在邊緣被擋掉。

### 4) How do we make access to limited inventory fair?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：先到先搶 -> 網路快、機器人者得利。
- 好解：公平 FIFO 隊列（依到達時間戳）+ 每人限購 + CAPTCHA / 登入驗證。
- 最佳解：開賣前一段時間開放「報名」，之後**隨機抽籤決定放行順序**（避免延遲/機器人優勢）；每人/裝置/付款方式限購；bot 偵測、rate limit；放行以簽名 token 控制 admission。取捨：隨機抽籤公平但體驗不同於 FIFO，需產品決策。

## 關鍵數字與 back-of-envelope
（補充，非原文，除 10,000 件為原文）
- 假設 1,000 萬使用者在 10 秒內到達 = 100 萬 req/s -> 單一 DB 或單一 Redis 無法直接承受，必須在邊緣/排隊層削峰。
- 實際進入庫存扣減的請求控制在數萬 QPS；成功寫入 DB 僅 10,000 筆。
- Reservation TTL 5-10 分鐘；單 Redis 節點可處理約 10 萬 ops/s。

## 可遷移的 pattern
1. **Reservation（暫存保留 + TTL）把慢操作（付款）從庫存扣減中拆開**。
2. **Redis Lua 原子扣減擋熱點，DB 只記成功結果**（處理 contention）。
3. **Virtual waiting room / admission control** 削峰並保證公平。
4. **Sorted set / delay queue 管理到期事件**（reservation、訂單逾時、優惠券）。
5. **狀態機 + CAS 解決付款與逾時的競態**，搭配 idempotency key。

## 常見追問
- **Redis 掛了會超賣嗎？** 以 DB 條件更新作最終防線（`stock>0`），Redis 只是前置過濾；故障時降級為 DB 路徑 + 更嚴格限流。
- **使用者付款到一半 reservation 過期？** 付款前再次驗證有效；過期後付款成功則退款或延長 hold（付款中狀態 `payment_pending` 延長 TTL）。
- **如何防刷單/機器人？** 登入 + CAPTCHA + 裝置指紋 + 限購 + 抽籤。
- **庫存分段如何避免最後幾件賣不出？** 段內賣完後向其他段借庫存，或最後階段切回單一 counter。
- **如何保證 exactly-once 扣款？** 付款 idempotency key + webhook 去重 + 狀態機。
