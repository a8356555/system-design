# Web Crawler
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/web-crawler ｜ 難度：Hard ｜ 類別：Data processing pipeline（非 user-facing）

## 一句話核心
把「抓頁面 → 解析 → 發現新 URL」拆成以 queue 串接的多階段 pipeline（SQS 提供 visibility timeout / 指數退避 / DLQ），再用 per-domain 的 robots.txt + 鎖 + rate limit 保持禮貌，最後以頻寬估算（~8 台機器 ≈ 3.9 天）、DNS 優化、URL/內容去重、depth 上限達成 10B 頁 5 天內爬完。

## 需求
本題設定：爬網頁抽取純文字，供訓練 LLM（類似 OpenAI 訓練 GPT-4）。若是搜尋引擎則還需 index 與排名（PageRank 等），但面試重點都在「如何有效率地爬」。

**Functional（Core）**
- 從給定的 seed URLs 開始爬網
- 抽取每頁的文字並儲存，供後續處理

Out of scope：實際處理文字（訓練 LLM）、非文字資料（圖片/影片）、動態內容（JS 渲染頁）、需登入的頁面。
原文提醒：不可能爬完整個網路，只爬「絕大多數」；這點可跟面試官確認。

**Non-functional（Core）**
- Fault tolerance：優雅處理失敗，恢復爬取不丟進度
- Politeness：遵守 robots.txt，不過度壓垮網站
- Efficiency：5 天內爬完
- Scalability：處理 10B 頁

Out of scope：安全、成本、法規遵循。

**規模假設**：10B 頁、平均每頁 2MB（含 HTML 與 inline 資源的總傳輸量；純 HTML 通常約 30KB，2MB 是規劃頻寬的合理最壞值）、資料需在開爬 5 天後可供訓練。
原文建議：BOE 估算延後到真正需要解決某個問題時才做，並與面試官溝通。

## Core Entities & API
非 user-facing，故定義 **System Interface**：
- Input：seed URLs
- Output：從網頁抽出的文字資料

資料表（逐步長出來）：Metadata DB 的 URL table（HTML 與文字在 blob storage 的連結、content hash、depth…）、Domain table（robots.txt 規則、最後爬取時間）。

**Data Flow**
1. 從 frontier 取 seed URL，向 DNS 取 IP
2. 用 IP 向外部伺服器抓 HTML
3. 從 HTML 抽文字
4. 把文字存進 DB
5. 抽出連結 URL，加入待爬清單
6. 重複 1-5 直到爬完

## High-Level Design
```
Seed URLs -> [Frontier Queue] -> Crawler --DNS--> Webpage (external)
                 ^                  |  
                 |                  v
                 +-- new URLs   S3 (text data)
```
- **Frontier Queue**：待爬 URL（Kafka / Redis / SQS，之後決定）
- **Crawler**：抓頁面、抽文字、抽新 URL
- **DNS**：網域 → IP
- **Webpage**：外部伺服器（系統邊界之外）
- **S3 Text Data**：blob storage，高擴展、高耐久、便宜
- 要問面試官 seed URL 是否提供；通常會提供，若無可由熱門搜尋引擎、新聞網站、社群平台、web directory 開始。

## Deep Dives

### 1) 如何做到 fault tolerant、不丟進度？
**問題**：單一 crawler 做太多事（DNS、抓頁、抽文字、抽 URL…），任何一環失敗進度全失；最容易失敗的是抓頁（網站掛、連線慢、頁面太大）。

**解法：多階段 pipeline**（資料處理題的第一直覺）
- **URL Fetcher**：抓 HTML，失敗可單獨重試；原始 HTML 存 blob storage。
- **Text & URL Extraction**：抽文字與連結並將新 URL 加入 frontier。原文認為兩者可分開，但都很簡單，合併可簡化設計。
- 好處：隔離失敗、獨立擴展與最佳化各階段、對需求變動更有彈性（例如 ML 團隊要把 image alt text 納入文字，只需換 extraction 階段，不必重抓）。
- 新增 **Metadata DB**（DynamoDB 可，PostgreSQL/MySQL 亦可）記錄已抓取/處理的 URL，包含 HTML 與文字在 blob storage 的連結。
- **反模式**：不要把原始 HTML 放進 queue（queue 不適合大 payload 且貴）；queue 訊息只放 Metadata DB 中的 URL id。

**抓取失敗如何重試？**
- **爛解：in-memory timer**：等幾秒再試。crawler 掛了 timer 就丟了，且幾秒內多半不會成功，需要指數退避。
- **好解：Kafka + 手動指數退避**：另開 failed-URL topic 與專門 retry 服務，訊息內存「下次可抓時間」，consumer 讀到時間未到就等。可行但實作與維運複雜。
- **最佳解：SQS + 指數退避**：SQS 沒有內建指數退避設定，但提供 primitives：
  - **Visibility timeout**：consumer 收到訊息未刪除，逾時後訊息再次可見（預設 30 秒，可設到最長 12 小時）。
  - 用 `ChangeMessageVisibility` 搭配 `ApproximateReceiveCount` 動態調整 timeout 以達指數退避。
  - 不無限重試：queue 的 redrive policy（`maxReceiveCount`）超過次數自動移到 **DLQ**。本題設 **5 次重試後視為網站離線**。

