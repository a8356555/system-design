# WhatsApp（Messaging App）
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/whatsapp ｜ 難度 medium ｜ 類別 Real-time Updates（作者 Stefan Mai）

## Threads 貼文觀點
來源：https://www.threads.com/@chunhao2026/post/DeCNymBDWN-

- 工程師的直覺是「每個 user 一個 durable queue」（例如 per-user Kafka topic）來保證訊息不丟。
- 但每個 Kafka topic 約 50KB+ metadata，× 10 億 user = 50TB+，不可行。
- WhatsApp 的解法是**把「送達保證」拆成兩條路**：
  1. **Redis Pub/Sub**（at-most-once）：只負責即時推送，輕量、不存訊息。
  2. **Inbox table**：先 durable write，保證訊息一定到得了（離線 / 漏推都靠它補）。
- 一句話：「即時」與「可靠」不要讓同一個元件同時扛，各給最適合的工具。

## 一句話核心
把訊息「先寫進 durable 的 Message + Inbox」，再用輕量的 Redis Pub/Sub（at-most-once）做即時推送；漏掉的靠 client ACK、heartbeat + sequence number、reconnect sync 補回。

## 需求
**Functional（Core）**
- 建立群聊（上限 100 人）。1:1 視為 2 人的特例。
- 收發訊息。
- 離線期間的訊息，上線後可收到（最長 30 天）。
- 收發 media。

Out of scope：音視訊通話、與商家互動、註冊與 profile 管理。

**Non-functional**
- 在線使用者收訊息延遲 < 500ms。
- 保證 deliverability（訊息一定能到使用者）。
- 能撐數十億使用者、高吞吐。
- 訊息在中央伺服器只保留必要時間（隱私，故用 TTL）。
- 單一元件故障要有韌性。

Out of scope：完整資安、spam / scraping 防護。

**規模數字（原文）**
- 10 億 user，約 2 億同時在線。
- 平均每人每天 ~20 則訊息；2 億 active × 20 = 40 億則/天 ≈ 40K msg/s。
- 1:1 每則寫 Message 一次 + 收件人 Inbox 一次；含群聊約 100K writes/s，DynamoDB 以 userId 為 partition key 可承受。
- WhatsApp 單機曾服務 1–2M 連線，所以約需數百台 Chat Server。

## Core Entities & API
**Entities**：User、Chat（2–100 人）、Message、Client（一個 user 可有多裝置）。

**API：用 WebSocket（over TLS）雙向通道**，指令（command）即 API：
- `createChat {participants, name} -> {chatId}`
- `sendMessage {chatId, message, attachments} -> {status, messageId}`
- `createAttachment`（後來改成 pre-signed URL 流程，見下）
- `modifyChatParticipants {chatId, userId, ADD|REMOVE}`
- Server 推給 client：`chatUpdate`、`newMessage`，**client 必須回 ACK**（才能確定真的到了 client，也才能刪 Inbox）。

為何不用 REST：高頻雙向更新，適合 WebSocket。

## High-Level Design
```
Client ==WebSocket== L4 LB ==> Chat Server(s) ---> DynamoDB (Chat / ChatParticipant / Message / Inbox / Clients / LastSeen)
                                   |  ^
                          publish  v  | subscribe(userId)
                                Redis Pub/Sub (sharded by userId)
Client --pre-signed URL--> Blob Storage (attachments, TTL 30d)
```

**1) 建群**：服務在 L4 LB 後，寫 DynamoDB。
- Chat table：PK = chatId。
- ChatParticipant：PK = chatId、SK = participantId；GSI：PK = participantId、SK = chatId（查某 user 的所有 chat）。
- 小群可用單一 DynamoDB transaction（最多 100 items），接近 100 人時可能要分批寫。
- 為何 L4 而非 L7：不需要 path / header routing，L4 效能較好。

**2) 收發訊息（先假設單台 Chat Server）**：in-memory hash map 存 userId -> websocket connection；sendMessage 查 participants，逐一從 map 找連線推送。假設全部在線且同一台，先求跑得通。

**3) 離線訊息**：每個 user 一個 Inbox。
1. 寫 Message table + 每個收件人一筆 Inbox。
2. 回傳 SUCCESS + messageId 給 sender。
3. 在線者嘗試即時推送 `newMessage`。
4. client ACK 後 server 刪除 Inbox 該筆。
- 離線者：上線時查 Inbox -> 取 Message -> 推送 -> ACK -> 刪。
- Message / Inbox 用 TTL 清除舊資料。

**4) Media**：見 Deep Dive 的附件三段式比較（附件走獨立 HTTP / blob storage，不經 WebSocket / DB）。

## Deep Dives

