# Temporal
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/temporal ｜ 分類：deep-dives

## 一句話重點
Temporal 是以 durable execution 為核心的 workflow orchestration：把每個外部操作的結果記進 Event History，worker 掛掉後由另一個 worker replay Workflow code 重建狀態；因此 Workflow code 必須 deterministic，外部副作用（Activity）必須 idempotent。

## 它是什麼 / 核心機制

### 從零推導出 Temporal（原文用「自己做一個」的方式講）
以電商 processOrder 為例：扣款 → 保留庫存 → 出貨 → 等送達（可能數天）→ 寄評價信。問題：Stripe 扣款成功後 server crash，新 server 怎麼知道扣過沒？重跑會重複扣款。

1. **Replay**：所有外部操作都經過 framework，完成時記錄「已完成 + 結果」（如 `ChargeCustomerCompleted {result: paymentId_123}`）。換一台 server 從頭再跑 function，framework 遇到已有紀錄的操作直接回傳舊結果，沒紀錄的才真正執行並記錄。→ 不需還原原本 process 就能重建程式狀態。
   - 若 Stripe 成功但 server 在回報前 crash，framework 可能重試 → 外部副作用仍須 idempotent。
   - 於是自然分出兩種 code：可 replay 的 **Workflow**（orchestration）與在外界作用的 **Activity**。
2. **Deterministic**：replay 必須走同一條路徑。反例：`if currentTime() < 5PM` 在 4:59 走 same-day 分支，replay 時已 5:03 走 next-day 分支，與 history 衝突。解法：時間也經過 framework（第一次記錄、replay 回傳同一個邏輯時間）。Temporal SDK 提供 workflow-safe 的 time 等操作；不能在 Workflow 直接讀時鐘或不確定的值。
3. **Durable timer**：`sleep(5 days)` 不能真的佔住一個 worker（可能同時數百萬訂單在等）。framework 計算 fireAt 持久化（`TimerStarted`），停止執行並釋放 worker；背景 scheduler 依 deadline 排序讀取，到期寫入 `TimerFired` 並重新排程 Workflow。Workflow 可睡 5 天或 5 個月而無 process 常駐。History Service 掛了，別的 instance 從 storage 恢復 pending timer；故障只會延遲 timer，不會遺失。
4. **Signal**：等待外部事件（carrier webhook 說包裹已送達）。把外部輸入 append 到 Workflow history（如 `PackageDelivered`）並喚醒 Workflow，replay 到 `waitUntilDelivered` 時已有事件 → 繼續。

### Temporal 是什麼
- Workflow = 可 replay 的 orchestration；Activity = 與外界互動的工作；結果記在 durable Event History；Workflow code 必須 deterministic；Timer 讓它等待不占 worker；Signal 讓外部送資訊進執行中的 Workflow。最後 code 看起來就是原本的 sequential 版本。

### 內部架構（原文說面試幾乎用不到，可略）
- **Frontend Service**：stateless 入口；**History Service**：擁有 Workflow Execution 的 durable state（處理 Activity completion、Signal、timer、decision）；**Matching Service**：管理 Task Queue；**Workers**：你的應用 process，主動 poll Temporal 取得工作、執行 code、回傳結果（Temporal Service 本身不執行你的 Workflow/Activity code）。四者可各自獨立 scale。
- **History Shards**：Workflow 分到固定數量的 shard，每個 History instance 擁有部分 shard；instance 增減/失效時 shard ownership 可轉移。
- **Mutable State**：Workflow 當前 server-side 狀態的 materialized view（pending activities、timers、child workflows），避免每次掃整份 Event History；Event History 仍是可還原狀態的 durable 紀錄。
- **Transfer Task（transactional outbox）**：狀態更新與「接下來要做的事」同一個交易持久化（Event History 更新 + Mutable State + Transfer Task），背景 processor 再送到 Matching，即使 History commit 後 crash 也知道還有工作要派發。Timer 用同機制（Timer Task）。
- 儲存：自架可用 PostgreSQL、MySQL 或 Cassandra；Temporal 管理 schema。
- **Workflow Cache + Sticky Execution**：Worker 在記憶體快取已重建的 Workflow，後續 Workflow Task 盡量路由回同一 Worker（Worker 同時 poll 一般 Task Queue 與 worker 專屬 Sticky Queue）。Worker crash 或 cache evict 時，下一個 Task 走一般 queue 由別的 Worker replay history。→ Event History 保證正確性，cache/sticky 只是效能優化。
- **Task Queue**：以名稱（如 `payments`）作為工作目的地，Worker poll 同名 queue。Workflow Task（跑 Workflow code 決定下一步）與 Activity Task（執行 Stripe/寄信等）不一定在同一批機器：可分 CPU-heavy fleet、GPU fleet、隔離的 payment service 等。Matching 不知道 Worker 實作，只做 task 與 polling worker 配對；有 worker 在 poll 時直接交付，否則存在 persistence DB 等待。Task Queue 可 partition 到多個 Matching instance 增加吞吐。