**Crawler 掛掉？** 起新的即可，關鍵是半途的 URL 不丟：
- **Kafka**：訊息保留在 log，靠 offset 追蹤；URL 成功抓取處理後才更新 offset，失敗則下一個 consumer 從原位置繼續。
- **SQS**：訊息保留至明確刪除；visibility timeout 隱藏訊息，crawler 失敗則逾時後重新可見；HTML 存入 blob storage 後才刪訊息。
- Parser worker 掛掉同理。
- 選 SQS 的理由：visibility timeout 讓指數退避易實作、自動 DLQ、託管擴展。原文也說對 Kafka/SQS 細節不熟時，這不一定是該深入的地方。

### 2) 如何做到 politeness 並遵守 robots.txt？
robots.txt 範例：
```
User-agent: *
Disallow: /private/
Crawl-delay: 10
```
- Crawl-delay 並非官方 Robots Exclusion Protocol 標準，部分大型爬蟲（如 Googlebot）會忽略，但遵守代表良好禮儀。

需做兩件事：**(a) 遵守 robots.txt（Disallow + Crawl-delay）；(b) rate limiting（業界標準對單一網域 1 request/秒）**。

流程：
1. 對每個網域抓 robots.txt（簡化：一次性下載；實際可討論更新頻率）。
2. 解析後存進 Metadata DB（Domain table）。
3. 從 queue 取 URL，檢查該網域規則。
4. 被 Disallow → **ack 訊息**（移出 queue）跳過。
5. 允許 → 檢查 Crawl-delay；若距上次爬取時間未達 → 用 `ChangeMessageVisibility` 延長 visibility timeout 延後重新處理。
6. 已超過延遲 → 爬取並更新該網域最後爬取時間。

**Race condition**：多個 crawler 同時拿到同網域 URL，都看到過期的「最後爬取時間」。解法：用原子操作（如 Redis `SET NX` + TTL = crawl delay）取得 per-domain lock；拿不到鎖就用 ChangeMessageVisibility 延後。
- 注意 `DelaySeconds` 只對新發送的訊息有效；已 in-flight 訊息要用 `ChangeMessageVisibility`（可延至 12 小時）。

**Rate limiting（多 crawler 下）**：
- 用集中式 store（Redis）追蹤每個網域每秒的請求數，sliding window；超過就等到下一秒。
- 問題：同步行為（多個 crawler 在窗口重置時同時重試，只有一個成功，反覆發生）。
- 解法：**jitter**，加上隨機延遲避免同時重試。

### 3) 如何擴展到 10B 頁並在 5 天內爬完？
原文建議：**scaling 討論留到最後**，才看得到完整系統與瓶頸（如後來才出現的 parser workers）。擴展與效率一起談。

**Crawler 數量估算（I/O 密集）**
- 網路最佳化 instance（如 c6in.32xlarge、c7gn.16xlarge）頻寬最高 200 Gbps。
- 200 Gbps ÷ 8 ÷ 2MB ≈ **12,500 pages/s**（理論值，實務達不到）。
- 受限於伺服器延遲、DNS、rate limit、politeness、retry 等，假設只能用 30% → **3,750 pages/s**。
- 為何 3,750 pages/s 不違反單網域 1 req/s？因為同時爬數百萬個不同網域，每個 crawler 維持數千併發連線，單一網域至多 1 req/s，但總吞吐很高。
- 單機：10B ÷ 3,750 ≈ 2,666,667 秒 ≈ 30.9 天；÷ 8 台 ≈ **3.9 天** < 5 天。
- 假設很多，實務需 load test；面試重點是展現推理。

**Parser workers**：下載 HTML → 抽文字 → 存回 blob storage。依 Further Processing Queue 的積壓量動態擴縮（Lambda、ECS on Fargate 等），不必預估數量。

**DNS 瓶頸**
- 規模上（每秒數千請求、數百萬網域）DNS 會成為真正瓶頸；新網域的解析需跨 DNS 階層多次往返；Mercator crawler 論文發現在自建 resolver 前，DNS 查詢佔每個 thread 運行時間的**最高 70%**。
- 第三方 DNS 供應商通常有 rate limit，花錢可提高；其他優化：
  - **DNS caching**：同網域 URL 共用同一次查詢。
  - **多個 DNS 供應商 round-robin**：分散負載、降低觸頂風險（原文提到是 Staff 候選人提出，實務、跳脫學術答案）。

