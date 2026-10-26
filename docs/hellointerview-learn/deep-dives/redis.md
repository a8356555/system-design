# Redis
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/redis ｜ 分類：deep-dives

## 一句話重點
Redis 是單執行緒、全記憶體的 data structure store：因為「一次一個 command」所以原子且好推理，因為「key 就是 sharding 單位」所以 key 設計 = 擴展設計；但它不是 system of record（async replication + 持久化視窗會丟寫入）。

## 它是什麼 / 核心機制

### 基本模型
- C 寫的 data structure store；全在記憶體，單執行緒依序執行 command（新版把 I/O 與背景工作移到其他 thread，心智模型仍是「一次一個、依序」）。不需 lock，簡單操作下單核很少是瓶頸。
- 所有物件 = 某個 string key 對應的 value，資料結構住在 value 裡。
- 資料結構：Strings、Hashes、Lists、Sets、Sorted Sets（priority queue）、Streams（append-only log）、Geospatial。Redis 8 把 Bloom filter、JSON、time series 內建（舊版靠 Redis Stack module）。
- 通訊模式：Pub/Sub、Streams，部分取代 Kafka / SNS/SQS。
- Wire protocol 為 RESP；例：SET/GET/INCR/XADD；Set 有 SADD/SCARD/SMEMBERS/SISMEMBER。

### 持久化（不保證的部分）
- RDB：週期性 snapshot，crash 會丟掉上次 snapshot 之後的所有資料。
- AOF：記錄每次寫入，但預設每秒 fsync 一次 → crash 最多丟約 1 秒已 ack 的寫入。可設每次寫入 fsync，但少有人這麼做（失去速度）。
- 因此沒有關聯式 DB 預設的 commit-on-disk 保證。AWS MemoryDB 等替代品犧牲一點速度換真正的磁碟持久性。

### 部署型態與 Cluster
- 單節點 / 單節點 + HA replica / cluster。
- Cluster：每個 key hash 到 16,384 個 hash slot 之一，slot 分配給節點（= sharding）；client 快取 slot→node map，自己算 slot 直連節點。加節點時 slot（與其中的 key）遷移過去。
- 節點間用 gossip protocol 共享 cluster state；問錯節點會得到 MOVED 回應（節點不會代為轉發）；client 收到 MOVED 後刷新 map（如 CLUSTER SHARDS）。
- Replication 是非同步：primary 先 ack 寫入、replica 還沒收到；primary 掛掉 replica 被 promote 時，最後一批已 ack 的寫入可能消失。這是 Redis 不能當 system of record 的最深層原因，也影響 lock。
- Replica 用於讀：cluster mode 下 client 發 READONLY 才能讀 replica（client library 多半有 flag）；非 cluster 直接把讀流量指向 replica。讀到的資料落後 replication lag。
- Cluster 沒有 query router：不會跨節點拆分/合併請求；除少數例外，一個 command 所需資料必須在同一節點，否則直接報錯而非變慢。→ 擴展方式 = 設計 key。
- Hash tag：只 hash `{}` 內部分，`{user:123}:posts` 與 `{user:123}:likes` 落在同一 slot，可做 MULTI transaction。

### 效能
- 單節點約 100k writes/sec；command 本身微秒級，經網路亞毫秒級讀取。
- N+1 在 SQL 是災難，在 Redis 因單次微秒級且可 pipeline / MGET（一次 round trip）而可承受（仍應避免）。

## 何時用 / 何時不用
**可用的 use case（Capabilities）**
- Cache：cache key = Redis key；TTL 保證過期後不會讀到舊值。TTL 處理 staleness、不處理 memory pressure：預設記憶體滿時 Redis 拒絕寫入，cache 要設 eviction policy（如 allkeys-lru，以 sampling 近似 LRU）。
- Distributed lock、Leaderboard（sorted set）、Rate limiting、Proximity search（GEO）、Event sourcing / work queue（Streams）、Pub/Sub。

