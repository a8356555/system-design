# Eng Blog 閱讀清單(領域特化機制的一手校準來源)

> 定位:[domain-specific-mechanisms.md](domain-specific-mechanisms.md) 給你推導鏈,本清單給你**真實系統的一手證據**——面試引用一句「Netflix 實際上是 per-title 優化 ladder」立刻和背書的人拉開差距。
> 收錄標準:**每條 URL 都經 WebFetch 實際驗證可訪問且內容相符**(2026-09 驗證)。官方一手來源優先;無法驗證的經典(多因網站擋爬)在各節末尾註明,不收未驗證連結。
> 用法:每篇 15-30 分鐘快讀,目標不是深究,是「知道真實世界長這樣 + 記住一個可引用的具體數字/決策」。

## Domain 1:影音 Encoding / Streaming

> 註:Netflix TechBlog 掛在 Medium、擋機器抓取,以下 Netflix 連結改以 Wayback 存檔快照(status 200)驗證 URL 真實存在,瀏覽器可正常開啟。

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [Per-Title Encode Optimization](https://netflixtechblog.com/per-title-encode-optimization-7e99442b62a2) | Netflix · 2015 | classic | 每部片各自跑一條 bitrate ladder(rate-distortion 找各解析度最佳交點)——「為何不用固定 ladder」的原文 |
| [Dynamic Optimizer: a perceptual video encoding optimization framework](https://netflixtechblog.com/dynamic-optimizer-a-perceptual-video-encoding-optimization-framework-e19f1e3a277f) | Netflix · 2018 | recent | 粒度細到 shot-based、用 VMAF 當最佳化目標——展示 per-title → per-shot 的迭代思路 |
| [Optimized shot-based encodes: Now Streaming!](https://medium.com/netflix-techblog/optimized-shot-based-encodes-now-streaming-4b9464204830) | Netflix · 2018 | recent | shot-based 上線的系統工程面(切鏡、平行 encode、產線整合) |
| [Serving 100 Gbps from an Open Connect Appliance](https://netflixtechblog.com/serving-100-gbps-from-an-open-connect-appliance-cdb51dda3b99) | Netflix · 2017 | classic | 單機 CDN 邊緣節點用 kernel/TLS/NUMA 調校打到 100Gbps(連 cs-fundamentals O2 zero-copy、A1 NUMA) |
| [MSVP: Meta's first ASIC for video transcoding](https://ai.meta.com/blog/meta-scalable-video-processor-MSVP/) | Meta · 2023 | recent | 專用 ASIC 取代 CPU/GPU 做 transcode 的成本/能效權衡 |
| [FFmpeg at Meta: Media Processing at Scale](https://engineering.fb.com/2026/03/02/video-engineering/ffmpeg-at-meta-media-processing-at-scale/) | Meta · 2026 | recent | 一天數百億次 ffmpeg 的規模化:multi-lane 平行 encode、transcode 中即時算品質度量 |
| [Low Latency, High Reach: Live Video Streaming at Twitch](https://blog.twitch.tv/en/2021/10/25/low-latency-high-reach-creating-an-unparalleled-live-video-streaming-network-at-twitch/) | Twitch · 2021 | classic | 自研 LL-HLS 把延遲 15s → ~3s(小 segment、chunked transfer、prefetch)——直播延遲取捨 |

*未收:YouTube 無單篇官方工程文(多為 research paper),大規模 transcoding 由 Meta 兩篇覆蓋;ABR/LL-HLS 無官方獨立專文,由 Twitch 篇覆蓋。*

## Domain 2:URL / ID 生成與機率型資料結構

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [Announcing Snowflake](https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake) | Twitter · 2010 | classic | 64-bit 分散式 ID 佈局與 roughly time-sortable 的價值——ID 產生器題的標準答案起點 |
| [Sharding & IDs at Instagram](https://instagram-engineering.com/sharding-ids-at-instagram-1cf5a71e5a5c) | Instagram · 2012 | classic | ID 生成塞進 Postgres(41b 時間 + 13b logical shard + 10b sequence)——ID 內嵌 shard routing、不另建 ID service 的取捨 |
| [Redis new data structure: the HyperLogLog](https://antirez.com/news/75) | antirez · 2014 | classic | HLL 用 ~12KB 估基數(0.81% 誤差)的原理——「算 UV 但記憶體有限」的第一手來源 |
| [When Bloom filters don't bloom](https://blog.cloudflare.com/when-bloom-filters-dont-bloom/) | Cloudflare · 2020 | classic | Bloom filter 原理 + 反面教訓:隨機記憶體存取超出 CPU cache 反而變慢(連 cs-fundamentals A1)——展示「懂理論也懂量測」 |
| [How Discord Stores Trillions of Messages](https://discord.com/blog/how-discord-stores-trillions-of-messages) | Discord · 2023 | recent | Snowflake ID 讓訊息可依時間排序 + channel/時間 bucket partition key——「ID 設計直接決定 sharding/查詢模式」 |

## Domain 3:Geo-indexing / Dispatch

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [H3: Uber's Hexagonal Hierarchical Spatial Index](https://www.uber.com/en-US/blog/h3/) | Uber · 2018 | classic | 為什麼用六邊形而非方格 + 64-bit 階層 cell id;把「找附近司機」轉成 cell 環查詢而非暴力算距離 |
| [Announcing the S2 Library: Geometry on the Sphere](https://opensource.googleblog.com/2017/12/announcing-s2-library-geometry-on-sphere.html) | Google · 2017 | classic | 立方體投影 + Hilbert 曲線把球面壓成 1D 可排序 key;面試對比 S2(方格/曲線)vs H3(六邊形)取捨(文件:[s2geometry.io](https://s2geometry.io/)) |
| [Engineering More Reliable Transportation with ML and AI at Uber](https://www.uber.com/en-US/blog/machine-learning/) | Uber · 2017 | classic | dispatch/ETA/需求預測跑「30M+ match-pair 預測/分鐘」;matching 不是選最近的車,是多目標打分 |
| [Uber's Fulfillment Platform: Ground-up Re-architecture](https://www.uber.com/en-US/blog/fulfillment-platform-rearchitecture/) | Uber · 2021 | recent | 訂單/供需 matching 生命週期抽象成支援拼車、預約、批次的平台;dispatch 的狀態機與 orchestration 分層 |
| [Building Uber's Fulfillment Platform for Planet-Scale using Cloud Spanner](https://www.uber.com/en-US/blog/building-ubers-fulfillment-platform/) | Uber · 2021 | recent | 高頻寫入下從 NoSQL 轉 NewSQL 換強一致的取捨;dispatch 為何需要交易一致性 |

*未收(擋爬無法驗證):DoorDash、Lyft 的 dispatch/ETA 文(全站 403);Redis GEO 無官方深度文。*

## Domain 4:協作編輯 / 檔案同步

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [How Figma's multiplayer technology works](https://www.figma.com/blog/how-figmas-multiplayer-technology-works/) | Figma · 2019 | classic | 權威伺服器 + 樹狀文件 + per-property LWW,避開完整 OT/CRDT——「CRDT 啟發但更簡單」是高分講法 |
| [Making multiplayer more reliable](https://www.figma.com/blog/making-multiplayer-more-reliable/) | Figma · 2022 | recent | write-ahead journal 把資料遺失窗口 60s → <1s、DynamoDB file-lock 防雙寫 |
| [Streaming File Synchronization](https://dropbox.tech/infrastructure/streaming-file-synchronization) | Dropbox · 2014 | classic | 上傳/下載兩階段重疊,下載端邊傳邊拿 block——同步延遲優化 |
| [Inside LAN Sync](https://dropbox.tech/infrastructure/inside-lan-sync) | Dropbox · 2015 | classic | UDP broadcast 探測 + 本地 block 交換繞過雲端;P2P 加速的三元件拆分 |
| [Rewriting the heart of our sync engine](https://dropbox.tech/infrastructure/rewriting-the-heart-of-our-sync-engine) | Dropbox · 2020 | recent | Nucleus:用 Rust 型別把非法狀態設計掉 + 確定性模擬測試;同步一致性與穩定 file id |
| [Local-first software](https://www.inkandswitch.com/essay/local-first/) | Ink & Switch · 2019 | classic | CRDT 作為離線優先、自動合併的基礎與實務取捨;CRDT vs OT 的思想源頭 |
| [What's different about the new Google Docs: Making collaboration fast](https://drive.googleblog.com/2010/09/whats-different-about-new-google-docs.html) | Google · 2010 | classic | OT 讓多人同區編輯不衝突的官方原文(注意:正文為 JS 渲染,建議瀏覽器開) |

## Domain 5:社交 / 訊息

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [How Discord Stores Billions of Messages](https://discord.com/blog/how-discord-stores-billions-of-messages) | Discord · 2017 | classic | Cassandra compound partition key(channel_id + 時間桶)分片訊息——「怎麼為 append-only 訊息選 partition key 避免熱點」 |
| [How Discord Stores Trillions of Messages](https://discord.com/blog/how-discord-stores-trillions-of-messages) | Discord · 2023 | recent | 遷 ScyllaDB 消除 GC 停頓 + Rust 資料服務 request coalescing 打散熱門頻道熱分區 |
| [Real-time Messaging](https://slack.engineering/real-time-messaging/) | Slack · 2023 | recent | WebSocket + Gateway/Channel Server 用 consistent hashing 路由;transient event(typing)的處理 |
| [Flannel: An Application-Level Edge Cache to Make Slack Scale](https://slack.engineering/flannel-an-application-level-edge-cache-to-make-slack-scale/) | Slack · 2017 | classic | 邊緣層 lazy-load + push 預測資料,取代開機拉全量——冷啟動 payload 優化 |
| [Instant Messaging at LinkedIn: Scaling to Hundreds of Thousands of Persistent Connections](https://www.linkedin.com/blog/engineering/archive/instant-messaging-at-linkedin-scaling-to-hundreds-of-thousands-) | LinkedIn · 2016 | classic | SSE + actor 撐單機十萬級長連線;點名 TCP queue/fd/heap 系統瓶頸(連 cs-fundamentals N1/O2) |

*未收(無法驗證):WhatsApp 無官方工程 blog;Instagram feed fan-out 獨立文未尋獲,由 Twitter the-algorithm 覆蓋。*

## Domain 6:搜尋 / 推薦

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [Elasticsearch from the Bottom Up, Part 1](https://www.elastic.co/blog/found-elasticsearch-from-the-bottom-up) | Elastic · 2013 | classic | inverted index、不可變 segment、refresh 達成 near-real-time——搜尋底層的標準答案 |
| [Unifying the LinkedIn Search Experience](https://www.linkedin.com/blog/engineering/search/unifying-linkedin-search-experience) | LinkedIn · 2013 | classic | typeahead 要平衡「prefix 最常見」與「最可能成功」;連到開源 Cleo(network-aware typeahead) |
| [Scaling the Instagram Explore recommendations system](https://engineering.fb.com/2023/08/09/ml-applications/scaling-instagram-explore-recommendations-system/) | Meta · 2023 | recent | 完整 multi-stage funnel:retrieval → Two-Tower 輕排 → 重排 → 過濾——recall→ranking 兩段式最清楚的官方藍圖 |
| [Twitter's Recommendation Algorithm](https://github.com/twitter/the-algorithm) | X/Twitter · 2023 | recent | in/out-of-network 候選源 + light/heavy ranker(~48M 參數)+ 過濾——真實三段式 timeline pipeline 與各段規模 |
| [Introducing Natural Language Search for Podcast Episodes](https://engineering.atspotify.com/2022/03/introducing-natural-language-search-for-podcast-episodes) | Spotify · 2022 | recent | Dense retrieval + ANN 語意召回與關鍵字檢索融合——向量檢索題可引用(連 de-system-design DE-11/ML-4) |
| [Introducing Voyager: Spotify's New Nearest-Neighbor Search Library](https://engineering.atspotify.com/2023/10/introducing-voyager-spotifys-new-nearest-neighbor-search-library) | Spotify · 2023 | recent | HNSW ANN 比 tree-based(Annoy)快 10 倍——ANN 選型與召回/延遲取捨 |

*未收(擋爬無法驗證):Netflix 推薦架構文(netflixtechblog.com 全站 403)。*

## Domain 7:交易(Payment / Ledger / 秒殺)

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [Designing robust and predictable APIs with idempotency](https://stripe.com/blog/idempotency) | Stripe · 2017 | classic | idempotency key 做 exactly-once 重試的原文——「如何避免重複扣款」直接搬這套 key + 結果快取 |
| [Online migrations at scale](https://stripe.com/blog/online-migrations) | Stripe · 2017 | classic | dual-write → 改讀 → 改寫 → 清理 四階段零停機遷移——「上億筆換表不停機」 |
| [Scaling your API with rate limiters](https://stripe.com/blog/rate-limiters) | Stripe · 2017 | classic | token bucket + 四層限流/降載(request/concurrent/load shedder)——「秒殺 API 如何保護後端」 |
| [Zero-Sum by Design: 10 Years of Uber's Payments Platform](https://www.uber.com/us/en/blog/ubers-payments-platform/) | Uber · 2026 | recent | double-entry + zero-sum + 不可變 money order + 強一致 ledger——「金流帳本為何 double-entry 且不可改」的一手證據 |
| [How LedgerStore Supports Trillions of Indexes at Uber](https://www.uber.com/us/en/blog/how-ledgerstore-supports-trillions-of-indexes/) | Uber · 2024 | recent | ledger 三種索引(強一致/最終一致/time-range)取捨與冷熱分層 |
| [Capacity Planning at Scale](https://shopify.engineering/capacity-planning-shopify) | Shopify · 2020 | classic | 秒殺前預測 + 安全餘量 + 提前 scale-up 演練抓瓶頸 |
| [How we prepare Shopify for BFCM](https://shopify.engineering/bfcm-readiness-2025) | Shopify · 2025 | recent | Game Day 混沌工程 + 壓測衝 200M req/min + resiliency matrix——大促驗證方法論 |

## Domain 8:基礎設施(限流 / 鎖 / Outbox·CDC / 重試)

| 標題 | 來源 · 年份 | 類型 | 借什麼 |
|---|---|---|---|
| [How we built rate limiting capable of scaling to millions of domains](https://blog.cloudflare.com/counting-things-a-lot-of-different-things/) | Cloudflare · 2017 | classic | sliding window counter(近似、省記憶體、誤差 0.003%)——限流演算法選型時對比 token bucket |
| [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) | Kleppmann · 2016 | classic | fencing token 與 Redlock 批判(效率鎖 vs 正確性鎖)——「為何 Redis 鎖不夠」的 canonical 出處 |
| [Solving the Dual-Write Problem (Transactional Outbox)](https://www.confluent.io/blog/dual-write-problem/) | Confluent · 2024 | recent | dual-write 問題與 outbox + CDC 解法——「DB 更新與發事件如何保持原子」 |
| [Building Reliable Reprocessing and Dead Letter Queues with Apache Kafka](https://www.uber.com/us/en/blog/reliable-reprocessing/) | Uber · 2018 | classic | 非阻塞 retry topic + DLQ——「消費失敗如何重試又不阻塞主流量」 |

*未收(擋爬無法驗證):Netflix DBLog 與 Debezium outbox 原文(403);DBLog 的 watermark 方法可查 arXiv 2010.12597。Crawler 無可驗證的一手官方文,建議略過。*

---

## 讀法建議

1. **配合 6 週 roadmap**:[study-roadmap.md](study-roadmap.md) 第 3-4 週讀哪組題,就配讀該 domain 的 1-2 篇 classic;recent 篇在 mock 前掃。
2. **每篇只帶走一句話**:讀完在 [domain-specific-mechanisms.md](domain-specific-mechanisms.md) 對應條目旁補一個可引用的數字或決策(例:「Discord 2023:熱分區用 request coalescing 解」)。
3. **擋爬名單的含意**:Netflix/DoorDash/Lyft/Debezium 的文章本身仍值得讀(瀏覽器開得了),只是本清單依「機器可驗證」標準未收;面試引用前自己開一次確認還在。
