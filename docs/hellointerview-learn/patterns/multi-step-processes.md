# Multi-step Processes
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/multi-step-processes ｜ 分類：patterns

## 一句話重點
跨多個服務、可能歷時數小時到數天的流程（訂單履約、付款、AI agent pipeline）要能撐過 crash、重試與部署。演進路線：單機原語 → Saga（補償）→ Event-driven choreography → Workflow orchestration／Durable execution（Temporal、Step Functions），把「系統層失敗處理」與「業務邏輯」分離。

## 原文大綱（原文）
- 介紹（原文）：Real production systems must survive failures, retries, and long-running operations spanning hours or days. Often they take the form of multi-step processes or sagas which involve the coordination of multiple services and systems.
- The Problem（原文重點）：引用 Jimmy Bogard 的演講「Six Little Lines of Fail」。範例：電商訂單履約——扣款、保留庫存、建立出貨標籤、等倉庫人員揀貨、寄確認信；每步呼叫不同服務或等人，都可能失敗／逾時，orchestrator 可能 crash 或被部署。補丁式作法（強化每個服務、delay queue、hook）讓系統更複雜脆弱，把系統層問題（crash、retry）與業務層問題（找不到商品怎麼辦）纏在一起。Workflow systems、event-driven sagas、durable execution 是解法；AI 系統設計面試尤其常用。
- 原文列出的相關題目：Uber、Payment System、Notification System
- Solutions：Single Server Primitives / The Saga Pattern / Event-Driven Choreography / Workflow Orchestration（Durable Execution Engines、How Durable Execution Works、Managed Workflow Systems、Implementations）
- When to Use in Interviews：Common interview scenarios / When NOT to use it
- Common Deep Dives：「What happens if the process running your saga crashes partway through?」「How will you handle updates to the workflow?」（Workflow Versioning、Workflow Migrations）「How do we keep the workflow state size in check?」「How do we deal with external events?」「How can we ensure X step runs exactly once?」
- Conclusion

## 內容（by agents）
### Single Server Primitives
單一程序內用 DB transaction、`try/catch`、retry loop、cron + 狀態欄位（polling table）。簡單、夠用於「步驟少、同一個 DB、可容忍重跑」。極限：crash 時 in-memory 狀態遺失；跨服務沒有 atomic transaction；等待型步驟（人、外部回呼）要自己寫 timer 與 poller。可加 **transactional outbox**（狀態更新與「待發訊息」同一交易寫入）降低雙寫不一致。

### The Saga Pattern
把長交易拆成一串本地交易，每步有對應 **compensating action**（反向操作：退款、釋放庫存）。失敗時反向執行已完成步驟的補償。特性：沒有 isolation（中間狀態可見，需 semantic lock／pending 狀態）；補償也可能失敗，需重試至成功；補償必須冪等；有些步驟不可逆（寄信）要排在最後。
兩種協調方式：choreography 與 orchestration（下）。

### Event-Driven Choreography
各服務訂閱事件、自行決定下一步（OrderCreated → PaymentService → PaymentSucceeded → InventoryService ...）。
優點：低耦合、無中央單點、天然適合 Kafka 事件流。
缺點：流程散落各服務，難以看全貌與除錯；循環依賴風險；難做 timeout、人工步驟、版本演進；補償邏輯分散。適合步驟少（3–4）、團隊自治的流程。

