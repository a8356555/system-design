# Networking Essentials
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/networking-essentials ｜ 分類：core-concepts

## 一句話重點
預設 TCP + HTTP/REST；只有明確需求才換 UDP / gRPC / SSE / WebSocket / WebRTC；水平擴展用 load balancer（WebSocket 用 L4，其他 L7）；並備好 regionalization（CDN、regional partitioning）與失敗處理（timeout + retry with exponential backoff + jitter、idempotency、circuit breaker）。

## 核心內容

### 前提
- Networking 在 infra / distributed systems 面試比重較高；full-stack、product 職通常只需表層理解。但面試官剛值完 on-call（LB、CDN 問題）時可能深挖。

### Networking 101：三個關鍵層
| 層 | 協定 | 作用 |
|---|---|---|
| Network (L3) | IP（InfiniBand 用於大型 ML 訓練，面試少見） | 路由與定址；分封包、跨網路轉送、best-effort delivery |
| Transport (L4) | TCP、UDP、QUIC | 端到端通訊；在 IP 之上提供可靠性、順序、flow control |
| Application (L7) | DNS、HTTP、WebSocket、WebRTC | 建在 TCP（WebRTC 用 UDP）之上，面向 web 應用的資料 |

- 層是抽象，讓開發者不必知道線路電壓。

**一次 web request 的流程**：DNS 解析 → TCP 三向交握（SYN / SYN-ACK / ACK）→ HTTP request → server 處理（多數 SWE 唯一會想到並能控制的延遲）→ HTTP response → TCP 四向結束（FIN/ACK/FIN/ACK）。
三個觀察：
1. 應用層可假設資料可靠、有序（TCP 保證），DNS + IP 解決尋址與路由。
2. 一次概念上的 request/response 背後有許多封包往返，越往上層延遲與處理越多（與 LB 討論有關）。
3. 連線是雙方都要維護的 state；除非用 HTTP keep-alive 或 HTTP/2 multiplexing，否則每個 request 都要重新建連線；對需要持久連線的 Realtime Updates 設計很重要。
- 「輸入網址按 Enter 會發生什麼」過去是熱門題，近年大廠較少。

### Network Layer
- IP 負責路由與定址；節點通常由 DHCP 在開機時分配 IP。
- Public IP 由 RIR 分配，網際網路路由基礎設施知道如何路由它們（例：17.x.x.x 屬於 Apple）。細節面試不重要。

### Transport Layer：TCP vs UDP（vs QUIC）
- 面試實際選擇是 TCP vs UDP；QUIC 可視為「更好的 TCP」但採用尚未普及。懂 QUIC / HTTP/3 對效能導向面試官是加分，但多數面試官希望你把時間花在別處。

**UDP**（machinegun / spray and pray）
- connectionless、不保證送達、不保證順序、較低延遲。只看得到來源/目的 IP 與 port，其餘是 binary blob。
- 適合速度比可靠性重要且 app 能容忍丟包/亂序：直播影音、線上遊戲、VoIP、DNS 查詢。VoIP 丟一點封包聽起來有小斷續，遠勝於重傳與 ACK 塞網路。
- 瀏覽器除 WebRTC 外沒有廣泛 UDP 支援。例：Facebook Live Comments 大量愛心/reaction，app 使用者可走 UDP 即時流，瀏覽器使用者則走較慢、批次的 HTTP 流並在 UI 上攤平。

**TCP**（網路的主力）
- connection-oriented、可靠有序且錯誤檢查、flow control（不壓垮接收端）、congestion control（避免網路崩潰）。同一 stream 內兩個訊息按序到達；未被 ACK 就重傳。

| | UDP | TCP |
|---|---|---|
| 連線 | Connectionless | Connection-oriented |
| 可靠性 | Best-effort | 保證送達 |
| 順序 | 無保證 | 維持順序 |
| Flow / Congestion control | 無 | 有 |
| Header 大小 | 8 bytes | 20-60 bytes |
| 速度 | 較快 | 因 overhead 較慢 |
| 用途 | Streaming, gaming, VoIP | 其餘一切 |

