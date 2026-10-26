# Instagram
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/instagram ｜ Medium ｜ Scaling Reads、Managing Long Running Tasks、Handling Large Blobs（作者 Evan King）

## 一句話核心
Metadata 與 media 分離（presigned URL 直傳 S3 + CDN 分發 + 非同步轉檔），Feed 用「fan-out on write / read 混合」解決 500M DAU 的低延遲讀取。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 建立含照片/影片與簡短 caption 的貼文。
- 追蹤其他使用者。
- 看到所追蹤對象貼文的時間序（chronological）feed。

**Out of scope（原文）**：按讚/留言、搜尋使用者/hashtag/地點、限時動態、直播。

**Non-functional（原文，來自 deep dive 標題）**
- Feed 低延遲（< 500ms）。
- 照片/影片即時顯示；照片最大 8MB、影片最大 4GB。
- 擴展到 **500M DAU**。

**規模（原文）**：500M DAU、每天 1 億貼文。
（補充）1 億貼文/天 ≈ 1,160 posts/s 平均；500M DAU × 約 10 次 feed 刷新 ≈ 50 億讀取/天 ≈ 5.8 萬 QPS 平均，讀寫比 ~50:1 以上。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`User`、`Post`（id, userId, caption, mediaId/s, createdAt）、`Media`（id, s3Key, type, status, variants）、`Follow`（followerId, followeeId）。
- API：
  - `POST /posts`（建立 metadata，取得 presigned upload URL）-> 直傳 S3 -> `POST /posts/{id}/complete`
  - `POST /follows` `{followeeId}`、`DELETE /follows/{id}`
  - `GET /feed?cursor=&limit=` -> `{posts[], nextCursor}`

## High-Level Design
原文大綱：(1) 建貼文 (2) 追蹤 (3) 時序 feed。

（補充，非原文 — 原文為 Premium）
- **建貼文**：Client 先向 Post Service 要 presigned URL，大檔分片（multipart）直傳 S3，完成後觸發 Post 建立；metadata 寫 DB（Postgres/Cassandra）。Media 不經過 app server。
- **追蹤**：`Follow` 表，兩個方向都要查：`follower -> followees`（建 feed）與 `followee -> followers`（fan-out）；NoSQL 用兩張表（以 follower、followee 各為 partition key）或 graph-like 索引。
- **Feed**：最簡單：讀時查「我追蹤的人」->「各人最新貼文」merge sort。對 500M DAU 太重，進入 deep dive。

## Deep Dives（依原文大綱逐條）
### 1) 低延遲 feed < 500ms（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解（fan-out on read）：讀取時 JOIN follows 與 posts，追蹤 500 人就掃 500 個時間線。
- 好解（fan-out on write）：發文時把 postId 推進每個 follower 的預計算 feed（Redis list / sorted set）；讀取 O(1)。缺點：大 V（千萬粉絲）發文寫放大。
- 最佳解：**混合**：一般使用者 fan-out on write；名人（粉絲數 > 閾值）不 fan-out，讀取時把名人的最新貼文與預計算 feed merge。fan-out 由 Kafka + worker 非同步執行；feed cache 只存 postId，只保留最近 N 筆（如 500-1000），舊的退回 DB 分頁。取捨：寫放大 vs 讀延遲；使用者不活躍時可不預算（lazy 重建）。

### 2) Media 即時顯示，照片 8MB、影片 4GB（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：檔案經 app server 轉存 -> 頻寬與記憶體瓶頸，4GB 超時。
- 好解：presigned URL 直傳 S3 + **multipart/resumable upload**；CDN 分發。
- 最佳解：上傳完成事件（S3 event -> queue）觸發非同步 **轉檔/縮圖 pipeline**（Managing Long Running Tasks：workflow engine 如 Temporal/Step Functions，或 worker + queue）：產生多尺寸圖、影片轉 HLS/DASH 多碼率（adaptive bitrate），狀態 `uploading -> processing -> ready`；ready 前貼文不進 feed 或顯示 placeholder。CDN 邊緣快取 + 影片分段播放以達成「即時」。取捨：轉檔成本與延遲、儲存多版本。

### 3) 擴展到 500M DAU（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 SQL。
- 好解：Post/Follow 表水平分片（posts 以 userId 或 snowflake id 分片）；Feed cache Redis cluster；讀副本；CDN 吸收大部分媒體流量（媒體是頻寬大宗）。
- 最佳解：各層獨立擴展——API 無狀態水平擴；Feed 寫入走 Kafka 並按 followerId 分區；熱門貼文/名人 metadata 多層快取；跨區域部署 + 地理路由；媒體冷熱分層（舊檔移至 S3 IA/Glacier）。

## 關鍵數字與 back-of-envelope
（補充，非原文，除 500M DAU 與 1 億貼文/天為原文）
- 每天 1 億貼文，平均媒體 2MB（混合照片與影片）≈ 200TB/天 ≈ 70PB/年（未計多版本）-> 儲存與 CDN 是成本大宗。
- Feed cache：500M 使用者 × 500 筆 × 8 bytes ≈ 2TB（只存 id），可行。
- 若平均 200 followers：1,160 posts/s × 200 ≈ 23 萬 fan-out writes/s。

## 可遷移的 pattern
1. **Presigned URL 直傳 + multipart 斷點續傳**：大檔不走 app server。
2. **Fan-out on write / read 混合**（以粉絲數閾值切換）。
3. **非同步處理 pipeline + 狀態機**（轉檔、縮圖、HLS）。
4. **CDN + Blob store + metadata 分離**。
5. **Feed 只存 id、hydrate 時批次查詢**，減少 cache 體積。

## 常見追問
- **名人發文瞬間如何不拖垮系統？** 不 fan-out，讀時 merge；或延遲/分批 fan-out 給活躍粉絲優先。
- **使用者追蹤/取消追蹤後 feed 怎麼更新？** 追蹤時回填最近 N 筆；取消時讀時過濾（或非同步清）。
- **Chronological 與排序演算法的差異？** 本題僅時序，排序需要 ranking service，無法純靠 sorted set。
- **影片 4GB 上傳中斷？** multipart 記錄已完成 part，從斷點續傳。
- **刪除貼文？** soft delete + 非同步清 feed cache 與 CDN purge；讀時過濾 tombstone。
