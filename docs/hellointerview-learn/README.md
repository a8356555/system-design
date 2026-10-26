# Hello Interview System Design 教材 — 整理索引

> 來源：[hellointerview.com/learn/system-design](https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction) 除了 Problem Breakdowns 以外的 5 個分類，共 43 篇。
> 32 題案例另見 [../hellointerview-breakdowns/](../hellointerview-breakdowns/README.md)。整理日期：2026-10-19，7 個 agent 並行產出。

## 讀前須知

- 🔓 **免費 29 篇**：照原文整理；整理者自己加的內容標「（補充）」。
- 🤖 **Premium 14 篇（by agents）**：原文只公開介紹與章節大綱。檔案第二行有 `🤖 by agents` 提示；只有標「（原文）」的段落來自原文，其他內容都是 agents 依大綱撰寫，**不是 Hello Interview 原文**。
  - 參考來源：檔尾列的 56 個外部連結，2026-10-19 已逐一確認可以開啟（HTTP 200），但連結內容沒有逐條和筆記比對。
  - 實際搜尋情況：大部分 agents 沒有實際上網搜尋，是憑既有知識寫的；只有 Numbers to Know 實際抓過 latency numbers 和 Redis benchmark。
- **建議用法**：免費篇當教材讀，Premium 篇當「參考答案草稿」，邊讀邊懷疑。

## 1. In a Hurry（速成總覽）🔓

| 篇 | 重點 |
|---|---|
| [Introduction](in-a-hurry/introduction.md) | 評分四面向：Problem Navigation / Solution Design / Technical Excellence / Communication。時間不夠就按 Delivery → Key Tech → Core Concepts 的順序準備 |
| [How to Prepare](in-a-hurry/how-to-prepare.md) | 先打地基再練題：選題 → 自己答 → 看解答 → peer mock。附 Easy / Medium / Hard 題目清單 |
| [Delivery](in-a-hurry/delivery.md) | 時間配置：需求約 5 分 / Entities 約 2 分 / API 約 5 分 / HLD 10–15 分 / Deep Dive 約 10 分。功能只挑前 3 個；容量估算只在會影響設計時才做 |
| [Core Concepts](in-a-hurry/core-concepts.md) | 預設選擇：REST、normalized RDB、cache-aside Redis、最終一致。不要太早 shard |
| [Key Technologies](in-a-hurry/key-technologies.md) | 每類元件準備一個熟悉的技術，談具體特性，不要泛談 SQL vs NoSQL。持久連線用 L4 LB，其餘用 L7 |
| [Patterns](in-a-hurry/patterns.md) | 8 個 pattern 總覽；從簡單方案開始（先 polling，再 SSE / WS） |

## 2. Core Concepts（核心概念）

| 篇 | | 重點 |
|---|---|---|
| [API Design](core-concepts/api-design.md) | 🔓 | 預設 REST，GraphQL / gRPC 要有理由才用；付款這類 POST 要主動提 idempotency key |
| [Caching](core-concepts/caching.md) | 🔓 | 先量化 DB 瓶頸再加 cache；主動講失敗模式：stampede、一致性、hot key、Redis 掛掉 |
| [CAP Theorem](core-concepts/cap-theorem.md) | 🔓 | P 必選，所以實際是 C vs A；判準是「短暫不一致是否災難」；同一系統可以按功能拆開選 |
| [Consistent Hashing](core-concepts/consistent-hashing.md) | 🔓 | modulo 擴容幾乎全部 key 要搬，ring 只搬一小部分；vnode 解結構性不均，hot key 要另外處理 |
| [Data Modeling](core-concepts/data-modeling.md) | 🔓 | 預設 Postgres；schema 從 access pattern 推導；先 normalize，需要時才 denormalize |
| [Networking Essentials](core-concepts/networking-essentials.md) | 🔓 | 預設 TCP + HTTP + REST；失敗處理的標準組合：backoff + jitter、idempotency、circuit breaker |
| [Sharding](core-concepts/sharding.md) | 🔓 | 沒算數字就先 shard 是常見錯誤；shard key 要對齊 query；避開 cross-shard，必要時用 saga，不用 2PC |
| [DB Indexing](core-concepts/db-indexing.md) | 🤖 | B-tree 預設、寫入多用 LSM；composite index 看 leftmost prefix；geo 選 geohash / quadtree / R-tree |
| [Numbers to Know](core-concepts/numbers-to-know.md) | 🤖 | 用現代量級的數字；常見失誤是過早 shard、高估延遲（數字附來源） |

## 3. Patterns（解題套路）🤖 全部 by agents

| 篇 | 重點 | 對應案例 |
|---|---|---|
| [Dealing with Contention](patterns/dealing-with-contention.md) | conditional write → 悲觀鎖 → OCC → isolation level → 分散式鎖，要加 TTL + fencing token | Ticketmaster、Flash Sale、Online Auction |
| [Large Blobs](patterns/large-blobs.md) | presigned 直傳 + multipart、CDN 下載；以 S3 event 為準，再跑 reconciliation | Dropbox、YouTube、Instagram |
| [Long-Running Tasks](patterns/long-running-tasks.md) | 202 + job id + worker；retry / DLQ / 冪等 / backpressure | LeetCode、Web Crawler、YouTube |
| [Multi-Step Processes](patterns/multi-step-processes.md) | 單機 → Saga → choreography → orchestration（durable execution）；exactly-once = at-least-once + 冪等 | Payment、Uber |
| [Realtime Updates](patterns/realtime-updates.md) | 分兩段：client 協定（poll / SSE / WS）＋ server 端路由（consistent hashing / pub/sub） | WhatsApp、FB Live Comments |
| [Scaling Reads](patterns/scaling-reads.md) | DB 內部優化 → replica / shard → cache + CDN；注意 lag、hot key、stampede | Bitly、FB News Feed |
| [Scaling Writes](patterns/scaling-writes.md) | shard → queue + load shedding → batching + 階層聚合；hot key 用 splitting | Top-K、Ad Click、Rate Limiter |

