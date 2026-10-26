# FB Live Comments
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/fb-live-comments ｜ 難度：medium ｜ 類別：Real-time Updates

## 一句話核心
讀寫極度不對稱（少數人留言、大量人觀看）的即時廣播題：寫入用普通 HTTP POST + DynamoDB，讀取用 SSE 推送；多 server 協調靠「hash 分片的 pub/sub + L7 consistent hashing 把同影片觀眾放同 server」（或 Dispatcher Service）；超大直播（mega-stream）則改變需求本身，用抽樣或「CDN 每秒 snapshot + client polling」。

## 需求
**Functional（Core）**
- Viewer 可對 Live 影片留言
- Viewer 觀看時能看到新留言
- Viewer 能看到加入之前的歷史留言

**Out of scope**：回覆留言、對留言 react

**Non-functional（Core）**
- 支援數百萬個同時進行的影片，每支直播每秒數千則留言
- Availability > consistency，eventual consistency 即可
- 低延遲：近即時廣播，端到端 < 200ms（一般網路條件）

**Out of scope**：資安（僅授權使用者可留言）、內容審核（spam/hate speech）

原文 Fun Fact：人類對 200ms 以內的互動感知為即時，是即時系統的目標延遲。

## Core Entities & API
**Entities**
- User（viewer 或 broadcaster）
- Live Video（由其他團隊擁有與管理，但需整合）
- Comment（user 在 live video 上發的訊息）

**API**
```
POST /comments/:liveVideoId
Header: JWT | SessionToken
{ "message": "Cool video!" }

GET /comments/:liveVideoId?cursor={last_comment_id}&pageSize=10&sort=desc
```
- userId 放在 header（session token / JWT），不放 body，避免被竄改冒名。
- 歷史留言需分頁。

## High-Level Design
元件：Commenter Client、Comment Management Service（建立與查詢留言）、Comments Database（DynamoDB：快、可擴展、高可用，留言簡單不需 transaction；Postgres/MySQL 也可）。

寫入流程：client 草擬留言 → `POST /comments/:liveVideoId` → Comment Management Service 驗證並寫 DB。

### 2) 看到新留言：先用 polling 起手
client 每幾秒用 `GET ...?since={last_comment_id}` 輪詢。不可擴展：頻率要跟著需求拉高，造成大量無效請求並壓垮 DB，要達近即時得每幾毫秒輪詢，不可行。原文提醒：若已知更好解可直接跳到，但要說明取捨；第一次見到題目從簡單開始也是好的基礎。

### 3) 歷史留言：分頁（infinite scrolling）
- **Bad：Offset pagination**（`offset=0&pagesize=10`）。DB 要數過前面所有 row，留言量大時變慢；更糟的是不穩定：滾動時有新增/刪除，offset 會錯位造成重複或漏掉。
- **Great：Cursor pagination**（`cursor={last_comment_id}&pageSize=10`）。cursor 指向特定項目，有 index 時不用掃前面 row；穩定。DynamoDB 查詢：`KeyConditionExpression: liveVideoId = :id AND commentId < :cursor`，`ScanIndexForward: false`，`Limit: pageSize`。缺點：每頁仍需一次 DB 查詢，高流量下仍可觀。

## Deep Dives

### 1) 如何做到即時廣播？（Push vs Polling）
- **Good：WebSockets**（雙向）。消除 polling，server 可立即推送。問題：本題讀寫比失衡，留言創建很少，大多數 viewer 只讀不寫，為每個 viewer 維持雙向連線開銷高；WebSocket 更適合讀寫平衡的聊天室。
- **Great：Server-Sent Events (SSE)**。基於標準 HTTP 的持久連線，server 單向推送；寫入用一般 HTTP POST。契合讀多寫少。
  - 挑戰：部分 proxy/load balancer 不支援 streaming response，造成 buffering 難追查；瀏覽器對同網域 SSE 連線數有上限（同時看多支直播會有問題）；長連線使監控除錯更複雜。
  - 流程：POST 留言並持久化 → Comment Management Service 透過 SSE 推給訂閱該影片的所有已連線 client。這個設計單機做法還不可擴展，進入下一題。

