# Metrics Monitoring（Datadog 類）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/metrics-monitoring ｜ 難度：hard ｜ 類別：Scaling Writes、Scaling Reads ｜ 作者 Stefan Mai

## 一句話核心
（原文）從 50 萬台機器收集指標、存成時序資料、提供 dashboard 查詢、並在 < 1 分鐘內評估告警；核心是每秒 500 萬點、約 1GB/s 的寫入，加上跨天/週的快速查詢與 cardinality 控制。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 從服務攝取指標（CPU、memory、latency、自訂 counter）
- 在 dashboard 上以 filter、aggregation、time range 查詢與視覺化
- 定義告警規則：時間窗內的門檻（如 p99 latency > 500ms 持續 5 分鐘）
- 告警觸發時通知（email、Slack、PagerDuty）
- Out of scope：日誌聚合與全文搜尋、分散式追蹤、ML 異常偵測

**Non-functional / 規模（原文）**
- 擴展到從 500k 台伺服器攝取 5M metrics/s
- Dashboard 查詢數秒內回應，即使跨數天或數週
- 告警低延遲：從指標發出到告警觸發 < 1 分鐘
- 高可用；dashboard 可最終一致，但告警評估要可靠
- 優雅處理延遲/亂序資料
- Out of scope：多 region 複製、強一致
- 原文註：1 分鐘看似慢，但告警多基於移動平均/趨勢，需累積資料；要立即觸發需精心設計指標（如 Amazon 用「距上一筆訂單的毫秒數」）；面試重點通常不在建 streaming event 系統

**規模數字（原文）**：500k servers × 100 points / 10s = 5M points/s；每點約 100-200 bytes -> 約 1GB/s 原始攝取。

## Core Entities & API
（原文僅標題；補充，非原文）
- Entities：Metric(name, labels/tags, ts, value)、Dashboard、AlertRule(query, threshold, window, channel)、AlertState
- API：
  - `POST /ingest`（批次 data points；或 agent 推送 / server 拉取）
  - `GET /query?metric=&filters=&agg=&from=&to=&step=`
  - `POST /alert-rules`

## High-Level Design
（原文僅標題；補充，非原文）
1. 攝取：Agent（每台機器）-> 負載平衡 -> Ingest Gateway（驗證、批次）-> Kafka（按 series hash 分區）-> Writer -> 時序資料庫（TSDB）。
2. 查詢：Query Service -> TSDB，支援聚合與 time range。
3. 告警：Alert Evaluator 週期性（如每 10-30s）對規則跑查詢/聚合，狀態機（OK/Pending/Firing）。
4. 通知：Alert Manager 去重、分組、靜默後，推送 email/Slack/PagerDuty。

## Deep Dives（依原文大綱逐條）
### 1) 如何對跨數週資料提供低延遲 dashboard 查詢？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每次查詢掃 raw 5M/s 資料，數週範圍要讀數百 TB。
- 好解：TSDB 按時間分區 + 欄式壓縮（delta-of-delta、Gorilla），並依 series 索引；縮小掃描。
- 最佳解：Downsampling/rollup：寫入時或背景任務預聚合成 1m、1h、1d 解析度（保存 min/max/sum/count 以便再聚合），查詢依時間範圍自動選擇適當解析度；舊資料 retention 分層（hot SSD -> cold object store）；常用 dashboard 查詢結果快取。
- 取捨：rollup 損失原始精度（尤其百分位，需保存 histogram/sketch 如 t-digest 才能合併）；多存一份資料。

### 2) 如何把告警延遲降到 1 分鐘內？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Evaluator 週期性對 TSDB 跑重查詢，要等資料落盤 + 查詢開銷，且每條規則獨立打 DB。
- 好解：在攝取路徑上平行消費 Kafka，對規則做串流式視窗聚合（維護每規則的滑動視窗狀態），不經過 TSDB。
- 最佳解：混合：關鍵規則走 stream（Flink/Kafka Streams）做 in-flight 視窗聚合；一般規則走週期查詢（共享查詢、批次同類規則）；規則按 series 分區到 evaluator 節點；處理遲到資料用 watermark + allowed lateness。
- 取捨：串流評估快但狀態管理複雜；週期查詢簡單但延遲較高。原文也指出面試不必過度堆疊 streaming 系統。

### 3) 如何在尖峰與故障期間確保高可用？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Agent 直接寫 TSDB，後端抖動就丟資料或拖垮 agent。
- 好解：中間放 Kafka 緩衝，agent 本地緩衝並重試；ingest gateway 無狀態可水平擴展。
- 最佳解：Kafka 吸收尖峰 + 背壓；寫入路徑與查詢路徑隔離；TSDB 副本 + 跨 AZ；告警 evaluator 做 leader election/多副本互備（alert 評估要可靠，dashboard 可降級）；對 agent 做取樣/降頻降級策略。
- 取捨：緩衝增加延遲與成本，但避免資料遺失；監控系統自身要被「更簡單的」系統監控（自我依賴問題）。

### 4) 如何處理 cardinality 爆炸？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：允許任意 label（如 user_id、request_id），series 數量爆增，索引與記憶體崩潰。
- 好解：限制每個 metric 的 label 數量與數值基數，攝取時拒絕或丟棄超額。
- 最佳解：per-tenant/per-metric series 配額 + 攝取時偵測高基數 label 並告警/降級；聚合掉高基數維度（pre-aggregation）；以 series ID（hash of labels）作索引，倒排索引控制大小；提供 cardinality 使用量儀表板給使用者。
- 取捨：限制維度會降低可觀測的細緻度，須教育使用者用 logs/traces 補足細節。

## 關鍵數字與 back-of-envelope
- （原文）5M points/s × 100-200B ≈ 0.5-1GB/s；500k servers。
- 補充：1GB/s ≈ 86TB/天原始量；經 TSDB 壓縮（Gorilla 約 1.37 byte/點）可降至十分之一以下，約數 TB/天量級。
- 補充：Kafka 假設單 broker 每分區 ~50MB/s 有效寫入，需數十個分區平行；Ingest 以批次（每請求數百點）降低請求數。
- 每台每 10s 發 100 點 -> agent 端批次成 1 個請求/10s，請求數僅 50k/s。

## 可遷移的 pattern（3-5 條）
1. 高吞吐寫入：agent 批次 + Kafka 緩衝 + 分區寫入。
2. 時序儲存：按時間分區、壓縮、rollup/downsampling + 分層 retention。
3. 告警：串流視窗評估 vs 週期查詢，視 SLA 選擇；處理遲到資料用 watermark。
4. 高基數控制：配額、聚合、拒絕。
5. 可靠性分級：告警路徑 > dashboard 路徑，降級順序明確。

## 常見追問（3-5 題，附簡短答案）
- Push 還是 pull？Pull（Prometheus）集中控制但需服務發現；Push 適合短生命週期工作，規模大時多用 agent push。
- 如何處理亂序/遲到資料？寫入以資料時間為準，TSDB 接受一定範圍內 out-of-order；告警視窗用 watermark。
- 告警風暴如何處理？去重、分組、抑制（inhibition）、for-duration 要求。
- 百分位如何跨主機聚合？不能平均 p99；用 histogram 或 t-digest/DDSketch 合併。
- 多租戶如何隔離？per-tenant 配額、獨立 Kafka topic/分區、查詢限流。
