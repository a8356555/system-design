# Data Structures for Big Data
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/data-structures-for-big-data ｜ 分類：deep-dives

## 一句話重點
用機率型／近似資料結構（Bloom filter、Count-Min Sketch、HyperLogLog、approximate quantiles）以固定小記憶體換取「可控誤差」，常能改變問題規模；但簡單 hash table 夠用時用它們是紅旗。（by agents）

## 原文大綱（原文）
公開介紹（原文大意）：有些系統要處理極大量資料，單純加機器不夠；專用資料結構可能改變問題形狀。但這類結構不常見是有原因的——在簡單 hash table 即可時使用 bloom filter 會被面試官視為紅旗。對新手不建議從這裡開始，應先熟悉 caching、load balancing、partitioning 等核心。

公開的 Bloom filter 直覺（原文大意）：用「村莊 1,000 人、每人一枚蓋章、一張紙」類比——章的痕跡都被蓋到 → 「可能」出席；有格子沒被蓋到 → 「絕對」沒出席；紙被蓋滿（飽和）則失效。結論：可證明「不在集合中」，不能證明「在集合中」。

章節標題（原文）：
- Bloom Filter：Intuition / How it Works / Use-Cases and Pitfalls（Web Crawling、Cache Optimizations）
- Count-Min Sketch：Intuition / How It Works / Use-Cases and Pitfalls（Top K、Caching）
- HyperLogLog：Intuition / How it Works / Use-Cases and Pitfalls（Analytics and Metrics Systems、Security、Cache Sizing and Analysis）
- Approximate Quantiles：Intuition / How it Works（Fixed-Width Buckets、Exponential Buckets、Dynamic Histograms）/ Use-Cases and Pitfalls（Performance Monitoring、SLOs、A/B Testing and Analytics、Load Balancing and Auto-scaling）
- Conclusion

## 內容（by agents）
### Bloom Filter（by agents）
- **How it works**：長度 m 的 bit array + k 個 hash function。insert：k 個位置設為 1；query：k 個位置全為 1 → 「可能存在」，任一為 0 → 「一定不存在」。無 false negative，有 false positive。不能刪除（counting bloom / cuckoo filter 可）。
- **容量公式**：false positive 率 p ≈ (1 - e^(-kn/m))^k；最佳 k = (m/n)·ln2；每元素約需 1.44·log2(1/p) bits。例：p=1% 約 9.6 bits/元素，p=0.1% 約 14.4 bits。10 億 URL、1% FP ≈ 1.2 GB。
- **Web Crawling**：用 bloom filter 判斷 URL 是否已爬過，省去對巨量 URL 集合的查詢；偶爾漏爬（FP）通常可接受。見 [web-crawler](../../hellointerview-breakdowns/web-crawler.md)。
- **Cache Optimizations**：在 cache/DB 前放 bloom filter 擋住「不存在的 key」查詢，防 cache penetration；LSM 的 SSTable 也用它跳過檔案（見 db-indexing）。
- **Pitfalls**：飽和後 FP 率飆升（需預估 n、必要時 scalable bloom filter 重建）；不能刪除；需要「精確」判斷時不可用（如已付款去重）；多 instance 同步（可放 Redis 的 RedisBloom）。

### Count-Min Sketch（by agents）
- **How it works**：d 列 × w 欄的計數器矩陣，每列一個 hash。更新：每列對應欄 +1；查詢：取 d 個計數器的最小值。只會高估（hash 衝突），不會低估。誤差：以機率 1-δ 保證 估計 ≤ 真值 + ε·N；w = ⌈e/ε⌉、d = ⌈ln(1/δ)⌉。
- **Top K**：Sketch 估頻率 + min-heap 維護候選 K 個，記憶體與資料基數無關。見 [top-k](../../hellointerview-breakdowns/top-k.md)。
- **Caching**：TinyLFU 用 CM sketch 估 key 的存取頻率，作為 admission policy（Caffeine 快取採用）。
- **Pitfalls**：高估偏誤對「長尾低頻 key」影響大（噪音超過其真實頻率）；只適合找 heavy hitter；不可列舉 key；跨節點可用「逐格相加」合併（mergeable）；需要精確帳務（計費、廣告扣款）不可用。

