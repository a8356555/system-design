# Payment System（Stripe 類支付系統）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/payment-system ｜ Hard ｜ Multi-step Processes（作者 Evan King）

## 一句話核心
商家發起付款 -> 向外部 card network 非同步授權；核心是「不丟、不重、可稽核」：idempotency key、持久化的 payment 狀態機、append-only ledger、以及對非同步外部系統的對帳（reconciliation）。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 商家可發起付款請求（對客戶收取特定金額）。
- 使用者可用信用卡/簽帳卡付款。
- 商家可查看付款狀態更新（pending / success / failed）。

**Out of scope（原文）**：儲存支付方式、退款、交易歷史與報表、其他支付方式（轉帳、電子錢包）、訂閱、對商家撥款（payout）。

**Non-functional（原文，來自 deep dive 標題）**
- 高度安全。
- 持久性與可稽核性：任何情況下交易資料都不可遺失。
- 交易安全與財務完整性，儘管外部支付網路本質上是非同步的。
- 可擴展至 **10,000+ TPS**（高峰）。

## Core Entities & API
（補充，非原文 — 原文只有標題）
- Entities：`Merchant`、`PaymentIntent`（id, merchantId, amount, currency, status, idempotencyKey）、`Transaction/Charge`（attempt 紀錄）、`LedgerEntry`（借貸分錄）、`Token/PaymentMethod`。
- API：
  - `POST /payments`（Header: `Idempotency-Key`）`{amount, currency, ...}` -> `{paymentId, clientSecret}`
  - 客戶端（瀏覽器）用 publishable key 把卡號直接送到支付服務的 tokenization 端點（不經過商家伺服器）。
  - `POST /payments/{id}/confirm` `{paymentMethodToken}`
  - `GET /payments/{id}`、Webhook `payment.succeeded/failed`。

## High-Level Design
原文大綱：(1) 商家發起付款 (2) 使用者用卡付款 (3) 系統提供狀態更新。

（補充，非原文 — 原文為 Premium）
- **發起**：Merchant -> API Gateway -> Payment Service：建立 `PaymentIntent(status=created)`，回傳 id。
- **付款**：前端 SDK 把卡資料 iframe/直送 Stripe 的 Card Vault（tokenization），得到 token；Payment Service 以 token 呼叫 acquirer / card network（Visa/Mastercard）授權；結果非同步，更新狀態。
- **狀態更新**：商家可 `GET` 輪詢，或訂閱 webhook；狀態機 `created -> processing -> succeeded | failed`（可能 `requires_action`，如 3DS）。

## Deep Dives（依原文大綱逐條）
### 1) The system should be highly secure（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：商家伺服器接收並轉送卡號 -> 商家與我們都擴大 PCI 範圍。
- 好解：Client-side tokenization：卡號只進 Card Vault（獨立隔離、HSM 加密、網路隔離），其他服務只看 token -> 縮小 **PCI DSS** 範圍。
- 最佳解：TLS 全程、欄位級加密（envelope encryption + KMS）、API key 分 publishable/secret 且可輪替、request 簽章（HMAC）、webhook 簽章驗證、最小權限、稽核日誌、欺詐偵測（風險評分）、速率限制。

### 2) Durability and auditability, no data ever lost（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：只存最新狀態、直接 UPDATE 覆蓋 -> 無歷史、出錯無法追查。
- 好解：關聯式 DB（ACID）+ 同步複製到多 AZ；所有狀態變更 append 一筆事件。
- 最佳解：**Append-only ledger（事件溯源 / 複式記帳）**：狀態由事件重建，不更新/刪除只新增補償分錄；交易事件先寫入 durable log（Kafka，replication factor 3、acks=all）再處理；CDC 同步到資料倉儲與稽核系統；定期備份 + PITR；日終與 acquirer 的**對帳**檔案比對。

### 3) Transaction safety and financial integrity despite asynchronous external networks（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：呼叫外部 API 後直接回應；逾時就重送 -> 可能重複扣款。
- 好解：**Idempotency key**（商家提供，服務端存 key -> 結果，重試回傳同一結果）；對外部呼叫也帶我們的 idempotency / reference id。
- 最佳解：Payment 作為**持久化狀態機**（Multi-step Process：可用 Temporal 等 workflow engine 或 DB 狀態 + Kafka consumer）：先記錄意圖（`processing`）-> 呼叫外部 -> 記錄結果；未知結果（timeout）進入 `unknown` 狀態，由背景 job 向 acquirer 查詢或等 webhook 補齊，**絕不盲目重送**。Transactional outbox 保證「DB 狀態更新」與「事件發送」原子；對帳 job 修正不一致；補償交易（void / refund）取代回滾。

### 4) Scalable to handle 10,000+ TPS（原文標題）
（補充，非原文 — 原文為 Premium；原文另有 Servers / Kafka / Database 三個小標題）
- **Servers**：Payment API 無狀態，水平擴展 + LB；Idempotency 檢查放在共享儲存。
- **Kafka**：以 `paymentId`（或 merchantId）為 partition key 保證單筆支付事件有序；consumer group 平行處理；分區數 >= 目標併發度；DLQ 處理毒訊息。
- **Database**：10k TPS 單機 Postgres 吃緊 -> 依 merchantId / paymentId 分片（或 Vitess/Spanner/Cockroach）；寫主多副本同步；熱點商家（大客戶）用更細 key 分散；讀走副本/快取；歷史資料冷熱分層。
- 取捨：分片後跨 shard 交易困難 -> 設計成單筆 payment 在單一 shard 內完成，跨實體走 saga。

### Bonus: How can we expand the design to support Webhooks?（原文標題）
（補充，非原文）事件進 Kafka -> Webhook Dispatcher 讀取商家訂閱 -> HTTP POST（簽章 header）-> 失敗以 exponential backoff 重試（數小時到數天）-> DLQ；至少一次投遞，商家需以 event id 去重；每商家限流與隔離，避免慢商家拖垮他人；提供手動重送與查詢事件 API。

## 關鍵數字與 back-of-envelope
- 10,000 TPS 高峰（原文）。
- （補充）每筆 payment ~2KB 事件 × 多次狀態變更 ≈ 10KB/筆 -> 10k TPS ≈ 100MB/s 的 Kafka 寫入，可行。
- 每年數百億筆 -> ledger 需分區與歸檔；延遲預算：授權往返外部網路通常 1-3 秒。

## 可遷移的 pattern
1. **Idempotency key**（所有金流/訂單/寫入 API）。
2. **Append-only ledger + 事件溯源**，補償而非回滾。
3. **持久化狀態機 / workflow engine** 處理多步驟且含外部非同步呼叫的流程。
4. **Transactional outbox + at-least-once + 消費端去重**。
5. **Reconciliation（對帳）** 作為最終一致性的安全網；**Tokenization** 縮小敏感資料範圍。

## 常見追問
- **外部呼叫逾時，結果未知怎麼辦？** 標為 unknown，用 reference id 向 acquirer 查詢或等 webhook，不重送新請求。
- **同一商家重複送出同一請求？** 同 idempotency key 回傳首次結果；key 綁定 request hash，內容不同回 422。
- **如何保證帳平？** 複式記帳（借貸總和為 0）+ 每日與 acquirer settlement file 對帳。
- **Webhook 重複/亂序？** event id 去重、帶 version/created 時間，商家以 `GET` 取得最新狀態為準。
- **為何不用分散式交易 (2PC) 跨外部網路？** 外部系統不支援；改用 saga + 補償 + 對帳。
