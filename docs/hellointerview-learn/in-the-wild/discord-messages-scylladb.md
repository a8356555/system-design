# How Discord Moved Trillions of Messages to ScyllaDB
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/discord-messages-scylladb ｜ 分類：in-the-wild ｜ 原始 eng blog：Discord Engineering, 2023-03-06（https://discord.com/blog/how-discord-stores-trillions-of-messages）

## 一句話重點
換資料庫（Cassandra → ScyllaDB）讓每次讀更便宜，但擋不住 hot partition 的流量；真正減少流量的是前面加 Rust data service，用 consistent hashing + request coalescing 把重複讀合併成一次。

## 背景與問題（規模、痛點）
- 2022 年初：177 個 Cassandra node，儲存數兆（trillions）則訊息；自 2017 起用 Cassandra。
- 單一 table：`PRIMARY KEY ((channel_id, bucket), message_id)`，`CLUSTERING ORDER BY (message_id DESC)`。bucket = 時間窗口，避免單一 partition 無限成長。partition 複製到 3 個 node。
- 寫入負載分散得很好，但讀取無法均勻：多數 live read 打最新 bucket，channel 熱度差異巨大 -> 熱門 channel 把數千讀取集中在同一個 partition / 同 3 個 node。
- 熱是因為資料本身熱門，不是 bucket 切太少；再 sharding 只會讓「依序讀 channel」這個主要查詢變複雜。
- 連帶傷害：讀寫皆 quorum（3 取 2），被熱門 channel 壓垮的 node 同時存著數千個冷門 channel，無關查詢也被拖慢。
- 維運問題：compaction 常落後（讀更慢 -> 吃掉 compaction 資源 -> backlog 更大，正回饋）；compaction 與線上流量搶 CPU/disk，加強 compaction 反而讓延遲更差；工程師靠「gossip dance」（下線一個 node 讓它 compact、回來 replay 漏掉的寫入、再換下一個）；JVM GC pause 造成延遲尖峰，最糟要重開 node。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
1. 舊：177 node Cassandra，單 table，partition = (channel, bucket)。
2. 爆：熱 partition + quorum 殃及池魚 + compaction debt + GC pause。
3. 新（儲存層）：換成 ScyllaDB —— 相同 query language / data model（schema 不用改），C++ 實作無 JVM GC；shard-per-core（每個 CPU core 處理自己那片資料與請求），單機效能更好、repair 更快。
4. 新（流量層）：API 與 DB 之間加一層 Rust data services（business logic 留在 API，data service 負責 DB 存取）。同 channel 的請求用 consistent hashing（routing key = channel_id）導到同一 instance，instance 內做 request coalescing。
5. data service 在 Cassandra 仍是主儲存時就先上線，已大幅減少 hot partition 事件，讓團隊有餘裕完成 ScyllaDB 測試調校。
6. 結果：177 -> 72 nodes；p99 read 從 40–125 ms 波動變成穩定 15 ms。

## 關鍵設計決策與取捨（這是主體，寫細）
- **區分兩個問題**：「每次讀多貴」（換 DB 解）vs「多少讀到達 DB」（coalescing 解）。快的 DB 不能阻止數千人同時讀同一筆。
- **Coalescing 機制**：第一個請求啟動 DB query，之後重疊的相同請求 join 既有 task，結果回來後同一份結果發給所有等待者。實作是 map<query key, in-flight task>，`get_or_start` 必須 atomic。例：@everyone 公告後數千人同時開 channel。
- **為何要 consistent hashing**：coalescing 只在同一 process 內有效，要讓相同資料的請求「碰頭」，必須路由到同一 instance；用 consistent hashing 讓 instance 增減時只有少量 channel 移動。
- **為何放在 data service 而非靠 DB**：ScyllaDB 的 cache 能重用底層工作，但不知道兩個獨立 RPC 在要同一則訊息；data service 看得到完整請求與 query key。
- **為何不直接 cache**：cache 也能吸收「第一次 query 結束後」的請求，但帶來 expiration / invalidation。Coalescing 較窄：永不回舊資料，只共享正在進行的工作。Discord 放棄一些 hit rate 換取簡單得多的一致性。
- **不改 schema 的遷移策略**：ScyllaDB 相容 Cassandra，風險小；data service 可獨立先上。
- **取捨**：data service 多一層 hop 與維運；coalescing 只對「時間上重疊」的請求有效；仍沒有完全消除 hot partition（原文：「went a long way」）。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 聊天 / 訊息儲存題：partition key = (channel, time bucket) + clustering 倒序的標準答案，以及為何 bucket 防止 partition 無限成長。
- Hot key / hot partition：論點「熱是流量問題不是 sharding 問題」；先 coalesce / cache，再考慮拆 key。
- 「為何不用 cache？」：coalescing 無 invalidation 問題、永遠強一致於進行中的讀。
- 資料庫選型：write-heavy 選 LSM（Cassandra/Scylla），但要預期 compaction、GC 帶來的維運成本。

## 相關題目
- [WhatsApp](../../hellointerview-breakdowns/whatsapp.md)（訊息儲存）
- [Distributed Cache](../../hellointerview-breakdowns/distributed-cache.md)（hot key、thundering herd）
- [Ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（熱門資源的流量集中）

## 自測問題（3-5 題附簡答）
1. 為什麼 (channel_id, bucket) 當 partition key，而讀還是會 hot？ 答：bucket 只防 partition 無限成長並分散寫入；多數讀取打最新 bucket，熱門 channel 把讀集中到同一 partition 的 3 個 replica。
2. 為何熱門 channel 會拖慢不相關查詢？ 答：同 node 也存著數千冷門 channel 的 partition，且 quorum 讀寫要等 2/3 replica，被壓垮的 node 拖慢所有需要它的查詢。
3. Request coalescing 為何需要 consistent hashing？ 答：合併只發生在同一 process 內，必須讓同資料的請求都落在同一 instance；consistent hashing 在 instance 增減時只搬少量 key。
4. Coalescing 與 cache 的差別？ 答：coalescing 只共享進行中的 query，不回舊資料、無 invalidation，但 hit rate 較低；cache 吸收更多請求但要處理過期與失效。
5. ScyllaDB 解決了什麼、沒解決什麼？ 答：解決 JVM GC 與維運、單機效能；沒解決熱 partition 的流量集中，那要靠減少到達 DB 的讀取。
