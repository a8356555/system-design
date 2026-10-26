# Indexing the Data Lake for Online Point Queries（Random Access Parquet, RAP）
> 原文：https://engineering.atspotify.com/2026/7/indexing-the-data-lake-for-online-point-queries/ ｜ Spotify / 2026-07 ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DcvtilziDyC（2026-09-01）

## 一句話重點
RAP 用放在 Parquet 檔外的 external index（key -> file ordinal + row numbers）搭配寫入端排序，讓同一份 Parquet 同時服務 batch analytics 與毫秒級 online point query。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
（注意：抓到的貼文只含七點中的前三點，後四點缺漏。）
- 問題不在 GCS 速度：單次請求 30-100ms 沒問題，瓶頸是 Trino、BigQuery 這類 SQL engine 的 scheduling overhead，即使只查一行也要等好幾秒才開始讀資料。
- External index 直接定位：Parquet 內建 Bloom filter 只能說「這個 key 不在這裡」，沒法告訴你在哪；RAP 的 index 是 definitive 的，給 key 就回傳 file ordinal 與 row numbers，完全跳過 scan。
- Sort by key：同一 user 的 rows 集中在同一 page，一次 ranged read 就拿到，不必跨多 page。
- 作者的整體框架：data lake 存 exabytes，卻讓「查一個 user」要好幾秒；RAP 讓一份檔案服務兩種存取模式。

## 原文重點（背景/規模數字 → 問題 → 架構與設計決策 → 取捨 → 結果；這是主體）
原文的完整整理已在既有筆記，不在此重寫：[Spotify Data Lake Point Queries](../../hellointerview-learn/in-the-wild/spotify-data-lake-point-queries.md)。一句帶過：外部 multimap index 解析到 row，並行 ranged read，只讀目標 page，必要時 covering index 免讀儲存。

**本篇相對既有筆記的補充（來自原文，既有筆記較少著墨）**
- 原文還列出降低「讀取量」與「讀取次數」的選項：
  - 讀取量：一個 key 一個 page（每個 key 邊界約 20 bytes 開銷）；ZSTD frame reset，保留一般 page 大小但犧牲 delta/run-length 編碼以換取 frame 層級可定址；storage alignment 把 key 之間補齊到 4KB/16KB 邊界（原文稱為 micro-optimization）。
  - 讀取次數：Blob/Variant 欄位（每個 key 讀單一欄，但失去 batch 分析的 per-field column pruning）；interleave columns（單次連續讀取跨所有欄位，代價是一般 reader 單欄掃描 I/O 變多）；covering index（把小值上提到 index entry，讀取次數為零）。
  - Co-grouping：用 nested/repeated column 讓每個 key 一列；較粗的分區（週 vs 日）減少每 key 檔案數，但犧牲 batch 查詢的 partition pruning 粒度。
- 原文雲端延遲參考：S3 Express One Zone、GCS Rapid Storage 為個位數毫秒。
- 規模經驗法則：TB 資料產生 GB 級 index；PB 資料產生 TB 級 index，大 index 用 hash bucketing 分散。

## 面試怎麼用
- 作者的重點可濃縮成講法：「慢的是 query engine 的規劃成本，不是 object storage」，先診斷瓶頸再選方案。
- 與其複製一份到 KV store（Bigtable/DynamoDB），不如在原檔上疊索引：省一份 storage、免維持兩份一致、免 migration。
- Bloom filter（機率、只能排除）vs external index（確定、可定位）的對比，是索引題的好切角。
- 取捨：寫入端排序與 page 切法會影響 batch 掃描壓縮與 pruning，要說明「一份資料兩種存取」不是免費的。

## 相關筆記
- [Spotify Data Lake Point Queries（既有筆記，含完整原文整理與自測題）](../../hellointerview-learn/in-the-wild/spotify-data-lake-point-queries.md)
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)（索引設計）
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
