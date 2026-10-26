# FB News Feed
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/fb-news-feed ｜ 難度：medium ｜ 類別：Scaling Reads（作者 Stefan Mai）

## 一句話核心
經典 fan-out 題：naive 的 fan-out on read（查 Follow → 查各人 Post → 排序）在追蹤很多人時會爆；改為 fan-out on write 預先計算 PrecomputedFeed（每人只存約 200 個 postId）；但對百萬追蹤者的大帳號改成「per-account hybrid」——不預算，讀取時再 merge；最後用「replicated（非 sharded）Post cache」解 viral post 的 hot key。

## 需求
**Functional（Core）**
- 建立 post
- friend/follow 其他人（本題採單向 follow，不是雙向 friend）
- 依時間倒序（最新在前）檢視所追蹤者的 feed
- 可分頁瀏覽 feed

**Out of scope**：like / comment、私人或受限可見度的 post

假設使用者已驗證，user ID 在 session 或 JWT。

**Non-functional（Core）**
- 高可用（availability > consistency），可容忍最多 1 分鐘的 post 延遲（eventual consistency）
- 發文與看 feed 都要快，< 500ms
- 可處理海量使用者（2B）
- 可追蹤無限多人、可被無限多人追蹤

原文強調：NFR 要量化，「單位數毫秒」與「一秒內」的系統架構截然不同。

## Core Entities & API
**Entities**：User、Follow（使用者間的單向連結，獨立成 entity）、Post。

**API**
```
POST /posts                    { content: {} }  -> { postId }
PUT  /users/[id]/follow        {}               -> 200   (PUT 保證 idempotent；取消追蹤用 DELETE，out of scope)
GET  /feed?pageSize={size}&cursor={timestamp?}  -> { items: Post[], nextCursor }
```
- Content 留空以容納 rich content；auth token 在 header，不深究。
- cursor 用 timestamp，代表使用者已看過最舊的那筆，下一頁回傳比它更舊的 N 筆。
- 原文提醒：資深者要把時間花在有趣的部分，「I'll come back if I have time for this」是好策略。

## High-Level Design
```
Client -> API GW/LB -> Post Service   -> Post table (DynamoDB)  [GSI: creatorId + createdAt]
                    -> Follow Service -> Follow table (PK userFollowing, SK userFollowed; GSI 反向)
                    -> Feed Service   -> 讀 Follow + Post(GSI) -> 排序
```
1. **建立 post**：水平擴展的 stateless service 在 API gateway/LB 後，寫入 DynamoDB（任何 KV 皆可，DynamoDB 簡單可擴展，前提是負載均勻分散在 partition）。
2. **follow**：多對多關係，可用 graph DB（Neo4j），但只做簡單查詢，用 KV 自己建模即可，避免「怎麼擴展 Neo4j」的問題。Follow 表：partition key = userFollowing，sort key = userFollowed；GSI 反向（PK userFollowed，SK userFollowing）。查詢：是否追蹤（PK+SK 查找）、我追蹤誰（PK range query）、誰追蹤我（GSI range query）。原文用獨立 table 方便講解，並註明 AWS 建議 DynamoDB single-table design。
3. **看 feed（naive）**：獨立 Feed Service（讀多、查詢型態不同）。Post table 加 GSI（PK creatorId，SK createdAt）。流程：取追蹤清單 → 取各人 posts → 依時間排序回傳。要立刻口頭點出警訊：追蹤很多人、每人很多 post、總集合很大。原文：先承認不可擴展，完成功能廣度再深入，常見失敗是在細節裡迷路。
4. **分頁**：以「已看最舊 timestamp」當 cursor，直接用 Post GSI 取更舊的 posts，其餘流程相同。

## Deep Dives

### 1) 追蹤很多人的使用者怎麼處理？
- 問題：先查 Follow 再對每個被追蹤者查 Post，一次讀取扇出成大量請求，稱 **fan-out on read**。數十到數百個請求還常見，上千個對低延遲服務很罕見。
- 解法：**fan-out on write**，在建立 post 時預先計算。建立 **PrecomputedFeed** 表：key = userId，value = 倒序 postId 列表，限制小數量（約 200），不需 secondary index。
- 產品面也是選項：問面試官能否調整產品，例如 Facebook 限制好友上限 5,000；追蹤 100k 人的使用者不太會在意貼文晚幾分鐘出現。
- 翻很深的頁：多數系統根本不支援（Google 翻幾十頁就沒了）。200 這個數字可依成本調整；需要更多內容時可退回 naive 的 Follow + Post 查詢。
- 儲存估算：postId 10 bytes × 200 = 2KB/user；2B users → 4TB，很合理。經驗法則：算每個 user/tenant 的美元成本；2KB 一個月不到一分錢，Facebook 美國用戶每年約賺 $100。
- 新問題：大帳號發文要寫入數百萬筆 feed。