## 4. Deep Dives（元件深入）

| 篇 | | 重點 |
|---|---|---|
| [API Gateway](deep-dives/api-gateway.md) | 🔓 | 核心是 routing，middleware 是附加；monolith 不需要，面試一句話帶過 |
| [Cassandra](deep-dives/cassandra.md) | 🔓 | LSM + vnodes、可調一致性；query-driven modeling，partition key 加時間 bucket |
| [DynamoDB](deep-dives/dynamodb.md) | 🔓 | 一致性逐次讀取指定、GSI 沒有 strong read；GSI vs LSI；RCU 4KB / WCU 1KB |
| [Elasticsearch](deep-dives/elasticsearch.md) | 🔓 | 用 CDC 掛在權威 DB 旁，不當主庫；少於 100k docs 不需要；深分頁用 search_after + PIT |
| [Kafka](deep-dives/kafka.md) | 🔓 | 只保證 partition 內有序；hot partition 有四種解法；處理完才 commit；retry topic + DLQ 要自己做 |
| [Proximity Search](deep-dives/proximity-search.md) | 🔓 | spatial index 只給候選再精算距離；幾何資料用 R-tree，移動點用 geohash / S2 / H3 |
| [Redis](deep-dives/redis.md) | 🔓 | 不是 source of truth；Redis lock 只是效率工具，需要 fencing token；16,384 slots |
| [Temporal](deep-dives/temporal.md) | 🔓 | workflow 必須決定性，activity 必須冪等；原本要自建狀態機 + retry 時才用 |
| [Time-Series DBs](deep-dives/time-series-databases.md) | 🔓 | append-only + 壓縮 + 時間分區；最大風險是 cardinality 爆炸（user_id 不能當 tag） |
| [Vector DBs](deep-dives/vector-databases.md) | 🔓 | 預設 HNSW；先用 pgvector / ES kNN，超過約 100M 向量再考慮專用 DB |
| [Change Data Capture](deep-dives/change-data-capture.md) | 🤖 | 讀 WAL / binlog 避免 dual write；需要業務語意就用 outbox；小心 replication slot 堆積 WAL |
| [Big Data 資料結構](deep-dives/data-structures-for-big-data.md) | 🤖 | Bloom 只有 false positive、CMS 只會高估、HLL 約 12KB；p99 要合併 sketch，不能取平均 |
| [Flink](deep-dives/flink.md) | 🤖 | 先問真的需要即時嗎；state + watermark + checkpoint + 2PC sink 達成 exactly-once |
| [Postgres](deep-dives/postgres.md) | 🤖 | 單主寫入、replica lag、GIN / GiST / BRIN；什麼時候該換引擎 |
| [ZooKeeper](deep-dives/zookeeper.md) | 🤖 | ephemeral sequential + watch 做 leader election / lock；新系統多用 etcd / KRaft |

## 5. In the Wild（真實公司案例）🔓

| 篇 | 重點 | 可支撐的論點 |
|---|---|---|
| [Discord × ScyllaDB](in-the-wild/discord-messages-scylladb.md) | 177 → 72 node、p99 從 40–125ms 降到 15ms；靠 request coalescing + 按 channel_id consistent hashing | 熱 partition 是流量問題，不只是 DB 選型問題 |
| [Figma Multiplayer](in-the-wild/figma-multiplayer.md) | 不用 OT，也不用完整 CRDT：property 級 LWW + 每份文件一個 server process | Google Docs 題的「簡化 CRDT」解 |
| [Meta ZGateway](in-the-wild/meta-zgateway-zippydb.md) | proxy 五招：pooling / batching / coalescing / read-through cache / admission control | 百萬 client 打同一個 DB 時怎麼辦 |
| [Shopify Reservations](in-the-wild/shopify-inventory-reservations.md) | 從 Redis 搬回 MySQL，讓 reservation 和帳本同在一個 transaction；SKIP LOCKED + expires_at 過濾 | Flash Sale / Ticketmaster 的 reservation 實作 |
| [Slack Job Queue](in-the-wild/slack-job-queue.md) | 在 Redis 前面加 Kafka 當磁碟 buffer，JQRelay 控制排出速率 | 只靠記憶體的 queue 會被 backlog 撐爆 |
| [Spotify Data Lake](in-the-wild/spotify-data-lake-point-queries.md) | 用 bucket + Bloom filter 把 90,000 個檔縮到約 12 個；外部 RAP 索引直接定位 key 的位置 | 在 data lake 上做 point query |

## 建議閱讀順序

1. **In a Hurry 全部**：先建立面試框架。
2. **Core Concepts**：依序讀 API Design → Data Modeling → Caching → Sharding → Consistent Hashing → CAP。
3. **Patterns × 案例對照**：每讀一個 pattern，就去 [../hellointerview-breakdowns/](../hellointerview-breakdowns/README.md) 找對應案例。
4. **Deep Dives**：按你面試常選的技術挑著讀（建議 Kafka、Redis、Postgres 或 DynamoDB、Elasticsearch）。
5. **In the Wild**：當作面試時「業界實例」的彈藥庫。
