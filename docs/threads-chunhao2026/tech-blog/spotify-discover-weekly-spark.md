# Apache Spark in Spotify（Discover Weekly 與規模化批次運算）
> 原文：未取得（貼文只附 wondering.app 課程大綱連結 https://wondering.app/learn/apache-spark-for-engineers-5-real-world-c91d611aed5f199957b95a60，非 Spotify 原始 eng blog；WebSearch 也找不到 Spotify 官方明確以 Spark 描述 Discover Weekly 的文章） ｜ Spotify / 日期不詳 ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/Deo6A1SD6mx（2026-10-18）

## 一句話重點
Discover Weekly 的本質是「固定時間窗口內掃過全站聽歌紀錄」的規模問題；用 Spark 把資料切分到大量機器平行算，並盡量把中間結果留在記憶體，才趕得上週一發布。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- Discover Weekly 不是什麼厲害演算法，而是跟時間賽跑的資料處理工程。
- 數億用戶、每人週一都要拿到重算過的 30 首歌；系統要在固定窗口內掃過所有人的聽歌紀錄，找出口味相近的人在聽什麼。
- 單機跑光讀資料可能就要好幾天（作者推估，非原文數字），趕不上週一早上。
- Spark：切分資料、分散到成百上千台機器、再合併，是標準 distributed computing 套路。
- Spark 盡量把中間結果留在記憶體，不像早期 Hadoop MapReduce 每步寫回硬碟；對需反覆比對相似度的流程，差別就是準時發布 vs 拖到下午。
- 結尾拋問題：有沒有遇過資料大到單機跑不完、逼你研究 distributed computing 的經驗？

## 原文重點（背景/規模數字 → 問題 → 架構與設計決策 → 取捨 → 結果；這是主體）
原文未取得，此節不編造 Spotify 內部細節。能確認的範圍：
- 貼文的學習來源是 wondering.app 的課程大綱，不是 Spotify 工程文章。
- 查得到的相關公開資料只有間接證據：@Scale 2016 的演講「Creating and scaling Spotify's Discover Weekly playlist」頁面僅提到「30 首個人化歌曲、每週一推送、推出後超過 5B streams / 40M 使用者」，頁面本身沒有 Spark 架構細節。Spotify 官方 blog 對資料處理另有 Scio（Apache Beam / Dataflow 的 Scala API）的文章，亦未確認與貼文所述 Spark 流程的對應。
- 因此貼文中「Spark 用於 Discover Weekly」「記憶體 vs MapReduce」只能視為作者或課程的教學性說法，未經原文驗證。

**通用技術背景（補充，非來自 Spotify 原文）**
- Spark：資料分區（partition）後在多 executor 平行處理，shuffle 時合併；RDD/DataFrame 可 cache 於記憶體，迭代型演算法（如 ALS 矩陣分解）比每輪落盤的 MapReduce 快。
- 這類推薦批次通常流程：收集 listening logs -> 平行計算 user/track 相似度或 embedding -> 產出每人 top-N -> 寫入 serving store 供快速讀取。（補充）

## 面試怎麼用
- 「離線批次推薦」題：先講為什麼是 batch（週更、可預算），而不是即時算；用 SLA（週一早上前完成）反推需要的平行度。
- 解釋 Spark vs MapReduce：中間結果留記憶體、減少磁碟 I/O，適合迭代型計算；也要講代價（記憶體成本、shuffle、資料傾斜、失敗重算靠 lineage）。（補充）
- 預算結果、讀取便宜：算好的 30 首清單寫進 key-value store，使用者開 app 只做一次 lookup。（補充）
- 引用時務必註明這是教學性案例，不是 Spotify 官方架構。

## 相關筆記
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)（batch vs stream 聚合）
- [FB News Feed](../../hellointerview-breakdowns/fb-news-feed.md)（預先計算 vs 即時計算）
- [Top K](../../hellointerview-breakdowns/top-k.md)