**不要用**
- 當 system of record（async replication + 持久化視窗 → 已 ack 寫入可能消失）。
- 工作集無法經濟地放進 RAM（記憶體是最貴的儲存位置）。
- 需要查詢彈性：無 join、無跨 key 查詢；cluster 下多 key 操作只能在單一 slot（hash tag 例外）。
- 需要長 retention、多獨立 consumer 可 replay 的 durable stream → Kafka。

## 面試常考的進階點

### Distributed Lock
- 取得：`SET lock:concert:343 my-token NX EX 30`。NX = 不存在才成功；EX 30 = 30 秒過期防 crash 後永久佔用；token = 隨機唯一值。
- 釋放不能直接 DEL（lock 可能已過期被別人拿走，盲刪會刪掉別人的鎖）：用 Lua script 檢查 token 相符才 DEL（整個 script 在單 thread 上當一個 command 執行 → 原子）。
- 這是 pessimistic locking（先拿鎖再做事）；Redis 也支援 optimistic：WATCH + MULTI/EXEC，被 watch 的 key 變動則 transaction abort。
- 失效模式：async replication → primary 剛授予 lock 就掛掉，promoted replica 不知道此鎖，會把同一把鎖給別人。
- Redlock：在多數獨立 Redis 節點上取鎖來對抗此問題，但有爭議：暫停/緩慢的 client 在 lock 過期後仍可能行動（Martin Kleppmann 的批評）。標準防禦是 fencing token（每次授鎖給遞增數字，storage 層拒絕舊 token 的寫入）；Redis 本身不提供。
- 結論：Redis lock 是「偶爾會失效的效率工具」而非正確性保證。若 stale holder 會破壞資料 → 把 invariant 放在資料所在處，或用 ZooKeeper / etcd 等 consensus 系統。實務上 `SELECT ... FOR UPDATE` 或 `UPDATE ... WHERE version = X` 常可取代 distributed lock。

### Leaderboard（Sorted Set）
- log 時間查詢排序資料。Post Search 例：`ZADD tiger_posts 500 "SomeId1"`，用 `ZREMRANGEBYRANK tiger_posts 0 -6` 只留 top 5（負 index 從最高排名算）。ZADD 對已存在 member 會更新 score → 重新加入即改排名。

### Rate Limiting
- Fixed window：INCR 當前 window 的 counter，超過 N 回 429 + Retry-After。
- 細節：只在 INCR 回傳 1（window 第一個請求）時設 expiry；每次都 EXPIRE 會讓持續流量永遠不重置 window。INCR+EXPIRE 要用 Lua script 合併，否則兩者之間 crash 會留下永不重置的 counter。
- Sliding window：每 user 一個 sorted set，score = timestamp；ZREMRANGEBYSCORE 清舊 → ZCARD 計數 → 未超過則 ZADD；用 Lua script 原子化。

### Proximity Search
- GEOADD / GEOSEARCH（FROMLONLAT … BYRADIUS）。複雜度 O(N + log(M))：底層是 geohash 存在 sorted set；N = grid-aligned 方形 bounding box 內的候選數，M = 實際落在半徑內的數量；先 seek（log）取候選，再二次過濾為精確半徑。

### Streams / Event Sourcing / Work Queue
- Append-only log，類似 Kafka topic；XADD 寫入，consumer group（XREADGROUP、XCLAIM / XAUTOCLAIM）協調誰處理哪個 item。
- Work queue：worker 讀 → 處理 → ack；consumer group 追蹤 pending 與 idle time；worker 掛掉則 idle time 上升，其他 worker XCLAIM 接手重做。無法區分慢與死 → item 可能被處理兩次 → 處理要 idempotent。
- Durable 程度取決於持久化設定（預設 crash 可能丟最近 entry）。
- Redis streams 適合：已有 Redis、queue 規模不大（背景 job、通知 fan-out、工作分配）。Kafka 適合：長 retention、多獨立 consumer replay、不容許丟訊息的規模。