- 面試預設 TCP，通常不用特別講。選 UDP 的條件：延遲最關鍵；可接受部分資料遺失；高流量 telemetry / log 可偶爾丟；不需支援瀏覽器（或有替代方案）。
- 常見混用：視訊會議用 TCP/HTTP 做 signaling 和認證，用 UDP/WebRTC 傳實際音視訊。

### Application Layer
應用層在 user space 處理，較靈活易改；低層在 kernel space，難改但高效。

**HTTP / HTTPS**
- Request-response、**stateless**（盡量縮小有狀態的面積；簡單 HTTP server 是 request 參數的函式）。
- 概念：methods、status codes、headers、body。常見 method：GET（idempotent、無 body）、POST、PUT、PATCH、DELETE（idempotent）。
- 常見 status：200、201、301、302、401、403、404、429、500、502。
- Headers 是彈性 key-value；例：`Accept-Encoding` / `Content-Encoding` 做 content negotiation（gzip、br），提供向後相容與優雅降級。
- HTTPS = HTTP + TLS，防竊聽與 MITM；公開網站必用。
- **別信任 request body**：HTTPS 只保證傳輸加密，不保證內容由你的 client 產生。常見錯誤是 body 帶 user ID 並直接用來查 DB，攻擊者改 ID 就能讀任意使用者資料。可以帶 user ID，但 server 必須能驗證。

**REST**（面試預設）
- 對 resources（像 DB table 或檔案）做簡單操作；利用 HTTP method + 路徑慣例，通常 JSON。Core Entities 常直接對應 resources。
- 範例：`GET /users/{id}`、`PUT /users/{id}`、`POST /users`（ID 由 server 指派）、`GET /users/{id}/posts`（巢狀）。
- 用 resource 思考而非 operation：`updateUser` → `PUT /users/{id}`；`startGame` → `PATCH /games` + `{"status":"started"}`。
- 缺點：不是高吞吐服務最有效的選擇，JSON 序列化效率不佳；但多數應用不被序列化卡住。需要特定能力才換 GraphQL / gRPC / SSE / WebSocket。

**GraphQL**（約 2015 由 Facebook 開源）
- 解決前後端問題：新頁面要嘛 (a) 拼湊多個 request（under-fetching，多次往返增加延遲）、(b) 巨型聚合 API（難維護、變更慢；over-fetching）、(c) 為每個頁面寫新 API。GraphQL 讓前端靈活地查詢剛好要的資料與形狀，適合 mobile 與減少傳輸量。
- 適用：前端需快速迭代、複雜 client、多團隊對重疊資料做寬查詢。也有後端執行延遲與複雜度的成本。
- 面試：需求固定，GraphQL 好處模糊，面試官常想看你優化特定 query pattern，GraphQL 常「礙事」。只在題目強調彈性（需快速適應變更需求）或需求刻意不確定時提。

**gRPC**
- Google 的高效能 RPC，HTTP/2 + Protocol Buffers（更嚴格 schema 的 JSON 替代品）。原文例：JSON `{"id":"123","name":"John Doe"}` 約 40 bytes，protobuf binary 編碼 15 bytes。
- `.proto` 定義 service，編譯出多語言 client/server stub；支援 streaming、deadlines、client-side load balancing。
- 適用：微服務內部、效能關鍵、延遲被網路而非 server 工作主導（部分 benchmark 吞吐達 10x）；編譯期型別檢查。
- 不適合公開 API（binary、工具較不成熟、瀏覽器不支援 gRPC）。建議：**對外 REST、對內 gRPC**；許多面試內外都用 REST 也可。別在處理其他實質瓶頸前過度最佳化協定（premature optimization）。

