# Behind the Scenes: Evolving Netflix's Ads Event Pipeline for Live — Part II
> 原文：https://netflixtechblog.medium.com/behind-the-scenes-evolving-netflixs-ads-event-pipeline-for-live-part-ii-826ebf9ad9fb ｜ Netflix（作者 Yogesh Nagarur） / 轉載站標示 2026-10-14（早於貼文日期，可能是轉載日，未確認） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DcTdHu2D6pP（2026-08-21）

> 取得方式備註：medium 與 netflixtechblog 直連皆 403；內容來自轉載站 noise.getoto.net 的整理，細節以其為準。貼文本身只列出第 1 點，其餘 5 點的作者解讀未取得。

## 一句話重點
把「同步寫 Metadata Registry」從 ad serving critical path 拿掉，改成 Flink 有狀態 streaming join，並在每個環節選「夠精準的保證」（best-effort + 下游 idempotent）而非理論最強規格。

## 作者的解讀（貼文重點）
- 最印象深刻的不是架構本身，而是每處都選「夠精準的保證」，不是「理論上最高規格」。
- 共整理 6 個關鍵設計（貼文抓到的只有第 1 個）。
- 設計 1：原本每次廣告出現都要先同步寫 Metadata Registry、等 ack 才能送廣告；新做法 ad server 只把 response 丟進 Kafka，下游 Flink job 做 streaming join，Registry 不再在 serving 路徑上。

## 原文重點
### 背景 / 規模
- Part I 把分散的 pipeline 收斂成集中收集、enrichment、標準 data contract 的 Ads Event Publisher，下游包含 frequency capping、metrics、billing、measurement partners、reporting。
- Live 場景：Jake Paul vs. Mike Tyson 賽事期間超過 1 億 concurrent viewers；Netflix 營運 25,000+ Flink jobs。

### 問題（舊架構）
Ad serving 需同步寫 Registry，在 live 規模下：
1. Scaling 瓶頸：每秒數百萬筆必須成功的寫入，直播中不敢加容量。
2. Critical dependency：Registry 掛了廣告就停。
3. 事件新鮮度：lookup timeout 使 enrichment 延遲、打破 frequency capping SLA。

### 六個設計決策
1. Streaming join 取代 DB lookup：Flink stateful stream processing 非同步比對 client event 與 ad-serving response。
2. 60 分鐘 matching window：事件在記憶體中等對應 response，涵蓋約 99.999% 事件。
3. Regional routing：不把 serving response 全球複寫；token 編碼 serving region，跨區事件被路由到有對應資料的 region。
4. Batch recovery：每小時 Maestro 排程的 Spark job 從 data warehouse 重新配對落單者（約 0.001%），讓晚到事件可處理且 streaming state 保持有界。
5. Dedup at rest：event ID hash 成 idempotent key 存在 Flink 本地 state，免網路 hop，維持 at-least-once。
6. 平行驗證 cutover：新舊 pipeline 吃全量流量，以決定性的 stable-key 切分決定誰發布；自動 audit 比對輸出，直到「well over 99.99%」一致才切換。

### 取捨
- Best-effort 而非 exactly-once：串流內 dedup 抓「vast majority」，consumer 端做最後 idempotent dedup。
- State 大小 vs 完整性：60 分鐘窗平衡維運成本與覆蓋率。
- 延遲 vs 複寫成本：單跳 reroute 優於全球複寫 response。
- 複雜度 vs 安全：平行運行較久但贏得 production 信任。

### 結果
- Ad serving 不再有 critical path DB 寫入；舊服務與 Metadata Registry 完全下線。
- Load test 達每秒數十萬事件，timeout 與錯誤可忽略。
- 啟用 live 廣告、串流內 dedup、更豐富的即時 enrichment。

## 面試怎麼用
- Ad click / impression 追蹤、event enrichment 題：論點「把同步依賴移出 serving path，用 stream join 補資料」。
- 保證等級的取捨：at-least-once + idempotent consumer 通常比追求 exactly-once 便宜。
- 無界 state 的處理：有界窗口 + 離線 batch 補償（streaming + batch 對帳，像 Lambda 的務實版）。
- 遷移題：dual-run + 決定性切分 + 自動 audit 的 shadow cutover 流程。
- 多 region：用 token 帶路由資訊，避免全域複寫。

## 相關筆記
- [Ad Click Aggregator](../../hellointerview-breakdowns/ad-click-aggregator.md)
- [Flink](../../hellointerview-learn/deep-dives/flink.md)
- [Kafka](../../hellointerview-learn/deep-dives/kafka.md)
- [Scaling writes](../../hellointerview-learn/patterns/scaling-writes.md)
