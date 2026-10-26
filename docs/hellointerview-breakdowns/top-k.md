# YouTube Top K
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/top-k ｜ 難度 hard ｜ 類別：Scaling Reads / Scaling Writes（作者 Stefan Mai）

## 一句話核心
對一條巨量 view event stream（VideoID firehose）精確回答「過去 1 小時/1 天/1 月/all-time 的 top K 影片」，且查詢要在數十毫秒內回應。解法主軸：讀端 precompute + cache、寫端 shard + Flink 批次聚合、每個 window 維護獨立聚合表（index on views）；進階選項有 sliding window、Count-Min Sketch 近似、專用 DB。

## 需求（Functional / Non-functional / 規模數字）
原文強調 top-K 變體極多，要主動釐清需求，跟隨面試官方向調整。

**Functional（Core）**
- 查詢 all-time top K 影片（最多 1k 筆）
- 查詢 1 {hour, day, month} 的 tumbling window 與 all-time（最多 1k 筆）

**Window 說明**
- Sliding window：10:06 的「過去 1 小時」= 9:06~10:06
- Tumbling window：對齊整點的完整區間，10:06 的「過去 1 小時」= 9:00~10:00
- 本題主動提議用 tumbling（較簡單），給面試官機會反對。

**Below the line**：任意時間區間（如 2025 年 10 月查 2024 年 6 月）、任意起迄點（假設都是從現在往回看）。K 上限 1k 是合理限制，要 top 1M 本質上是要全量資料，由別的系統提供。

**Non-functional（Core）**
- view 發生到被計入最多延遲 1 分鐘
- 結果必須精確（不近似；稍後 deep dive 回頭討論）
- 回應在數十毫秒內 -> 必須 precompute，從 cache 提供
- 能處理極大量 views/秒
- 能支援極大量影片

規模提示：YouTube Shorts 每日 70B views；每秒約上傳 1 小時內容。

## Core Entities & API
**Entities**：Video、View（事件）、Time Window（all time / last hour / day / month）。

**API**
```
GET /views/top-k?window={WINDOW}&k={K} -> { videoId: string, views: number }[]
```
因為 K 上限 1k，不需分頁。原文提醒不要在顯而易見處花太多時間，資深候選人要把時間留給有趣的部分。

資料入口：假設已存在一條 Kafka `ViewEvent` topic（由 video ID 分區），不需要自己設計 view API。

## High-Level Design（元件與資料流）
原則：先做出能運作但不最佳的系統，再優化；沿途告知面試官瓶頸（"elephant in the room"）。

**1) All-time top K**
```
Kafka(ViewEvent, partition by videoId) -> View Consumer -> Postgres(VideoViews: videoId, views)
Client -> LB -> Top-K Service -> SELECT videoId, views FROM VideoViews ORDER BY views DESC LIMIT k
```
views 欄位加 index，query 走已排序的 index，約 O(k)；代價是每次寫入要更新 index（O(1) append 變成 O(log n)）。明顯瓶頸：全部寫到單一 Postgres。

**2) Tumbling windows**
- 表加 timestamp 欄位（view 所屬那一小時），每個影片每個有 view 的小時一列。寫入次數不變（仍是一個 event 一次寫入），但列數爆增。
- 查詢：
```
SELECT videoId, SUM(views) FROM VideoViews
WHERE timestamp >= {start} AND timestamp <= {end}
GROUP BY videoId ORDER BY SUM(views) DESC LIMIT k
```
需要掃描，處理數十億列很慢，標記為瓶頸留待 deep dive。

## Deep Dives

### 1) 如何減少對 DB 的查詢次數？（Scaling Reads）
利用 NFR 的 1 分鐘寬限做 caching/precomputation。

**好解：快取每個 window 的 top K**：Redis/Memcached；key = `top-k:{window}:{window 起點時間戳}`（原文為 truncated_timestamp），value = 整個 response；miss 時計算後寫入（TTL 數小時）。命中時亞毫秒級，遠低於數十毫秒要求。
- 缺點：cache 過期時 (a) 湧入大量 DB 請求，(b) 這些請求都違反 SLA（top K 查詢本身慢）。(a) 可用 request coalescing（每台 server 同時間只放一個請求到 DB，其他等待）緩解，(b) 無法解決。