**Server-Sent Events (SSE)**
- 建在 HTTP 上，server 可在**單一** HTTP response 中隨時間推送多筆訊息（`data: {...}` 逐行 chunk），同一條 TCP 連線，client 逐行處理。
- 限制：連線不能開太久（server / LB / 中間 proxy 會關閉）；標準定義 `EventSource` 會自動以最後收到的訊息 ID 重連，server 要記住並補發錯過的訊息。還有行為不良的網路會把 SSE 批次成單一 response。多數面試官不知道這些限制，但實作過的人會想確認你有實戰經驗。
- 適用：client 要即時收到通知/事件（拍賣競標價格更新）。細節見 Realtime Updates deep dive。

**WebSockets**
- 持久、TCP 風格的雙向連線，瀏覽器廣泛支援；server 可主動推、client 也可主動送。
- 由 HTTP "upgrade" 發起，可利用既有 cookie / headers。
- 流程：client 發 HTTP WebSocket handshake → 升級，WebSocket 接管 TCP → 雙方傳 binary 訊息 → 連線保持到明確關閉。不規定應用層協定，常用序列化 JSON，自行定義訊息 API。
- 注意：client 能 upgrade 不代表基礎設施支援，路徑上所有 firewall / proxy / LB 都須支援。
- 適用：高頻率、持久、雙向（即時應用、遊戲）。若只是 request/response 或 SSE 推播足夠，WebSocket 是 overkill。**沒有理由就直接上 WebSocket 是拿「thumbs down」的好方法**：基礎設施昂貴、stateful 連線（尤其大規模）需要大量配套。

**WebRTC**
- 瀏覽器間 peer-to-peer，不經中介 server 傳資料；唯一使用 UDP 的應用層協定。適合影音通話/會議，偶爾用於協作編輯。
- 多數 client 不允許 inbound 連線且在 NAT 後面，所以需要：
  - **Signaling server**：記錄可用 peers 與連線資訊。
  - **STUN**：打洞（hole punching）取得公開可路由的位址與 port。
  - **TURN**：relay 服務，經中央 server 轉送（STUN 失敗時的 fallback）。
- 四步驟：連 signaling server 認識 peers → 向 STUN server 取得公開 IP/port → 透過 signaling 互換資訊 → 建立直連並傳資料。
- 面試建議：只用在影音通話/會議。協作編輯雖可用 WebRTC + CRDT，但通常仍需中央 server 存文件，故 Google Docs breakdown 用 WebSocket。WebRTC 很難做對，原文見過太多候選人在不需要 P2P 的題目硬走 WebRTC 而離題。

### Load Balancing
- 擴展：vertical（更大的機器）vs horizontal（更多機器）。原文個人偏好盡量 vertical（現代硬體很強，見 Numbers to Know），但面試最常見是 horizontal，所以需要 LB 告知 client 該連哪台。

**Client-side load balancing**
- Client 自己決定連哪台，通常查詢 service registry / directory 取得 server 列表，再直連；需定期 poll 或被推送更新。快速高效，省去每個 request 的額外 hop。
- 例 1 Redis Cluster：節點間用 gossip 協定共享叢集資訊；client 問任一節點拿到 nodes 與 shards，hash key 決定 shard 與節點；打錯節點會收到 MOVED 回應。
- 例 2 DNS：resolver 回傳輪轉的 IP 列表，每次順序不同 → client-side LB。可用來避免 LB 本身單點故障：兩個 LB（不同 data center / region）用 DNS 輪轉，其一掛掉 client 自動試另一個。
- 適用：(1) 少量可控 client（Redis Cluster client、gRPC client-side LB）；(2) 大量 client 但可容忍更新慢（DNS；更新速度受 TTL 限制）。
- 面試：內部微服務之間很合適（gRPC 內建）；其他場景需要 dedicated LB。

**Dedicated load balancers**
- 位於 client 與 backend 之間的 server / 硬體；多一個 hop，但換得快速更新 server 清單與細緻路由控制。適合 client 不可控或需快速更新。

