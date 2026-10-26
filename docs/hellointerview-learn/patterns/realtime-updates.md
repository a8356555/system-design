# Real-time Updates
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/realtime-updates ｜ 分類：patterns

## 一句話重點
Real-time 要拆成兩個 hop：(1) server → client 用什麼連線（polling / long polling / SSE / WebSocket / WebRTC）；(2) 事件來源 → 持有該 client 連線的 server（polling DB、consistent hashing、pub/sub）。先選最簡單能滿足的，再談規模與順序性。

## 原文大綱（原文）
- 介紹（原文）：Real-time Updates addresses the challenge of delivering immediate notifications and data changes from servers to clients as events occur... covers architectural approaches to enable low-latency, bidirectional communication.
- The Problem（原文重點）：以 Google Docs 為例，一人打字其他人要在毫秒內看到，不可能每個人每幾毫秒 polling。標準 HTTP 是 request-response，server 無法主動推送。
- 原文列出的相關題目：Ticketmaster、Uber、WhatsApp、Robinhood、Google Docs、Strava、Online Auction、FB Live Comments、Online Chess、ChatGPT、Flash Sale
- The Solution：兩個 hop——第一 hop 為 server 到 client，第二 hop 為 source 到 server。
- Client-Server Connection Protocols：Networking 101（Layer 3 IP、Layer 4 TCP/UDP、Layer 7 DNS/HTTP/WebSocket/WebRTC；Request Lifecycle）→ Simple Polling: The Baseline / Long Polling: The Easy Solution / Server-Sent Events (SSE): The Efficient One-Way Street / Websockets: The Full-Duplex Champion / WebRTC: The Peer-to-Peer Solution / Overview
- Server-Side Push/pull：Pulling with Simple Polling / Pushing via Consistent Hashes / Pushing via Pub/Sub
- When to Use in Interviews：Common Interview Scenarios / When NOT to Use
- Common Deep Dives：「How do you handle connection failures and reconnection?」「What happens when a single user has millions of followers who all need the same update?」「How do you maintain message ordering across distributed servers?」
- Conclusion；腳註（原文）：Hello Interview 自己大量使用 SSE，處理 networking edge case 花了驚人的時間。

## 內容（by agents）
### Networking 101（重點）
- L3 IP：best-effort，封包可能遺失／重複／亂序。
- L4 TCP：連線導向、可靠有序、有握手與維護成本；UDP：無連線、不保證，延遲低。
- L7 HTTP/WebSocket/WebRTC：多數建立在 TCP 上（WebRTC 資料走 UDP/SRTP/SCTP）。
- 持久連線的代價：每條連線佔 server 記憶體與 file descriptor；LB 需支援 sticky／long-lived connection；proxy 與 idle timeout 會切斷連線。

### 第一 hop：Client-Server 協定
| 方式 | 機制 | 優點 | 缺點 | 適用 |
|---|---|---|---|---|
| Simple Polling | client 定時 GET | 最簡單、無狀態、好擴充、走一般 HTTP | 延遲 = 輪詢間隔、空請求浪費 | 更新不頻繁、秒級延遲可接受 |
| Long Polling | server 掛住請求直到有資料或逾時，client 立即重連 | 近即時、相容性佳、不需特殊基礎設施 | 每次事件都要新請求、header 開銷、連線佔用 | 無法用 WS/SSE 的環境、簡單 chat／通知 |
| SSE | 單向 HTTP streaming（`text/event-stream`），內建自動重連與 `Last-Event-ID` | 簡單、走 HTTP/2、易穿 proxy | 單向（server→client）、舊瀏覽器每網域連線數限制（HTTP/1.1 約 6） | 通知、live feed、股價、LLM token streaming |
| WebSocket | HTTP Upgrade 後全雙工 TCP | 低延遲雙向、小 frame 開銷 | 有狀態、LB／proxy 需設定、需自行處理重連／心跳／背壓 | 聊天、協作編輯、遊戲、交易 |
| WebRTC | P2P（STUN/TURN/ICE 打洞），UDP | 最低延遲、省 server 頻寬 | 複雜、需 signaling server 與 TURN fallback | 影音通話、P2P 遊戲 |
**Overview 決策**：預設 polling → 要近即時但單向用 SSE → 要雙向用 WebSocket → 音視訊／P2P 用 WebRTC。面試中別一開口就上 WebSocket。

