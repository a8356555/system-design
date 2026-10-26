# How and Why Netflix Built a Real-Time Distributed Graph, Part 3 — Querying the Graph with gRPC
> 原文：https://netflixtechblog.com/how-and-why-netflix-built-a-real-time-distributed-graph-part-3-querying-the-graph-with-grpc-0f3468349607 ｜ Netflix（作者 Nilesh Mishra, Ajit Koti） / 2026-08-07 ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/Dci51VaDSCs（2026-08-27）

> 取得方式備註：原文經 Wayback Machine 存檔（https://web.archive.org/web/2026/https://netflixtechblog.com/how-and-why-netflix-built-a-real-time-distributed-graph-part-3-querying-the-graph-with-grpc-0f3468349607）核對，下列「原文重點」已逐條對照原文。貼文只列出前 2 點，其餘作者解讀未取得。

## 一句話重點
Graph serving layer 靠 BFS 批次平行遍歷、async-first 小 thread pool、把多跳打包進單一 gRPC 呼叫，在 8B nodes / 150B edges 上做到單跳 P50 15-30ms、3-hop P99 100-150ms。

## 作者的解讀（貼文重點）
- 規模：8B nodes、150B edges；single-hop P50 15-30ms，3-hop P99 100-150ms。
- BFS 而非 DFS：每一層 nodes 一次平行處理，把 N 個 sequential network calls 壓成幾個 parallel batch；例如先一次拿所有 profiles，再一次拿所有 viewing histories，兩個 round trip 搞定。
- 16-24 threads 承載 thousands 的 concurrent queries：async-first，thread 永不 block 在 I/O，dispatch 完就走、callback 回來再接，打破「concurrency ≈ thread count」直覺。

## 原文重點
### 背景 / 規模
- 8 billion nodes、150+ billion edges；單跳 P50 15-30ms、P99 低於 100ms；3-hop P99 100-150ms。
- 兩種 workload：Shallow & wide（例如「這個 account 用過哪些裝置」，單一 node 取數百條 edge，壓力在 I/O throughput）；Deep & narrow（account → profiles → content 的多跳，壓力在循序依賴與網路 overhead）。

### 架構與設計決策
- 三層：Graph Query Service（接 gRPC、驗證 traversal spec）→ Storage Abstraction Layer（位於 execution engine 與底層 KVDAL storage 之間；node/edge 查詢介面、大型 adjacency list 串流、node cache）→ Enrichment Layer（按需向外部 Netflix 服務取 metadata，批次、與 graph 組裝平行、來源掛了就降級）；Execution Engine 負責 BFS 逐層展開與過濾。
- 請求先被解析成 execution plan（跳數、每跳 edge 數、回看時間、是否偏好最新），由「應用預設→全域→每層→每 edge type」層層覆寫合併，讀 storage 前每一跳規則已定，避免 over-fetch。
- BFS：一次處理一層的所有 node，層內可平行呼叫；代價是記憶體用量上升，以每個 edge type 在每一跳的上限控制。
- Adjacency list 直接查找；大型 adjacency list 以 100 筆一批串流，避免記憶體尖峰。
- 把多跳邏輯打包進單一 gRPC 請求：client 若逐跳送，每跳 10ms 網路就先有 20ms overhead（2 跳）；原文以此為 sub-100ms 目標的動機。
- Async-first：整條執行管線用非同步組合，僅 16-24 條 thread（分成多個專用 pool）處理數千並發請求；等 storage 回應時 thread 去做別的 query。thread pool 依工作型態分開（fetch node、讀 adjacency list、enrichment），如廚房分工位，一個 pool 滿了不拖垮其他；例：adjacency-list pool 有 8 個 worker。
- Adaptive concurrency limiting：健康時緩慢加（100→101→102…），timeout/錯誤飆高時大步退（如 100→70），與 per-pool 上限並用，避免無界並發壓垮 storage。
- 預設 eventual consistency：讀最近 replica、免協調成本；RDG 不是資料的 source of truth。
- 選擇性 cache：accounts、profiles、content 等穩定 node 用 EVCache，node lookup hit rate 70-80%（common query path 的 storage call 約少 3-4 倍）；只快取常讀且慢變化的資料，變動快的 edge 不快取。Smart TTL：依 node 最後活動時間、graph retention（例 100 天）、cache TTL（例 30 天）判斷，99 天前才活動過的 node 一天後就從 graph 過期，故不進 cache。
- Enrichment 為 opt-in 且 fail-open：外部服務不可用不擋 query，client 每次請求指定需要的外部資料。
- 階層式過濾：保守預設（例 100 天 lookback、每跳 300 edges），可在全域、每一跳（per-depth）、edge type 層級覆寫，較窄者勝（例：預設 100 天、caller 對 started_watching 設 30 天）；selection 模式 LATEST（依時間排序取最新，預設）與 ANY（先遇到先取、不排序，較快，適合「有沒有看過」）。這套分層覆寫源自「每個團隊要不同 lookback 就得改 code」的痛點。
- 過濾盡量下推到 storage 串流來源（邊串流邊濾、湊夠 limit 就停止讀取）。

### 取捨
- BFS 換延遲，付出記憶體，用 per-edge-type limit 約束。
- Async 大幅降低基礎設施成本（原文稱最意外的收穫；原本需每 instance 數百 thread，現 16-24 即可），但 async stack trace 難除錯，以各階段（驗證、storage、enrichment、端到端）metrics 彌補。
- Cache 不碰快速變動資料以免 stale。

### 結果
- 單跳 P50 15-30ms、P99 < 100ms；3-hop P99 100-150ms；RDG 服務每秒數萬（tens of thousands）query。2-hop 範例（Stranger Things 觀看紀錄）原文稱可在 100ms 內完成。

## 面試怎麼用
- Social graph / friend-of-friend / recommendation 查詢題：論點「多跳用 BFS 分層批次，延遲 = 跳數 × 一次批次 RTT，而非節點數 × RTT」。
- 高並發服務：non-blocking I/O 的 event-loop 模型為何用少量 thread 就夠，並說明代價是可觀測性。
- 超級節點（hub）：per-hop / per-edge-type limit、分批串流 adjacency list。
- Cache 策略：只快取穩定、熱門實體，量化目標 hit rate 70-80%。
- 可降級設計：enrichment fail-open。
- （補充，原文未提 Cassandra）原文只寫底層為 KVDAL 儲存、以 adjacency list 組織 edge，而非原生 graph DB，可作為「不一定要 Neo4j」的案例；KVDAL 底層是否 Cassandra 屬 Part 2 / 外部知識，此處未核對。
- 一致性取捨：查詢多為「這個 member 最近做了什麼」，預設 eventual consistency 讀近端 replica。

## 相關筆記
- [Cassandra](../../hellointerview-learn/deep-dives/cassandra.md)
- [Caching](../../hellointerview-learn/core-concepts/caching.md)
- [Scaling reads](../../hellointerview-learn/patterns/scaling-reads.md)
- [Networking essentials](../../hellointerview-learn/core-concepts/networking-essentials.md)
