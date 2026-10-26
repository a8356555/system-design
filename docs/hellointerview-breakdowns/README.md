# Hello Interview Problem Breakdowns — 整理索引

> 起點：Threads [@chunhao2026](https://www.threads.com/@chunhao2026) 的〈System Design Interview 系列〉貼文 → 貼文連到 [Hello Interview problem breakdowns](https://www.hellointerview.com/learn/system-design/problem-breakdowns/whatsapp) → 全部 32 題逐篇整理。
> 整理日期：2026-10-18。產出：6 個 agent 並行，每題一檔。

## 讀前須知

- **Threads 只抓到最新 3 篇系統設計貼文**（WhatsApp / Tinder / GitHub App JWT），更早的貼文需要登入捲動才看得到。貼文觀點寫在這 3 檔的開頭。
- **16 篇是 Premium**：原文只公開需求、規模與章節大綱；檔內 deep dive 的解法是整理者補充，已標「（補充，非原文）」。這類解法的可信度比免費篇低，請當作參考答案，不要當成原文。
- **原文本身前後不一致的地方**（檔內已註明）：Tinder 的 swipes/day（100 vs 200）、Distributed Rate Limiter 的用戶數（100M DAU vs 10M users）。
- 標記：🔓 免費全文 ｜ 🔒 Premium（僅大綱）｜ 🧵 有 Threads 貼文

## 題目總表

| 題目 | 來源 | 核心難點 | 3 條關鍵 pattern |
|---|---|---|---|
| [WhatsApp](whatsapp.md) | 🔓🧵 | 訊息不丟又要快 | 先 durable 寫 Inbox，再用 Redis Pub/Sub 盡力推送；heartbeat + per-user seq + polling 分層補漏、client ACK 才刪；大群改 chat-level channel |
| [Tinder](tinder.md) | 🔓🧵 | 同時互滑不能漏 match | pair key 排序 co-locate 雙向 swipe；Redis Lua 原子層 + Cassandra durable；選擇性一致性（match 強、feed 可 stale）+ Bloom filter 去重 |
| [GitHub App JWT](github-apps-jwt.md) | 🧵（GitHub 官方文件） | 證明身份 + 授權範圍 | 長效 key 只用來鑄短效 token；identity（JWT）與 scope（installation token）分離；`iat` 回推 60s 防 clock skew |
| [Ticketmaster](ticketmaster.md) | 🔓 | 熱門場次搶票 | Reservation + TTL（`SET NX EX`）+ DB OCC 兜底；狀態 + 過期時間在讀寫時判斷（implicit expiry）；virtual waiting queue + admitted set |
| [Dropbox](dropbox.md) | 🔓 | 大檔上傳 / 多裝置同步 | control plane / data plane 分離（presigned URL）；client chunking + multipart + fingerprint 續傳；push + poll 混合同步、content-defined chunking |
| [Uber](uber.md) | 🔓 | 2M 位置寫入/秒、配對不重複 | Redis GEO in-memory index；driverId 分散式鎖 + TTL；Kafka 配對成功才 commit、durable execution（Temporal）處理逾時 |
| [Top-K (YouTube)](top-k.md) | 🔓 | 700k TPS 計數 + 多時間窗 | precompute + cache 可回 stale；Kafka partition = DB shard、Flink 先聚合；把複雜度從讀移到寫、Count-Min Sketch 近似 |
| [Bitly](bitly.md) | 🔓 | 唯一短碼 + 高讀取 | scaling reads 階梯 index→Redis→CDN；counter + Base62 + counter batching；讀寫服務分離、TTL 對齊過期 |
| [YouTube](youtube.md) | 🔓 | 大檔上傳 + 串流 | presigned URL + multipart resumable；上傳事件觸發 DAG 轉檔；ABR manifest + segment 全上 CDN |
| [LeetCode](leetcode.md) | 🔓 | 跑不可信程式碼 | long-running task 回 job id + queue + polling；多層沙盒；Sorted Set 排行榜，避免 over-engineering |
| [Web Crawler](web-crawler.md) | 🔓 | 大規模 + 禮貌爬取 | 多階段 pipeline + queue 解耦 + DLQ；per-domain politeness（robots、crawl-delay、SETNX）；頻寬估算、DNS cache、分層去重 |
| [Distributed Rate Limiter](distributed-rate-limiter.md) | 🔓 | 1M RPS 一致計數 | Lua 擴大 atomic boundary；consistent hashing 分片；fail-open / fail-closed 要明說取捨 |
| [Ad Click Aggregator](ad-click-aggregator.md) | 🔓 | 高寫入 + 精確計費 | Flink event-time + watermark 預聚合，S3 + Spark 對帳（Lambda）；熱門 ad 加 key 後綴分散；impression ID + HMAC 冪等 |
| [FB Live Comments](fb-live-comments.md) | 🔓 | 百萬觀眾即時推送 | 讀寫不對稱 → SSE；按 videoId 分片 pub/sub + L7 consistent hashing；超大直播改 CDN snapshot + polling |
| [FB News Feed](fb-news-feed.md) | 🔓 | fan-out 放大 | fan-out on write 預存 200 postId；大帳號 hybrid 讀時 merge；hot post 用 replicated cache |
| [FB Post Search](fb-post-search.md) | 🔓 | 不用 ES 的搜尋 | 自建 inverted index + 預排序；like 里程碑更新 + two-stage 重排；結果快取 + 冷資料搬 S3 |
| [Gopuff](gopuff.md) | 🔓 | 庫存不超賣 + 就近 DC | 同庫 SERIALIZABLE 交易勝過分散式鎖；先半徑預篩再呼叫外部服務；讀寫一致性分級 |
| [Google Docs](google-docs.md) | 🔒 | 並發編輯 | per-doc 單一 authority + consistent hashing；OT vs CRDT；snapshot + op log + compaction |
| [Strava](strava.md) | 🔒 | 長時間 GPS 活動 | offline-first + client 生成 id 冪等同步；GPS 批次降 QPS；Sorted Set 排行 |
| [Job Scheduler](job-scheduler.md) | 🔒 | 準時執行 10k jobs/s | DB 為 SoT + 近期 job 預載 Redis ZSET；visibility timeout + ack + DLQ；scheduler 分片 lease + outbox |
| [Google News](google-news.md) | 🔒 | 低延遲 feed | cursor 分頁；預算 feed + 多層快取防 stampede；WebSub push 優先 + 自適應 polling |
| [Instagram](instagram.md) | 🔒 | 媒體 + feed | presigned 直傳 + metadata/media 分離；fan-out 混合（名人閾值）；轉檔狀態機 |
| [Flash Sale](flash-sale.md) | 🔒 | 1 萬件庫存被瞬間搶購 | reservation + TTL；Redis Lua 原子扣減 + CAS 狀態機；waiting room / admission control |
| [Payment System](payment-system.md) | 🔒 | 不丟、不重複扣款 | idempotency key 貫穿、unknown 狀態先查詢不盲重試；append-only ledger + 對帳；狀態機 + outbox |
| [Online Auction](online-auction.md) | 🔒 | 出價併發 | 按 auctionId 分區、單一 writer；先寫 durable log、current max 為衍生值；先拉再訂閱推送 |
| [camelcamelcamel](camelcamelcamel.md) | 🔒 | 價格追蹤 + 通知 | 熱度分級爬取 + 眾包；不可信資料要驗證；只存變動點 |
| [Yelp](yelp.md) | 🔒 | 評論 + 地理搜尋 | 預算衍生欄位；UNIQUE + upsert 取代 check-then-insert；ES geo + CDC |
| [Distributed Cache](distributed-cache.md) | 🔒 | 分片 + 熱 key | consistent hashing + vnode；async replica + failover；hot key 多副本 / key splitting |
| [ChatGPT](chatgpt.md) | 🔒 | 長串流 + GPU 稀缺 | 生成與連線解耦（Redis Stream + SSE resume）；GPU 公平排隊 + continuous batching；KV cache 重用 |
| [Notification System](notification-system.md) | 🔒 | 不丟 + 優先級 | 先持久化再 ack；優先級隔離防 HOL；at-least-once + 冪等、campaign 分批限速 |
| [Online Chess](online-chess.md) | 🔒 | 配對 + 有狀態對局 | 原子 CAS 配對；session pin 單節點 + move log；server 權威時鐘 |
| [Robinhood](robinhood.md) | 🔒 | 行情 fan-out + 下單 | 上游只訂一次再 fan-out + conflation；client_order_id + 狀態機 + 對帳；價格最終一致、訂單強一致 |
| [Metrics Monitoring](metrics-monitoring.md) | 🔒 | 時序寫入 + 告警 | agent 批次 + Kafka；rollup + 分層 retention、存 histogram 才能合併百分位；cardinality 控制 |

## 跨題 pattern 對照（同一招出現在哪些題）

| Pattern | 出現的題目 | 一句話 |
|---|---|---|
| **Reservation + TTL / 短期獨佔鎖** | Ticketmaster、Flash Sale、Uber、Online Chess | 把「慢步驟（付款、司機確認）」和「搶資源」拆開；用 TTL 自動釋放，DB 約束兜底 |
| **Redis Lua 原子操作** | Tinder、Flash Sale、Rate Limiter、Online Auction、Online Chess | read-check-write 整段包進 Lua，把 atomic boundary 擴大到整個判斷 |
| **單一 writer / 按 key 分區序列化** | Online Auction、Google Docs、Robinhood、Payment | 同一個實體的寫入都送到同一個 partition 或 authority，就不必用鎖 |
| **先 durable，再盡力推送** | WhatsApp、Notification、Online Auction、Ad Click | 正確性靠持久層，即時性靠 pub/sub，兩條路分開 |
| **Idempotency key + at-least-once** | Payment、Robinhood、Notification、Job Scheduler、Ad Click、Strava | 重試一定會發生，所以讓重複的請求無害 |
| **Unknown 狀態先查詢，不盲重試** | Payment、Robinhood | 外部副作用逾時時，先查詢或對帳，不要直接重送 |
| **Presigned URL 直傳 + multipart** | Dropbox、YouTube、Instagram | 讓 app server 只碰 metadata，bytes 直接走 S3/CDN |
| **Fan-out on write / read 混合** | FB News Feed、Instagram、WhatsApp（大群）、FB Live Comments | 依粉絲數或群組人數切換策略，名人走讀時 merge |
| **Precompute + 多層 cache** | Top-K、Google News、FB News Feed、Yelp、Bitly | 把運算從讀路徑移到寫路徑或批次，允許回 stale |
| **Stream 預聚合（Flink）+ 對帳** | Ad Click、Top-K、Metrics | event-time + watermark，再用批次對帳當 source of truth |
| **熱 key 處理** | Ad Click（後綴分散）、FB News Feed（replicated cache）、Distributed Cache、Rate Limiter | 寫熱用 key splitting，讀熱用多副本 |
| **Queue 解耦 + DLQ + visibility timeout** | Web Crawler、LeetCode、Job Scheduler、YouTube | 長任務非同步化，worker 掛掉工作不會丟 |
| **Waiting room / admission control** | Ticketmaster、Flash Sale、ChatGPT | 流量超過容量時，在入口排隊，不讓後端被打爆 |
| **SSE + Last-Event-ID 續傳** | FB Live Comments、ChatGPT、Ticketmaster | 單向推送、斷線後補送，比 WebSocket 簡單 |
| **Geo index** | Uber、Yelp、Gopuff、Tinder | Redis GEO / ES geo / 先半徑預篩，再做昂貴計算 |
| **Durable execution（Temporal）** | Uber、YouTube | 多步驟流程加 timer，crash 後可從中斷處繼續 |
| **選擇性一致性** | Tinder、Robinhood、Gopuff、Online Auction | 錢、配對、庫存走強一致，feed、價格、顯示走最終一致 |

## 建議閱讀順序

1. **入門（easy）**：Bitly → Dropbox → Gopuff → LeetCode
2. **核心套路**：Ticketmaster（reservation）→ WhatsApp（durable + push）→ FB News Feed（fan-out）→ Uber（geo + lock）
3. **高寫入 / 串流**：Top-K → Ad Click Aggregator → Distributed Rate Limiter → Web Crawler
4. **即時推送**：FB Live Comments → Tinder → FB Post Search → YouTube
5. **Premium 補充篇**（當作練習題：先自己推，再對照）：Payment → Flash Sale → Google Docs → 其餘

和本 repo 既有文件的關係：跨題 pattern 的深入版本見 [../cross-cutting-patterns.md](../cross-cutting-patterns.md)，題目地圖見 [../question-map.md](../question-map.md)。