### 第二 hop：Server-Side Push/pull
- **Pulling with Simple Polling**：server 端更新寫 DB，connection server 定期查（或 client polling 後端）。簡單，但 DB 讀壓大、有延遲。
- **Pushing via Consistent Hashes**：以 user/room ID 做 consistent hashing，決定其連線落在哪台 server；事件來源直接把訊息路由到對應 server。優點：直接、低延遲；缺點：需維護 membership／服務發現，節點增減時重新分配連線，熱點 room 難分散。
- **Pushing via Pub/Sub**：connection server 訂閱 channel（Redis Pub/Sub、Kafka、NATS、SNS）；事件發布到 channel，所有訂閱的 server 收到後推給本機連線。優點：解耦、天然 fan-out；缺點：Redis Pub/Sub 為 at-most-once 不保存訊息，Kafka 提供持久與重放但 partition 數與 consumer 規劃需注意；每台 server 都可能收到不相關訊息（需精細 channel）。

## 常見深入題（by agents）
- **連線斷線與重連？** 指數退避 + jitter 避免 thundering herd；client 帶 last seen offset／event ID，server 補發遺漏（需短期保存 log，如 Redis Stream／Kafka）；心跳偵測死連線；重連後做 state resync（拉快照 + 增量）。
- **一個人有百萬 follower？** fan-out on write 會爆；hybrid：大 V 採 fan-out on read／pull，一般用戶 push；用 pub/sub topic 讓每台 connection server 只訂閱一次再本機 fan-out；分層 fan-out tree；批次與合併更新；對低活躍用戶不推送（只在上線時拉）。
- **跨 server 訊息順序？** 同一 room／conversation 路由到同一 partition（以 key 分區），partition 內單調遞增 sequence number；client 依 sequence 去重與重排；全域順序通常不需要也太貴；協作編輯用 OT／CRDT。

## 面試怎麼用（by agents）
- 訊號：聊天、即時通知、即時報價、拍賣出價、司機位置、協作編輯、直播留言、LLM streaming。
- 流程：先問延遲需求與方向（單向／雙向）→ 選第一 hop → 再選第二 hop → 說明規模（連線數 / server、sticky、重連）。
- 不要用：資料更新頻率低、分鐘級可接受（polling 就好）；別為「即時」堆砌基礎設施。
- 加分：講連線數估算（單機約數萬～十萬）、資源上限、重連風暴、訊息遞送語意（at-least-once + 去重）。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [uber](../../hellointerview-breakdowns/uber.md)
- [whatsapp](../../hellointerview-breakdowns/whatsapp.md)
- [robinhood](../../hellointerview-breakdowns/robinhood.md)
- [google-docs](../../hellointerview-breakdowns/google-docs.md)
- [strava](../../hellointerview-breakdowns/strava.md)
- [online-auction](../../hellointerview-breakdowns/online-auction.md)
- [fb-live-comments](../../hellointerview-breakdowns/fb-live-comments.md)
- [online-chess](../../hellointerview-breakdowns/online-chess.md)
- [chatgpt](../../hellointerview-breakdowns/chatgpt.md)
- [flash-sale](../../hellointerview-breakdowns/flash-sale.md)

## 自測問題（by agents）
1. SSE 與 WebSocket 如何取捨？答：單向推送用 SSE（簡單、自動重連）；需雙向低延遲用 WebSocket。
2. 為何有「兩個 hop」？答：client 連在某台 server 上，事件來源需要先找到/廣播到那台 server。
3. Pub/Sub 的 Redis 實作有什麼風險？答：不持久、at-most-once；斷線期間訊息遺失，需搭配可重放的 log。
4. 重連風暴如何避免？答：指數退避 + jitter、server 端限流、分批。
5. 如何保證聊天室內訊息順序？答：同 room 同 partition，server 發 sequence number，client 依序號排序去重。

## 參考來源
- https://html.spec.whatwg.org/multipage/server-sent-events.html
- https://datatracker.ietf.org/doc/html/rfc6455 （WebSocket）
- https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API
- https://redis.io/docs/latest/develop/interact/pubsub/
- https://slack.engineering/real-time-messaging/ （Slack real-time messaging，連線與 fan-out 設計）
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