### 附件（High-Level 第 4 條的取捨）
- 爛解：Chat Server 收 media 存進 DB。DB 不擅長大 binary blob，且吃掉 Chat Server 頻寬。
- 好解：Chat Server 收 media 再轉存 blob storage（TTL 30 天），收件者用 pre-signed URL 下載。缺點：Chat Server 白白轉手一次；沒處理「全員收到後提前過期」；加密與安全需額外處理。
- 最佳解：client 向 Chat Server 要 pre-signed URL（如 `getAttachmentTarget`），**直接上傳 blob storage**，再把 URL 當 opaque 欄位送進訊息。取捨：同樣尚未處理「全員下載後過期」與加密。
- CDN：因群聊上限 100 人，cache 效益有限（原文結論）。

### DD1：怎麼撐數十億同時用戶（跨 Chat Server 路由）
問題：sender 與 recipient 可能連在不同 Chat Server。
- 爛解 1：LB 後單純水平擴充。server 沒有目標連線，送不到。
- 爛解 2：**每個 user 一個 Kafka topic**。Kafka 不是為數十億 topic 設計，每 topic 約 50KB overhead，10 億 user = 50TB+。想用「super topic」按 server 分組，最後等於重造下面的好解，卻沒好處。（對應 Threads 貼文的核心論點）
- 好解：**Consistent hashing**，user 固定對應某台 Chat Server，用 ZooKeeper / etcd 維護註冊表。取捨：Chat Server 之間要互連（機器要大、數量要少）；擴縮容要小心斷線重連避免 thundering herd，擴容期間事件要雙寫兩台，否則掉訊息。
- 最佳解：**Redis Pub/Sub**。
  - 連線時，Chat Server subscribe 該 userId 的 channel；要送訊息時 publish 到收件人的 channel，所有訂閱的 Chat Server 收到後轉給 websocket。
  - Pub/Sub 是 at-most-once：沒人訂閱或 Redis 短暫故障就丟。**所以寫入順序是：(1) 寫 Message + Inbox（durable）(2) 回 sender 成功 (3) 才 publish（best-effort）**。第 3 步失敗也不會丟，因為 Inbox 還在。
  - 與 Kafka 差異：Pub/Sub 只是記憶體中指向 subscriber 連線的指標，無持久化、無 offset。
  - 實際要 shard 成 Redis cluster（以 userId 分 channel）。Canva 的 benchmark：單台 Redis 撐 100,000 mouse position updates/s，利用率 27%。
  - 取捨：多一跳（個位數 ms）延遲；每台 Chat Server 要連每台 Redis。

**Partition by chat 還是 by user？**
- 情境 1：每人 250 個 1:1 chat -> by user 每連線訂 1 個 channel；by chat 要訂 250 個。選 by user。
- 情境 2：每人 1 個 100 人群 -> by chat 只 publish 1 次；by user 要 publish 99 次。選 by chat。
- WhatsApp 以 1:1 為主且群上限 100，所以 by user。
- Senior 加分：這是「celebrity problem」，可**依群大小自適應**：超過門檻（例如 25 人）的大群，user 連線時額外訂閱 chat-level channel，送訊息時改 publish 到 chat channel。群規模變動時有一小段時間要雙發（publish 到兩種 channel）。

### DD2：多裝置（multiple clients）
- 不能再靠 user-level Inbox。
- 新增 Clients table（by userId）；查 participants 時展開成所有 clients；**Inbox 改成 per-client**；送訊息時發給所有 clients。
- Pub/Sub 不用改（仍訂閱 userId）。
- 限制每帳號裝置數（例如 3 個）避免儲存與吞吐暴增；需要機制停用失效 client。

### DD3：WebSocket 假連線（silently dead）
- 爛解：靠 TCP timeout，可能要數分鐘。
- 好解：**ACK timeout + server retry**（500–2000ms 逾時，重試數次後關閉連線，強制 client 重連並從 Inbox 同步）。缺點：只有在送訊息時才偵測得到，安靜期間沒發現。
- 最佳解：**Application-level heartbeat**，每 10–30 秒 ping、5 秒內要 pong，否則關閉；偵測上限 = interval + timeout（例 10s + 5s = 15s）。代價：2 億連線 × 10 秒間隔 = 2000 萬 ping/pong 每秒（訊息很小，可接受）。

