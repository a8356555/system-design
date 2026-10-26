# Time Series Databases
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/time-series-databases ｜ 分類：deep-dives

## 一句話重點
TSDB 的高吞吐來自一組簡單想法的組合：append-only + LSM tree + delta/XOR 壓縮 + 時間分區 + Bloom filter + downsampling + block metadata；但這一切建立在「低 cardinality tag、規律資料、小 delta」的假設上，假設被打破（如 user_id 當 tag）就比通用資料庫更糟。

## 它是什麼 / 核心機制

### 先決警告
有時間序列資料不代表需要 TSDB。Top-K 題是經典例子：看似適合 TSDB，但需要跨海量 series 排序與聚合，多數 TSDB 不擅長。建議先把通用 DB（Postgres / DynamoDB）撐到極限，遇到真正瓶頸才用專用技術。

### 動機範例（為何 vanilla Postgres 撐不住）
- 100,000 台 server，每台每 10 秒送 5 個 metric（CPU、memory、disk I/O、network）→ 50,000 metrics/sec，約 43 億筆/天，約 300 億筆/週。
- 簡單查詢（host-42 過去一小時平均 CPU）在大表上很慢；加 index 又拖累寫入；50,000 writes/sec 起跳（burst 更高）會壓垮單台 Postgres；每列重複存 host 與 metric name → 每點 50-100 bytes，實際資訊（timestamp + float）只有 16 bytes。
- InfluxDB、TimescaleDB、Prometheus 即為此負載而生。

### 構成元件
1. **Append-only storage**：不就地更新，永遠寫到檔尾。傳統更新要 find → read → modify → write，是 random I/O（HDD 只有約 100-200 ops/sec；SSD 也偏好循序）。Append-only 只有 sequential write：SSD 可達數十萬次/秒循序寫入，HDD 也可達數萬。
2. **LSM tree**（InfluxDB、Cassandra、LevelDB 的核心）：
   - 寫進記憶體 memtable（排序結構，如 red-black tree / skip list）→ 滿了 flush 成不可變的排序檔 SSTable（循序寫）→ 背景 compaction 合併小 SSTable、去除重複與 tombstone。
   - 排序的好處：binary search 點查、range query 相鄰、compaction 時 merge sort。
   - 寫入不阻塞於讀取。代價：讀可能要查多個 SSTable；write amplification（compaction 反覆重寫）。適合高寫入、願意用讀效能換寫效能。
3. **Delta encoding + 壓縮**：相鄰值相近 → 存差值；varint 讓小數字只占 1-2 bytes（1 約 1 byte、1,000,000 約 3 bytes）。
   - Timestamp 用 delta-of-delta：規律的 10 秒間隔，delta-of-delta 全是 0 → 幾乎零開銷。Facebook Gorilla 論文：timestamp 平均可壓到約 1 bit/值。
   - Float 用 XOR 壓縮：相近浮點 XOR 後大量前導 0，只存第一個不同 bit 的位置與有意義的 bits；一般約 1.37 bytes/值（vs raw double 8 bytes）。原文提醒不必背 1.37，重點是對冗餘多的資料可有強壓縮。
4. **Time-based partitioning**：依時間窗（天/週）分區（不一定在不同機器，需要時可以）。TimescaleDB 稱 chunk，Prometheus 也有。好處：寫入都進「now」分區、不需決定路由；讀取只看相關分區；retention 只要丟掉舊分區檔案，無須昂貴的 DELETE。
5. **Bloom filter**：每個 SSTable 維護自己 key 的 Bloom filter，回答「一定不在 / 可能在」且零磁碟 I/O；允許 false positive、不會 false negative。調校良好約 10 bits/key、1% false positive；數十個 SSTable 的讀取可降到 1-2 次。對「長時間範圍只找單一 series」特別有用。
6. **Downsampling / rollups**：背景預先聚合（min/max/sum/count）。範例政策：24 小時內原解析度（10 秒）、7 天內 1 分鐘平均、30 天內 5 分鐘平均、1 年內 1 小時平均。查上個月平均 CPU 讀 5 分鐘 rollup，資料量比原始 10 秒少 288 倍。以儲存與寫入放大換取歷史查詢速度。Ad Click Aggregator 也用此技巧。
7. **Block-level metadata**：每個 block 記 min/max timestamp（有時含 min/max value），查詢時做 block pruning（例：查 CPU > 10%，block 值域 0-5% 就整塊跳過）。

### 資料模型
- Measurement（類似 table，如 cpu_usage）、Tags（有 index 的 metadata，用於過濾，如 host、region）、Fields（實際測量值，無 index）、Timestamp。
- 例：`cpu_usage,host=server-1,region=us-west value=45.2 1699999200000000000`
- tag vs field 選錯 → 查詢慢或 cardinality 爆炸。

### Storage engine 流程
- 寫入先到 WAL（durability，crash 可恢復）→ 同時進 in-memory buffer（依 measurement + tag 組合組織，即 memtable）→ 達門檻 flush 成不可變、壓縮的檔案 → 背景 compaction。
- 檔案：Header → 各 block（timestamps 用 delta-of-delta + varint；values 用 XOR）→ 檔尾 Index（series → block offsets）→ Footer。查特定 series = seek index + seek data，兩次磁碟操作，與檔案大小無關。

