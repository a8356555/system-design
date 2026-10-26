# Hystrix：Netflix 的 latency 與 fault tolerance library（Case Study）
> 原文：https://github.com/Netflix/Hystrix/wiki（Home / How-it-Works / Configuration 三頁已讀；下列「原文重點」多數段落只出自此 wiki）；另以 Netflix TechBlog 2011-12-08 Ben Schmaus「Making the Netflix API More Resilient」（Hystrix 的前身設計，原文經 Wayback Machine 存檔（https://web.archive.org/web/2026/https://netflixtechblog.com/making-the-netflix-api-more-resilient-a8ec62159c2d）核對；該文本身未出現 Hystrix 名稱，也未談 thread pool 隔離細節）補充，見「2011 TechBlog 原文補充」一節 ｜ Netflix / 2011 起，2012-11 開源（日期取自貼文，wiki 頁面未逐字確認發布日） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DeeijLkjI_M（2026-10-14）

## 一句話重點
Hystrix 的核心不是「斷路器」本身，而是每個依賴一個獨立 thread pool（bulkhead）加上 pool 滿了直接拒絕的 fail fast；一個依賴變慢只會榨乾自己的 pool，不會拖死整個服務。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- 每天處理數百億次呼叫的系統，靠的不是把請求排隊處理完，而是直接拒絕。
- Netflix 的說法：高流量網站上，一個後端依賴變慢，幾秒內就能榨乾所有 application 資源。Netflix API team 從 2011 年認真處理，2012 年 11 月正式發布 Hystrix。
- 故障機制：依賴變慢，呼叫方 thread 卡在等回應，請求持續堆積，直到整個 thread pool 被佔滿，連與該依賴無關的新請求都處理不了。
- 核心解法是 thread pool isolation：每個依賴有自己的 pool；pool 滿了就拒絕新請求而非排隊，這才是真正的 fail fast。
- 具體門檻：10 秒滾動視窗內 20 個以上請求且錯誤率超過 50%，電路跳 Open，短路 5 秒，之後放一個請求試探是否恢復。

## 原文重點
### 背景與規模數字（Hystrix wiki）
- 動機：服務數多時可用性乘積下降。wiki 的例子：30 個服務各 99.99% uptime，整體約 99.7%，約每十億請求 300 萬次失敗，每月超過 2 小時 downtime。
- 依賴變慢會耗盡 container 所有 thread，並向上游傳播成 cascading failure。
- 規模：Netflix API 每天 10+ 億次 Hystrix command 執行（How-it-Works 頁寫 "10+ billion"），約 40+ 個 thread pool，每個 5-20 threads；Home 頁稱每天有數百億次 thread-isolated 與數千億次 semaphore-isolated 呼叫。
- 開銷：單機 60 RPS 時，thread 隔離額外延遲 median 可忽略、p90 約 3ms、p99 約 9ms，被認為值得。

### 目標
- 防止單一依賴耗盡 container 所有 thread；load shedding 與 fail fast，而非排隊；可行時提供 fallback；用 circuit breaker 與 bulkhead 隔離故障；即時監控與動態調整設定。

### 執行流程（每次呼叫）
1. 建立 HystrixCommand，以 execute / queue / observe / toObservable 執行。
2. 查 response cache。
3. 查 circuit 狀態：Open 就直接短路走 fallback。
4. 查 thread pool / queue / semaphore 是否有空位，沒有就 reject 走 fallback。
5. 實際呼叫依賴（有 timeout）。
6. 回報 success / failure / rejection / timeout 給 metrics，更新 circuit 健康度。
7. 失敗（exception、circuit open、pool 滿、timeout）則走 fallback；成功則回傳。

### Circuit breaker 狀態機
- Closed -> Open：滾動視窗內請求量超過 requestVolumeThreshold 且錯誤率超過 errorThresholdPercentage。
- Open：短路所有請求。
- Half-open：經過 sleep window 後放一個測試請求；成功則 Closed，失敗則回 Open。
- 預設值（Configuration 頁）：requestVolumeThreshold 20、errorThresholdPercentage 50、sleepWindow 5000ms、rolling stats window 10000ms、執行 timeout 1000ms、thread pool coreSize 10、maxQueueSize -1（用 SynchronousQueue，即不排隊）。這與貼文的 10 秒 / 20 請求 / 50% / 5 秒完全對應。