**最佳：cron 定期預先計算並暖 cache**：定時 job 為每個 window 預算 top K 並寫入 cache，Top-K Service 只讀 cache，永不查 DB。因為 cron 提前於過期時間執行，解決 (b)。缺點：維運複雜度（cron 失敗、落後監控）。對策：cache entry 保留數小時，cron 晚到時可暫時回傳 stale 資料而非什麼都沒有。

### 2) 如何處理海量寫入？
**估算**
- 吞吐：70B views/day / (100k 秒/day) = 700k TPS（用 100k 取代 86,400 簡化計算）。現代 RDBMS 單節點約 10k+ writes/s，遠遠不夠。
- 影片量：1 小時內容/秒 / (6 分鐘內容/影片) * 100k 秒/day = 1M videos/day；10 年 = 3.6B videos（原文後續以 4B 計）。
- 單純 ID + count 表：4B * (8 bytes ID + 8 bytes count) = 64 GB；每次需要「所有影片一份計數」就至少 64 GB。
- 估算目的是看對設計的影響，不是比心算。

**Sharding ingestion**：Kafka 本來就依 videoId 分區 -> 一個 consumer 對應一個 partition，DB 也用同樣方式分 shard。要把單 shard 壓到約 10k TPS 需 70 個 instance，仍太多。分片後 top K 要查每個 shard 再 merge（手動或用 Citus）；**各 shard 的 top K 取出後 merge，數學上保證包含全域 top K**（因為每支影片只在一個 shard）。cron 改為對每個 shard 發查詢再合併。

**Batching ingestion（Flink）**：流量集中在少數熱門影片，同一影片的 views 先聚合再寫。Flink 負責批次/聚合、checkpoint/recovery、延遲事件。使用 `BoundedOutOfOrdernessWatermarkStrategy`（容忍約 30 秒遲到事件，小於 1 分鐘）+ 1 小時 tumbling window 每影片加總。Flink 讀 Kafka，掛掉可回到 checkpoint offset 重播。結果：寫入變成每小時一大塊（需分散到各 shard，DB 對批量寫更有效率），寫入量比之前少 2-100 倍，shard 數可降到約 5-10 個。

### 3) 如何優化 top K 查詢本身？
cache miss 或預算期間，窗口查詢仍低效：要先對每影片加總 window 內所有 views，再取 top K，會處理數百 GB 資料（分鐘到小時級）。移到 Spark/Hadoop 也只是平行化並付出更高成本，senior+ 應該簡化問題而非堆硬體。原文也指出，實務上公司內部可能是資料倉儲 ETL job 定期跑再發布到 cache，但面試要展現設計能力。

**好解：粗粒度聚合**：除了每小時，再維護每日聚合；查詢月視窗加總日聚合而非 24*30 = 720 筆小時資料。做法：cron 定期查 DB 再寫回新表，或在 Flink 加更多 tumbling window（日、月）輸出到新表。缺點：cron 讀寫增加本就吃緊的 DB 負載；延遲鏈長（寫小時 -> 起 cron -> 聚合 -> 寫回 -> 再讀）。可辯稱大粒度 top-K 變動慢，新鮮度要求低，但還能更好。

**最佳：每個 window 一張聚合表（含 views index）**：例如 VideoViewsLastHour，top-K 查詢直接讀 index 達 O(k)。Flink 仍以小時粒度聚合，每次小時結束時改寫各 window 表（而非只寫小時粒度表）。代價：把複雜度從讀移到寫，要寫 4 張表。可在 Postgres 用 unlogged tables 避免 WAL、將 fsync 延後到 transaction 結尾、挑適當 batch size，但要靠 benchmark，不屬於面試範疇。

**最佳（有但書）：全在 Flink 記憶體內聚合**：用 Flink 原生分散式 state（RocksDB 將 state 放磁碟），完全移除 Postgres；Flink 內直接算 top K，每分鐘結束寫入 cache（Redis sorted set sink），不需 top-K cron。結構：Kafka source（30 秒 bounded out-of-orderness watermark）-> keyBy videoId -> RollingWindowAggregator（記憶體保存各 window 計數，window 結束時 emit VideoWindowCount）-> keyBy window -> TopKAggregator（用 heap 保留 top K，emit TopKResult）-> Redis sink。Kafka 像錄音帶，失敗可 rewind 到 checkpoint 重播。缺點：高度依賴 Flink 知識，面試官可能要求「不要用 Flink」或解釋底層；容易變成 coding / low-level design 面試。原文結論：為完整性而列，一般不建議在系統設計面試中採用。

