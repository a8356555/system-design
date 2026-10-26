# Price Tracking Service（CamelCamelCamel）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/camelcamelcamel ｜ 難度：medium ｜ 作者 Evan King

## 一句話核心
（原文）追蹤 Amazon 商品價格歷史並在降價時通知用戶；核心挑戰是「對 Amazon 要 polite」地蒐集 5 億商品價格、防範 Chrome extension 的惡意資料，以及降價事件的 fan-out 通知。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 用戶可查看 Amazon 商品價格歷史（網站或 Chrome extension）
- 用戶可訂閱降價通知並設定門檻（網站或 extension 一鍵訂閱）
- Out of scope：商品搜尋/探索、跨零售商比價、評論整合

**Non-functional（原文）**
- Availability > Consistency（eventual consistency 可接受）
- 支援 5 億（500M）Amazon 商品
- 價格歷史查詢 < 500ms
- 降價通知在價格變動後 1 小時內送達
- Out of scope：價格資料強一致、sub-minute 即時更新

**規模數字（原文）**：500M products；Chrome extension 1M 活躍用戶。

## Core Entities & API
（原文僅有標題，以下為補充，非原文 — 原文為 Premium）
- Entities：Product(asin, title, url)、PricePoint(asin, ts, price)、User、Subscription(user, asin, threshold)
- API：
  - `GET /products/{asin}/price-history?range=90d` -> `[{ts, price}]`
  - `POST /subscriptions {asin, threshold}`
  - `POST /prices {asin, price, ts}`（extension 回報用，需驗證）

## High-Level Design
（原文僅有兩個需求的標題；圖與細節為補充，非原文）
1. 查價格歷史：Client -> API Gateway -> Price History Service -> 時序儲存（依 asin 分區，按時間排序）。
2. 訂閱降價：Client -> Subscription Service -> 訂閱 DB（以 asin 為 key，方便降價時反查）。
3. 資料來源：Crawler 週期性抓價 + extension 眾包回報 -> 寫入 Price 儲存 -> 發出 price-change event -> Notification Worker。

## Deep Dives（依原文大綱逐條）
### 1) 如何有效率地發現並追蹤 5 億商品？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 cron 全量輪詢 500M 商品。以每商品每天一次估算約 5.8k req/s 持續打 Amazon，必被封鎖，且大部分冷門商品根本沒人看。
- 好解：依「熱度」分級排程：有訂閱者/高瀏覽量的商品高頻（每小時），冷門低頻（每天~每週）。Priority queue + 分散式 crawler fleet，per-domain rate limit、rotating proxies、遵守 robots/退避。
- 最佳解：混合「Crawler + extension 眾包」。用戶在 Amazon 頁面瀏覽時 extension 順帶回報價格，熱門商品幾乎免費獲得資料；crawler 只補洞（長尾 + 久未更新）。商品發現靠 extension 回報的新 ASIN 與 sitemap。
- 取捨：眾包省成本、擴散快，但引入資料可信度問題（見下題）；crawler 可靠但貴且有被封風險。

### 2) 如何處理 Chrome extension 用戶的惡意價格更新？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：直接信任 extension 傳來的價格並寫入。任何人都能把價格改成 $0.01 觸發全站通知，或污染歷史。
- 好解：Server 端 sanity check（與最近價格偏差過大則拒收/待審）+ per-user rate limit。
- 最佳解：多來源共識（quorum）：同一 ASIN 在一個時間窗內需 N 位獨立用戶回報相近價格才採信；用戶信譽分數加權；可疑值再派 crawler 驗證（以官方抓取為 ground truth）。異常者降權或封鎖。
- 取捨：quorum 增加延遲，冷門商品可能湊不到 N 人，需 fallback 到 crawler。

### 3) 如何有效處理價格變動並通知訂閱者？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每次價格更新就掃全部 Subscription 表比對門檻，O(訂閱數)。
- 好解：Subscription 以 asin 為 partition key，價格變動時只查該 asin 的訂閱者，再比門檻。
- 最佳解：只在「價格真的變動」時才發 event（dedupe）到 Kafka（key=asin）；訂閱按 threshold 排序，只取 threshold >= newPrice 的那段；Worker 批次發送、用 notified 標記避免同一降價重複通知。SLA 為 1 小時，可批次化而非逐筆即時。
- 取捨：1 小時 SLA 讓我們可用批次/微批降低成本，不必追求 streaming。

### 4) 如何快速提供價格歷史圖表查詢？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每次請求即時從 raw 資料掃整段並聚合。
- 好解：時序友善儲存（按 asin + 時間 range 分區，如 Cassandra/DynamoDB 以 asin 為 PK、ts 為 SK），只存「價格變動點」而非每次抓取。
- 最佳解：只存變動點（step function，資料量大減）+ 預先算好 1m/3m/1y 的 downsampled 視圖 + CDN/Redis 快取熱門商品圖表資料。
- 取捨：預聚合要多存一份、需維護，但換取 <500ms 穩定延遲。

## 關鍵數字與 back-of-envelope
- 500M 商品；若每天全量刷新 1 次 = 500M/86400 ≈ 5.8k req/s（對 Amazon 太重，故需分級）。
- 若熱門 1% (5M) 每小時刷新 = 5M/3600 ≈ 1.4k req/s，可行。
- 只存價格變動點：假設平均每商品每月變動數次，500M × ~5 點/月 × ~20B ≈ 數十 GB/月量級，遠小於全量取樣。
- 通知 SLA 1 小時 -> 可批次處理。

## 可遷移的 pattern（3-5 條）
1. 依熱度分級的 crawl/refresh 排程（priority + per-domain rate limit）。
2. 眾包資料 + quorum/信譽 + 官方抓取驗證，抵禦不可信客戶端。
3. 以「被訂閱的 key」為 partition，事件驅動做反向索引式通知，避免全表掃描。
4. 只存變動點（change-only）+ downsampling 預聚合 + 快取，服務時序圖表。
5. 把 SLA 放寬（1 小時）換成批次處理的成本優勢。

## 常見追問（3-5 題，附簡短答案）
- 被 Amazon 封鎖怎麼辦？降低頻率、proxy 池、依賴 extension 眾包降低 crawler 比重、必要時改用官方 API/聯盟資料。
- 同一降價會重複通知嗎？Subscription 記 last_notified_price，只有再次跨越門檻才通知；通知 key 做 idempotency。
- 如何支援「歷史最低價」徽章？在寫入時維護 per-asin min/max 摘要欄位，查詢 O(1)。
- Extension 用戶百萬級回報量？客戶端先本地 dedupe + 只在價格與已知值不同時才上報，server 端以 asin 分區 Kafka 削峰。
- 價格有多幣別/多 marketplace？asin 加上 marketplace 作為 key 一部分。