### Scaling
- 等待中的 workflow 只占 DB 空間，不占 Worker；所需 Worker compute 取決於「可執行的工作量」而非「開啟中的流程數」。
- Temporal Service 可分開擴：Frontend（API 流量）、History（shard 所有權）、Matching（queue partition）。若瓶頸在 Workflow state 更新，加 application Worker 沒用，要加 History 或其 DB 容量。

## 何時用 / 何時不用
**用**：多步驟流程要在失敗與長時間等待下存活。徵兆：你開始自己寫 state machine（持久化做到哪一步、排程下一步、重試、worker crash 後恢復）。
- 多個相依步驟需可靠完成（YouTube：切段 → 平行轉碼 → 合併）。
- 流程需長時間開著等外部事件（Uber：等司機回應或 timeout 再試下一位）。
- 需從部分執行中恢復（YouTube worker 在 DAG 中途消失仍可重建並繼續）。
- 重試與恢復已成為應用邏輯的重要部分（等於在自建 workflow engine）。
- 單一非同步 job，queue 就夠；Temporal 價值在於協調跨多步驟與失敗的整個流程。

**不用 / 限制**
- 簡單背景 job（Notification System breakdown 刻意用 queue，因為要展示 delivery/retry 機制；單一獨立 job 用 SQS 更簡單）。
- Streaming workload：不是 Kafka 的替代品。
- 外部副作用仍需 idempotency（Activity 可被重試，Stripe/DB 呼叫可能執行多次）。
- Workflow code 有限制：結果會變的操作（DB 查詢、外部 API）通常必須放 Activity。
- 面試警告：不是每個面試官都允許用 Temporal；若題目本身就是要你設計 durable workflow orchestration，放進 Temporal 等於一格解掉最難的部分。理解其原理即得到自行設計的藍圖。

## 面試常考的進階點
1. **為什麼需要 deterministic**：replay 對 history 比對；時間/隨機/外部呼叫會造成分支不一致。
2. **Idempotency**：Activity at-least-once；crash 發生在「外部成功」與「記錄完成」之間會重試 → 用 idempotency key 等方式讓外部操作安全重試（Multi-step Processes pattern）。
3. **Durable timer vs 常駐 sleep**：timer 以 deadline 排序存在 durable storage；服務故障僅延遲不遺失；Flash Sale 的庫存保留過期可用 Temporal timer 在 Sale Service 之外 durable 地到期。
4. **Signal vs polling**：外部事件寫入 history 並喚醒 Workflow，無須 worker 常駐。
5. **Transactional outbox**：state + Transfer Task 同交易，避免「狀態更新了但下一步工作遺失」。
6. **效能 vs 正確性分離**：Event History = 正確性；sticky cache = 效能。
7. **瓶頸定位**：Worker 備份（加 Worker）vs Workflow state 更新率（加 History/DB）。
8. **Task Queue 路由**：不同 Activity 類型獨立 fleet（CPU/GPU/隔離的 payment）；queue partition 提升吞吐。
9. **Temporal 與替代方案**：事件協調（choreography）、AWS Step Functions；Multi-step Processes 文章比較取捨。
10. **回答策略**：先講你要設計的流程在哪需要故障恢復/等外部輸入；queue+worker 夠就保持簡單；否則以「不然得自建狀態追蹤/重試/恢復」作為引入 Temporal 的具體理由。

## 關鍵數字
- 原文無硬性效能數字。範例中：Uber 提供司機 offer 後等 10 秒；訂單範例 timer 5 天；History 以「固定數量」的 History Shards 分片（未給數值）。

## 相關題目
- [Uber](../../hellointerview-breakdowns/uber.md)（逐一向司機 offer，等 10 秒）
- [YouTube](../../hellointerview-breakdowns/youtube.md)（影片處理 DAG）
- [Flash Sale](../../hellointerview-breakdowns/flash-sale.md)（庫存保留 timer）
- [Notification System](../../hellointerview-breakdowns/notification-system.md)（反例：用 queue）
- [Job Scheduler](../../hellointerview-breakdowns/job-scheduler.md)、[Payment System](../../hellointerview-breakdowns/payment-system.md)（補充：相近的多步驟/重試議題）

## 自測問題
1. Replay 如何避免重複扣款？它的前提是什麼？
   答：每個 Activity 完成結果記在 Event History，replay 時直接回傳舊結果不重呼叫。前提是 history durable；若外部成功但未被記錄就 crash 仍可能重試 → Activity 須 idempotent。
2. 為何 Workflow code 不能直接呼叫 `currentTime()` 或查 DB？
   答：replay 必須與 history 走同一路徑；時間/DB 結果會變造成分支不同。需用 SDK 的 workflow-safe API，或把會變的操作放 Activity。
3. Workflow sleep 5 天時，什麼東西在持有它？
   答：History Service 中的 Timer Task（含 deadline）持久化在 DB；背景 timer processor 到期寫 TimerFired 並排程 Worker。沒有 process 常駐，服務重啟後從 storage 恢復。
4. Transfer Task 解決什麼問題？
   答：state 更新與「接下來要派發的工作」同交易寫入（transactional outbox），即使 commit 後 crash 也不會遺失下一步派發。
5. 什麼情況下不該用 Temporal？
   答：單一簡單背景 job（SQS 即可）、高量 streaming（用 Kafka）；另外要記得它不免除 idempotency 責任。