### Workflow Orchestration
由中央 orchestrator 明確定義步驟、順序、重試、timeout、補償。
#### Durable Execution Engines
以一般程式碼（Go/Java/TS/Python）寫 workflow，引擎保證「程式執行到哪都不會丟」，crash 後在別台機器續跑。代表：Temporal / Cadence、Azure Durable Functions、Restate、Inngest。
#### How Durable Execution Works
- 引擎把 workflow 每個外部動作（activity 呼叫、timer、signal）的結果記入 **event history**（append-only log）。
- Worker crash 後，新 worker 從頭 **replay** workflow 程式碼，遇到已有歷史的步驟直接回放結果、不重複執行副作用，直到追上為止再往下走。
- 因此 workflow 程式碼必須 **deterministic**（不可直接用隨機、現在時間、網路 I/O，須透過引擎 API）；副作用放在 activity（at-least-once，需冪等）。
- Timer／sleep 可以睡數天且不佔 worker 資源。
#### Managed Workflow Systems
AWS Step Functions（JSON/ASL 狀態機）、Google Workflows、Azure Logic Apps、Temporal Cloud。省維運，但受限於 DSL、執行次數計價、vendor lock-in。
#### Implementations
自建（DB + queue + poller）、開源 Temporal、雲端 Step Functions；Airflow 偏批次 DAG 而非事件驅動 saga。選型：需要複雜重試／長等待／版本管理 → Temporal；AWS 生態且流程簡單 → Step Functions。

## 常見深入題（by agents）
- **跑 saga 的 process crash 怎麼辦？** 狀態必須持久化：自建就每步前後寫 DB（狀態機）並有 recovery job 掃描卡住的 instance；durable execution 則靠 event history replay 自動續跑。
- **workflow 要更新怎麼辦？**
  - Versioning：新程式碼用 version marker／`getVersion`（Temporal patching）讓舊執行中的 instance 走舊分支，新 instance 走新分支；或 pin 版本，舊 instance 跑完才下舊 worker。
  - Migrations：長壽命 instance 可選擇性遷移（signal 注入、continue-as-new 到新版本），或寫轉換邏輯；避免改變已執行過步驟的順序（破壞 determinism）。
- **workflow state 太大？** 不把大 payload 放 history，只存參照（S3 key、DB id）；用 continue-as-new／child workflow 切分 history；history 有上限（Temporal 約 50K events / 50MB）。
- **外部事件（人工核准、webhook）？** 用 signal／callback token（Step Functions task token）讓 workflow 等待；搭配 timeout 與提醒；webhook 先落地再 signal，確保不丟。
- **某步驟如何剛好執行一次？** 實務上做不到真正 exactly-once，要 at-least-once + 冪等：每步帶 idempotency key（workflowId+stepId）傳給下游（如 Stripe Idempotency-Key）、下游去重表、conditional write。

## 面試怎麼用（by agents）
- 訊號：「訂單／付款／出貨流程」「多服務協調」「要等人或外部系統」「失敗要補償」「長時間（天）」「AI agent 多步驟」。
- 先講為什麼單機 + cron 不夠（crash、跨服務），再給 saga + orchestrator；可說「我會用 Temporal／Step Functions」並解釋 replay 與冪等。
- 不要用：單一 DB transaction 可解、步驟少且短、一次性簡單背景任務（用 [long-running-tasks](./long-running-tasks.md) 的 queue + worker 即可）。
- 主動提：補償動作、冪等、timeout、可觀測（每個 instance 目前卡在哪）。

## 相關題目
- [uber](../../hellointerview-breakdowns/uber.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)
- [notification-system](../../hellointerview-breakdowns/notification-system.md)
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)

## 自測問題（by agents）
1. Saga 的補償為何必須冪等？答：補償可能因失敗被重試，重複執行不能二次退款。
2. Choreography 與 Orchestration 差在哪？答：前者事件驅動、去中心但難追蹤；後者中央協調、可視性與錯誤處理較佳但有協調者依賴。
3. Durable execution 如何在 crash 後續跑？答：持久化 event history，replay deterministic 程式碼並回放已完成步驟結果。
4. 為什麼 workflow 程式碼要 deterministic？答：replay 時必須走出與原執行相同的決策路徑。
5. 如何實現「扣款只執行一次」？答：idempotency key + 下游去重；整體 at-least-once + 冪等。

## 參考來源
- https://microservices.io/patterns/data/saga.html （Chris Richardson, Saga）
- https://docs.temporal.io/workflows （Temporal workflows / determinism）
- https://docs.temporal.io/workflows#event-history
- https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html
- https://learn.microsoft.com/en-us/azure/architecture/patterns/saga
- https://stripe.com/docs/api/idempotent_requests
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