### 查詢執行
1. 依時間過濾挑出相關 partition；2. 在記憶體 tag index 查 tag filter 得到 series；3. 讀 buffer（最新）與磁碟檔（較舊）並合併；4. 串流式邊讀邊聚合（不必全載入記憶體）。
- 善用 time locality 與 series locality。

### Worked example（多 tag 查詢）
- 每個 measurement + tag 組合 = 一條 series；例子 4 條 series。每 series 的資料在檔案中連續成壓縮 block；範例 block 由 32 bytes 壓到約 13 bytes（約 60% 減少）。
- Tag index = inverted index（同 Elasticsearch 的概念，只是 tag value → series，而非 word → document）。
- 查 `region='us-west' AND env='prod'`：查 tag index → 取 series 集合交集（Series 1, 2）→ 查 file index 取 block 位置 → 只讀 Block 0、1（跳過 us-east 的）→ 套時間過濾 → 計算 mean（範例結果 54.1）。
- 對比 Postgres：就算有 index，仍需抓分散各處的 row 再取 value 欄；TSDB 把需要的資料物理上放在一起（寫入優化輔助讀取）。

## 何時用 / 何時不用
- 用：高吞吐 metrics/監控/事件資料，多為 append、依時間範圍查詢、tag 低 cardinality、資料規律。原文宣稱在目標負載上約比通用 DB 好 10-100 倍。
- 不用：Top-K 這類需跨大量 series 排序/聚合；高 cardinality 的查詢維度；一般情況先用 Postgres/DynamoDB 撐。
- 若不確定 TSDB 的資料假設，退回熟悉技術比硬用不懂的技術好（staff+ 的標誌是理解資料假設）。

## 面試常考的進階點
1. **Cardinality problem（最重要失效模式）**：cardinality = 唯一 tag 組合數。1,000 hosts × 50 metrics = 50,000 series 可接受；若加上 10 million 唯一 user_id tag → 約 5000 億潛在 series。TSDB 在記憶體維護所有 series 的 index，會 OOM 且查詢變慢。→ user ID、request ID 等高 cardinality 值只能當 field、不能當 tag；可寫入，但失去 TSDB 讀取優勢。
2. **LSM 取捨**：寫入吞吐 vs 讀放大 + write amplification；Bloom filter 與 block metadata 補償讀取。
3. **Retention 設計**：time-partition 讓刪除 = drop file；與 downsampling 配合（細粒度短保存、粗粒度長保存）。
4. **需求協商技巧**：面試官說「10 秒樣本存 1 年」，你可以說只需一週細粒度，之後 downsample 成 5 分鐘平均存一個月 → 預見問題、說明挑戰、提出替代（即使被否決也展現 staff+ 思維）。
5. **WAL + memtable 的 durability**：crash 後由 WAL 回復尚未 flush 的資料。
6. **為何比 Postgres 快**：避免 random I/O、每點 bytes 數大幅壓縮（50-100 bytes → 個位數 bytes）、series 資料物理共置、tag index 先縮小範圍、partition 與 block pruning。
7. **模式可遷移**：append-only、LSM、Bloom filter、rollup、time partition 在其他 infra 題也適用（Cassandra、Ad Click Aggregator）。
8. **後設題**：「這題真的需要 TSDB 嗎？」— Top-K 反例。
9. **（補充）** Prometheus 為 pull-based、單節點為主；水平擴展常搭配 Thanos / Cortex / Mimir 等——原文未涉及，僅供延伸。

## 關鍵數字
- 範例規模：100,000 servers × 5 metrics / 10 秒 = 50,000 metrics/sec ≈ 4.3B points/天 ≈ 30B rows/週。
- Postgres 每點 50-100 bytes vs 實際資訊 16 bytes。
- HDD random 約 100-200 ops/sec；SSD 循序寫入可達數十萬/秒；HDD 循序可達數萬/秒。
- Gorilla：timestamp 約 1 bit/值；float XOR 約 1.37 bytes/值（vs 8 bytes）。
- Bloom filter：約 10 bits/key、約 1% false positive。
- Rollup：5 分鐘 vs 10 秒 = 288 倍資料量差。
- 整體：目標負載上比通用 DB 好約 10-100 倍。

## 相關題目
- [Metrics Monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（downsampling）
- [Top-K](../../hellointerview-breakdowns/top-k.md)（反例：TSDB 不適合）

## 自測問題
1. 為何 vanilla Postgres 存 50,000 metrics/sec 會出問題？
   答：寫入吞吐壓垮單機、index 拖慢寫入、數百億列使查詢慢、每列重複存 host/metric name 導致每點 50-100 bytes。
2. Delta-of-delta 與 XOR 壓縮分別用在哪、為何有效？
   答：timestamp 間隔規律 → delta-of-delta 趨近 0（~1 bit/值）；float 相鄰值相近 → XOR 後多為 0，只存有意義 bits（~1.37 bytes/值）。
3. 什麼是 cardinality 爆炸？怎麼避免？
   答：唯一 tag 組合數過大（如 user_id 當 tag）→ 記憶體 series index 爆、查詢變慢。高 cardinality 值放 field 不放 tag（但失去查詢優勢）。
4. 時間分區帶來哪三個好處？
   答：寫入集中於當前分區、讀取只掃相關分區、retention 直接刪舊分區。
5. 為何 Top-K 不適合直接用 TSDB？
   答：需跨海量 series 排序/聚合，這不是 TSDB 設計的強項；通用方案反而較合適。
