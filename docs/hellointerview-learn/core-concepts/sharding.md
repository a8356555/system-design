# Sharding
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/sharding ｜ 分類：core-concepts

## 一句話重點
單機 DB 撐不住時才 shard：依 access pattern 選高 cardinality、分佈均勻的 shard key，預設 hash-based（搭配 consistent hashing），並設計避開 cross-shard query 與 cross-shard transaction。最常見的錯誤是還沒算數字就先 shard。

## 核心內容

### 為什麼 shard
- 先 vertical scale（更大的機器），但終會碰到天花板：查詢變慢、寫入成為瓶頸、儲存接近上限。連 Amazon Aurora 也大約在 256 TiB 封頂。
- 唯一真正的出路：把資料分散到多台機器 = sharding。
- Partitioning vs sharding：partitioning 通常指在**單一** DB instance 內切分；sharding 是跨**多台機器**切分。實務上常混用，不用糾結，只要說清楚資料在一台還是多台。

### Partitioning（先講清楚）
- 把大 table 切成小塊，仍在同一台 DB。例：orders 表 500M 列、2 TB，查上個月訂單要掃全表，index 巨大難維護，vacuum / analyze / rebuild index 可能鎖整張表。分 partition 後只掃相關 partition。
- **Horizontal partitioning**：切 rows（如每年一個 partition），欄位相同、列變少。
- **Vertical partitioning**：切 columns（常用欄位一塊、大或少用欄位一塊），列相同、欄位變少。

### Sharding 定義
- Sharding = 跨多台機器的 horizontal partitioning。每個 shard 是獨立 DB，有自己的 CPU、memory、storage、connection pool；沒有任何一台持有全部資料或承擔全部流量，儲存容量與讀寫吞吐隨 shard 數擴展。
- 新問題：選 shard key、query routing、避免 hotspot、資料成長時 rebalance。

### 怎麼 shard：兩個決定
- **What to shard by**（shard key）：用哪個欄位分組。
- **How to distribute**（策略）：用什麼規則把組指派到 shard。

### 選 Shard Key
壞 key 導致分佈不均、hot spot（一個 shard 被打爆、其他閒置）、query 必須打所有 shard。好 key 要：
- **High cardinality**：值很多。boolean 只有兩個值最多兩個 shard，無意義；user ID 有百萬級值。
- **Even distribution**：值均勻分佈。按 country shard 且 90% 用戶在美國 → 該 shard 巨大。User ID 通常分佈良好；creation timestamp 只有在新資料不會全堆在最新 shard 時才可行。
- **Aligns with queries**：最常見的 query 最好只打單一 shard。依 user_id shard，則「取使用者 profile」「取使用者訂單」只打一個 shard。

| 範例 | 評價 | 原因 |
|---|---|---|
| user_id（以使用者為中心的 app） | 好 | 高 cardinality、均勻，多數 query 本來就限定單一使用者 |
| order_id（電商 orders 表） | 好 | 高 cardinality，query 多半針對特定訂單，隨時間均勻分佈 |
| is_premium (boolean) | 壞 | 只有兩個值，一個 shard 裝全部免費用戶而過載 |
| created_at（成長中的表） | 壞 | 新寫入全進最新 shard，成寫入 hot spot，舊 shard 幾乎閒置 |

### Sharding Strategies
| 策略 | 做法 | 優點 | 缺點 / 適用 |
|---|---|---|---|
| **Range-based** | 連續值範圍分配（user 1–1M → shard 1，1M–2M → shard 2…） | 簡單；range scan 高效（user ID 500K–600K 只打一個 shard） | 真實 access pattern 通常不均：依 created_at 分，幾乎所有流量打最新 shard。適合不同使用者自然查詢不同範圍，如 multi-tenant SaaS（Company A 的 ID 範圍只被 A 查） |
| **Hash-based（預設）** | `shard = hash(user_id) % 4`，hash 打散資料 | 分佈均勻；新使用者平均分到各 shard；面試官預設你用這個 | 加減 shard 時 modulo 變動，幾乎所有資料換 shard（4→5）。解法：consistent hashing，需要有 resharding 計畫 |
| **Directory-based** | 查表（mapping table / service）決定位置 | 極度靈活：大流量使用者可移到專屬 shard；rebalance 只改 mapping；可實作複雜邏輯 | 每個 request 都要多一次 lookup（延遲）；directory 成為關鍵依賴 / SPOF（掛了即使資料 shard 健康整個系統也停擺）。面試很少是答案，會引來一堆追問 |

