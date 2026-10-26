# Managing Long Running Tasks
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/long-running-tasks ｜ 分類：patterns

## 一句話重點
把重工作拆成兩階段：API 立即驗證、丟進 queue、回傳 job ID（毫秒內）；獨立 worker 慢慢做並更新狀態，client 輪詢或被推送結果。難點在失敗重試、冪等、backpressure、混合負載與 job 相依。

## 原文大綱（原文）
- 介紹（原文）：splits API requests into two phases: immediate acknowledgment and background processing. web server 立即驗證請求，把 job 推進 queue（Redis/RabbitMQ），回傳 job ID；獨立 worker 持續從 queue 取 job、執行耗時工作、把狀態更新到 database。
- The Problem（原文情境）：個人頁面查 DB < 100ms 很棒；但產生年度活動 PDF 報表（多表聚合、百萬列、畫圖）至少 45 秒，同步處理時 browser 乾等，且 web server／load balancer 常有 30–60 秒 timeout，使用者也無進度回饋。類似情境：影片轉碼、縮圖、寄大量電子報、匯入大 CSV。
- The Solution
- Trade-offs：What you gain / What you lose
- How to Implement：Message Queue / Workers / Putting It Together
- When to Use in Interviews：For Example
- Common Deep Dives：Handling Failures / Handling Repeated Failures / Preventing Duplicate Work / Managing Queue Backpressure / Handling Mixed Workloads / Orchestrating Job Dependencies
- Conclusion

## 內容（by agents）
### The Solution：非同步兩階段
```
Client -POST /reports-> API: 驗證 + INSERT job(status=PENDING) + enqueue -> 202 {jobId}
Worker: dequeue -> status=RUNNING -> 做事 -> 結果寫 blob store -> status=DONE
Client: GET /jobs/{id} (polling) 或 SSE/WebSocket/webhook 通知
```
回 HTTP 202 Accepted + `Location: /jobs/{id}`。

### Trade-offs
**得到**：快速回應、API 與重工作隔離（獨立擴縮）、可重試、削峰、worker 可用不同機型（GPU）。
**失去**：複雜度（queue、worker、狀態機、監控）、最終一致（結果不是立即）、需要處理重複與失敗、使用者體驗要設計（進度、通知）。

### How to Implement
- **Message Queue**：SQS / RabbitMQ / Kafka / Redis（Sidekiq、BullMQ、Celery）。要點：at-least-once、visibility timeout／ack、DLQ、可持久化。
- **Workers**：無狀態 consumer；依 queue 長度自動擴縮；graceful shutdown（收到 SIGTERM 處理完或放回 queue）；長任務定期 heartbeat／延長 visibility timeout。
- **Putting It Together**：Job table（id, type, payload, status, attempts, result_url, error, timestamps）+ queue + worker + 結果通知。Client 取結果：polling（簡單）、SSE／WebSocket（即時）、webhook（對外 API）。

## 常見深入題（by agents）
- **Handling Failures**：worker crash → 未 ack 的訊息 visibility timeout 後重新可見；checkpoint 長任務進度以便續跑；`attempts` 計數。
- **Handling Repeated Failures**：指數退避 + jitter、最大重試次數、超過後進 DLQ 並告警；區分暫時性（網路）與永久性（壞輸入）錯誤，永久錯誤不重試（poison message）。
- **Preventing Duplicate Work**：at-least-once 必然重複 → 冪等：job ID 當 idempotency key、狀態機用 conditional update（`PENDING→RUNNING` 只能一人成功）、輸出寫入用確定性 key；提交端也要冪等（client 帶 request-id 去重）。
- **Managing Queue Backpressure**：監控 queue depth／age；autoscale worker；入口 rate limit 或回 429；per-tenant 配額避免 noisy neighbor；有界 queue + load shedding；佇列過長時降級（拒絕低優先）。
- **Handling Mixed Workloads**：長短任務分開 queue（獨立 worker pool），避免短任務被長任務 head-of-line blocking；優先級 queue；不同資源需求（CPU/GPU）分池。
- **Orchestrating Job Dependencies**：簡單 chain 可由 worker 完成後 enqueue 下一步；有 fan-out/fan-in、條件分支、人工等待時，改用 workflow engine（Temporal、Step Functions、Airflow），見 [multi-step-processes](./multi-step-processes.md)。

## 面試怎麼用（by agents）
- 訊號：任務 > 數秒（轉碼、報表、批次匯入、AI 推論、爬蟲、排程）、需要重試、尖峰流量。
- 例：YouTube 上傳後轉碼、LeetCode 程式碼評測、Job Scheduler、Dropbox 後處理。
- 不要用：工作 < 100ms 且可同步完成、需要立即強一致回應。
- 一定要講：job 狀態機、冪等、重試與 DLQ、如何通知結果、queue 選型理由。

## 相關題目
- [youtube](../../hellointerview-breakdowns/youtube.md)
- [leetcode](../../hellointerview-breakdowns/leetcode.md)
- [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)
- [dropbox](../../hellointerview-breakdowns/dropbox.md)
- [web-crawler](../../hellointerview-breakdowns/web-crawler.md)

## 自測問題（by agents）
1. 為什麼回 202 而不是等結果？答：避開 timeout、改善體驗、隔離重工作。
2. worker 處理到一半 crash 會怎樣？答：訊息未 ack，visibility timeout 後重投遞；因此 handler 必須冪等。
3. 如何避免重複執行同一 job？答：job ID 作 idempotency key，conditional update 狀態轉換，輸出 key 確定性。
4. queue 越積越多怎麼辦？答：autoscale、限流／429、優先級與配額、load shedding、告警 queue age。
5. 長短任務混在一起有何問題？答：head-of-line blocking；分 queue／worker pool。

## 參考來源
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html
- https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/202
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