### 隔離策略取捨
- Thread pool（Netflix 偏好）：能設 timeout、可讓呼叫方「放手走人」，隔離最徹底；代價是 thread context switch 開銷（見上）。
- Semaphore：只限制並發數，無法 timeout；適合延遲低且可信任的 client、極高 QPS 的記憶體內呼叫。
- maxQueueSize 預設 -1：刻意不排隊，與「寧可拒絕不要排隊」一致。

### Fallback 設計
- getFallback 應避免再走網路；常見是 cache、預設值、靜態內容或降級回應（補充）。

### 2011 TechBlog 原文補充（Making the Netflix API More Resilient，已對照原文）
- 背景：API 為數百種裝置仲介 catalog 與 subscriber metadata，處理約每日 10 億請求；尖峰約 20,000 RPS，10 秒 = 20 萬個 client 請求，可放大成 100 萬+ 對上游服務的請求。
- 三原則：依賴故障不應破壞會員體驗；API 應自動採取修正動作；要能看到「現在」的狀況（而非 15-30 分鐘前）。
- 作法：以裝飾（decorator）程式碼包住對每個 service dependency 的呼叫並追蹤結果；失敗太頻繁就停止呼叫、回 fallback，讓故障服務有恢復時間，並定期放少量呼叫通過，成功就重新開放全部流量。承襲 Michael Nygard《Release It!》的 CircuitBreaker pattern。
- 觸發 fallback 的三種情況（比基本 CircuitBreaker 更廣）：呼叫逾時；與該依賴互動的 thread pool 與有界 task queue 100% 滿載；client library 丟 exception。這些都計入該服務錯誤率，超過門檻就 trip circuit、不再嘗試連線直接回 fallback。
- 三種 fallback：Custom fallback（client library 提供的方法，或用 API server 本地資料如 cookie、JVM cache）；Fail silent（回 null，適合可選資料）；Fail fast（資料必要或無好 fallback，回 5xx，雖傷 UX 但保護 API server 並加速恢復）。理想是全部有 custom fallback，但維護完整覆蓋很難。
- 即時統計：以 10 秒滾動視窗計每個依賴的請求，超過 10 秒的資料丟棄；dashboard 用同一份統計（約 60 個 circuit，圓圈大小=流量、顏色=健康度，2 分鐘 sparkline 僅供顯示、不影響 circuit 邏輯）。
- 實例：shared cache 偶爾載入未完整填充的 Java 物件，團隊暫時繞過 cache 直連 DB，結果 DB 被 throttle；因 DB select 已有 custom fallback，circuit 自動 trip，改查本地 query cache（涵蓋大部分活躍資料），影片觀看量幾乎不受影響；dashboard 顯示該 circuit 錯誤率 80%、200 台 instance 中 157 台在回 fallback。
- （2011 文的 10 秒視窗與前述 wiki 預設的 rolling window 10000ms 一致；20 請求 / 50% / 5 秒等門檻僅見於 wiki 與貼文，2011 文未提。）

## 面試怎麼用
- Resilience / cascading failure 論點：為何 timeout 與 retry 不夠，需要 bulkhead（每依賴獨立資源池）加 circuit breaker。
- 任何 fan-out 到多個下游的題目（News Feed、API gateway、Uber）：說明每個下游獨立 pool、pool 滿即 reject 的設計，以及 Open / Half-open / Closed 三態與可調參數。
- Load shedding vs queueing：排隊在依賴變慢時只會讓 latency 與記憶體爆炸（補充：Little's law），拒絕才能保住健康請求。
- 取捨：thread isolation 的 p99 約 9ms 成本 vs semaphore 的輕量但無 timeout。
- 現況提醒（補充）：Hystrix 已進入維護模式，業界轉向 Resilience4j 與 service mesh 層級的 outlier detection，面試可講概念為主。

## 相關筆記
- ../../hellointerview-breakdowns/distributed-rate-limiter.md
- ../../hellointerview-breakdowns/metrics-monitoring.md
- ../../hellointerview-learn/patterns/scaling-reads.md
