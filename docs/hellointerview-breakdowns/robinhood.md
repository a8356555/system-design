# Robinhood
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/robinhood ｜ 難度：hard ｜ 類別：Real-time Updates ｜ 作者 Joseph Antonakakis

## 一句話核心
（原文）Robinhood 是 broker 而非 exchange：向外部 exchange 下單/取消，並訂閱成交 feed；設計重心是把即時股價 fan-out 給大量用戶、追蹤訂單狀態更新，以及訂單一致性。

## 需求（Functional / Non-functional / 規模數字）
**背景（原文）**
- Symbol（ticker）、Order、Market Order（以當前市價立即成交，只有股數）、Limit Order（指定價格，可掛單等待成交或被取消）
- 假設的外部 exchange：同步 request/response 下單與取消；可訂閱 symbol 的 trade feed，每筆成交 push（symbol、單股價格、股數、orderId）
- 面試時應簡短釐清 exchange 介面，因為這些假設影響整體設計

**Functional（原文）**
- 用戶可看到股票即時價格
- 用戶可管理訂單（市價/限價；建立/取消）
- Out of scope：盤後交易、ETF/選擇權/加密貨幣、即時 order book

**Non-functional（原文）**：原文該節內容未公開（Premium）；以下為補充，非原文：價格推送低延遲、下單不可重複/遺失（強一致）、高可用。

## Core Entities & API
（原文僅標題；補充，非原文）
- Entities：User、Symbol、Order(id, user, symbol, side, type, qty, limit_price, status, exchange_order_id)、Trade/Fill
- API：
  - `POST /orders {symbol, side, type, qty, limit_price?, idempotency_key}`
  - `DELETE /orders/{id}`、`GET /orders`
  - SSE/WebSocket：`subscribe symbols` -> 推送價格

## High-Level Design
（原文僅標題；補充，非原文）
1. 即時價格：Exchange trade feed -> Price Ingest（單一/少數連線訂閱）-> 價格分發層 -> 推送給訂閱的 client。
2. 訂單：Client -> Order Service -> 寫入 Orders DB（status=pending）-> 呼叫 exchange 同步下單 -> 更新 exchange_order_id/status；成交資訊由 trade feed 回來，Order Service 以 orderId 關聯並更新狀態，再通知用戶。

## Deep Dives（依原文大綱逐條）
### 1) 系統如何擴展即時價格更新？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每個 client 輪詢 REST API 取價，N 用戶 × 頻率打爆後端。
- 好解：WebSocket/SSE 推送，Price Ingest 寫入 Redis，推送服務讀取後轉發。
- 最佳解：Exchange feed 只由少數 ingest 節點訂閱一次；用 Pub/Sub（Redis/Kafka）按 symbol 分 channel；Push 節點只訂閱「其連線用戶關心的 symbols」（連線與 symbol 的 inverted index）；對熱門 symbol 做 conflation（合併為每 100-250ms 最新價，只推最新值）。
- 取捨：conflation 降低頻寬與延遲壓力，犧牲每筆 tick 的完整性（散戶 app 可接受）。

### 2) 系統如何追蹤訂單更新？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Client 輪詢 `GET /orders/{id}`，或每個 Order Service 實例自己訂閱 feed，造成重複處理。
- 好解：訂單成交資訊從 trade feed 進入 Kafka，Order Updater 消費並依 orderId 更新 DB，再經推送通道通知。
- 最佳解：以 exchange_order_id 為 partition key 的 Kafka 保證單訂單事件有序；Updater 冪等（以 trade/fill id 去重）；更新後發 order-update 事件到 per-user channel，推送給該用戶連線；斷線重連時以 DB 為真相補齊。
- 取捨：多一層 stream 增加延遲但可靠、可重放；部分成交需聚合 fill。

### 3) 系統如何管理訂單一致性？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：先呼叫 exchange 再寫 DB，若中間崩潰則 DB 不知道這筆已下單，造成幽靈訂單或重複下單。
- 好解：先把訂單寫入 DB（pending）再呼叫 exchange；失敗/超時時依狀態處理。
- 最佳解：Idempotency key + 狀態機（pending -> submitted -> partially_filled/filled/cancelled/rejected）；用 client_order_id 當 exchange 端冪等鍵；超時時以「查詢 exchange 狀態」對帳而非盲目重試；transactional outbox 確保下單意圖不遺失；定期 reconciliation 對 exchange 的日終報表。
- 取捨：嚴格順序與單訂單序列化犧牲少許吞吐，換取金融正確性；此處是強一致場景（不同於價格推送的最終一致）。

### 其他（原文有 "Some additional deep dives" 章節，內容未公開）
補充：訂單取消與成交的競爭（cancel vs fill race）、風控（餘額/買力檢查）、市場開盤尖峰。

## 關鍵數字與 back-of-envelope
- 原文未公開具體數字。補充估算：假設 10M 用戶、峰值 1M 同時在線、每人訂閱 ~10 個 symbol。
- 市場全部股票約 8k symbols，但熱門 symbol 的 tick 頻率可達數百/秒 -> 必須 conflation。
- 1M 連線 ÷ 每台 ~50K = 約 20 台 push 節點。
- 下單量遠小於價格推送量（寫少讀多推多），但正確性要求最高。

## 可遷移的 pattern（3-5 條）
1. 上游單點訂閱 + Pub/Sub 按 key 分發，解耦「資料源」與「大量訂閱者」。
2. Conflation/節流：推送最新值而非每個 tick。
3. 外部副作用（下單）用 idempotency key + 狀態機 + 對帳。
4. 事件流（Kafka）按 entity key 分區，保證單實體有序並冪等消費。
5. 不同資料不同一致性：價格最終一致、訂單強一致。

## 常見追問（3-5 題，附簡短答案）
- 下單 exchange 超時怎麼辦？以 client_order_id 查詢實際狀態，不要盲重送。
- 取消與成交同時發生？以 exchange 回報為最終真相，狀態機容許 cancel_rejected。
- 如何防止超賣/餘額不足？下單前在 DB 原子凍結買力。
- Client 斷線期間錯過更新？重連後 REST 拉最新訂單與快照，再接上推送。
- 如何擴展到多 exchange？Order Router 抽象各 exchange adapter。
