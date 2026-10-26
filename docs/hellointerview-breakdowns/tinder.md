# Tinder（Dating App）
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/tinder ｜ 難度 medium ｜ 類別 Product design（作者 Joseph Antonakakis）

## Threads 貼文觀點
來源：https://www.threads.com/@chunhao2026/post/DemOZTnDOVq

- 場景：兩人在**同一毫秒**互相右滑，match 不能漏掉 -> 需要 **strong consistency**。
- 解法：**Redis + Lua script** 對 key `swipes:user1:user2` 做原子操作（寫入自己的 swipe 並讀對方的 swipe 是同一步），**Cassandra 當 durable source**。
- 重點是**選擇性一致性**：feed 可以 stale，但 mutual match 不能漏。不是整個系統都要 strong consistency，而是把強一致只花在真正需要的那一條路徑。

## 一句話核心
把「A 滑 B」與「B 滑 A」路由到同一個 key / partition，在同一個原子操作內「寫自己 + 讀對方」，才不會兩人同時右滑卻都沒偵測到 match；feed 則用「預先計算 + 索引資料庫」換低延遲，容許些微 stale。

## 需求
**Functional（Core）**
- 建立 profile，含偏好（年齡範圍、興趣）與最大距離。
- 看到符合偏好且在最大距離內的候選人 stack。
- 一個個右滑 / 左滑（yes / no）。
- 互相右滑時收到 match 通知。

Out of scope：上傳照片、match 後 DM、super swipe / 付費功能。

**Non-functional**
- Swipe 要 **strong consistency**：後滑的人若對方已右滑，必須收到 match。
- 規模：20M DAU，約 100 swipes/user/day。
- 載入 stack 延遲 < 300ms。
- 不重複顯示已滑過的 profile。

Out of scope：防假帳號、monitoring / alerting。

**規模數字（原文）**
- 20M DAU × 100 swipes/day = 2B swipes/day；原文另一處以 200 swipes/day 算出 4B swipes/day（原文前後不一致，面試時以你自己宣告的假設為準）。
- 20M × 100 swipes × 100 bytes ≈ 200GB/day 的 swipe 資料。

## Core Entities & API
**Entities**：User（既是使用者也是被展示的 profile）、Swipe（swiping_user -> target_user，yes/no）、Match（兩人互相 yes）。

**API**（user 身分放 header 的 session token / JWT，不放 body）：
- `POST /profile {age_min, age_max, distance, interestedIn, ...}`
- `GET /feed?lat=&long=&distance= -> User[]`：其他 filter 由 server 端從 profile 載入；位置由 client 傳（因為會變）。不需要分頁，用完就再呼叫一次（是推薦而非 paging）。
- `POST /swipe/{userId} {decision: "yes"|"no"}`

## High-Level Design
```
Client -> API Gateway -> Profile Service -> Profile DB
                      -> Swipe Service   -> Swipe DB (Cassandra, partition by swiping_user_id)
                                         -> Push (APNS / FCM) 通知先滑的人
```
1. **Profile**：標準 client-server-DB。
2. **Feed（初版）**：SQL `WHERE age BETWEEN ... AND lat/long BETWEEN ...`，原文自己點明這很慢，留給 deep dive。
3. **Swipe**：獨立 Swipe Service + Swipe DB。理由：swipe 寫入遠多於 profile 變更，需獨立擴展；資料量大且偏寫入，適合 Cassandra（CommitLog + Memtable + SSTable）。以 swiping_user_id 為 partition key，「A 是否滑過 B」落在單一 partition。代價：eventual consistency（deep dive 處理）。
4. **Match 通知**：後滑的 B 立即在回應看到「You matched!」；先滑的 A 可能是數週前，改用 APNS / FCM push。流程：A 過去右滑 B 並持久化 -> B 右滑 A -> server 查到反向 swipe -> 顯示給 B + push 給 A。

## Deep Dives

### DD1：Swipe 一致性與低延遲
**失敗情境**：A、B 同時右滑 -> 兩邊各自查反向 swipe 都沒有 -> 然後各自寫入 -> 兩人都沒收到 match。

原文補充：也可不要 strong consistency，改 availability，用定期對帳 job 找出漏掉的 mutual swipe 並通知雙方（他們會以為對方剛滑）。是值得討論的取捨，但面試官多半會要求你選 consistency。

- 爛解：**DB polling** 找互相右滑。延遲高、沒有即時回饋（失去「立即 match」的體驗）、輪詢造成 DB 負載。
- 好解：**Transaction**（寫入與檢查反向 swipe 同一個 transaction）。Cassandra 只有 LWT（Paxos，僅限單一 partition，無跨 partition 原子性、無 rollback，且多輪來回有效能開銷）。問題：以 swiping_user 分 partition，雙方 swipe 在不同 partition，跨 partition 不支援。
- 最佳解 A：**Sharded Cassandra + 單 partition transaction**
  - Partition key = `user_pair`（兩個 ID 排序後 `smaller:larger`），clustering key = (from_user, to_user)。
  - A->B 與 B->A 落在同一 partition，用 batch 在該 partition 內「寫入 + 讀對方」。
  - 取捨：同一對 user 的歷史累積使 partition 變大；活躍 user 造成 hot partition；需要清理 / 封存策略。