| | L4 (transport) | L7 (application) |
|---|---|---|
| 依據 | IP + port，不看內容 | HTTP 內容：URL、headers、cookies |
| 連線 | 維持 client↔server 持久 TCP 連線（如同直連同一 backend） | 終止進來的連線並對 backend 建新連線 |
| 特性 | 快、高效、最少檢查；不能依應用資料路由 | 較吃 CPU、功能彈性（API vs 網頁分流、cookie 黏著，類似 API Gateway） |
| 適用 | **WebSocket** 與其他需持久連線的協定、重效能 | HTTP 流量（除 WebSocket 外所有討論過的協定）、long polling |
- 部分 L7 LB 明確支援 WebSocket，但一般 WebSocket 傾向 L4。

**Health checks 與容錯**：LB 監控 backend 健康，掛掉就不再導流。TCP health check（是否接受新連線）簡單；L7 health check 打 HTTP（200 vs 500 / 無回應）。

**LB 演算法**：Round Robin、Random、Least Connections、Least Response Time、IP Hash（session 黏著）。
- Stateless 應用通常 round robin 或 random；新 server 加入會自然被分到流量。
- 持久連線（SSE / WebSocket）用 **Least Connections**，避免單一 server 逐漸累積所有連線。

**實作**：硬體（F5 BIG-IP）、軟體（HAProxy、NGINX、Envoy）、雲端（AWS ELB/ALB/NLB、GCP LB、Azure LB）。企業硬體 LB 可支撐數億 requests/s，軟體較受限；面試幾乎不談 LB 擴展，若 LB 吞吐很大，提硬體 LB 是不錯的出路。

### Common Deep Dives
**Regionalization and Latency**
- 全球服務通常有多個 data center（AWS 的 availability zones）並複製到全球多個城市。
- 物理限制：NY 到倫敦 <1ms（附近）vs >80ms；光纖約 2/3 光速，約 200,000 km/s；NY–倫敦約 5,600 km，理論最小往返 ≈ 56ms（尚未計處理時間）。
- 原則是 data locality：資料盡量靠近運算、靠近使用者。若 user data 在 LA 而 web server 在 NY，每次 DB query 都多幾十 ms。
- 策略：
  - **CDN**：全球數百到數千城市的 edge location；資料可快取（靜態內容、很少變）時從 edge 回，極快。面試中適用高度可快取且全球查詢的資料（例：Facebook 搜尋結果），降延遲並減少 backend 負載。
  - **Regional partitioning**：依區域分割資料。例 Uber：在 Miami 不會叫 NY 的司機；單一城市只有幾千名 riders/drivers。把鄰近城市合併成區域（Northeast US、Southwest US），各區有自己的 DB 與同地 servers，查詢由區域服務與本地 DB 處理，快上加快。

**Failures and Fault Modes**
- 「The network is reliable」是分散式系統最危險的假設；網路呼叫會失敗、延遲或回傳意外結果。
- **Timeouts + Retries with Backoff**：超時就放棄並重試，處理暫時性失敗。需要 idempotent API。重試可能雪上加霜，所以要 backoff：等待時間逐次拉長，並加入隨機性（**jitter**），避免所有 client 同步重試像 jackhammer。面試官常想聽到魔術詞「**retry with exponential backoff**」，senior 會被追問 jitter。
- **Idempotency**：重試有副作用時（付款 $10 重試變 $20 甚至 $2,000）。GET 天然 idempotent；寫入用 **idempotency key**（唯一識別 request）。例：使用者每天只買一件，key = user ID + 日期。server 檢查是否已處理（或處理中）該 key，只處理一次；友善的 API 等待完成並把結果回給所有請求者，不友善的就回錯誤「request already exists」，兩者都避免重複扣款。
- **Circuit breakers**（防連鎖失敗）：DB 掛掉要逐台重啟時，大量重試與憤怒使用者（thundering herd）可能讓第一台永遠起不來。運作：
  1. 監控呼叫外部服務的失敗；
  2. 失敗超過門檻→「跳閘」進入 open 狀態；
  3. open 時請求立即失敗，不實際呼叫；
  4. 一段 timeout 後進入 half-open；
  5. 以測試請求決定關閉電路（恢復）或維持 open。
  - 優點：fail fast、減少已吃緊服務的負載、自我修復（不需全流量測試恢復）、較好的使用者體驗（快速 fallback 取代卡死 UI）、系統穩定（單一服務失敗不拖垮全部）。
  - 適用：第三方外部 API、DB 連線與 query、微服務間呼叫、可能 timeout 的重運算、任何可能失敗或變慢的網路呼叫。面試被追問可靠性、failure modes、disaster recovery 時是好答案。