## Challenges of Sharding
### Hot Spots and Load Imbalance
- 即使 key 良好，某些 shard 仍可能流量遠高於其他，抵銷 sharding 的好處（單一過載 shard 成瓶頸）。
- **Celebrity problem**：依 user_id shard，Taylor Swift 的 shard 流量是一般的 1000x。hash 分佈無法解決，因為問題在於某些 key 本身更活躍。
- **Time-based sharding** 的 hot spot：所有新寫入打最新 shard，舊 shard 只處理歷史讀取。
- 偵測：監控 shard 的 query latency、CPU、request volume，某個 shard 持續偏高即 hot spot。
- 處理：
  - **Isolate hot keys 到專屬 shard**（如只放名人帳號）；這也是 directory-based 有用的情境，但不會一開始就用。
  - **Compound shard keys**：如 `hash(user_id + date)`，讓單一使用者的資料隨時間分散到多個 shard。
  - **Dynamic shard splitting**：資料庫自動分裂過大/過熱的 shard。MongoDB balancer 會 split 並遷移 range-based chunks（含 hashed shard key）；Vitess 支援 online resharding，但由 operator 發起、非自動。

### Cross-Shard Operations
- 需要多個 shard 資料的 query 很貴：要查多個 shard、等全部回應、自己彙整。例：依 user_id shard 時，「全站 top 10 熱門貼文」要送到全部 64 個 shard、等 64 個回應、合併，約 64x 網路呼叫與延遲。
- 無法完全消除，但可最小化：
  - **Cache 結果**：top 10 快取 5 分鐘；適合不要求即時準確（最終一致 OK）的 leaderboard、trending、aggregate stats。
  - **Denormalize** 讓相關資料同在一個 shard：把常一起查的貼文資訊存在使用者 shard。重複資料、更新更複雜，但常值得。
  - **接受罕見 query 的代價**：admin dashboard「全 shard 使用者總數」一天看幾次，慢可接受。
- 面試：若對常見 use case 說「查所有 shard 再彙整」，要停下來想：能 denormalize？能 cache？能用背景 job 預先計算？面試官預期你最小化 cross-shard query。

### Maintaining Consistency
- 單 DB 的 transaction 簡單（扣庫存+建訂單包在一個 transaction）。Sharding 後，帳戶在 shard 1、交易紀錄在 shard 2，就無法用單一 DB transaction。
- **2PC**（two-phase commit）：coordinator 請所有 shard prepare，等全部確認後 commit。保證一致但慢且脆弱；任一 shard 或 coordinator 中途失敗可能卡死。多數 production 系統避免。
- 替代方案：
  - **設計避開 cross-shard transaction**（最佳）：依 user_id shard，使用者的餘額、交易紀錄、profile 都放同一個 shard，全是單 shard transaction。
  - **Saga**：把操作拆成一連串獨立步驟，每步有補償動作；失敗則對先前步驟執行補償，獲得最終一致而不需 2PC。例：A 轉帳給不同 shard 的 B：(1) 扣 A 的錢 (shard 1) → (2) 加 B 的錢 (shard 2) → (2) 失敗則退款給 A（補償）。
  - **接受最終一致**：如 denormalized 的 follower count 各 shard 幾秒內不同，最終收斂。
- TLDR：多數應用可設計成完全避免 cross-shard transaction；若總是需要分散式交易，多半是 shard key 或 shard 邊界選錯。

