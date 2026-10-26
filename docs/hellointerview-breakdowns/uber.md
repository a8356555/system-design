# Uber
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/uber ｜ 難度 hard ｜ 類別：Real-time Updates / Multi-step Processes（作者 Evan King）

## 一句話核心
Uber = 「高頻司機定位寫入 + 地理鄰近搜尋」加上「派單時每位司機同一時間只能收到一個請求」的一致性問題。關鍵招式：Redis Geo（in-memory geohash）、Redis distributed lock + TTL、queue（Kafka 延後 commit offset）、durable execution（Temporal）處理司機逾時，以及 geo-sharding。

## 需求（Functional / Non-functional / 規模數字）
**Functional（Core）**
- Rider 輸入起點與終點，取得 fare estimate
- Rider 依估價請求叫車
- 請求後配對到附近可用的司機
- 司機可接受/拒絕請求，並導航到上車/下車點

**Below the line**：行後評分（雙向）、預約排程、不同車種（X、XL、Comfort）。

**Non-functional（Core）**
- 低延遲配對（< 1 分鐘內配對成功或失敗）
- 配對強一致：不得讓司機同時被指派多趟
- 高吞吐，尖峰/特殊活動（同一地點 100k requests）

**Below the line**：資安隱私/GDPR、故障韌性與 failover、監控告警、CI/CD。

## Core Entities & API
**Entities**
- Rider：個資、付款方式
- Driver：個資、車輛資訊、偏好、可用狀態
- Fare：起訖點、預估費用、ETA（也可併入 Ride，無對錯）
- Ride：從 rider 確認估價請求到結束的完整紀錄：rider、driver、車輛、狀態、規劃路線、實際車資、上下車時間戳
- Location：司機即時經緯度與最後更新時間

**API**（身分走 session/JWT，不放 body；時間戳由 server 產生；fareEstimate 從 DB 取，絕不由 client 傳入）
```
POST  /fare   { pickupLocation, destination } -> Fare       # POST 因為會建立 Fare 實體
POST  /rides  { fareId } -> Ride                              # 觸發配對流程（配對在後端，不另開 endpoint）
POST  /drivers/location { lat, long } -> Success/Error       # driverId 來自 session/JWT
PATCH /rides/:rideId { accept/deny } -> Ride                 # 接受後回傳上車點座標
```

## High-Level Design（元件與資料流）
```
Rider Client --> API Gateway --> Ride Service --> DB (Fare, Ride)
                                   |  \--> Third-party Mapping API (距離/時間)
                                   v
                          Ride Matching Service <-- Location Service <-- Driver Client (定位上報)
                                   |
                                   v
                          Notification Service --(APNs / FCM)--> Driver Client
                                                  Driver PATCH /rides/:id --> API GW --> Ride Service
```
1. **Fare estimate**：Ride Service 呼叫 Mapping API 取距離與時間，套用 pricing model，建立 Fare 存 DB 並回傳。
2. **Request ride**：不需新服務，只新增 Ride 表；建立 Ride（status = requested，連到 Fare）後觸發配對。
3. **Matching**：加入 Driver Client、Location Service（接收/儲存司機定位並提供最新位置）、Ride Matching Service（依距離、可用性、評分等排序，演算法抽象帶過）。
4. **Accept/decline**：Notification Service 透過 APNs（iOS）/FCM（Android）推播給排名第一的司機；司機接受 -> PATCH -> Ride Service 更新 status = accepted 並回傳上車座標；拒絕則通知下一位。

## Deep Dives

### 1) 高頻定位更新與高效鄰近搜尋
問題：
- 約 10 million 司機、每 5 秒上報 -> 約 2 million updates/秒；DynamoDB 或 Postgres 要嘛撐不住，要嘛貴到不可行。以 DynamoDB 每筆 100 bytes、on-demand $1.25 / million WRUs，2M 寫/秒一天超過 $200k。
- 沒優化的 lat/long 查詢要全表掃描算距離；一般 B-tree 不適合多維地理資料。