**效率：去重**
- **URL-level dedup**：放入 queue 前先查 Metadata DB URL table，已存在就跳過。
- **Content-level dedup**：不同 URL 可能同內容（`http://example.com` vs `http://www.example.com`，或不同網域內容相同）。抓完後 hash 內容，已見過就跳過昂貴的解析。兩種做法：
  - **Hash 存 Metadata DB + index**：hash 欄位建 index 快速比對。index 變大會拖慢寫入的擔憂其實過度悲觀，現代 DB 處理得很好。
  - **Bloom filter**：機率資料結構，說「不在」是確定的，說「在」有小機率誤判（false positive）；可用 Redis + RedisBloom（`BF.ADD` / `BF.EXISTS`），或用 Redis bit operations / 應用程式記憶體實作；加大 filter 與 hash function 數可降低誤判率。原文觀點：Bloom filter 在此偏 overkill，index 更實際；會提是因為候選人常提到。

**Crawler traps**
- 頁面不斷自我連結或連到大量頁面，使爬蟲永遠爬不完。
- 解法：**最大 depth**（以從 seed 起算的連結跳數計，非 URL path 段數）；seed 為 depth 0，URL table 加 depth 欄位，每跟隨一次連結 +1，超過門檻（如 15-20）就停止該分支。

### 額外 deep dive（原文列舉）
- **動態內容**：用 headless browser（如 Puppeteer）渲染。
- **監控**：Datadog / New Relic 監控 crawler 與 parser。
- **大檔案**：先送 HTTP HEAD 檢查 `Content-Length`，超過門檻（如 10MB）就跳過。
- **持續更新**：新增 **URL Scheduler**，parser workers 把 URL 寫進 Metadata DB，由 scheduler 依最後爬取時間、熱門程度等邏輯排程。
- **優先級爬取**：SQS 用多個不同優先級 queue，crawler 先 poll 高優先級；Kafka 無原生優先級消費，可用每個優先級一個 topic。

## 關鍵數字與 back-of-envelope
- 10B 頁 × 2MB（含 inline 資源；純 HTML 約 30KB）；5 天內完成
- 單機頻寬 200 Gbps → 12,500 pages/s 理論值；用 30% → 3,750 pages/s
- 單機 30.9 天 → 8 台約 3.9 天
- 單網域限速 1 req/s；SQS visibility timeout 預設 30 秒、最長 12 小時
- 5 次重試後視為離線（DLQ）
- crawler trap depth 上限 15-20
- Mercator：DNS 佔 thread 時間最高 70%
- 大檔門檻範例 10MB

## 面試官期待
- **Mid（E4，80/20）**：理解高階資料流並實作簡單可運作的系統（如 HLD）；能談 politeness 與 robots.txt 基本概念；對如何擴展有些想法，不要求 queue 技術與 rate limiting 的深度。
- **Senior（60/40）**：除 HLD 外要深入 politeness / robots.txt；能討論如何擴展與在 5 天內有效率爬完；熟悉 queue、cache 運作。
- **Staff+（40/60）**：至少深入 3 個以上關鍵領域，展現創新與最佳解；衡量標準是面試官是否從討論中獲得新見解；若做完上述所有 deep dive（即使不完整）就在好位置。

## 可遷移的 pattern
1. **多階段 pipeline + queue 解耦**：資料處理題第一直覺；隔離失敗、各階段獨立擴展與重試，中間產物放 blob storage，queue 只傳 id。
2. **Queue 的可靠投遞語意**：visibility timeout / offset commit 讓 worker 掛掉不丟工作；指數退避 + DLQ 處理反覆失敗。
3. **Per-key 禮貌 / 限流**：以 domain 為 key 做 Redis 分散式鎖（SET NX + TTL）與 sliding window rate limit，加 jitter 防止同步重試（thundering herd）。
4. **分層去重**：先 URL-level（便宜）再 content-hash（hash + index 優先，Bloom filter 為可選的機率式選項）。
5. **容量估算驅動機器數**：頻寬 ÷ 單頁大小 × 利用率 → 吞吐，再除以總量得機器數；並找出被忽略的瓶頸（如 DNS）。

## 常見追問
- **crawler 在處理途中掛掉怎麼辦？** 訊息保留在 queue（SQS 靠 visibility timeout 重新可見；Kafka 靠 offset 未提交），其他 crawler 接手；HTML 存入 blob 後才 ack/刪除。
- **如何避免對同一網站太兇？** 解析並儲存 robots.txt，Disallow 的 ack 跳過；Crawl-delay 以 Domain table 記錄最後爬取時間，不夠久就 ChangeMessageVisibility 延後；Redis per-domain lock 防併發；全域 1 req/s sliding window + jitter。
- **怎麼知道需要幾台機器？** 單機頻寬 200 Gbps ÷ 2MB ≈ 12,500 pages/s，取 30% 利用率 ≈ 3,750 pages/s；10B 頁約 31 天單機，8 台約 3.9 天。
- **兩個不同 URL 內容相同怎麼辦？** 抓取後 hash 內容，於 Metadata DB（hash 欄位 index）或 Bloom filter 比對，重複就跳過解析。
- **如何避免被 crawler trap 困住？** 記錄 depth 並設上限（15-20）。
- **如何支援定期重爬？** 加 URL Scheduler，根據最後爬取時間 / 熱門度決定何時重新放入 queue。
