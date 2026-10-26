# Online Chess
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/online-chess ｜ 難度：hard ｜ 類別：Real-time Updates、Dealing with Contention

## 一句話核心
（原文）Chess.com/Lichess 類平台：技能配對、即時對局（server 驗證每步並掌管雙方時鐘）、全球排行榜；難點是避免重複配對、500K 並行對局的 game server 擴展、跨延遲的公平時鐘、10M 玩家排行榜。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 透過技能配對找對手並開局
- 即時下棋
- 檢視全球排行榜與自己的排名，對局結束後短時間內更新
- 只支援一種格式：3 分鐘 blitz（每方總計 3 分鐘，只在自己回合計時，無加秒）
- Out of scope：觀戰/廣播、聊天/好友、謎題/復盤、錦標賽、反作弊

**Non-functional / 規模（原文）**
- 10M 註冊玩家、峰值 500K 並行對局
- 每局兩位玩家 -> 1M 並行連線，另需驗證每一步與每局兩個時鐘的運算
- Server 驗證每步合法性、掌管時鐘（防止玩家謊報）
- （原文 NFR 條列內文未公開，其餘為上述規模帶出的要求）

## Core Entities & API
（原文僅標題；補充，非原文）
- Entities：Player(rating)、Game(id, white, black, moves, status, clocks)、Move、MatchRequest
- API：
  - `POST /matchmaking/queue`（加入配對）
  - WebSocket：`move {game_id, from, to}`、server 推送 `state`/`clock`/`result`
  - `GET /leaderboard?top=100`、`GET /players/{id}/rank`

## High-Level Design
（原文僅標題；補充，非原文）
1. 配對：玩家入佇列（含 rating、時間控制）-> Matchmaker 依 rating 相近配對 -> 建立 Game -> 通知雙方連線到指派的 game server。
2. 對局：雙方 WebSocket 連到同一 game server（一局的狀態在單一節點記憶體）；server 驗證走法、更新棋盤與時鐘、廣播給對手；結束時寫入結果與棋譜。
3. 排行榜：結果事件 -> 更新 rating -> 更新排行（Redis sorted set），讀 top N 與 rank。

## Deep Dives（依原文大綱逐條）
### 1) 如何避免玩家被配對進兩場對局？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：Matchmaker 讀取兩位等待玩家、各自建立 Game，併發的多個 matcher 可能同時選中同一位玩家。
- 好解：DB transaction 內 `SELECT ... FOR UPDATE SKIP LOCKED` 或條件式更新（status: waiting -> matched）搶占玩家。
- 最佳解：把「玩家狀態」作為單一真相，以原子的 compare-and-set 把兩位玩家同時標記為 in_game（同 transaction）；或單一 matchmaker 分片（以 rating 區間分區）序列化決策。
- 取捨：悲觀鎖簡單但吞吐有限。

#### 若配對規模超過 Postgres 怎麼辦？（原文子題目）
（補充，非原文）改以 Redis（sorted set 依 rating + Lua 腳本原子 pop 兩人）或依 rating bucket 分片的記憶體 matchmaker；用 Lua 保證原子；玩家狀態仍有持久備援以便崩潰恢復。

### 2) 如何擴展 game server 到 500K 並行對局？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：任意無狀態 server 處理每一步，每步都讀寫 DB，延遲高且需分散式鎖。
- 好解：一局固定 pin 在一台 game server（棋盤與時鐘在記憶體），以 game_id 一致性雜湊/由 allocator 指派；每步非同步落盤。
- 最佳解：Game Allocator + registry（Redis/etcd）記錄 game->server；server 週期 checkpoint/追加走法日誌，節點故障時由另一台從日誌重建並恢復雙方連線（含時鐘補償）。500K 局 / 每台約 10-20K 局 ≈ 25-50 台。
- 取捨：有狀態服務簡化一致性與延遲，但需處理故障轉移、部署時的 draining。

### 3) 如何在延遲不均下維持時鐘公平？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：以 client 回報的時間為準，容易作弊且受網路抖動影響。
- 好解：Server 為唯一計時者：記錄「收到走法」的 server 時間，輪到誰就從上次走法時間起扣。
- 最佳解：Server 權威時鐘 + 延遲補償（估計每位玩家 RTT，對低延遲玩家不吃虧；可有上限，如補償最多數百 ms）；用單調時鐘 (monotonic clock)；client 僅作顯示預測，以 server 事件校正；超時由 server 計時器觸發 flag 判負。
- 取捨：補償越多越公平但可被濫用；需設上限。

### 4) 如何在 10M 玩家下讓排行榜正確且快速？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：`SELECT ... ORDER BY rating DESC` 全表排序，rank 用 COUNT(*) 計算。
- 好解：DB 上對 rating 建索引，top N 走索引；個人 rank = COUNT(rating > mine)。
- 最佳解：Redis Sorted Set（ZADD/ZREVRANK/ZREVRANGE，O(log N)）；以對局結果事件（Kafka）驅動更新，保證冪等（以 game_id 去重）；DB 為真相來源，Redis 可重建。需「短時間內更新」，非同步事件即可。
- 取捨：Redis 單 key 約能容納千萬成員；超大或需分區榜時分桶（區域/分段）並合併。

### 其他（原文提及）
Final Design 與「反作弊為何有趣但不在範圍」（原文末尾提及，內容未公開）。

## 關鍵數字與 back-of-envelope
- （原文）10M 玩家、500K 並行局、1M 並行連線。
- 補充：blitz 3 分鐘每方，平均 ~40 步/局，局長約 6 分鐘 -> 每秒約 500K × 40 / 360s ≈ 55K moves/s 的全域走法吞吐。
- 補充：1M WebSocket 連線，每台 ~50K -> 約 20 台連線節點（若與 game server 合一則依上面估計 25-50 台）。
- 每局棋譜極小（<1KB），寫入負載輕。

## 可遷移的 pattern（3-5 條）
1. 避免雙重分配：原子 compare-and-set / SKIP LOCKED / Redis Lua。
2. 有狀態 game session pin 到單一節點 + 日誌/checkpoint 容錯。
3. Server 權威時鐘 + 延遲補償，不信任 client。
4. Redis Sorted Set 做排行榜，事件驅動且冪等更新。
5. WebSocket 長連線 + allocator/registry 路由。

## 常見追問（3-5 題，附簡短答案）
- Game server 當機？從走法日誌重建狀態並補償時鐘，讓雙方重連。
- 玩家斷線？設重連寬限期，時鐘持續走；超時判負。
- 配對等待過久？逐步放寬 rating 範圍。
- 如何更新 rating？Elo/Glicko，結果事件非同步、以 game_id 保證只算一次。
- 部署新版 game server？draining：不再接新局，等現有對局結束。
