# How Spotify Serves Point Queries from an Exabyte Data Lake
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/spotify-data-lake-point-queries ｜ 分類：in-the-wild ｜ 原始 eng blog：Spotify Engineering（原文標示 2026-07-27；https://engineering.atspotify.com/2026/7/indexing-the-data-lake-for-online-point-queries/）

## 一句話重點
Spotify 的 RAP（Random Access Parquet）是一個放在資料檔「外面」的索引，記錄每個 key 在哪個檔案的哪些 row，加上寫入端調整（同 key 排在一起、key 變更就開新 page、小值直接放進索引），讓 data lake 不需第二份拷貝也能做 point query。

## 背景與問題（規模、痛點）
- Data lake = 物件儲存（GCS / S3）上的檔案；分析（Trino、BigQuery）與 ML 訓練直接掃檔案。Spotify 在 GCS 保存 exabytes，完整歷史而非近期窗口，且單一副本作為真相。
- Parquet 欄式：值按欄打包，檔案切 row group、再切 page，footer 描述位置；同欄值壓縮好，可跳過不需要的 page。適合「過去一週各國平均收聽時間」這種掃兩欄的查詢。
- 但「某個人聽了什麼」是散落在許多檔案的數百 bytes：要拖整個大 page，還要付完整分散式查詢計畫成本（Trino / BigQuery 把任何 query 都排成分散式分析 job）。物件儲存本身不是元兇：GCS 請求 30–100 ms，S3 Express One Zone 與 GCS Rapid Storage 已到個位數 ms；貴的是讀取周圍的一切。
- 常見解法：把需要快的資料複製到 Bigtable / DynamoDB（按 GB 計價的第二份拷貝），團隊因而要配給「值得線上服務」的資料；其餘留在 lake 但太慢。
- AI agent 會比人類問更多問題，讓這個取捨更尖銳。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
1. 規模：數億使用者，一天的收聽事件約落在 1,000 個檔案；一個約 90 天的窗口 = 90,000 個候選 Parquet 檔（GB 到 TB 掃描量）。
2. 第一步，依查詢維度 bucket：路徑如 `date=2026-07-14/bucket=0427/part-00031.parquet`；`hash(user_42) % 1000 = 427`，確定性排除其他 bucket。每天 1 個候選檔，90,000 -> 90。
3. 第二步，Bloom filter（每檔 user-ID 欄一個，快取在 metadata store，只能確定「不存在」）：90 -> 約 12 個（該使用者真正活躍的天）。
4. 問題：仍要打開檔案，一連串相依讀取（footer -> row group metadata -> 掃 key 欄 -> column/page index -> 目標 page），無法平行。
5. RAP 外部索引：builder job 讀現有 Parquet 的 footer 與 page 位置並掃 key 欄，寫出 key -> 精確位置的對應，不動原檔。每次 pipeline 執行 append 一個新 index fragment，舊 fragment 不修改（增量維護便宜）。查詢變成「一次索引命中 + 一輪平行 ranged read」。
6. 寫入端優化：同 key 實體相鄰（排序，常近乎免費）、key 改變就開新 page（每個邊界約 20 bytes header）；page 從 ~4 MB 夾帶數千其他使用者的 100 bytes，變成只含該 key。檔案仍是標準 Parquet，其他 reader 不受影響。
7. Covering index：builder 掃 row 時順便把小值甚至預先聚合（事件數、總播放時間）直接複製進索引 entry，可完全不讀儲存。每個命中檔案最後是一次幾 KB 的 ranged read 或零讀取。
8. 原文提醒：無端到端延遲數字，也沒有採用範圍，財務論述是主張而非量測，須帶懷疑。

## 關鍵設計決策與取捨（這是主體，寫細）
- **外部、確定性的索引 vs 剪枝**：Parquet min/max 的 skip 是精確的「這裡不可能有」；Bloom filter 是機率式（確定沒有或可能有）；剪枝只能告訴你哪裡「不是」。RAP 是確定性的，直接解析到 row number（近似常數時間），再用快取的檔案 metadata 轉成 byte range，發出彼此獨立的平行 ranged read。
- **索引結構**：multimap（一個 user ID 出現在多檔多 partition）。每個 entry：key（可為複合鍵，如 user_id + date）、檔案（dictionary-encoded ordinal 而非完整路徑，因同樣少數路徑重複於數百萬 entry）、檔案內 row numbers、可選的 value count（可分頁而不需先抓取）。索引大小：1 TB 資料產生 GB 級索引；1 PB 產生 TB 級。大索引用 key hash 分 bucket，與資料檔相同手法。
- **page 是最小可定址單位**：你不能只讀半個 page，page 可大到約 4 MB 而目標 row 只有約 100 bytes；工程師常誤以為可讀單一 byte，被 OS 與 page 邊界打臉。效能圍繞原子資料單位設計。這就是為什麼必須改寫入端。
- **不拷貝、不重寫 pipeline**：與既有基礎設施疊加（原文所稱 organic system design），沒有大遷移或資料碎片化；同樣的檔案既供 BigQuery 掃週報，也回答一個人的問題，成本約一次儲存讀取。
- **Secondary index**：因 RAP 是蓋在不修改的檔案上的結構，加第二維度（如 seller_id）只是服務層的決定，建另一個存取結構即可；「新索引花一個索引，而非一次 migration」。對比 DynamoDB secondary index 是資料的受管拷貝。取捨：檔案仍按原 key 排序 / bucket，seller_id 查詢會散落到更多檔案，只能靠合併相鄰 byte range 緩解，永遠不如主鍵便宜。
- **連續譜觀點**：資料在「便宜、適合掃描」與「貴、適合 point lookup」之間；RAP 多了一個點，便宜到不必配給。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 「資料湖 / 物件儲存上做低延遲查詢」：bucket -> Bloom filter -> 外部索引 的分層縮小搜尋空間。
- 索引設計論點：covering index、secondary index、append-only fragment 的增量維護；索引大小遠小於資料。
- 儲存格式意識：欄式適合掃描、不適合點查；page / block 才是 IO 的真實單位。
- 「不要為了快就多一份拷貝」：在成本、一致性、遷移風險上的論述。

## 相關題目
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（OLAP / 資料湖）
- [Metrics Monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)（欄式儲存與壓縮）
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)（索引設計）
- [Distributed Cache](../../hellointerview-breakdowns/distributed-cache.md)（拷貝到快取的替代方案）

## 自測問題（3-5 題附簡答）
1. 為什麼 data lake 適合掃描卻不適合 point lookup？ 答：Parquet 欄式 + 大 page，找散落的少量 row 要拖整個大 page 且付分散式查詢計畫成本；問題不在物件儲存延遲（GCS 30–100 ms）。
2. bucket 與 Bloom filter 各把 90,000 檔縮到多少？ 答：bucket 後 90（每天 1 個），Bloom filter 後約 12；兩者都只是剪枝，之後仍需相依讀取。
3. RAP 與 Bloom filter / min-max 的本質差異？ 答：後者只告訴你哪裡不可能有；RAP 是確定性外部索引，直接給檔案與 row number，可平行 ranged read。
4. 為何還要改寫入端？ 答：page 是最小讀取單位（可到 ~4 MB），要把同 key 排一起並在 key 變更時開新 page，才能讓 page 只含目標 key；covering index 甚至可免讀。
5. Secondary index 的代價？ 答：檔案仍按原 key 排序 / bucket，次要鍵查詢散在更多檔案，只能合併相鄰 byte range，永遠不如主鍵查詢便宜。