### HyperLogLog（by agents）
- **How it works**：對每個元素 hash，取前 b bits 選 bucket，後面位元的「前導 0 的個數 + 1」記錄最大值；以調和平均估算 cardinality。標準誤差 ≈ 1.04/√m；Redis 用 16384 個 6-bit register（12 KB）、標準誤差 0.81%，可數到 2^64 級基數。可 merge（取 max），可做 union，不易做 intersection。
- **Analytics and Metrics**：近似 DAU/UV、每個 URL 的獨立訪客；每個 key 只需 ~12KB。見 [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（unique users）。
- **Security**：偵測異常（單一 IP 在短時間打到的獨立 user/路徑數暴增）、DDoS / scan。
- **Cache Sizing and Analysis**：估算 working set 的獨立 key 數，以決定 cache 容量。
- **Pitfalls**：只能算「有多少種」，不能列出是誰、不能刪除；小基數誤差相對較大（有 small-range correction）；不適合需精確去重的計費。

### Approximate Quantiles（by agents）
- **問題**：p50/p95/p99 不能像平均值那樣合併；精確算需要存所有資料。
- **Fixed-Width Buckets**：等寬 histogram，簡單但長尾解析度差。
- **Exponential Buckets**：bucket 邊界等比（如 Prometheus histogram、HdrHistogram）→ 對 latency 這種長尾分佈相對誤差一致；可跨 instance 逐桶相加合併。
- **Dynamic Histograms / sketches**：t-digest、DDSketch、GK、KLL：自適應調整，尾端精度高，可 merge。DDSketch 保證相對誤差。
- **Performance Monitoring / SLOs**：每台機器本地記 histogram，匯總時合併桶再算 p99（切勿對各機 p99 取平均）。見 [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)。
- **A/B Testing & Analytics**：比較兩組 latency 分佈而非僅平均。
- **Load Balancing & Auto-scaling**：以尾端延遲（p95/p99）作為擴縮或路由訊號。
- **Pitfalls**：bucket 邊界選錯造成 p99 誤差大；Prometheus 對 histogram 的 quantile 為在桶內線性內插的估計。

### 面試使用原則（by agents）
1. 先問：精確解法的記憶體算得出嗎（10 億 × 8 bytes ≈ 8GB，一台機器放得下）？放得下就別用近似結構。
2. 說出誤差方向與可接受性（FP vs 高估 vs 相對誤差）。
3. 說明可合併性（mergeable）→ 分散式聚合的關鍵。
4. 為何是紅旗：增加複雜度與誤差，卻沒帶來必要的規模收益。

## 關鍵數字（by agents，附來源）
| 結構 | 記憶體 | 誤差 | 來源 |
|---|---|---|---|
| Bloom filter | ~9.6 bits/元素 @1% FP；14.4 bits @0.1% | 單邊（只有 FP） | 公式推導，見 Wikipedia |
| HyperLogLog (Redis) | 最多 12 KB / key | 標準誤差 0.81% | Redis 官方文件 |
| Count-Min Sketch | w=⌈e/ε⌉, d=⌈ln(1/δ)⌉ | 單邊高估，≤ε·N | Cormode & Muthukrishnan 2005 |

## 相關題目
- [top-k](../../hellointerview-breakdowns/top-k.md)
- [web-crawler](../../hellointerview-breakdowns/web-crawler.md)
- [ad-click-aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)

## 自測問題（by agents）
1. Bloom filter 能出現 false negative 嗎？答：不能；只有 false positive。
2. CM Sketch 為何只高估？答：不同 key 共用計數器，只會多算；取 min 降低但不消除。
3. 為何不能平均各機器的 p99？答：分位數不可線性合併；須合併 histogram / sketch 後再計算。
4. Redis HLL 12KB 為何能數十億基數？答：只存 bucket 內最大前導零，記憶體與基數幾乎無關。
5. 何時不該用 Bloom filter？答：資料量可放進 hash table、或不容許 FP（付款去重）。

## 參考來源
- Redis HyperLogLog docs: https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs/
- Bloom filter (Wikipedia, 公式): https://en.wikipedia.org/wiki/Bloom_filter
- Cormode & Muthukrishnan, An Improved Data Stream Summary: The Count-Min Sketch (2005)
- Flajolet et al., HyperLogLog (2007)
- DDSketch (Datadog, 2019): https://www.vldb.org/pvldb/vol12/p2195-masson.pdf
- Prometheus histograms: https://prometheus.io/docs/practices/histograms/
（以上引用自既有知識；2026-10-19 已確認連結可開啟（HTTP 200），內容未逐條比對。）