### 2) 如何支援數百萬同時觀眾？
單機可處理約 100k 量級連線，實際瓶頸是 CPU、memory、file descriptor。注意：65,535 是 port 範圍不是連線上限，TCP 連線由 (src IP, src port, dst IP, dst port) 唯一識別，調校後單 port 可處理數十萬甚至百萬連線。需水平擴展，分兩部分。

**Part 1：Server 協調問題**
UserA 連 Server 1、UserB 連 Server 2，同看 Video 1；留言打到 Server 1 時，Server 1 無法直接推給 UserB。

- **Good：Naive Pub/Sub（每台 server 處理每則留言）**。先把讀寫流量拆開，建立 **Realtime Messaging Servers** 專職推送（寫少讀多，需獨立擴展）。round robin 分配連線；server 在記憶體維護 `liveVideoId -> [sseConnections]`。Comment Management Service 發布到 channel，所有 Realtime server 訂閱後推給自己的相關 viewer。缺點：每台 server 都處理所有影片的所有留言，即使沒有相關 viewer，浪費運算，Facebook 規模不可行。
- **Great：Partitioned Pub/Sub + Viewer Co-location**。channel 分片：每個影片一個 channel 會耗資源（Kafka 可能不可行），改用 `hash(liveVideoId) % N` 限制 channel 數。server 只訂閱它需要的 channel。但 round robin 會讓一台 server 訂到很多 channel，所以用 **L7 load balancer（NGINX/Envoy）依 liveVideoId 做 consistent hashing**，讓同影片觀眾落在同一台 server；或用 Zookeeper 存動態 mapping（更彈性，運維更複雜）。挑戰：load balancing 與 pub/sub 訂閱要協調；觀眾組成變化時需更新訂閱；server 擴縮時 routing 需同步。
- **Great：Dispatcher Service 取代 Pub/Sub**。反轉模型：Comment Management Service 問 Dispatcher「哪些 server 有人在看這支影片」，Dispatcher 維護動態 map（heartbeat + registration），直接轉發給這些 server。優點：不需管 pub/sub 訂閱、路由邏輯集中、可加 load-based routing。多個 Dispatcher 實例放在 LB 後，共用 Zookeeper/etcd。挑戰：影片突然爆紅時 mapping 要即時更新，多實例需協調 cache invalidation。
- **技術選型**：Kafka 高擴展與容錯，但不擅長動態訂閱（使用者切換影片）；Redis pub/sub 低延遲且動態訂閱友善。Redis pub/sub 是 fire-and-forget 也沒關係，因為留言已持久化，斷線漏掉的靠 catch-up 機制補。
- 原文結論：兩者都可，pub/sub 通常邊角案例較少，面試會選它。

**Part 2：Mega-Streams（如世足決賽，數億觀眾）**
5,000 comments/s、平均 4 個字，等於 30 秒內讀完《戰爭與和平》；螢幕顯示最後 20 則時，每則只停留約 4ms。沒人讀得了，用戶感受的是群體「氛圍」，所以低延遲與逐則可靠送達的目標變得不重要——需求本身改變了。

- **Good：抽樣 subset**。依留言速度動態調整抽樣率：100/s 可取 50%，5,000/s 取 1-2%，讓每個 viewer 每秒收到大致固定數量。可優先 viewer 追蹤的人、有 reaction 的、認證帳號的留言。缺點：仍維持百萬 SSE 連線，成本仍高。
- **Great：CDN-based delivery + 週期性 snapshot**。改成 pull：server 為每個 mega-stream 維護最近 100-200 則的 ring buffer，每秒（或更頻繁）snapshot 寫入 Redis 或 CDN origin，由 CDN 全球邊緣快取；client 每秒 polling CDN，拿到新 snapshot 後不要一次全部倒出（會卡頓），用動畫依 timestamp 分散顯示。CDN 本來就為同內容服務百萬人而生。
  - 可動態設閾值：超過 100,000 同時觀眾或 500 comments/s 自動從 SSE 切到 CDN。
  - 取捨：延遲 1-2 秒而非 < 200ms（對 mega-stream 無妨）；「read your own write」由 client optimistic insert 自己的留言解決；切回 SSE 時需 hysteresis 避免在門檻附近來回抖動（flapping）。
- 原文：講抽樣展現強理解，講 CDN 方案展現 staff-level 思維（認知到極端規模下需求會改變）。