### 4) 如果需要支援 sliding window？
沿用「每個 window 一張表」，但維護方式不同：每新增一分鐘的 views，就加上這分鐘的增量（increment），並減去 60 分鐘前那一分鐘的 views（decrement）。
- Flink 以分鐘粒度聚合；每過一分鐘：讀取 T-60 分鐘那一分鐘的 views 作 decrement，把最近一分鐘寫入 VideoViews，並用 increment - decrement 更新 VideoViewsLastHour。對每個 window（hour/day/month）都做，all-time 的 decrement 永遠為 0。
- 挑戰：現在要讀（取 decrement）也要 update，放大 DB 壓力；VideoViews 要保留一整個月的分鐘粒度資料以備遞減，產品上很浪費。
- 務實替代：向面試官提議「最近一小時」用 sliding，「日、月」維持 tumbling，符合產品體驗（月榜變動慢，小時榜變動快）。
- 另一替代：用不同 consumer group 延遲消費 Kafka，一組負責 increment，另一組負責在過期後 decrement；需要 Kafka 保留 1 個月以上，但不需保留分鐘粒度的 DB 資料，利用 Kafka log 特性。
- Flink 原生 sliding window：1 分鐘 slide 會使記憶體乘以 60 * 24 * 30 = 43,200 倍，不可行。

### 5) 可否使用近似演算法？
放寬「精確」需求：top 影片之間通常差距很大，top-K 產品多半關注趨勢而非金融級排行榜。**Count-Min Sketch (CMS)**：用多個 hash function 把 item 映射到 2D counter 陣列，只記住出現次數不記 ID，記憶體可從數百 GB 降到數百 MB。操作只有 `add(item, count)` 與 `estimate(item)`（無 list 操作，需搭配 sorted list/heap）。
流程：view 進來 -> 加到 CMS -> 立即 estimate（得到上界/近似值）-> 放入 sorted list/heap（定期截斷；因 K 最多 1000，保留 1000 筆）-> 查詢時直接取 sorted list 前 K。每個 window 各自維護一組 sketch + sorted list。

**好解：Redis**：原生支援 CMS 與 sorted set。consumer 對每個 view 做 `CMS.INCRBY` + `CMS.QUERY`，再 `ZADD` 到 sorted set，保持 1000 筆；優化：consumer 保存下界，低於 top 1000 的 item 不必 ZADD。挑戰：durability，CMS 已更新但 sorted set 尚未更新就可能不一致；從 Kafka 重建很慢，Redis AOF 難以對應 Kafka offset。不能只說「反正是近似」，原文警告簡單方案會引來面試官深入追問細節。
**最佳：Flink**：CMS 與 sorted list 都放在 Flink state（checkpointed），圖看起來差不多但這是 job 內的自訂程式碼，不是新增基礎設施。節點掛掉從 checkpoint 還原並由 Kafka 重播；比 Redis 更可靠且更有效率（記憶體內）。挑戰同前：要求面試官與你都懂 Flink 底層。
**對 sliding window 的限制**：CMS 若保證只 decrement 先前 increment 過的 item，可以支援 remove；Redis 沒有 `CMS.DECRBY`，只有 Flink 或自行實作的記憶體版本可做。這超出面試預期範圍。

### 6) 專用資料庫有發揮空間嗎？
time-series（TimescaleDB、InfluxDB）與 real-time OLAP（Druid、Pinot、ClickHouse）常被提及。原文建議：與其累積大量你不熟的專用技術，不如掌握簡單 primitives；面試官會追問原理，理解「為什麼會有 X」比只知道名字更重要。核心挑戰是**高基數（billions of videoIds）**，用 precompute 與 cache 解決。

