# 5 Techniques Meta Uses to Scale a Database to Millions of Clients
> 來源：https://www.hellointerview.com/learn/system-design/in-the-wild/meta-zgateway-zippydb ｜ 分類：in-the-wild ｜ 原始 eng blog：Meta Engineering（原文標示 2026-09-03；https://engineering.fb.com/2026/09/03/core-infra/zgateway-proxy-zippydb-meta/）

## 一句話重點
Meta 在 ZippyDB 前面加 reverse proxy「ZGateway」，用 connection pooling、batching、request coalescing、read-through caching、admission control 五招，分別對治「連線太多、請求開銷、重複讀、快取失效、流量超載」五種不同瓶頸。

## 背景與問題（規模、痛點）
- ZippyDB：Meta 內部數百個團隊共用的 key-value 資料庫；超過一百萬台 client 機器在使用。
- 連線不是免費：每條連線佔記憶體（即使 idle），建立時耗 CPU 做 authentication 與加密。Meta 描述單台 DB host 接受數萬條 incoming 連線，典型 client 也持有數萬條 outgoing 連線。許多應用同時重啟會讓 DB 一邊重建連線一邊服務查詢而過載。
- 重複工作：一千個應用讀同一個 profile，DB 就做一千次相同 lookup；一秒後再問又做一次，即使沒變。
- 鄰居干擾：一個團隊的流量尖峰填滿 queue，拖慢流量沒變的其他團隊。

## 演進過程（舊架構 → 哪裡爆 → 新架構，保留原文數字）
- 舊：每個應用自己管 connection pool 直連 DB；每個新 instance 多一個 pool，DB 仍須維持所有 client 的連線。
- 爆：>1M client 主機 × 數萬連線；重複讀；無法隔離團隊流量。
- 新：應用把請求送到 ZGateway，由 gateway 代為維護對 ZippyDB 的連線；每個 client 只連一小組 ZGateway host。因請求都經過同一服務，gateway 能合併原本各自重複的工作，並有地方在超載時控制放行量。
- 原文未提供前後數字對比（只有規模描述）。

## 關鍵設計決策與取捨（這是主體，寫細）
1. **Connection pooling**：client 端 pool 只能在單一應用內重用；gateway 讓多個 client 共享對 DB shard 的後端連線池。新 client 沿用既有後端連線，不必對每個需要的 DB host 各開一條。
2. **Batching**：把 73、81、92 三個 key 合成一個後端請求，DB 仍做 3 次 lookup，但共享序列化、網路傳輸、請求處理的固定開銷。寫入同理（獨立更新一起傳、仍各自套用）。也減少計入 use case rate-limit 預算的後端請求數。取捨：等越久批次越有效率，但先到的 caller 延遲越高。ZGateway 的界限：timer 到期，或批次達 size / request-count 上限即 flush；同時限制 in-flight 批次數以保護 gateway 記憶體（DB 變慢時）。批次大小與等待時間要符合 workload 的 latency budget。
3. **Request coalescing**：多個 caller 要同一 key（user:73）時，後到者掛到進行中的 lookup，結果回來全部拿到。與 batching 的差別：batching 不同 key 仍要 N 次 lookup；coalescing 同 key 只要 1 次。前提：請求要到達同一 gateway、指向同一 record 且讀取要求相容；每個 gateway 只追蹤自己的 outstanding work，無法跨 gateway 合併。取捨：要記憶體追蹤進行中的 lookup 與等待者；DB 變慢時等待者累積，需限制 outstanding 數量並在完成 / 逾時時清理。lookup 完成後就不再有幫助 -> 需要 cache。
4. **Read-through caching**：先查 gateway 本機記憶體 cache，miss 才讀 ZippyDB 並存起來。過期或失效時避免 thundering herd：每個 caching gateway 用 per-key fill lock，一個請求去取值其餘等待（= 保留結果的 coalescing）。取捨：資料可能 stale；用 CDC（change-data-capture）stream 失效或刷新，並約定讀取最多落後寫入多少。
5. **Admission control**：依 use case 與 priority 分成有界 queue，輪流服務（scheduler）；某團隊 queue 滿了只拒絕它自己的超額請求，其他團隊照常；CPU / 記憶體壓力也影響放行量。取捨：部分 caller 會收到錯誤而不是等待；caller 必須 backoff 再重試，否則重建同樣的過載。
- **總原則**：先搞清楚 DB 的資源花在哪（連線過多 / 重複讀 / 流量超出容量），再選對應技術。代價是多一個要維運的服務與額外延遲。

## 面試怎麼用（這個案例可以拿來支撐哪類題目的哪個論點）
- 「Scaling reads」：用 coalescing + read-through cache 處理 hot key，說明兩者互補（coalescing 只管進行中、cache 管完成後）。
- 「Scaling writes」：batching 的延遲 vs 吞吐取捨，flush 條件（時間 / 大小）。
- 多租戶共享資源：per-tenant bounded queue + admission control 防 noisy neighbor。
- 在 DB 前加 proxy / gateway 層的理由與成本。

## 相關題目
- [Distributed Cache](../../hellointerview-breakdowns/distributed-cache.md)
- [Distributed Rate Limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)（admission control 對照）
- [Top-K](../../hellointerview-breakdowns/top-k.md)（write batching）

## 自測問題（3-5 題附簡答）
1. 為什麼 client 端自己做 connection pool 還不夠？ 答：每個 client instance 各有一個 pool，DB 仍要維持所有 client 的連線；gateway 讓連線在 client 間共享。
2. Batching 與 coalescing 差在哪？ 答：batching 是不同 key 共享傳輸 / 處理開銷，lookup 次數不變；coalescing 是相同 key 只做一次 lookup。
3. Batching 的核心取捨與 ZGateway 怎麼限制？ 答：等越久越有效率但延遲越高；以 timer 或大小 / 請求數上限 flush，並限制 in-flight 批次數。
4. 為何 coalescing 之後還需要 read-through cache？ 答：coalescing 在 lookup 結束後失效，之後的請求要重讀；cache 保留結果，並用 per-key fill lock 避免 thundering herd。
5. Admission control 怎麼避免一個團隊拖垮所有人？ 答：按 use case / priority 分有界 queue 輪流服務，滿了只拒絕該團隊超額請求；caller 要 backoff。