### Pub/Sub
- 即時廣播給「當下在聽的人」；at-most-once、不持久化：subscriber 離線就錯過。需要持久/replay → Streams 或 Kafka/RabbitMQ，或 Pub/Sub 搭配 queue（SNS→SQS、Kafka）或 outbox pattern。
- 常被誤傳的限制已過時：舊版 cluster Pub/Sub 把每則訊息廣播到每個節點，加節點不加容量；Redis 7 起 sharded Pub/Sub（SPUBLISH / SSUBSCRIBE）把 channel hash 到 slot 擁有者，容量隨 cluster 擴展。
- Channel 只是名字，不需建立；連線開銷是 per node 而非 per channel（一個連線收所有訂閱的 channel）；最後一個 subscriber 斷線後 channel 從記憶體移除，之後 publish 直接丟棄。
- 自己用 key 存 subscriber server 地址做 Pub/Sub：hop 多一跳（3 vs 2），且最後一跳常需新建 TCP 連線；還要 heartbeat/TTL 清除死掉的 server，複雜度高。結論：「use case 像 Pub/Sub 就用 Pub/Sub」。

### Hot Key
- 例：100 節點 cache，單一商品流量暴增到與其餘總和相當 → 該節點過載。
- 對策：
  1. Client-side caching：app server 記憶體快取最熱 key；代價是多一層 cache 的 staleness（最多一個 TTL），適合短 TTL + 少量 key。
  2. Key copies：`product:123:1`…`:10` 分散到不同節點，reader 隨機選後綴；需維護熱 key 清單，每次寫入要 fan-out 到所有副本。
  3. Read replicas：放大讀容量；但 cluster client 預設讀 primary，要設定才會用 replica；且對 write-hot key 無效（寫入仍都落在擁有該 slot 的 primary）。
- 評分：能辨識 hot key (+)，主動設計補救 (++)。相關 pattern：Scaling Reads / Scaling Writes。

## 關鍵數字
- 單節點約 100k writes/sec；command 微秒級；網路讀取亞毫秒。
- 16,384 hash slots。
- AOF 預設每 1 秒 fsync（最多丟約 1 秒）。
- 範例：lock TTL 30 秒；Geohash 在 Redis 為 52-bit 整數（見 proximity-search）。

## 相關題目
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（distributed lock）
- [Uber](../../hellointerview-breakdowns/uber.md)（lock、GEO）
- [Distributed Rate Limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)
- [Distributed Cache](../../hellointerview-breakdowns/distributed-cache.md)
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)（sorted set）
- [Top-K](../../hellointerview-breakdowns/top-k.md)

## 自測問題
1. 為什麼 Redis 單執行緒還這麼快、又好推理？
   答：全記憶體、command 微秒級，一次執行一個 command 不需 lock，單核很少是瓶頸；原子性來自依序執行（含 Lua script）。
2. Redis lock 的釋放為何要用 Lua script？它仍有什麼失效模式？
   答：要檢查 token 再 DEL 才不會刪掉別人（過期後被重取）的鎖，Lua 讓檢查+刪除原子。失效：async replication 下 failover 後新 primary 不知道鎖；暫停的 client 過期後仍動作。需 fencing token 或改用資料層（FOR UPDATE / version）/ ZooKeeper / etcd。
3. Cluster 中想對兩個 key 做 MULTI transaction 怎麼辦？
   答：用 hash tag（`{user:123}:posts`、`{user:123}:likes`）讓它們落在同一 slot。
4. Hot key 有哪三種對策？各自陷阱？
   答：client-side cache（staleness ≤ TTL）、key copies（需維護熱 key 清單，寫入要 fan-out）、read replicas（需 client 設定 replica read；對 write-hot key 無效）。
5. Pub/Sub 與 Streams 怎麼選？
   答：Pub/Sub at-most-once、不持久，只送給當下在線者；需要離線補收、ack、replay 就用 Streams（或 Kafka）。量大且需長 retention/replay → Kafka。