### 3) 斷線重連如何不漏留言？
- **Bad：忽略斷線**。重連後只收新留言，行動網路不穩時體驗差。
- **Great：Last-Event-ID + client 端追蹤**。SSE 內建 `Last-Event-ID`：每則推送帶 event ID（用 comment ID），瀏覽器自動重連並帶最後收到的 ID，server 先補送遺漏再繼續串流。需要更多控制時，client 把最後 comment ID 存 localStorage/app storage，用 `GET /comments/:liveVideoId?since={last_comment_id}&limit=100` 主動補抓；UX 可用 2-3 倍速動畫播放，或顯示「你錯過了 47 則留言」+ 跳到 live。行動端在 app 進背景前主動斷開 SSE 並記錄位置，回前景再補（OS 本來就會限制背景連線，且省電）。
  - 補送要有上限：例如只補最近 5 分鐘，更久則優雅降級。
  - 挑戰：重連可能打到不同 Realtime server，需共享 Redis cache 讓任何 server 都能補送最近留言；SSE 與 HTTP catch-up 要依 comment ID 去重與合併，避免重複或缺口。

### Final Design
Commenter Client → Comment Management Service → DynamoDB；同時發布到分片 pub/sub（Redis）→ Realtime Messaging Servers（L7 LB consistent hashing 放置觀眾）→ SSE → Viewer；mega-stream 走 snapshot → CDN；Redis 保留近期留言供 catch-up。

## 關鍵數字與 back-of-envelope
- 延遲目標 < 200ms
- 單 server 約 100k 同時連線量級（受 CPU/memory/FD 限制）
- Channel 數 = `hash(liveVideoId) % N`
- Mega-stream 範例：5,000 comments/s × 4 字；顯示 20 則 → 每則約 4ms
- 抽樣率範例：100/s → 50%；5,000/s → 1-2%
- Ring buffer：最近 100-200 則；snapshot 每秒
- 切換門檻範例：100,000 同時觀眾 或 500 comments/s；CDN 延遲 1-2 秒
- 補送上限範例：5 分鐘

## 面試官期待
- **Mid-level**（80/20）：主動發現 polling 的限制並想到 push 模型；稍微提示後想出 pub/sub，並在協助下擴展。
- **Senior**（60/40）：快速帶過 HLD，把時間花在 scaling；以最少提示推導出 pub/sub，主動帶領 scaling 討論並權衡方案。
- **Staff+**（40/60）：不只提出 pub/sub，還主動指出可靠性/可擴展性限制並提出解法；對實際技術有深入理解，能詳談取捨。

## 可遷移的 pattern
1. **讀寫比失衡 → 選 SSE 而非 WebSocket**：單向推送 + 普通 HTTP 寫入，適用通知、live dashboard、新聞 feed 推送。
2. **拆分 read/write 服務獨立擴展**：Realtime Messaging Servers 與 Comment Management Service 分開。
3. **分片 pub/sub + consistent hashing 同位置放置**：用 `hash(key) % N` 限制 channel 數，LB 讓相關連線落在同 server，減少每台處理的無關訊息。
4. **極端規模下重新質疑需求**：mega-stream 改為抽樣或 CDN snapshot，用延遲換規模；加上 hysteresis 避免模式抖動。
5. **持久化 + 可重放的 catch-up**：pub/sub 可 fire-and-forget，因為 DB 與 Redis 能依 ID 補送；有界重放 + client 去重。

## 常見追問
- **為什麼不用 WebSocket？** 讀寫失衡，雙向連線開銷不值得；但聊天室這類平衡場景 WebSocket 較佳。
- **Kafka 還是 Redis pub/sub？** Kafka 擴展與容錯好但不擅長動態訂閱；Redis pub/sub 低延遲、動態訂閱友善，漏訊息可由 DB 補。
- **Pub/Sub 與 Dispatcher 差別？** pub/sub 較簡單邊角案例少；Dispatcher 路由集中、可做 load-based routing，但 mapping 在爆紅時需快速刷新。
- **斷線一小時怎麼辦？** 有界補送（例如 5 分鐘），更久優雅降級。
- **Mega-stream 如何讓自己的留言立即可見？** client optimistic insert，不依賴 CDN polling。