## Sharding in Modern Databases
- 通常不會自己從頭實作。Cassandra、DynamoDB、MongoDB 讓你指定 partition key，其餘自動處理，但機制不同：
  - **Cassandra**：partitioner（如 Murmur3Partitioner）+ virtual nodes，一種 consistent hashing，把 partition key 映射到節點的 token range。
  - **DynamoDB**：hash partition key 路由到內部 partition，隨成長 split/merge；不是使用者可見的經典 ring 式 consistent hashing。
  - **MongoDB**：依 shard key 切 range-based chunks（用 hashed shard key 則 range 在 hash 空間）；背景 balancer 自動 split 與遷移 chunk；不是經典 consistent hashing。
- SQL 方面：Vitess、Citus 是在 MySQL / PostgreSQL 前的開源 sharding 層，處理 routing、cross-shard 操作、resharding；AWS Aurora、Google Cloud Spanner 提供內建 sharding 的分散式 SQL。
- 面試足夠說：「用 DynamoDB，user_id 當 partition key」或「用 Vitess 依 user_id shard，並規劃 operator 驅動的 online resharding」。

## 面試怎麼用
**何時提**：別過早 sharding，要先證明單機不夠。遇到容量規劃撞到極限時再提：
- Storage：「5 億用戶 × 5KB = 2.5TB，單台 Postgres 可以，但成長 10x 就要 shard。」
- Write throughput：「尖峰 50K writes/s，單台 DB 吃力，需要 shard。」
- Read throughput：「即使有 read replicas，100M DAU 每人多次 query，需要把讀取分散到 shard。」
- 公式：找出瓶頸 → 說明單 DB 為何擴展不了 → 提出 sharding。可參考 Numbers to Know。原文稱「第一名的 sharding 錯誤」就是還沒證明必要就先 shard。

**怎麼說（四步，社群 app 例）**
1. 依 access pattern 提出 shard key：「多數 query 以使用者為中心（feed、貼文、followers、likes），所以依 user_id shard。」
2. 選分佈策略：「hash-based，搭配 consistent hashing，hash user_id 均勻分散。」
3. 講取捨：「全域 query（trending posts）要查所有 shard；用 cache 與背景 job 預先計算來處理。」
4. 成長：「從 64 個 shard 起步留空間；consistent hashing 讓加 shard 時只搬一部分資料。」

陷阱：沒有數字就 shard；選 boolean / created_at 當 key；忽略 celebrity hot key；把 cross-shard 彙整當常態；提 2PC 當解法；directory-based 惹出 SPOF 追問。

## 關鍵數字
- Aurora 單一 DB 上限約 256 TiB。
- 範例：orders 表 500M 列、2 TB；5 億用戶 × 5KB = 2.5TB；尖峰 50K writes/s；100M DAU；64 shards（起步）；cache 5 分鐘；名人 shard 1000x 流量。
（皆為原文舉例。）

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [instagram](../../hellointerview-breakdowns/instagram.md)
- [whatsapp](../../hellointerview-breakdowns/whatsapp.md)
- [payment-system](../../hellointerview-breakdowns/payment-system.md)（saga / 避免 cross-shard txn）
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)

## 自測問題
1. Partitioning 與 sharding 差在哪？答：partitioning 在單一 DB 內切表；sharding 是跨多台機器的 horizontal partitioning。
2. 好的 shard key 有哪三個特性？答：高 cardinality、分佈均勻、與常見 query 對齊（單 shard 命中）。
3. 為何 hash-based 是預設，缺點與解法？答：分佈均勻；加減 shard 時 modulo 造成大量搬移，用 consistent hashing 緩解。
4. 不用 2PC，如何處理跨 shard 的一致性？答：設計避免跨 shard transaction（相關資料同 shard）、saga + 補償動作、接受最終一致。
5. Celebrity hot spot 怎麼辦？答：隔離到專屬 shard、compound shard key、動態 split，或搭配 cache / replica。
