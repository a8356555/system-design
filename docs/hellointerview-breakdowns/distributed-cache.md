# Distributed Cache
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/distributed-cache ｜ 難度：medium ｜ 類別：Scaling Reads ｜ 作者 Evan King

## 一句話核心
（原文）跨多台機器、記憶體內的 key-value 儲存，水平擴展並用 partition + replication 達成高可用；難點是擴展、key 分布均勻、熱 key（讀/寫）與效能。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- set / get / delete key-value
- 可設定 key 的過期時間（TTL）
- 依 LRU 淘汰資料
- Out of scope：用戶可設定 cache 大小
- 原文提醒：LRU 是假設，要向面試官確認；也可能是 LFU、FIFO、自訂策略

**Non-functional（原文）**
- 高可用，eventual consistency 可接受
- 低延遲：get/set < 10ms
- 可擴展至 1TB 資料、peak 100k requests/s
- Out of scope：durability、強一致、複雜查詢、transaction

## Core Entities & API
（原文僅標題；補充，非原文）
- Entity：Key-Value pair（key, value, ttl/expire_at）
- API：`GET /{key}`、`PUT /{key} {value, ttl}`、`DELETE /{key}`

## High-Level Design
（原文僅有三個需求的標題；補充，非原文）
1. 基本 KV：單機 hash table（O(1) get/set/delete）。
2. TTL：每筆存 expire_at；懶刪除（讀時檢查）+ 週期性取樣清掃（active expiry）。
3. LRU：hash map + doubly linked list，get/set 時把節點移到頭，滿了從尾端淘汰，所有操作 O(1)。
單機版先成立，再於 deep dives 擴展成叢集。

## Deep Dives（依原文大綱逐條）
### 1) 如何確保 cache 高可用與容錯？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：單節點、無備援，節點掛掉整份資料消失，所有請求打回 DB。
- 好解：每個 shard 做 primary-replica 非同步複製，primary 掛掉由 replica 提升（failover）。
- 最佳解：複製 + 自動 failover（Sentinel/Raft/Cluster gossip 偵測），客戶端或 proxy 能感知拓撲變更；複製採非同步以保延遲（可能丟最後幾筆寫入，cache 可接受）。可選跨 AZ 放置 replica。
- 取捨：同步複製更安全但增加寫延遲；本題 availability > consistency，選非同步。

### 2) 如何確保 cache 可擴展？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：單機垂直擴展，容量與 QPS 有上限（1TB / 100k rps 單機吃力）。
- 好解：Hash partition，`node = hash(key) % N`；但增減節點時幾乎全部 key 重新映射，造成大量 cache miss。
- 最佳解：Consistent hashing（含 virtual nodes）；增減節點只搬移約 1/N 的 key。以 1TB 資料、每節點約 64GB 估算約 16-20 台（含 replica 加倍）。
- 取捨：由 client library、proxy 或 gossip 的 cluster-aware 節點來做路由；各有維運複雜度差異。

### 3) 如何確保 key 在節點間均勻分布？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：節點在環上單點，分布不均，某節點負擔過大。
- 好解：每個實體節點對應多個 virtual nodes（例如 100-200 個）攤平。
- 最佳解：virtual nodes + 使用良好雜湊（murmur/xxhash）；或固定 slot 數（如 Redis 16384 slots）再映射到節點，搬移以 slot 為單位，易於再平衡。
- 取捨：slot 方式再平衡簡單、可觀測；vnode 彈性較高但 metadata 較大。

### 4) 若有被大量讀取的熱 key 怎麼辦？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：忽略，單節點被打爆，成為瓶頸並連鎖失敗。
- 好解：為熱 key 增加 read replicas，讓讀請求分散到多個副本。
- 最佳解：客戶端本地 near cache（短 TTL）+ 熱 key 偵測（取樣計數）後自動複製成 `key#1..k` 多份，讀時隨機選一份。
- 取捨：本地快取/多副本會有短暫不一致；本題接受 eventual consistency。

### 5) 若有被大量寫入的熱 key 怎麼辦？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：所有寫入打同一 primary，序列化瓶頸。
- 好解：對計數類寫入做 sharding：把 key 拆成 `key:0..k`，寫入隨機落一個，讀時聚合。
- 最佳解：客戶端/proxy 端 write batching/合併（coalescing）+ sharded counter；若可容忍遺失，先在本地累積再定時 flush。
- 取捨：讀取需聚合多個 shard（讀放大）；合併寫入降低延遲壓力但增加資料遺失窗口。

### 6) 如何確保 cache 效能？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每請求新建連線、同步序列化重物件。
- 好解：連線池/持久連線、pipelining/批次請求、輕量序列化。
- 最佳解：單線程事件迴圈（避免鎖）+ 記憶體分配器優化（slab）+ 客戶端直連正確節點（避免多一跳）+ 壓縮大 value；記憶體淘汰採近似 LRU（取樣）降低 metadata 成本。
- 取捨：近似 LRU 省記憶體與 CPU，命中率略降；壓縮換 CPU。

## 關鍵數字與 back-of-envelope
- 1TB / 約 64GB 每節點 ≈ 16 台 primary（×2 加 replica ≈ 32 台）。
- 100k rps / 16 台 ≈ 6k rps/台，遠低於單機能力（Redis 可達數十萬 ops/s），容量才是主約束而非 QPS。
- 延遲預算 <10ms：同 AZ 網路 RTT ~0.5ms，記憶體操作微秒級，有大量餘裕。

## 可遷移的 pattern（3-5 條）
1. Consistent hashing + virtual nodes / slots 做可再平衡的分片。
2. Primary-replica 非同步複製 + 自動 failover，以可用性換一致性。
3. 熱 key：讀 -> 多副本/本地快取；寫 -> key splitting + sharded counter。
4. LRU = HashMap + Doubly Linked List（O(1)）；TTL = 懶刪除 + 取樣清掃。
5. 先確認是 cache 還是 store（durability 需求）再決定架構。

## 常見追問（3-5 題，附簡短答案）
- Cache stampede 怎麼辦？single-flight/互斥鎖、TTL 加 jitter、提前刷新。
- 如何做 cache-aside vs write-through？cache-aside 簡單通用；write-through 一致性高但寫延遲高。
- 節點新增時如何避免冷啟動？以 slot 逐步遷移、預熱或雙寫。
- 需要持久化怎麼辦？AOF/snapshot（RDB），代價是延遲與複雜度。
- 為何不用強一致？cache 本是加速層，miss 可回源，強一致代價高。