- 最佳解 B（原文最終偏好）：**Redis 原子操作 + Cassandra 當 durable storage**
  - Key = `swipes:{smaller_id}:{larger_id}`，Value 是 hash：`{<id>_swipe: right/left, ...}`。
  - Lua script：`HSET` 寫自己的 swipe，再 `HGET` 對方的 swipe，同一個原子步驟。若自己是 right 且對方是 right -> `create_match`。
  - 用 consistent hashing 讓同一對 key 落在同一 shard，水平擴展。
  - 取捨：要管 Redis cluster（節點故障、ring rebalance）；記憶體管理。但因 Cassandra 是 durable 層，Redis 可積極 expire，定期 flush 到 Cassandra，只留近期 swipe。Redis 資料遺失的後果只是「很近期的 swipe 偵測不到 match」，使用者可再滑，歷史仍在 Cassandra。

### DD2：Feed / stack 低延遲
初版 SQL 無法達成 < 300ms（尤其地理查詢）。
- 好解：**索引型資料庫**（Elasticsearch / OpenSearch，含 geospatial index）做即時查詢。挑戰：主 DB 與搜尋索引同步，用 **CDC**；ES 偏讀取，更新量大時要 **batch** 寫入。
- 好解：**預先計算 + 快取** feed（背景 job）。挑戰：重度使用者會耗盡 cache；profile / 位置變動造成 stale；用完還是得跑昂貴 query。
- 最佳解：**兩者結合**。開 app 先給 cache 的 feed，快用完（例如剩幾張）時背景觸發刷新，由 ES 即時產生新的，使用者感覺 stack 無限。
- **如何避免 stale feed**：
  - cache 設嚴格 TTL（< 1 小時）並排程重算。
  - 只替近期活躍的使用者預先計算（warm cache）。
  - 可調參數：TTL、cache 的 profile 數、被預算的使用者範圍（原文強調：設計成可調參數，不用改邏輯就能調校）。
  - 使用者更改 filter、或位置大幅移動時，在背景觸發 feed 刷新。

### DD3：不重複顯示已滑過的 profile
- 爛解：feed builder 查 swipe DB 做 contains check。(1) 可用性優先的 DB 可能尚未同步到所有 replica，會漏掉剛滑的 (2) swipe 歷史很長時 contains 越來越貴。
- 好解：加 **client 端 cache**（保存最近 K 筆 swipe），過濾剛滑過但尚未落地的。理由：假設使用者單裝置，client 也是系統一部分；後端為了暫存「還沒落到所有 partition 的資料」而維護 cache 太貴。同時對「stack 快用完時再取新 feed」很有用（例如滑到 200 張的 ~150 張時預取，並過濾期間已滑過的）。仍有 swipe 歷史龐大的問題。
- 最佳解（原文稱略為 over-engineered 但合理）：針對歷史很大的使用者，建 **Bloom filter** 並 cache。只有 false positive（會誤以為滑過，因此少數人永遠不會被顯示），沒有 false negative（不會重複顯示）。錯誤率可調（與空間 trade-off）。挑戰：filter 要隨 swipe 更新，cache 掛了要重建，大規模下重建昂貴。

## 關鍵數字與 back-of-envelope
- 20M DAU；~100 swipes/user/day -> 2B swipes/day（原文另處用 200/day 得 4B/day，不一致）。
- 100 bytes/swipe -> 約 200GB/day。
- Feed 延遲目標 < 300ms；feed cache TTL < 1h（原文建議）。
- Cassandra LWT：Paxos、單 partition、多輪往返。

## 面試官期待
- **Mid（E4）**：定義 API 與資料模型，HLD 涵蓋 feed、swipe、match；不要求深入特定技術，但要設計出支援一般 + geo-spatial filter 的方案，以及避免重複顯示已滑 profile。
- **Senior（E5）**：快速帶過 HLD，深談高效 feed 生成與管理、如何確保 match 成功建立；主動說明 feed 取捨、知道可用哪種索引（geo index），知道 cache 何時 stale。
- **Staff+**：深入各主題，甚至轉向自己感興趣的方向；清楚講出方案取捨，把面試官當 peer。

## 可遷移的 pattern
1. **Co-locate 相關資料以得到單 partition 原子性**：把 (A,B) 的雙向事件用排序後的 pair key 放同一 shard。（類似：互相關注、好友請求、雙向 block）
2. **Redis Lua script 做 read-modify-write 原子操作 + 資料庫當 durable source**：快速一致層 + 持久層分工，Redis 可丟、可重建。
3. **選擇性一致性**：只在不能出錯的路徑（match）用 strong consistency，其他（feed）接受 stale / eventual。
4. **預先計算 + 即時索引查詢混合**，並用 TTL、活躍度、閾值當可調旋鈕。
5. **Bloom filter 去重**：已看過 / 已處理過的大集合，接受 false positive、零 false negative。

## 常見追問
- **為什麼不直接用 Cassandra LWT？** 只支援單 partition；以 swiping_user 分 partition 時雙向 swipe 在不同 partition。需改以 user_pair 為 partition key，但會有 partition 成長與 hot partition 問題。
- **Redis 掛了會漏 match 嗎？** 只會漏掉很近期尚在 Redis 的 swipe；歷史在 Cassandra，使用者可再滑；也可用對帳 job 補（原文提到對帳作為 availability 優先的替代方案）。
- **Feed 為什麼會 stale？怎麼處理？** 對方改位置 / profile，或自己改 filter / 位置；用短 TTL、背景重算、只 warm 活躍使用者、事件觸發刷新。
- **Bloom filter 的代價？** 有 false positive，少數 profile 永遠不被顯示；需要維護與重建。
- **先滑的人如何得知 match？** 後滑者在 swipe 回應立即看到；先滑者透過 APNS / FCM push。