**爛解**：每筆定位直接寫 DB、對原始資料做鄰近查詢。
**好解：批次寫入 + 專用 geospatial DB**：以短間隔聚合後批量寫以降低寫入次數；地理資料庫用 quad-tree 等結構（遞迴切四象限）；Postgres 可用 PostGIS 外掛。缺點：批次間隔造成資料延遲，可能導致配對不佳。
**最佳：Redis in-memory geospatial store**：Redis 用 geohash 把經緯度編成 52-bit 整數 score 存在 sorted set（member = driverId）；`GEOADD` 寫入（會覆寫該司機前一個位置，所以永遠是最新）、`GEOSEARCH`（Redis 6.2 起，取代 GEORADIUS / GEORADIUSBYMEMBER）查半徑/邊界框。不需批次處理。處理離線司機的陳舊資料：維護以時間戳為 score 的 companion sorted set，週期性移除超過門檻（例如 30 秒）的項目，兩個集合都清。
  - 挑戰是 durability：開 RDB/AOF persistence、用 Redis Sentinel 做自動 failover；即使資料遺失，因為每 5 秒就會重新上報，只需那麼久就能重建狀態，影響極小。

### 2) 如何降低定位更新造成的負載同時維持準確？
**最佳：Adaptive location update intervals**：client 端用裝置感測器與演算法，依速度、方向、與待處理請求的距離、司機狀態動態調整頻率（靜止或慢速可少報，高速或頻繁轉向則多報）。挑戰：演算法設計與測試複雜。
原文提醒：別忽略 client，很多情況需要 client 側邏輯提升效率（如檔案上傳的 chunking 與壓縮）。

### 3) 如何防止同一司機同時收到多個請求？
一致性定義：一個 ride request 同一時間只問一位司機，且每位司機同一時間只會有一個請求，司機有 10 秒接受/拒絕，否則換下一位。原文指出這與 Ticketmaster 的「結帳保留票」幾乎同構。

**爛解：application-level locking + 手動 timeout**：每個 Matching Service 實例自己標記 lock 並計時。問題：多實例間無協調、race condition；實例 crash 後 lock 殘留、其他實例不知道；實例越多越嚴重。
**好解：DB 狀態更新 + timeout 處理**：把鎖移到 DB，司機狀態設為 "outstanding_request"，接受 -> accepted，拒絕 -> available；用 Ride Service 內的計時器處理逾時。問題：in-memory timeout 在服務 crash/重啟時遺失，lock 永久殘留；補 cron 可行但增加複雜度並有延遲。
**最佳：Redis distributed lock + TTL**：以 driverId 為 key，TTL = 10 秒的接受視窗；取鎖成功才可對該司機發請求；接受則 DB 設 accepted 並釋放鎖；逾時鎖自動過期，司機可被重新考慮。挑戰：依賴 Redis 的可用性與效能，需要監控與 failover；因鎖只持有 10 秒、資料短暫，恢復容易，是合理取捨。

### 4) 如何確保尖峰期不掉單？
**爛解**：無 queue、先來先處理（現況）。無法快速擴容，且 Matching Service 實例掛掉時處理中的請求遺失，rider 無限等待。
**最佳：Queue + dynamic scaling**：請求先進 queue，Matching Service 消費；queue 過長時水平擴增實例；可依地理區域切分 queue。用 Kafka 在**成功配對後才 commit offset**，若服務掛掉，訊息仍在 queue，由新實例接手。可用託管服務（SQS、Amazon MSK、Confluent Cloud）降低維運負擔。挑戰：FIFO 可能被慢請求卡住（head-of-line blocking），可改 priority queue（依司機距離、評分等優先順序）。

