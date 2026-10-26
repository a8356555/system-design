# Strava（運動追蹤）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/strava ｜ Medium ｜ Scaling Writes、Real-time Updates（作者 Evan King）

## 一句話核心
Client 端離線優先（本地累積 GPS 統計、事後同步）+ 高吞吐 GPS 寫入的分層處理 + 好友即時分享與排行榜（Redis sorted set）。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 使用者可開始、暫停、停止、儲存跑步與騎行。
- 活動進行中可查看路線、距離、時間等資料。
- 可查看自己已完成的活動，以及好友的活動。

**Out of scope（原文）**：好友管理、驗證與授權、留言/按讚。

**Non-functional（原文）**
- 高可用（availability >> consistency）。
- 在沒有網路的偏遠地區也能運作。
- 運動中要提供準確且即時的本地統計。
- 擴展到 1000 萬個同時進行的活動。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`User`、`Activity`（id, userId, type, state, startTime, endTime, distance, duration）、`Route/GpsPoint`（activityId, lat, lng, ts）、`Friend`。
- API：
  - `POST /activities` -> `{activityId}`（開始）
  - `PATCH /activities/{id}` `{state: paused|resumed|completed}`
  - `POST /activities/{id}/points`（批次上傳 GPS 點）
  - `GET /activities/{id}`、`GET /users/{id}/activities`、`GET /feed`（好友活動）

## High-Level Design
原文大綱：開始/暫停/停止/儲存（原文）；進行中看資料（原文）；看自己與好友的已完成活動（原文）。

（補充，非原文 — 原文為 Premium）
- **開始/暫停/停止**：client 是 source of truth，活動狀態機在手機本地（`NotStarted -> Active <-> Paused -> Completed`）；狀態變更時非同步同步到 Activity Service，寫入 DB。
- **進行中資料**：距離/時間/配速全部在手機端用 GPS 計算並顯示（因為要離線、要低延遲）；伺服器不參與即時顯示。
- **看活動**：完成後 client 上傳完整 route；Activity Service 寫 DB（metadata）+ 物件儲存/時序儲存（GPS 點）；好友活動透過 friend graph 查詢，列表走分頁。
- DB 選擇：Activity metadata 用 Postgres/DynamoDB（以 userId 為 partition key、startTime 為 sort key）；GPS 點量大，可存 blob（序列化後的 polyline）而非逐點一列。

## Deep Dives（依原文大綱逐條）
### 1) How can we support tracking activities while offline?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：每個 GPS 點即時送 server -> 無網路就全丟。
- 好解：client 本地 buffer（SQLite），有網路時批次上傳。
- 最佳解：本地即為 source of truth，所有統計在 device 計算；活動結束或網路恢復時以 activityId（client 生成 UUID）做 idempotent 上傳，斷點續傳（記錄已上傳 offset）。取捨：電量（GPS 取樣頻率、批次大小）、本地儲存上限、時鐘漂移（以 device 單調時間 + GPS 時間戳）。

### 2) How can we scale to support 10 million concurrent activities?（原文標題）
（補充，非原文 — 原文為 Premium）
- 計算：GPS 每 ~4 秒一點 -> 1000 萬 / 4 = 250 萬 writes/s（若即時上傳）。
- 爛解：每點一個 request 寫 RDBMS -> 撐不住。
- 好解：client 批次（例如每 30-60 秒或活動結束時一批）-> 寫入降 1-2 個數量級；寫入走 Kafka 緩衝再 consumer 批次落地。
- 最佳解：因為統計在本地算，**根本不需要即時上傳**，只在結束時上傳一次 -> 寫入從「連續串流」變成「完成事件」；需要即時分享的才開串流。儲存層用 partition by userId 的 NoSQL（Cassandra/DynamoDB），GPS blob 放 S3。

### 3) How can we support realtime sharing of activities with friends?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：好友 polling `GET` -> 浪費且延遲高。
- 好解：opt-in「Live」模式，client 週期上傳位置，好友以 WebSocket/SSE 訂閱；Pub/Sub 以 activityId/userId 為 channel。
- 最佳解：只對正在觀看的好友 fan-out（訂閱制，而不是推給所有好友）；大 V 追蹤者多時只維持 pull 或延遲 N 秒的 CDN 快取；最終一致即可（available >> consistent）。

### 4) How can we expose a leaderboard of top athletes?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：`SELECT ... ORDER BY distance DESC LIMIT 100` 每次全表掃。
- 好解：DB 索引 + 定期預先計算（cron）-> 可接受但不即時。
- 最佳解：**Redis Sorted Set**（`ZINCRBY leaderboard:{week}:{segment}`），活動完成事件經 Kafka 更新；依時間窗與好友/區域分多個 key；舊 key 設 TTL。大規模用 shard + 合併 top-K。取捨：重建性（可由 DB 重算）、記憶體。

## 關鍵數字與 back-of-envelope
（補充，非原文，除 1000 萬為原文）
- 1000 萬並發活動，若 4s 一點即時上傳 -> ~250 萬 writes/s；批次 60s 一次 -> ~17 萬 requests/s。
- 一個 1 小時活動 ~900 點 × ~20 bytes ≈ 18KB（壓縮後更小）；每天 5000 萬活動 ≈ ~1TB/天原始 GPS。

## 可遷移的 pattern
1. **Offline-first / client 為 source of truth + idempotent 同步**（client 生成 id）。
2. **批次化降低寫入 QPS**：把連續串流改成事件。
3. **Pub/Sub 訂閱制 fan-out**：只對在看的人推送。
4. **Redis Sorted Set 做排行榜**，DB 做可重建的 source of truth。
5. **時序/大 blob 分開存**（metadata 在 DB、軌跡在物件儲存）。

## 常見追問
- **GPS 不準/漂移怎麼辦？** client 端 Kalman filter / 速度門檻過濾離群點，server 端可再校正。
- **重複上傳怎麼辦？** activityId + 點序號 idempotent；server 以 (activityId, seq) 去重。
- **如何防作弊（開車當跑步）？** 速度/配速異常檢測、感測器資料交叉驗證，非同步離線偵測。
- **Segment（路段）排行榜怎麼做？** 以 geohash 預索引 segment，活動完成後非同步比對 route 是否通過 segment 並計時，結果寫入該 segment 的 sorted set。
- **好友活動 feed？** 活動完成時 fan-out on write 到好友 feed，或讀時合併（好友少時）。