### 2) 追蹤者很多的帳號怎麼處理？
有 < 1 分鐘的窗口可以完成寫入（NFR 容忍）。
- **Bad：Blast the requests**。Post Service 一次對所有 feed 發寫入。連線數與延遲都撐不住；一台 host 寫數百萬筆、另一台閒置，負載不均、難擴展。
- **Good：Async workers + queue**。用 SQS（需 at-least-once 且高可擴展）。發文時丟 postId + creatorId，worker 查該 creator 所有 followers 並 prepend 到各自 feed。挑戰：大帳號 worker 工作量巨大；每個 queue 項目工作量差異極大（1M followers vs 1k followers），可能需拆分任務。
- **Great：Async workers + Hybrid feeds**。per-account 決定是否預算：像 Justin Bieber（9,000 萬+ followers）不寫入 followers 的 feed，在 Follow table 加旗標標示該 follow 不預算，worker 忽略這類請求。讀取時 Feed Service 取（部分）預算好的 feed，再 merge 這些未預算帳號的近期 posts。大多數使用者「兩者都做一點」。原則：不要 one-size-fits-all，針對不同問題組合不同解。取捨：Feed Service 讀取時要做 merge，運算變多；預算門檻可調。

### 3) Post 讀取不均（hot key）怎麼辦？
多數 post 只被讀幾天；大帳號的 post 在最初幾小時讀取量巨大。DynamoDB 需負載均勻分散在 keyspace，Post1 500 rps 而其他為 0 就是不均。Post 很少被編輯，這是好的前提。
- **Good：分散式 Post cache（大 keyspace）**。Redis，以 postId 為 key 均勻分散；長 TTL + LRU；編輯時 invalidate。可容納 N×M 的 posts。缺點：cache 本身有同樣的 hot key 問題，剛好有多個 viral post 的 shard 負載不均，其他 host 閒置，難擴展。
- **Great：Redundant（replicated）Post cache**。不分片，改成多個完整副本，LB 分流，每個 instance 都能服務任何 post，不需彼此協調。viral post 流量攤在 N 個 instance。代價：冷啟動時 N 個 instance 各自 miss，會有 N 次 DB 請求而非 1 次（遠小於無 cache 的數百萬次）；cache 能容納的不同 post 數較少，但 DynamoDB 本身能承受一些變動。

### Final Design
API GW/LB → Post / Follow / Feed Service；Post table（+GSI）、Follow table（+GSI）、PrecomputedFeed table；SQS + feed workers；Redundant Post cache；大帳號走 read-time merge。

## 關鍵數字與 back-of-envelope
- 2B users；可容忍 post 延遲 1 分鐘；API < 500ms
- PrecomputedFeed：~200 postIds/user × 10 bytes = 2KB/user；× 2B = 4TB
- Facebook 好友上限 5,000（原文舉例）
- 讀取扇出：數十到數百請求常見，上千罕見
- 大帳號例：Justin Bieber 9,000 萬+ followers

## 面試官期待
- **Mid-level**（80/20）：定義清楚 API 與資料模型，得到功能完整的 HLD；可有部分 Good 解，不需涵蓋所有 deep dive 的 scaling 邊角。
- **Senior**（60/40）：快速帶過 HLD，至少詳談 2 個 deep dive；知道處理 fan-out 的方法；迭代診斷效能瓶頸；主動點出 fanout 與效能問題。
- **Staff+**（40/60）：涵蓋全部 deep dive（及原文未列的）；主動發現系統問題並談效能調校。

## 可遷移的 pattern
1. **Fan-out on read vs write，per-account hybrid**：依發文者追蹤者數量決定預算與否（也適用通知、timeline、活動流）。
2. **預算結果只保留小視窗**：每人只存 ~200 筆 id，深層分頁退回 naive 查詢；用「使用者通常只看前幾筆」換取大幅成本節省。
3. **Async workers + queue 吸收寫入放大**：容忍輕微延遲（NFR 允許 eventual consistency）；注意工作量不均需拆任務。
4. **Replicated cache 解 hot key**：分片 cache 無法解單 key 熱點，改用多副本 + LB，以多幾次 cold miss 換 N 倍吞吐。
5. **先廣度後深度 + 先調整產品再調整技術**：先做出完整 naive 方案並口頭標出瓶頸；問能否用產品限制（上限、延遲）縮小問題。

## 常見追問
- **為什麼不用 graph DB？** 只需簡單查詢，不需要 traversal，KV 自建就夠，避免 Neo4j 擴展問題。
- **使用者翻到第 100 頁？** 多數系統不支援；200 筆上限可調，不夠時回退 naive 查詢。
- **名人發文如何不爆？** 不 fan-out on write，讀取時 merge 其近期 posts；門檻可調。
- **為什麼用 PUT 做 follow？** PUT idempotent，連點兩次不會失敗。
- **Redis 分片 cache 為何仍有 hot key？** viral post 只落在單一 shard；改成每個 instance 都能服務任何 post。