### 5) 司機沒回應怎麼辦？（Multi-step Processes）
Human-in-the-loop 是使用 Multi-Step Processes pattern 的強烈訊號。原文提到 Uber 是 Cadence 的原作者，孕育了 Temporal。
**好解：Delay queue**：派單給司機時同時排一則延遲訊息（如 SQS delay queue），10 秒後處理；檢查 ride 是否仍未指派，若是就送給排名清單的下一位並再排延遲訊息。挑戰：需要管理多個延遲訊息，司機在延遲訊息處理前才接受時要能優雅取消、避免錯誤重派；與 matching service 之間需要協調以避免 race。
**最佳：Durable execution（Temporal / AWS Step Functions）**：整個配對流程建模為 durable workflow：發給第一位司機 -> 設 10 秒 timeout -> 接受則完成 -> 拒絕或逾時換下一位 -> 直到找到或名單用完。狀態持久化，服務 crash 後可從中斷處繼續。挑戰：引入 orchestration 系統的學習與維運成本，但對任務關鍵系統通常值得。

### 6) 如何進一步擴展以降延遲、提吞吐？
**爛解：Vertical scaling**：貴、需停機、不可無限擴展、無容錯。
**最佳：Geo-sharding + read replicas**：依地理切分資料（服務、message queue、DB 都可依地區切），並用 read replica 提升讀取吞吐；同時縮短 client 與 server 距離降延遲。唯一需 scatter-gather（查詢多個 shard）的情境是邊界上的鄰近搜尋。挑戰：分片的複雜度、資料均勻分布與 rebalancing；可用 consistent hashing 與複寫策略。

## 關鍵數字與 back-of-envelope
- 司機 10 million，每 5 秒上報 -> 約 2 million 更新/秒。
- DynamoDB 2M 寫/秒、100 bytes：on-demand 約 $1.25 / million WRUs，超過 $200k/天。
- 司機接受視窗 10 秒；配對目標 < 1 分鐘；陳舊定位清除門檻範例 30 秒。
- 尖峰：同一地點 100k requests。
- Redis geohash：52-bit 整數 score。

## 面試官期待（Mid / Senior / Staff）
- **Mid（E4）**：80/20。API 與 data model 清楚、HLD 可運作；理解需要 spatial index 但不一定落到具體解；至少做到 ride request locking 的「好解」。
- **Senior（E5）**：60/40。快速帶過 HLD，深入討論至少 2 項：加速位置搜尋、司機鎖定、request queueing；能講出架構取捨（含 sharding、replication）。
- **Staff+**：40/60。深入 3 個以上關鍵領域，有創新與最佳解；面試官聽完有新收穫。

## 可遷移的 pattern
1. **In-memory geo index（Redis GEOADD/GEOSEARCH）+ 以 TTL/時間戳清除陳舊資料**：任何「附近的 X」（外送、共享單車、附近好友）。
2. **Distributed lock with TTL 作為短期獨佔預約**：與 Ticketmaster 同構；key = 被爭奪資源（driverId / ticketId），TTL = 回應視窗。
3. **Queue 延後 commit offset 確保 at-least-once 不掉單**，搭配地區分區與 priority queue 避免 head-of-line blocking。
4. **Durable execution（Temporal）取代手刻 timer/cron/delay queue**：適用有人類參與、逾時重試、多步驟流程。
5. **Client 端邏輯減載（adaptive interval）+ geo-sharding**：把成本轉移到 client、把資料依地理切分降延遲。

## 常見追問
1. **為何不直接用 DynamoDB/Postgres 存定位？** 2M 寫/秒要嘛撐不住要嘛成本過高（DynamoDB 估算 > $200k/天），且 B-tree 不適合多維查詢。
2. **Redis 掛掉丟失定位怎麼辦？** RDB/AOF + Sentinel failover；且司機每 5 秒重報，影響只持續約一個上報週期。
3. **司機離線的陳舊位置怎麼處理？** companion sorted set 以時間戳為 score，週期性刪除超過門檻（如 30 秒）的項目。
4. **為何 in-memory timer 不行？** 服務 crash/重啟 timer 就消失，鎖永久殘留；改 Redis TTL 或 durable execution。
5. **跨 shard 邊界的鄰近搜尋？** 需 scatter-gather 查詢相鄰 shard，這是 geo-sharding 唯一需要的情況。
6. **如何避免 queue 被慢請求卡住？** 用 priority queue，依司機距離、評分等排序。
