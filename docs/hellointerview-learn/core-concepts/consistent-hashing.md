# Consistent Hashing
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/consistent-hashing ｜ 分類：core-concepts

## 一句話重點
Consistent hashing 把資料與節點都放在 hash ring 上、順時鐘找第一個節點，讓增減節點時只需搬移一小部分資料；搭配 virtual nodes 平衡負載。多數面試只要說「DynamoDB/Cassandra 底層用它」，只有設計 distributed DB / cache / message broker 才需深入。

## 核心內容

### 動機範例：Ticketmaster 的 sharding
- 起初單一 DB；平台成長後一台 DB 撐不住，要把資料分散到多個 DB（sharding）。
- 問題：怎麼知道某 event 該存哪個 DB instance？

### 第一次嘗試：Modulo hashing
- `database_id = hash(event_id) % number_of_databases`
- 例（3 個 DB）：Event #1234 → 1、#5678 → 0、#9012 → 2。
- **加節點的問題**：改成 `% 4` 後，幾乎所有 event 的歸屬都改變（#1234 從 DB1 變 DB0），不只新節點的資料，所有 DB 的資料都要搬，造成 DB 負載暴衝、使用者無法存取或變慢。
- **移除節點的問題**：DB 掛掉改成 `% 2`，同樣大規模重新分配。

### Consistent Hashing
- 把「資料」和「資料庫」排在一個環（hash ring）上。
- 步驟：
  1. 建立固定點數的 ring（示範用 100 點；實務通常 0 ~ 2^32 - 1）。
  2. 把 DB 節點放在 ring 上（4 個 DB：0、25、50、75）。
  3. 要找 event 存哪：hash event ID，在 ring 上找該位置，**順時鐘走到第一個 DB instance**。
- **加節點**：在位置 90 加 DB5 → 只有落在 75~90 的 event 要搬（原本去 DB1）；其他不動。原文計算：約搬 DB1 上 60%（15/25 範圍）的資料，約佔全部 15%。
- **移除節點**：DB2（位置 25）掛了 → 只有原屬 DB2 的資料搬到 DB3（位置 50）；其他不動。

### Virtual Nodes
- 問題：移除 DB2 後，DB2 的全部資料落到 DB3，DB3 負載變 DB1/DB4 的 2 倍。
- 解法：每個 DB 在 ring 上放多個點（hash "DB1-vn1"、"DB1-vn2"、"DB1-vn3"…），虛擬節點自然交錯分佈於環。
- DB2 掛掉時，DB2-vn1 的資料給 DB1、vn2 給 DB3、vn3 給 DB4… 負載平均分散到剩餘節點。vnode 越多越平均。
- 加節點時，新節點的 vnode 散布在環上，從多個既有節點各吸一小塊，而不只幫單一鄰居分擔，一開始叢集就較平衡。

### Hot Spots
- 即使 vnode 讓資料均勻，仍可能有 hot spot：某些 key 流量遠高於其他（Taylor Swift 演唱會的讀取量是一般 event 的 100x）。Consistent hashing 均勻分配的是 key，不是 traffic。
- 對策：
  - **Read replicas**：把熱門 key 複製到多節點並 load balance 讀取（最常見）。
  - **Key-space salting**：熱 key 加隨機後綴（`taylor-swift-{0..9}`）使其 hash 到不同節點，讀取時 scatter 後彙整。
  - **Adaptive rebalancing**：即時監控流量，把 key range 從過載節點移走；營運複雜，DynamoDB 等會自動做。
- 面試重點區分：**virtual nodes 防止結構性不平衡（key 分佈不均）；replication 與 salting 防止 workload 不平衡（流量不均）**。

### Data Movement in Practice
- Consistent hashing 只決定資料「該在哪」，不會憑空搬 TB 資料。
- 實務上多數分散式 DB 搭配 replication 處理故障而不搬資料：DynamoDB 每個 partition 複製到三個 AZ，primary 掛了以 Raft 等共識演算法提升 replica，不需搬資料；Cassandra 把資料複製到 ring 上連續 N 個節點，讀取可由倖存 replica 服務。
- 資料移動主要發生在計畫性成員變動（擴容、永久替換節點以恢復 replication factor），此時 consistent hashing 保證只需重新複製有界的一部分 key。

### 真實世界
- 適用任何要把資料分散到叢集的場景：DB、cache、message broker、app server。
- Apache Cassandra（ring 分散）、DynamoDB（partition placement）、CDN（決定哪個 edge server 快取特定內容）。
- **Redis Cluster 例外**：用固定 hash slot，16,384 slots，`CRC16(key) mod 16384`，把 slot 範圍分配給節點；較易推理，但 rebalance 需要更多協調。「consistent hashing vs fixed hash slots」是可討論的設計取捨。
- 術語被鬆散使用：Kleppmann（DDIA）指出有些號稱 consistent hashing 的系統其實是固定 slot 範圍的 hash partitioning；核心原則是「rebalance 時最小化資料移動」。

## 面試怎麼用
- 一般題：用 DynamoDB / Cassandra 等時，只需說「它們底層用 consistent hashing 處理擴縮」。
- 深入題：設計 distributed database / distributed cache / distributed message broker，需講清楚：
  - 為何勝過 modulo sharding；
  - virtual nodes 如何平衡負載；
  - 節點故障與新增的處理；
  - hot spot 成因與緩解（replication、key salting）；
  - consistent hashing 與 replication 的關係（容錯）。
- 陷阱：把 hot key 問題歸給 consistent hashing 解決；忘了 vnode；以為節點失效一定要搬 TB 資料（忽略 replication）；一般題花太多時間實作 hash ring。

## 關鍵數字
- Hash 空間通常 0 ~ 2^32 - 1。
- 加第 5 個節點範例：約搬全部資料的 ~15%（vs modulo 幾乎全搬）。
- Redis Cluster：16,384 slots，CRC16 mod 16384。
- DynamoDB：每個 partition 複製到三個 AZ。

## 相關題目
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（原文範例）
- [web-crawler](../../hellointerview-breakdowns/web-crawler.md)（分散 workload，補充）

## 自測問題
1. Modulo hashing 加節點為何災難？答：N 變動使幾乎所有 key 的歸屬改變，需大規模搬資料與負載暴增。
2. Consistent hashing 如何決定 key 的位置？答：hash key 後在環上順時鐘走到第一個節點。
3. Virtual nodes 解決什麼？答：移除/新增節點時負載只落到單一鄰居的不平衡；讓負載散到多個節點。
4. Virtual nodes 能解 hot key 嗎？答：不能；vnode 解結構性不均，hot key 需 replication、key salting 或 adaptive rebalancing。
5. Redis Cluster 與 consistent hashing 的差異？答：Redis 用 16,384 固定 hash slot（CRC16 mod 16384）分配給節點，簡單但 rebalance 需更多協調。
