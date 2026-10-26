# Job Scheduler（任務排程器）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/job-scheduler ｜ Medium ｜ Managing Long Running Tasks、Scaling Writes（作者 Evan King）

## 一句話核心
Job 存 DB + 以時間索引找出到期工作 -> 丟進 message queue -> worker 執行；關鍵在「2 秒內準時」、「10k jobs/s 水平擴展」、「at-least-once（失敗可重試、不丟）」。

## 需求（Functional / Non-functional / 規模數字）
**名詞（原文）**
- Task：抽象工作（如「寄 email」），可重用。
- Job：Task 的實例 = task + 排程時間 + 參數（如「週五 10:00 寄信給 john@example.com」）。

**Functional（原文）**
- 可排程 job：立即執行、未來某時間、或週期性（如「每天 10:00」）。
- 可監控 job 狀態。

**Out of scope（原文）**：取消或重新排程 job。

**Non-functional / 規模（原文有部分）**
- 系統需能執行 **10k jobs/s**（原文）。
- 大綱標題顯示：job 需在排定時間 **2 秒內**執行；**at-least-once** 執行（原文標題）。
- （補充）高可用、可擴展、job 不遺失。

## Core Entities & API
原文有「Core Entities / The API / Data Flow」標題但內文鎖住。（補充，非原文）
- Entities：`Task`（id, code/handler）、`Job`（jobId, taskId, userId, scheduleType, executeAt, cron, params, status）、`Execution`（jobId, runId, startedAt, status, attempt）。
- API：
  - `POST /jobs` `{taskId, schedule: {type: immediate|once|cron, ...}, params}` -> `{jobId}`
  - `GET /jobs?status=...`、`GET /jobs/{id}`（含執行紀錄）
- Data flow：User -> API -> Job DB；Scheduler 掃描到期 -> Queue -> Worker -> 更新狀態。

## High-Level Design
原文大綱：(1) 立即/未來/週期性排程；(2) 監控狀態。

（補充，非原文 — 原文為 Premium）
- **排程**：API Service 寫 Job 表。週期性 job 存 cron 表達式，另存 `next_run_time`；每次執行完計算下一個 `next_run_time`（或預先展開成下一筆 execution 記錄）。
- **執行**：Scheduler 定期查詢 `executeAt <= now AND status = pending` -> 推 queue -> Worker 取出執行 -> 寫 Execution/狀態。
- **監控**：user 查 Job/Execution 表，狀態機 `PENDING -> QUEUED -> RUNNING -> SUCCESS|FAILED|RETRYING`。Index：`(userId, createdAt)`、`(executeAt, status)`。

## Deep Dives（依原文大綱逐條）
### 1) How can we ensure the system executes jobs within 2s of their scheduled time?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：每秒對全表 poll `executeAt <= now` -> 全表掃 + 延遲取決於 poll 間隔。
- 好解：`executeAt` 加 index，Scheduler 每 ~1 秒查「未來 N 分鐘內即將到期」的 job，**提前載入記憶體/Redis sorted set（score = executeAt）**，到時間才推 queue。
- 最佳解：**兩階段**：(a) 分鐘級 cron 把下一個 5-10 分鐘的 job 從 DB 撈出，依 partition 丟入 delay queue（SQS delay、Redis ZSET、時間輪 timing wheel）；(b) 近期 job 由記憶體 timer 精準觸發。DB 僅做 durable store，不在熱路徑。取捨：提前載入需處理期間新增/修改 job（以 buffer window 與 version 處理）。

### 2) How can we ensure the system is scalable to support up to 10k jobs per second?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 Scheduler + 單一 DB -> 單點瓶頸。
- 好解：DB 水平分片（依 jobId hash 或 executeAt 時間桶）；Queue 分區；Worker 自動擴縮（依 queue depth）。
- 最佳解：**Scheduler 也分片**：每個 Scheduler 實例負責一組 shard（以 `hash(jobId) % N` + 租約/leader election 由 ZooKeeper/etcd 管理），避免重複觸發；寫入走 DynamoDB 類 NoSQL（partition key = 時間桶+shard，避免 hot partition）；Worker 依 job 類型分不同 queue/pool 隔離資源。
- 計算：10k/s × 86400 ≈ 8.6 億 jobs/天；每筆 ~1KB 元資料 ≈ 0.86TB/天 -> 需分片、TTL 清舊紀錄。

### 3) How can we ensure at-least-once execution of jobs?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：Worker 取出就刪 message -> worker 崩潰後 job 遺失。
- 好解：**Visibility timeout + ack**：Worker 完成後才 ack；逾時未 ack 的 message 重新可見（SQS 行為）。
- 最佳解：加上 **heartbeat / lease 延長**處理長任務（Managing Long Running Tasks）；失敗 exponential backoff + 最大重試次數 + **DLQ**；因為是 at-least-once，要求 Task 本身 **idempotent**（帶 `jobId+runId` 作為 idempotency key，下游去重）。Scheduler 層：把「狀態改成 QUEUED + 發送 queue」做成 transactional outbox，避免 DB 已更新但沒送出。
- 取捨：exactly-once 難以達成，要靠 at-least-once + idempotency。

### Final Design（原文標題，內容鎖住）
（補充）API -> Job DB -> Scheduler（分片）-> Delay/Priority Queue -> Worker pool -> Status 更新 -> Monitor。

## 關鍵數字與 back-of-envelope
- 10k jobs/s（原文）、2s 精準度（原文標題）。
- （補充）若 Worker 每個 job 平均 1 秒，穩態需 ~1 萬並行 worker slot；長任務（分鐘級）需更多並行與 lease 管理。
- Queue 吞吐：SQS 標準佇列幾乎無限 TPS；Kafka partition 單分區約數 MB/s~十萬 msg/s。

## 可遷移的 pattern
1. **DB 為 source of truth + 近期工作預載到記憶體/Redis ZSET（兩階段排程）**。
2. **Visibility timeout / ack / DLQ 的 at-least-once 執行模型** + **idempotent consumer**。
3. **Transactional outbox**：DB 狀態與 queue 發送一致。
4. **Scheduler 分片 + lease/leader election** 避免重複觸發與單點。
5. **Heartbeat/lease 延長處理長任務**。

## 常見追問
- **週期性 job 如何避免漂移？** 以排定時間（非實際完成時間）計算下一次 `next_run_time`；錯過的 run 看策略是補跑還是跳過。
- **兩個 Scheduler 同時撈到同一 job？** 以 `UPDATE ... WHERE status='pending'` 條件更新（CAS）或分片租約，只有一方成功。
- **Worker 執行到一半崩潰？** Visibility timeout 到期 message 重現，另一台接手；Task 需 idempotent。
- **優先級怎麼做？** 多個 queue（高/中/低）或 priority queue，Worker 加權輪詢。
- **如何支援取消/重排？**（原文列 out of scope）以 version/tombstone 標記，Worker 執行前檢查狀態。