### DD4：Redis 沒送到怎麼辦（連線者漏訊息）
Inbox 已保證「最終」會送到，這裡是求「快速」補上。
- 好解：**定期 polling** sync（30–60 秒）。2 億連線每 30 秒一次 ≈ 700 萬 QPS，間隔是延遲與負載的旋鈕。
- 好解：**每 chat 一個遞增 sequence number + gap detection**（Redis INCR 產生）。缺點：聊天安靜時偵測不到缺口，仍需 polling 兜底。
- 最佳解：**每個 user 一個全域 sequence，附在 heartbeat 裡**。client 發現本地 seq 落後就立刻 sync。一個 seq 涵蓋所有 chat，一個 heartbeat 內就能偵測。代價：要原子計數器（Redis INCR）多一個依賴。
- 實務：heartbeat 偵測死連線 + sequence 偵測漏訊息 + polling 當最後兜底，三者並用。

### DD5：訊息亂序
- 答案：**不直接解**。嚴格排序要延遲 + 重排機制（類比 Flink 的 bounded out-of-orderness watermark），使用者寧可快一點看到。
- 做法：Chat Server 用 NTP 同步時鐘，收到訊息時蓋 server timestamp，所有 client 按此排序顯示，故各 client 排序一致。偶爾有訊息「插到上面」，使用者可接受。

### DD6：Last seen
- 爛解：每次 heartbeat 都寫 DB。2 億連線 × 10–30 秒 = 每秒數百萬寫入，資料還立刻過期。
- 最佳解：**利用連線狀態**。只在 disconnect 時寫 LastSeen table（每 user 一筆），用 DynamoDB conditional expression（新時間 > 舊時間才更新）避免多 server 競態。
- 查詢流程：client 發 `getLastSeen`；Chat Server 並行 (a) 查 LastSeen table 回 `updateLastSeen` (b) 轉發給 target 的 Pub/Sub channel；target 若在線，由其 Chat Server 回 `ONLINE`。client 合併，收到 ONLINE 就顯示綠點，否則顯示最後斷線時間。
- 取捨：兩個回應可能有時間差，client 要能無縫更新；依賴 Chat Server 回報 disconnect，server 掛掉會漏（可在連線時也寫一次補強）。

## 關鍵數字與 back-of-envelope
- 10 億 user；2 億同時在線；每人每天 20 則 -> 40 億則/天 ≈ 40K msg/s；含 Inbox 與群聊 ≈ 100K writes/s。
- 單機 1–2M 連線 -> 2 億連線需數百台。
- Per-user Kafka topic：50KB × 10 億 = 50TB+。
- Heartbeat：2 億 / 10s = 2000 萬 ping-pong/s；polling：2 億 / 30s ≈ 700 萬 QPS。
- Heartbeat 偵測上限 = 10s + 5s = 15s。
- 單台 Redis Pub/Sub 100K updates/s @ 27% 利用率（Canva）。

## 面試官期待
- **Mid（E4）**：80% 廣度。定義清楚 API、做出功能完整的 HLD；擴充方案有粗糙處但知道缺點。會被追問 WebSocket 是什麼。
- **Senior（E5）**：快速帶過 HLD，把時間花在 scaling 與健壯性；懂 consistent hashing、長連線機制；能比較 by chat vs by user 等取捨。
- **Staff+**：往下挖 2–3 層，談 failure mode、bottleneck、fault tolerance、DB 最佳化、regionalization、cell-based architecture。

## 可遷移的 pattern
1. **Durable write first, best-effort push second**：先寫 durable store 再做 at-most-once 推送，把「即時」與「可靠」拆開（通知、feed、聊天、IoT 都適用）。
2. **Client ACK 驅動刪除**：Inbox 項目只在 client ACK 後刪，且用 TTL 兜底。
3. **Pub/Sub 做跨 server 路由，不要用 per-entity durable queue**：避免千萬 / 億級 topic。
4. **Heartbeat + sequence number + polling 三層偵測**：死連線、漏訊息、最後兜底。
5. **Celebrity problem -> 自適應 partition**：大群 / 熱點走不同的 fan-out 策略（fan-out on write vs read 的同類思想）。

## 常見追問
- **為什麼不每個 user 一個 Kafka topic？** Kafka 每 topic 約 50KB overhead，10 億 user 約 50TB+，且不是為億級 topic 設計。
- **Redis 掛了或沒送到，訊息會丟嗎？** 不會，因為 Message + Inbox 先 durable 寫入；client 重連 sync、sequence gap、polling 會補回。
- **怎麼保證順序？** 不保證嚴格順序；以 server 收到時間（NTP 同步）蓋章，client 依此排序，使用者可接受偶爾插入。
- **為何用 L4 LB？** 不需要 L7 的 path / header routing，L4 效能更好（原文也說多數現代 L7 支援 WebSocket）。
- **Last seen 如何避免寫入放大？** 只在 disconnect 寫一筆；在線狀態由 Pub/Sub 即時詢問 target 所在 Chat Server。
