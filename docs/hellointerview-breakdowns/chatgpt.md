# ChatGPT
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/chatgpt ｜ 難度：hard ｜ 類別：Real-time Updates、Managing Long Running Tasks ｜ 作者 Evan King

## 一句話核心
（原文）LLM 當黑盒；設計重心在 serving 系統：快速串流 token、調度有限 GPU、控制對話變長時的成本。首 token 延遲比總完成時間更重要。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 在 chat 發送 prompt 並收到 AI 回覆
- 檢視過往 chat 並續聊，先前上下文帶入 prompt
- Out of scope：編輯/分支訊息、圖像/音訊/影片、分享協作、Custom GPTs/tool calling/web browsing、全文搜尋聊天紀錄

**Non-functional（原文）**
- 首 token 延遲優先（空白畫面幾秒就像壞掉）
- GPU 昂貴且有限，要刻意控制「誰在何時拿到算力」
- 規模：200M+ DAU；每人每天數個 prompt -> 峰值約 20k prompts/s；回覆需數秒 -> 同時約 120k 個串流中

## Core Entities & API
（原文僅標題；補充，非原文）
- Entities：User、Chat、Message(chat_id, role, content, seq)、Run/Generation(status)
- API：
  - `POST /chats/{id}/messages {prompt}` -> 回 SSE 串流
  - `GET /chats`、`GET /chats/{id}/messages`
  - `POST /runs/{id}/cancel`

## High-Level Design
（原文僅標題；補充，非原文）
1. 發 prompt：Client -> Gateway -> Chat Service：存 user message -> 組 prompt（歷史 + 新訊息）-> 送進 inference 排程 -> GPU worker 生成 -> 串流 token 回 client，完成後存 assistant message。
2. 續聊：Message 存 DB（以 chat_id 分區，seq 排序）；載入最近 N 則（受 context window 限制）組 prompt。

## Deep Dives（依原文大綱逐條）
### 1) 如何將 token 串流回 client？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Client 輪詢，等完整回覆才一次顯示，延遲高、浪費請求。
- 好解：SSE（Server-Sent Events）單向串流，HTTP 友善、自動重連，適合 token 單向推送。
- 最佳解：SSE 為主（WebSocket 雙向能力用不到，且 LB/代理較難處理）；token 先寫入 Redis Stream/PubSub 的 per-run channel，由 gateway 轉發，解耦「生成 worker」與「連線節點」。
- 取捨：SSE 簡單、可穿 HTTP infra，但不雙向；WebSocket 彈性大但有狀態連線成本高。

### 2) 如何在重連與部署時保持串流不中斷？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：串流與連線節點綁死，連線斷了或部署重啟就整個生成作廢，浪費 GPU。
- 好解：生成與連線分離；token 持久寫入外部 buffer（Redis Stream），client 帶 `Last-Event-ID` 重連後從該位置接續。
- 最佳解：run 是 durable 的一等公民（有 run_id、status、offset）；worker 生成完整結果落地 DB；部署採 connection draining，client 自動重連至任何 gateway 並 resume。
- 取捨：額外的 buffer 與寫入成本，換取可恢復串流與不浪費已付費的 GPU 計算。

### 3) 如何在 GPU worker 間路由與調度生成請求？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Round-robin 隨機打 GPU，不管負載，出現長尾與 OOM。
- 好解：請求進 queue，worker 依容量拉取（pull model），避免過載。
- 最佳解：Continuous batching（vLLM 類）讓多請求共用 GPU 並在 token 級插入/退出；依 KV cache 親和性（prefix caching、同 chat 路由到同 worker）提升命中；依模型/大小分池；autoscaling 依 queue depth。
- 取捨：大 batch 提升吞吐但增加單請求延遲；與首 token 延遲目標需權衡。

### 4) 如何避免重度用戶霸佔 GPU，同時讓付費層更好？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：單一 FIFO，一個用戶或腳本灌爆 queue，其他人全被拖慢。
- 好解：per-user rate limit / quota（token bucket）+ 多個優先級 queue（free/plus/pro）。
- 最佳解：加權公平排隊（weighted fair queuing）+ 付費層預留容量、free 層在尖峰時降級（較小模型/排隊）；admission control 在入口就拒絕或延後，而非讓請求在 GPU 排隊逾時。
- 取捨：嚴格優先級可能餓死 free 用戶，需有保底配額/aging。

### 5) 對話變長時，如何控制推論成本而不讓助理顯得健忘？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每次把完整歷史全送進模型，成本隨長度二次增長（attention），最終超過 context window。
- 好解：滑動視窗，只保留最近 N 則。
- 最佳解：摘要壓縮（舊訊息由小模型摘要）+ 保留近期原文 + prefix/KV cache 重用已處理的前綴，只對新增 token 計算；必要時對重要事實做檢索（RAG）。
- 取捨：摘要有資訊損失；cache 佔 GPU 記憶體。

#### 取消 run 並回收 GPU（原文子題目）
（補充，非原文）Client 發 cancel -> 設 run 狀態為 cancelled（寫入 Redis 旗標）-> worker 每個 decode step 檢查旗標，立即中止、釋放 KV cache 與 batch slot；斷線也應視為隱式取消（含寬限期以支援 resume）。

## 關鍵數字與 back-of-envelope
- （原文）~20k prompts/s 峰值；~120k 並行串流；200M+ DAU。
- 120k 並行 SSE 連線，每個 gateway 節點約 10-50k 連線 -> 數台到十幾台即可，連線層不是瓶頸，GPU 才是。
- 若每串流平均 ~50 tokens/s，120k 串流 ≈ 6M tokens/s 的生成吞吐（補充估算）。

## 可遷移的 pattern（3-5 條）
1. 長任務：把「執行」與「連線」解耦，輸出寫入可重放的 buffer，支援 resume。
2. SSE 用於單向串流；連線節點無狀態化。
3. 稀缺資源（GPU）用 queue + 公平加權調度 + admission control。
4. 成本隨 context 成長 -> 摘要 + prefix/KV cache + 檢索。
5. 以取消/逾時機制及時回收昂貴資源。

## 常見追問（3-5 題，附簡短答案）
- 首 token 延遲怎麼降？prefix caching、小 prompt、避免排隊（admission control）、就近部署。
- GPU 掛了怎麼辦？偵測後重新排程，從 buffer 已生成的 token 之後 resume 或重新生成。
- 訊息順序與一致性？以 (chat_id, seq) 排序，單 chat 同時間只允許一個 active run。
- 如何防止 prompt injection / 濫用？輸入過濾與 moderation，屬 out of scope 但可提。
- 如何計費/限額？以 token 計量，非同步寫入 usage 表，配額由 Redis 計數。
