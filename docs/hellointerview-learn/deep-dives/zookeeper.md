# ZooKeeper
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/zookeeper ｜ 分類：deep-dives

## 一句話重點
ZooKeeper 以 ZNode 階層樹 + watch + ZAB 共識提供強一致的小型協調服務（config、service discovery、leader election、lock）；是資料量小、讀多寫少的「協調資料」儲存，不是通用資料庫，且新系統常被 etcd / Raft 內建取代。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：協調分散式系統很難——如何讓數十、數百台伺服器協作：選 leader、維護一致設定、偵測故障。ZooKeeper 2008 年釋出、已老，出現許多替代品，但在 Apache 生態系仍居核心。學習它能理解通用的分散式問題，核心是三個簡單 primitive：階層命名空間、資料節點、watch。以聊天應用為 Motivating Example：單機時 Alice 傳訊給 Bob 都在同一台伺服器記憶體內，不需協調；擴成多台後需知道使用者在哪台。

章節標題（原文）：
- A Motivating Example
- ZooKeeper Basics：Data Model: ZNodes / Server Roles and Ensemble / Watches
- Key Capabilities：Configuration Management / Service Discovery / Leader Election / Distributed Locks
- How ZooKeeper Works：Consensus with ZAB / Strong Consistency Guarantees / Read and Write Operations / Sessions and Connection Management / Storage Architecture / Handling Failures
- ZooKeeper in the Modern World：Current Usage in Major Distributed Systems / Alternatives to Consider / Limitations / So when should you use ZooKeeper then?（Smart Routing、Certain Infrastructure Design Problems、Durable Distributed Locks）
- Summary / References

## 內容（by agents）
### A Motivating Example（by agents）
聊天 app 多機後：需要「user → server」映射（service/路由發現）、server 上下線（偵測）、設定一致、單一 leader 做維運任務。直接用 DB 輪詢太慢且無事件通知；自己做共識很難 → 用 ZooKeeper。見 [whatsapp](../../hellointerview-breakdowns/whatsapp.md)。

### ZooKeeper Basics（by agents）
- **ZNodes**：類似檔案系統路徑的樹（`/app/config`、`/app/workers/w1`）。節點可存小資料（預設上限約 1 MB，建議遠小於此）。類型：persistent、ephemeral（session 結束自動刪除）、sequential（自動附單調遞增序號）、container/TTL。
- **Server Roles and Ensemble**：ensemble 為奇數台（3/5/7），一個 leader + followers（+ 可選 observers 擴讀不參與投票）。需 majority quorum 存活（3 台容忍 1 故障、5 台容忍 2）。
- **Watches**：client 對節點讀取時註冊一次性 watch，變更時收到通知（需重新註冊）；避免輪詢。保證：client 先收到 watch 事件再看到新資料。

### Key Capabilities（by agents）
- **Configuration Management**：設定寫在 znode，服務 watch 變動即時重載；因強一致，所有人最終看到同一版本。
- **Service Discovery**：服務啟動時建立 ephemeral znode 註冊自己；掛掉 session 過期節點消失；client 列出 children 並 watch。
- **Leader Election**：每個候選建立 ephemeral+sequential 節點，序號最小者為 leader，其餘 watch 前一個節點（避免 herd effect）；leader 死亡則次小者接任。
- **Distributed Locks**：同樣用 ephemeral sequential；持有最小序號者持鎖，釋放即刪節點。注意：session 過期＝鎖自動釋放，但 GC pause/網路分區下舊持有者可能仍以為持鎖 → 需 fencing token（用 zxid 或節點版本）。

### How ZooKeeper Works（by agents）
- **Consensus with ZAB**（ZooKeeper Atomic Broadcast）：所有寫入轉給 leader，leader 提出 proposal（帶遞增 zxid = epoch+counter），多數 follower ack 後 commit。Leader 失效 → 選舉（最新 zxid 勝出）→ 同步 → 恢復廣播。與 Raft 概念相近。
- **Strong Consistency Guarantees**：寫入 linearizable；單一 client 的請求 FIFO 順序；讀取為 sequentially consistent（follower 讀可能落後）。需要最新值時用 `sync()` 再讀。
- **Read and Write Operations**：讀可由任一 server 處理（可水平擴展讀）；寫需 quorum，吞吐不隨機器數增加反而略降。
- **Sessions and Connection Management**：client 與 server 維持 session，靠 heartbeat 與 session timeout（常見數秒～數十秒）；斷線時可重連到其他 server 維持 session；逾時則 ephemeral 節點被清除。
- **Storage Architecture**：記憶體保存完整資料樹（所以資料量要小）；寫入先寫 transaction log（建議專用磁碟、fsync），定期 snapshot。重啟時載入 snapshot + 重放 log。
- **Handling Failures**：少數節點掛 → 照常服務；follower 掛 → 其上 client 重連；leader 掛 → 重新選舉（通常秒級，期間無法寫）；失去 quorum → 停止服務（選 CP）。網路分區時少數側無法服務。