- **爛解：InfluxDB / Prometheus**：以 videoId 做 tag/series，每分鐘寫入，用 downsampling 與 `top()`。不可行：數十億個 distinct series，`top()` 等於掃描；它們擅長寫入與窄查詢（單一 videoId 畫曲線），不擅長跨所有 series 的分析查詢。
- **好解：TimescaleDB**（Postgres + hypertables + continuous aggregates）：每小時聚合做成 hypertable（依小時與 videoId 分區）並在 views 加 index，單一小時查詢仍是 O(k)。大視窗無法直接用這些 index（60 個排序列表無法直接合併），所以用 continuous aggregates（類 materialized view）維護 last hour/day/month rollup 並在 rollup 表的 views 上建 index，加上 retention/compression policy。與自建方案非常相似，仍需 cache，且預聚合要算力所以仍需 shard。
- **好解：Real-time OLAP**：從 Kafka 進、寫入時預聚合。
  - Druid：ingestion-time rollup（時間 bucket + videoId + count aggregator），背景 compaction 將舊資料 re-rollup 到更粗粒度。
  - Pinot：star-tree index 與 materialized views 預聚合；固定模式的 top-K 可大幅 prune；也可產生離線預聚合 segments（分/時/日）。
  - ClickHouse：Materialized View -> SummingMergeTree / AggregatingMergeTree 在 ingest 時維護分/時/日 rollup，把壓力放在寫入；固定視窗讀 rollup 表 `ORDER BY views DESC LIMIT K`。
  - 挑戰：大規模下會有不穩定（節點中斷、compaction 影響 SLA），要能深入講原理並教面試官。
- 原文觀察：TimescaleDB 解法與自建方案如此相似並非巧合：好的設計通常是能最容易表達理想 data flow 的那個。

## 關鍵數字與 back-of-envelope
- 70B views/day -> 約 700k TPS（以 100k 秒/天估算）。
- 單節點 RDBMS 約 10k+ writes/s -> 若不批次需約 70 shard；批次後約 5-10 shard。
- 影片數：1M videos/day -> 10 年 3.6B（取 ~4B）；計數表 4B * 16 bytes = 64 GB。
- 批次後寫入量比原本少 2-100 倍。
- CMS 可將記憶體從數百 GB 降到數百 MB。
- Flink 原生 sliding window（1 分鐘 slide）記憶體倍增 43,200 倍。
- K 上限 1k；延遲容忍 1 分鐘；回應 10's ms；Flink watermark 容忍約 30 秒。

## 面試官期待（Mid / Senior / Staff）
- **Mid**：80/20。能給出 end-to-end 但未必最佳的方案；對瓶頸有一些洞察並能解決部分；熟悉相關技術但會有些錯誤。
- **Senior**：60/40。端到端接近最佳；找出多數瓶頸並主動解決；對 data flow 有直覺，懂 streaming vs batch 的選擇，能憑經驗比較各技術。
- **Staff+**：40/60。涵蓋未列舉的 deep dive，並能談各種替代方案；標誌是能清楚看見整個解空間並以信心和判斷力評述選項。

## 可遷移的 pattern
1. **先做能跑的簡單系統，標示瓶頸，再逐步優化**：每步告知面試官你看到的瓶頸。
2. **Precompute + cache（cron 暖 cache、stale-while-revalidate）**：把昂貴查詢移出 request path，並保留舊值避免任務遲到時無資料。
3. **依 key 對齊分片（Kafka partition = DB shard）+ 各 shard 取 top K 再 merge**：資料分區無交集時，局部 top K 的合併保證全域 top K。
4. **寫入前用 stream processor（Flink）批次聚合 + watermark 處理遲到事件**：熱門 key 先合併，寫入量降 2-100 倍，且 offset checkpoint 使錯誤可重播。
5. **把複雜度從讀移到寫（每個 window 預維護一張帶 index 的表）**；需要時用 sketch（CMS + heap）以近似換記憶體。

## 常見追問
1. **為何 tumbling 而非 sliding？** 較簡單，且對 hour/day/month 的榜單多半足夠；sliding 需 increment/decrement 並保存細粒度資料。可提議只有 last hour 用 sliding。
2. **為何 shard 後 top K 能 merge 正確？** 每影片只屬於一個 shard，每個 shard 的 top K 必包含該 shard 在全域 top K 中的成員，合併後再取 K 即為全域結果。
3. **cache 過期造成大量請求（thundering herd）怎麼辦？** request coalescing 與 cron 預算暖 cache，並保留舊 entry 數小時作 stale fallback。
4. **要求近似時怎麼做？** CMS + heap/sorted list（Redis 或 Flink state）；Flink 版本較可靠；注意 Redis 版本的 durability 與 sliding window 限制。
5. **為什麼不用 InfluxDB/Prometheus？** 數十億 series 高基數，top() 要掃全部；它們擅長單一 series 查詢而非跨 series 分析。
6. **遲到事件怎麼處理？** Flink bounded out-of-orderness watermark（約 30 秒，< 1 分鐘 SLA）。
