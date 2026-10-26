# Google News（新聞聚合器）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/google-news ｜ Medium ｜ Scaling Reads（作者 Evan King；站內標題為 News Aggregator）

## 一句話核心
Crawler/Feed ingest 持續抓取 publisher 內容寫入儲存，讀取端以 CDN + 預先計算的 feed cache + cursor 分頁服務超大讀取流量；重點在「讀多寫少」與「30 分鐘新鮮度」。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 檢視來自全球數千個 publisher 的聚合新聞 feed。
- 可「無限」捲動 feed。
- 點擊文章導向 publisher 網站閱讀完整內容。

**Out of scope（原文）**：依興趣自訂 feed、儲存文章稍後閱讀、分享到社群。

**Non-functional**
- 原文：新聞平台 **availability 優先於 consistency**（用戶寧願看到稍舊內容也不要看不到）。
- 原文 Deep Dive 標題暗示：feed 請求 **< 200ms**；文章在發佈後 **30 分鐘內**出現在 feed；能應付突發新聞流量。
- 規模數字：原文未公開（補充：假設 1 億 DAU、數千萬篇文章/天級別需自行與面試官確認）。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`Publisher`（id, feedUrl, crawlFrequency）、`Article`（id, publisherId, title, summary, url, thumbnailUrl, publishedAt, category）、`Feed/Region`。
- API：
  - `GET /feed?cursor={opaque}&limit=20&region=...` -> `{articles[], nextCursor}`
  - 點擊：前端直接用 `article.url` 開新分頁（可選 `GET /click/{id}` 做 redirect + 計數）。

## High-Level Design
原文大綱：(1) 聚合 feed、(2) 無限捲動、(3) 點擊導向 publisher。

（補充，非原文 — 原文為 Premium）
- **聚合**：Crawler Service 定期抓 publisher 的 RSS/Atom 或爬 HTML，解析後去重（URL canonical / 內容 hash / simhash 近似去重），寫入 Article DB；縮圖寫 S3。
- **Feed 讀取**：Feed Service 從 DB 查最新文章（依 region/語言）；因全使用者看到的內容幾乎相同（未個人化），可大量快取。
- **無限捲動**：cursor-based pagination（用 `(publishedAt, articleId)` 作為 cursor），不用 offset。
- **點擊**：僅導向 publisher 原站，我們不託管全文（避免版權與儲存成本）。

## Deep Dives（依原文大綱逐條）
### 1) How can we improve pagination consistency and efficiency?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：`OFFSET/LIMIT` -> 新文章插入導致重複/遺漏，offset 愈大愈慢。
- 好解：**Keyset/cursor 分頁**：`WHERE (publishedAt, id) < (cursor) ORDER BY ... LIMIT n`，走複合 index，穩定且 O(log n)。
- 最佳解：cursor 為 opaque token（編碼 timestamp+id）；對熱門 feed 預先建「快照 feed」並於 cursor 內帶 snapshot version，讓同一次捲動 session 看到一致的序列。取捨：快照 vs 新鮮度。

### 2) How do we achieve low latency (< 200ms) feed requests?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：每次請求 query DB 並 join publisher。
- 好解：Redis 快取每個 feed（region/category）最新 N 筆 article id list + article metadata。
- 最佳解：**預先計算 feed**（背景 job 寫入 Redis sorted set，score = publishedAt）+ **CDN 邊緣快取**第一頁（短 TTL 例如 30-60 秒）+ 後續頁走 cursor。Read replica / 分區。取捨：快取一致性（AP 可接受 stale）。

### 3) How do we ensure articles appear in feeds within 30 minutes of publication?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：統一每小時全量爬所有 publisher。
- 好解：依 publisher 更新頻率自適應 crawl 排程（大站 1-5 分鐘、小站 30 分鐘）；用優先級 queue。
- 最佳解：優先使用 **RSS push / WebSub / sitemap ping**，沒有的 fallback 輪詢；crawl 任務放 queue 由 worker pool 並行抓取，遵守 robots.txt 與 rate limit；新文章寫入後主動 invalidate/更新 feed cache。以 SLA 監控「publish -> visible」延遲。

### 4) How do we handle media content (images/videos) efficiently?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：直接 hotlink publisher 圖片 -> 慢、對方站被打爆、可能失效。
- 好解：抓取時下載縮圖到 S3，CDN 分發。
- 最佳解：產出多種尺寸/格式（WebP/AVIF）的 thumbnail，lazy loading；影片只存 poster + 外連（不託管）。取捨：儲存成本 vs 速度與可靠度。

### 5) How do we handle traffic spikes during breaking news?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：靠 origin 自動擴容 -> 反應不及、DB 被打垮。
- 好解：CDN + 多層快取（edge、Redis、app local cache），Feed 無個人化因此 hit rate 極高。
- 最佳解：預熱 + request coalescing（cache stampede 防護，singleflight）+ 限流與降級（回傳稍舊 feed）+ 讀寫分離。因 AP 取向，可接受 stale-while-revalidate。

### 6) Bonus: category-based feeds（原文標題）
（補充，非原文）每個 category 有自己的 feed key（`feed:{region}:{category}`）；文章入庫時由分類器（規則或 ML）打標籤，寫入多個 feed 的 sorted set。

### 7) Bonus: personalized feeds（原文標題）
（補充，非原文）兩階段：candidate generation（熱門 + 類別 + 追蹤來源）-> ranking（點擊歷史、新鮮度、多樣性）；使用者行為經 Kafka 更新 user profile/embedding；個人化 feed 不易 CDN 快取，需在 Feed Service 層組合共享快取 + 小量個人排序。

## 關鍵數字與 back-of-envelope
（補充，非原文）
- 1 億 DAU × 每人 10 次 feed 請求/天 = 10 億/天 ≈ 1.2 萬 QPS 平均，高峰 ×5-10 ≈ 10 萬 QPS。
- 寫入：1 萬 publisher × 每 5 分鐘 = ~33 crawl/s；新文章 ~數十萬/天 -> 寫入極小，系統是 read-heavy（讀寫比 > 1000:1）。
- 文章 metadata ~1KB × 50 萬/天 ≈ 0.5GB/天，不是儲存問題。

## 可遷移的 pattern
1. **Cursor/Keyset 分頁取代 offset**（所有無限捲動 feed）。
2. **預先計算 feed + 多層快取（CDN -> Redis -> DB）** 處理 read-heavy。
3. **Cache stampede 防護**：request coalescing、stale-while-revalidate。
4. **Pull + Push 混合的 ingest**：RSS push 優先、輪詢 fallback，依來源活躍度自適應頻率。
5. **AP 取向 + 可降級**：寧可給舊資料，也不要沒資料。

## 常見追問
- **重複文章（多個 publisher 轉載）？** canonical URL + simhash/MinHash 近似去重，聚類成 story cluster。
- **cursor 失效怎麼辦？** cursor 只含時間與 id，不依賴 server 狀態，天然穩定。
- **怎麼知道文章是否發佈？** RSS `pubDate`、sitemap `lastmod`、WebSub 通知。
- **突發新聞如何優先顯示？** 熱度信號（多來源同時報導的 cluster 大小）加權排序。
- **多語言/多地區？** feed key 帶 locale/region，各區獨立快取與 crawler。