### ZooKeeper in the Modern World（by agents）
- **Current Usage**：Kafka（傳統模式用於 controller 選舉與 metadata，KRaft 模式已取代，Kafka 4.0 移除 ZK）、HBase、Hadoop/YARN HA、Solr、ClickHouse Keeper（相容替代）、早期 Flink HA（亦可用 K8s）。
- **Alternatives**：etcd（Raft，Kubernetes 的後端）、Consul（服務發現＋KV）、Raft 內建（KRaft）、雲端託管（DynamoDB conditional writes / Redis redlock 做簡單鎖）。
- **Limitations**：運維複雜（JVM、ensemble、session timeout 調校）；資料必須小；寫吞吐有限；不適合大量短暫 key；watch 一次性、有 herd effect 風險；client API 低階，容易寫錯（建議用 Curator）。
- **So when should you use ZooKeeper then?**
  - **Smart Routing**：需強一致的「誰負責哪個 shard／partition」映射，客戶端根據 ZK 直接路由（如 Kafka 舊版、分片資料庫的 shard map）。
  - **Certain Infrastructure Design Problems**：在已使用 ZK 的 Apache 生態系中（HBase、Kafka 舊版），或要自建需要 leader election/成員管理的基礎設施元件。
  - **Durable Distributed Locks**：需要高正確性（搭配 fencing）的鎖；若只是效率型鎖，Redis 即可。見 [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)。
  - 面試回答：多數情況直接說「用 etcd/ZK 這類 CP 協調服務」即可；新設計不必強調 ZK 本身。

### Summary（by agents）
ZK = 小而強一致的協調核心。學到的通用概念：quorum、leader/follower、ephemeral 節點＝存活偵測、watch＝變更通知、fencing token。

## 關鍵數字（by agents，附來源）
- ensemble 建議 3 或 5 台（ZooKeeper 官方 Admin Guide）；3 台容忍 1 台、5 台容忍 2 台故障。
- znode 預設資料上限約 1 MB（`jute.maxbuffer`，官方 Admin Guide）。
- 讀吞吐可達 數萬～十萬 ops/s 量級、寫則為數千～萬級（ZooKeeper 官方 Performance 頁，3 台 ensemble、讀寫比例決定；請以官方圖表為準）。
- 典型 session timeout：數秒～數十秒（tickTime 預設 2000 ms，session timeout 介於 2×~20× tickTime）。

## 相關題目
- [job-scheduler](../../hellointerview-breakdowns/job-scheduler.md)（leader election、鎖）
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)（成員管理／shard map）
- [whatsapp](../../hellointerview-breakdowns/whatsapp.md)（user → server 路由）
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（分散式鎖／seat hold 對照）

## 自測問題（by agents）
1. 為何 ensemble 用奇數台？答：多數決，偶數台不增加容錯（4 台仍只容忍 1）。
2. Ephemeral sequential 節點如何做 leader election？答：序號最小者為 leader，其餘 watch 前一節點，故障時遞補。
3. ZK 的讀一定是最新的嗎？答：不一定，follower 讀可能落後；用 sync() 取得最新。
4. 為何分散式鎖需 fencing token？答：session 過期或 GC pause 下舊持有者可能仍在寫入，用單調遞增 token 讓下游拒絕舊請求。
5. 為何新系統少選 ZK？答：運維複雜、資料量限制；etcd/KRaft/Consul 更貼近需求。

## 參考來源
- ZooKeeper Programmer's Guide / Admin Guide: https://zookeeper.apache.org/doc/current/
- ZooKeeper Recipes and Solutions (leader election, locks): https://zookeeper.apache.org/doc/current/recipes.html
- Junqueira et al., ZAB / Zab: High-performance broadcast for primary-backup systems (2011)
- Kleppmann, "How to do distributed locking" (fencing tokens): https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
- KIP-833 / Kafka KRaft（取代 ZooKeeper）: https://kafka.apache.org/documentation/#kraft
（以上引用自既有知識；2026-10-19 已確認連結可開啟（HTTP 200），內容未逐條比對。）