### 延伸練習（原文）
Wireshark 抓封包看整個協定堆疊；Mac Network Link Conditioner 模擬延遲與丟包，看網站/app 反應。

## 面試怎麼用
- 預設：TCP、HTTP/HTTPS、REST；對內可提 gRPC。
- 觸發器與對應：
  - 即時推送單向 → SSE；高頻雙向 → WebSocket（要先講理由）；影音通話 → WebRTC。
  - WebSocket → L4 LB + Least Connections；一般 HTTP → L7 LB。
  - 全球低延遲 → CDN 與 regional partitioning。
  - 可靠性追問 → timeout + retry with exponential backoff + jitter、idempotency key、circuit breaker。
- 陷阱：無理由使用 WebSocket / WebRTC / GraphQL；以為 client 送的 user ID 可信；忘記 WebSocket 需要整條基礎設施支援與 stateful 連線的代價；重試沒搭配 backoff/jitter/idempotency；把 UDP 用在需支援瀏覽器的設計卻沒有替代方案。

## 關鍵數字
- NY–倫敦：約 5,600 km，光纖約 200,000 km/s，理論最小往返約 56 ms；近距離 <1ms vs 跨洋 >80ms。
- TCP header 20-60 bytes，UDP 8 bytes。
- Protobuf 範例 15 bytes vs JSON 40 bytes；gRPC 部分 benchmark 吞吐約 10x。
- 硬體 LB 可到數億 requests/s。

## 相關題目
- [whatsapp](../../hellointerview-breakdowns/whatsapp.md)（WebSocket / L4 LB）
- [fb-live-comments](../../hellointerview-breakdowns/fb-live-comments.md)（UDP vs HTTP 批次、SSE）
- [online-auction](../../hellointerview-breakdowns/online-auction.md)（SSE 更新價格）
- [google-docs](../../hellointerview-breakdowns/google-docs.md)（WebSocket vs WebRTC+CRDT）
- [uber](../../hellointerview-breakdowns/uber.md)（regional partitioning）
- [payment-system](../../hellointerview-breakdowns/payment-system.md)（idempotency）

## 自測問題
1. 何時選 UDP 而非 TCP？答：延遲最關鍵、可容忍丟包（直播、遊戲、VoIP、telemetry）、且不需支援瀏覽器或有替代方案。
2. SSE 與 WebSocket 如何選？答：單向 server push（拍賣價格）用 SSE；高頻雙向才用 WebSocket，後者基礎設施與 stateful 連線成本高，需先說理由。
3. L4 與 L7 LB 差異？WebSocket 用哪個？答：L4 看 IP/port、維持持久 TCP 連線、快；L7 看 HTTP 內容、可依 URL/header/cookie 路由。WebSocket 傾向 L4，並搭配 Least Connections。
4. 為什麼重試要加 jitter 與 idempotency key？答：避免所有 client 同步重試（jackhammer），並避免副作用（重複扣款）。
5. Circuit breaker 三種狀態與作用？答：closed（正常）→ 失敗超門檻 open（立即失敗）→ timeout 後 half-open（試探請求決定恢復或維持 open）；fail fast、減少負載、避免連鎖失敗。
