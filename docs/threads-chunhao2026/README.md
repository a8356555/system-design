# Threads @chunhao2026 — 系統設計貼文與延伸閱讀

> 作者：[@chunhao2026](https://www.threads.com/@chunhao2026)（財金轉軟體工程師，做過支付、電商，現為 HubSpot senior SWE）。帳號從 2026-06-26 開始發文。
> 抓取：2026-10-19（270 篇），2026-10-24 登入後補收連結預覽卡與 6 篇新貼文（共 276 篇，新貼文皆為 PM/Business 系列）。作者說自己的學習流程是：HelloInterview 的影片 / Blog → 記下不懂的名詞 → 匯入 wondering.app 做成課程 → 每天上 30 分鐘。

## 這個資料夾有什麼

| 檔案 | 內容 |
|---|---|
| [posts.md](posts.md) | 系統設計相關 64 組貼文，原文照錄。每組 = 主文 + 作者同日接續留言，依系列分類並附目錄 |
| [tech-blog/](tech-blog/) | 作者解讀過的 15 篇 eng blog：找回原文後，和作者觀點一起整理 |
| [all_posts.jsonl](all_posts.jsonl) | 全部 276 篇原始資料（url / date / text / links，links 含連結預覽卡） |
| [build_posts.py](build_posts.py) | 從 all_posts.jsonl 重建 posts.md |
| [urls-with-links.txt](urls-with-links.txt) | 登入後收集的「貼文 ↔ 連結卡」配對（含作者 LinkedIn bio 雜訊，已在合併時濾掉） |
| [urls.txt](urls.txt) | 從個人頁收集到的貼文連結 |

作者常用 wondering.app 的連結附在貼文裡，但那只是課程大綱，不是原文；真正的來源是 HelloInterview 和各家 eng blog。HelloInterview 已另外整理在 [../hellointerview-breakdowns/](../hellointerview-breakdowns/README.md)（32 題）和 [../hellointerview-learn/](../hellointerview-learn/README.md)（43 篇）。

## 連結預覽卡的結論（2026-10-24）

作者的連結卡幾乎都是 wondering.app 課程或 HelloInterview 題目（已整理過）。唯一新增的 eng blog 連結是 Netflix TimeSeries 的 medium 版，證實了 agent 用搜尋比對出的原文正確。其餘 Tech Blog 貼文（LinkedIn MUSE、Meta GPU、Netflix graph 等）**連卡片都沒附**，所以 tech-blog/ 裡用搜尋比對出的原文維持不變。

## ⚠️ 已知缺口

- **長貼文不完整**：作者常把一篇拆成「主文 + 3–4 則接續留言」（例如「七個重點」）。個人頁只會顯示每串的第一則留言，所以 `posts.md` 裡很多組只有前 1–3 點。要補齊，需在登入狀態下到 `/@chunhao2026/replies` 分頁再跑一次收集腳本。
- **未收錄**：PM / Business / UX / Podcast Blog 系列、多數 Cross-domain 思維文、AI 工具類（Claude Code、MCP、RAG、OpenAI agents）、Git、Unit test、生活與職涯文。這些都在 `all_posts.jsonl` 裡。

## Tech Blog 延伸閱讀（15 篇）

來源欄說明：✅ 直接讀到原文 ｜ 🗄 用 Wayback 存檔核對 ｜ ⚠️ 只有轉載站或摘要（檔頭有註明）｜ ❌ 找不到原文

| 篇 | 來源 | 核心設計 | 面試可用在 |
|---|---|---|---|
| [Netflix 即時分散式圖查詢](tech-blog/netflix-realtime-graph-query.md) | 🗄 | 8B nodes / 150B edges；用 BFS 分層平行處理、多跳合併成一次 gRPC；adaptive concurrency | 社群圖、推薦、多跳查詢 |
| [Netflix 兩代 Flink autoscaler](tech-blog/netflix-flink-autoscaler.md) | 🗄 | CPU 指標看不出 backpressure；改用 True Processing Rate；每個 job 一條 Temporal workflow | 串流系統的擴縮容與觀測指標 |
| [Netflix GenRec](tech-blog/netflix-genrec-llm-recommendation.md) | 🗄 | 用 prompt 取代上千個人工特徵；prefill-only 打分 | LLM 原生推薦系統 |
| [Netflix MAPS 冷啟動](tech-blog/netflix-cold-start-multimodal.md) | 🗄 | 兩個優化各自上線都不顯著，合併才有效；IPS 離線評估；Embedding Store 解耦 | 冷啟動、多模態 embedding |
| [Netflix Hystrix](tech-blog/netflix-hystrix-circuit-breaker.md) | ✅ wiki + 🗄 2011 原文 | 每個依賴一個 thread pool（bulkhead），滿了直接拒絕；fallback 三型態 | Circuit breaker、級聯故障 |
| [Netflix 時序資料分層儲存](tech-blog/netflix-timeseries-tiered-storage.md) | ⚠️ | 15 PB 冷層從 Kafka/Flink/S3 改成 Cassandra 原生；靠資料不可變性關掉 read repair | 冷熱分層、immutable data |
| [Netflix 直播廣告事件處理流程](tech-blog/netflix-ads-event-pipeline-live.md) | ⚠️ | 同步寫入移出關鍵路徑，改用 Flink streaming join + 每小時 Spark 補配對 | 廣告點擊、at-least-once + 冪等 |
| [Netflix 生產規模 Spark 除錯](tech-blog/netflix-debugging-spark-at-scale.md) | ⚠️ | 資料傾斜讓抽樣抓不到 bug；用分支隔離平行實驗；AQE 偷偷改成 broadcast join | 大數據除錯、data skew |
| [LinkedIn MUSE 語義搜尋](tech-blog/linkedin-muse-semantic-search.md) | ✅ | 雙塔 + Matryoshka embedding；1.3B profile 離線預算向量；週批 + 每日 CDC | 向量搜尋、ANN + 過濾 |
| [LinkedIn Premium 統一資料](tech-blog/linkedin-premium-unified-data.md) | ✅ | 三條產品線共用 Target Audience graph；難點在計費 ledger 整合 | 多產品共用資料模型 |
| [Meta AI 訓練儲存](tech-blog/meta-gpu-training-storage.md) | ✅ | 三層 metadata 查詢壓成一層 O(1)；fat client 直連；用 GPU host 閒置記憶體做 cache | metadata 瓶頸、分層快取 |
| [WhatsApp 端對端加密下的詐騙偵測](tech-blog/whatsapp-on-device-scam-detection.md) | ✅ | 模型在裝置端推論；differential privacy + TEE；模型版本放透明度 ledger | 隱私與偵測的取捨 |
| [Dropbox 機群效率](tech-blog/dropbox-fleet-efficiency.md) | ✅ | 先榨乾現有機群再買硬體：Deep Sleep、負載平衡、SMR、依故障率汰換 | 容量規劃、成本 |
| [Spotify Random Access Parquet](tech-blog/spotify-random-access-parquet.md) | ✅ | 瓶頸是 SQL engine 排程而不是儲存；外部確定性索引（主體見 [in-the-wild 那篇](../hellointerview-learn/in-the-wild/spotify-data-lake-point-queries.md)） | 在 data lake 上做 point query |
| [Spotify Discover Weekly × Spark](tech-blog/spotify-discover-weekly-spark.md) | ❌ | 只整理貼文：在固定時間窗內掃全站資料的規模問題 | 批次運算 |

**沒整理的 Tech Blog 貼文**（偏 AI 工程流程，不屬系統設計）：GitHub 的 AI code ownership 與 gh-stack 疊層 PR、LinkedIn AI code review、Slack agentic testing、Spotify 給 LLM 的 context layer、小模型 fine-tune、OpenAI agents 加速。

## posts.md 各系列重點

- **System Design Interview**（5）：Fan-out on Read vs Write、Uber、WhatsApp、LeetCode、Tinder → 對應 [../hellointerview-breakdowns/](../hellointerview-breakdowns/README.md)
- **System Design / Case Study**（5）：Circuit Breaker、OAuth 2.0、Netflix Hystrix、GitHub Apps JWT、Spotify Spark
- **Tool**（14）：ZooKeeper、Elasticsearch、REST、gRPC、Docker、Flink、CDN、JWT、DNS、Load Balancer、Database Index、ACID、Idempotency、Consistent Hashing
- **Comparison**（12）：DynamoDB vs Redis、Write-Through vs Write-Back、四種 NoSQL、ZooKeeper vs Redis、K8s vs Docker、Polling vs WebSocket、Temporal vs Airflow、MQ vs Event Bus vs Broker、Parallelism vs Concurrency、Sharding vs Partitioning、TCP vs UDP 等
- **Small Quiz**（8）：「四句話有一句是錯的」，題目涵蓋 database index、OAuth 2.0、async/await、Docker、WebSocket、REST API，適合當自我測驗
