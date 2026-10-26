# Google Docs（協作文件編輯器）
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/google-docs ｜ Hard ｜ Real-time Updates（作者 Stefan Mai）

## 一句話核心
多人同時編輯同一份文件，核心是「並發編輯的合併（OT / CRDT）」+「WebSocket 長連線的水平擴展（同一文件的人要路由到同一台）」。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 使用者可建立新文件。
- 多人可同時編輯同一份文件。
- 使用者可即時看到彼此的修改。
- 使用者可看到其他人的游標位置與在線狀態（presence）。

**Out of scope（原文）**：複雜文件結構（假設是純文字編輯器）、權限與協作層級、文件歷史與版本。

**Non-functional**：原文內文被鎖，僅有標題「What are the non-functional requirements」。
（補充，非原文）合理推定：最終一致（所有 client 收斂到相同文件）、低延遲（< 100ms 可見他人編輯）、高可用、可擴展到數百萬 WebSocket 連線、儲存成本可控、不丟資料。

**規模數字**：原文未公開；大綱提到「millions of websocket connections」。

## Core Entities & API
（補充，非原文 — 原文為 Premium）
- Entities：`Document`（id, title, snapshot）、`Editor/User`、`Edit/Operation`（docId, userId, op, revision）、`Cursor/Presence`。
- API：
  - `POST /docs` -> `{docId}`
  - WebSocket `/docs/{id}`：client 送 `{type: "insert", pos, text, baseRevision}`；server 廣播已轉換的 op；另有 `cursor` 訊息。
  - `GET /docs/{id}`：載入 snapshot + 之後的 ops。

## High-Level Design
原文大綱（標題）：
1. 建立新文件（原文）
2. 多人並發編輯 —「Collaborative Edits Breakdown」（原文）
3. 即時看到變更 —「When the Document is Loaded」「When Updates Happen」（原文）
4. 游標與 presence（原文）

以下為（補充，非原文 — 原文為 Premium）：
- **建立文件**：POST 至 Document Service，寫入 DB（docId 用 UUID/snowflake），回傳 id。
- **並發編輯**：
  - 爛解：整份文件 last-write-wins -> 互相覆蓋。
  - 較好：Lock（悲觀鎖）-> 體驗差，不是即時協作。
  - 好解：**Operational Transformation (OT)**：由中央 server 排序所有 ops，client op 帶 baseRevision，server 對併發 op 做 transform 後 apply、廣播。需要單一 authority per document，實作複雜但 Google Docs 實際採用。
  - 另解：**CRDT**（如 Yjs/Automerge）：每個字元有全域唯一 id，op 可交換、可去中心化合併，不需 server 排序；代價是 metadata 膨脹（tombstone）。面試中 OT + 中央 server 較簡單好講，CRDT 適合 offline-first / P2P。
- **載入文件時**：client 抓最近 snapshot + revision，再開 WebSocket 從該 revision 之後訂閱 ops，避免漏掉載入期間的編輯。
- **更新發生時**：client 本地樂觀套用 -> 送 server -> server transform/apply/持久化 -> ack 給作者、廣播給其他人。
- **游標/presence**：走同一條 WebSocket 但屬於 ephemeral 訊息，不持久化，只廣播（可限頻 + 放在記憶體/Redis），斷線以 heartbeat timeout 判定離線。

## Deep Dives（依原文大綱逐條）
### 1) How do we scale to millions of websocket connections?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：任意 WebSocket server 接任意連線，用 DB polling 同步 -> 延遲高、DB 被打爆。
- 好解：所有 server 透過 Pub/Sub（Redis/Kafka）以 docId 為 channel 廣播；每個 server 只訂閱自己手上有連線的 doc。缺點：同一文件的 op 排序仍需要單一寫入者，否則 transform 順序不一致。
- 最佳解：**以 docId consistent hashing 路由**，同一文件的所有連線落在同一台 Document Server（sticky routing 由 LB / 服務發現做，如 ZooKeeper/etcd 管理 shard 指派）。該台在記憶體內持有文件狀態與 op 序列，免去分散式排序問題；一台掛掉由 hash ring 重新指派、client 重連並從 revision 補 ops。取捨：熱門文件（上千人同編）單台是上限，需限制同時編輯人數或把「只讀觀眾」降級走 fan-out 層。
- 單機連線數：調 ulimit/epoll，單台約 10 萬級連線（取決於記憶體），百萬連線 ≈ 10-20 台。

### 2) How do we keep storage under control?（原文標題）
（補充，非原文 — 原文為 Premium）
- 爛解：每個按鍵存一筆 op、永遠保留 -> 儲存與重放成本線性成長。
- 好解：**定期 snapshot + 只保留 snapshot 之後的 op log**；載入時 snapshot + replay。
- 最佳解：背景 **compaction**：op log 超過 N 筆或 T 分鐘就合併成新 snapshot，舊 op 移到冷儲存（S3）或丟棄（因 out of scope 無版本歷史）；client 端 op 批次/合併（連續輸入合成一個 insert）；CRDT 則需做 tombstone GC。
- 取捨：snapshot 頻率 vs 載入重放時間 vs 寫入放大。

### Some additional deep dives you might consider（原文有此標題，內容鎖住）
（補充，非原文）offline 編輯與重連合併、undo/redo（需 inverse op）、權限、版本歷史、富文字格式 op。

## 關鍵數字與 back-of-envelope
（補充，非原文）
- 假設 1 億 DAU、同時在線 1000 萬連線 -> 單台 5-10 萬連線約 100-200 台 WS server。
- 每人每秒約 1-3 個按鍵，批次 100-200ms -> 每文件寫入 ~5-10 ops/s，小。真正瓶頸是連線數與 fan-out，不是儲存吞吐。
- 純文字文件 ~100KB，snapshot 小；op 約 50-100 bytes。

## 可遷移的 pattern
1. **單一 authority per entity + consistent hashing 路由**：把分散式排序問題變成單機問題（同樣用於 chat room、遊戲房間、拍賣）。
2. **OT/CRDT 處理並發編輯**：中央排序 vs 可交換 op，二選一並講清取捨。
3. **Snapshot + op log + compaction**：控制 event-sourcing 型儲存成長。
4. **Ephemeral vs durable 訊息分流**：presence/cursor 不落地，只廣播。
5. **載入時 snapshot+revision、再訂閱增量**：避免載入與訂閱之間漏事件（通用的 catch-up pattern）。

## 常見追問
- **OT 和 CRDT 怎麼選？** 有中央 server 且需求單純 -> OT 較省 metadata；要 offline-first 或去中心化 -> CRDT。
- **client 斷線重連怎麼辦？** 帶上最後確認的 revision，server 回補缺的 ops；若落後太多就重新載 snapshot。
- **WebSocket server 掛了？** hash ring 重新指派，op log 已持久化，client 自動重連；未 ack 的本地 op 重送（需 op id 去重，確保 idempotent）。
- **熱門文件幾千人同時編輯？** 限制編輯者數量，其餘人只讀，走 Pub/Sub fan-out 或 CDN 快照。
- **怎麼保證 op 不遺失？** server 先 append 到 durable log（Kafka/DB）再 ack；ack 前 client 保留 pending op。
