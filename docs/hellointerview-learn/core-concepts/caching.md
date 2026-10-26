# Caching
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/caching ｜ 分類：core-concepts

## 一句話重點
高讀取流量、DB 變瓶頸時就說 cache：預設 Redis + cache-aside + LRU + TTL，然後主動點出一兩個失敗模式（stampede、consistency、hot key）及處理方式。

## 核心內容

### 為什麼要 cache
- 從 Postgres 讀 user profile 約 50 ms，從 Redis 這類 in-memory cache 讀約 1 ms，約 50x 延遲改善。DB 資料在 disk，每次 query 都付 disk access 成本；memory 離 CPU 近。
- 代價：invalidation 與 failure handling 的新問題。

### Where to Cache
| 位置 | 說明 | 何時用 |
|---|---|---|
| External cache (Redis/Memcached) | 獨立服務，所有 app server 共用；支援 LRU eviction、TTL | **面試預設答案**。先講它，再視需要疊其他層 |
| CDN | 地理分散的 edge servers；Cloudflare/Fastly/Akamai 也能快取公開 API response、HTML、跑 edge logic，但最常見最有效的是媒體傳遞 | 系統大量提供 static media 時最安全的引入時機 |
| Client-side | 瀏覽器 HTTP cache、localStorage、mobile 本地儲存；也包括 client library 快取（Redis client 快取 cluster metadata / slot 對應以直接路由） | 後端控制力有限、資料易 stale、invalidation 難。例：Strava 離線時把 run 資料存裝置再同步 |
| In-process | 在 app process 記憶體內快取，比 Redis 更快（無網路呼叫） | 小而熱、少變動：config、feature flags、小型 reference dataset、hot keys、rate limiting counters、預先算好的值。缺點：每個 instance 各自一份、不共享，一台更新其他台不知道。**只當 external cache 之上的優化層** |

- CDN 流程：請求→最近 edge→命中直接回；未命中從 origin 抓、存起來、回傳；之後同區域使用者直接從 CDN 拿。
- 延遲對比：origin 在 Virginia、使用者在印度，每個請求多 250–300 ms；CDN 在附近 edge 約 20–40 ms。

### Cache Architectures
| 模式 | 流程 | 優點 | 缺點 / 何時用 |
|---|---|---|---|
| **Cache-aside (lazy loading)** | app 先查 cache；miss 則查 DB、寫入 cache、回傳 | 只快取需要的，cache 精簡；**面試預設，只記一個就記這個** | miss 時多一次延遲 |
| Write-through | app 只寫 cache，cache 同步寫 DB 後才回 | 讀取永遠新鮮 | 寫入變慢；可能快取永遠不會被讀的資料；仍有 dual-write 問題（一邊成功一邊失敗→不一致，需 retry/錯誤處理，否則要分散式交易）；需特殊 cache 實作（Redis 本身不原生支援）；面試較少用。適合「讀必須新鮮、可容忍較慢寫入」 |
| Write-behind (write-back) | app 只寫 cache，cache 批次非同步寫 DB | 寫入極快 | cache 在 flush 前當機會**遺失資料**；適合高寫入吞吐 + 最終一致，如 analytics / metrics pipeline |
| Read-through | cache 當 smart proxy，app 不直連 DB；miss 時 cache 自己抓 | 集中 caching 邏輯 | 較複雜、需特殊 library；少有理由在面試提，除非談 CDN（CDN 本質就是 read-through） |

- Read-through 與 write-through 是讀/寫對應的一對，系統常合用。

### Cache Eviction Policies
- **LRU**：淘汰最久沒被存取的；用 linked list / ring buffer 做到 O(1)；許多系統預設，適應大多數 workload。**安全預設答案**。
- **LFU**：淘汰存取次數最少的；每 key 一個計數器（有些實作用近似 LFU）；適合持續熱門的 key（trending videos、top playlists）。
- **FIFO**：只看插入時間淘汰最舊；忽略使用模式，可能淘汰熱資料，很少用。
- **TTL**：不是淘汰策略，而是為每個 key 設過期時間；常與 LRU/LFU 並用；資料必須定期刷新時（API response、session token）必備。

### Common Caching Problems
**1. Cache Stampede (Thundering Herd)**
- 熱門 entry 過期瞬間，大量請求同時 miss 並直接打 DB，原本一次 query 變成數百上千次。例：首頁 feed TTL 60 秒，12:01:00 過期，高流量下可能壓垮 DB 引發連鎖失敗。
- 處理：
  - Request coalescing（single flight）：只讓一個 request 重建 cache，其他等結果。**最有效**。
  - Cache warming：到期前主動刷新熱門 key。只在 TTL 型過期有用；若是寫入時 invalidate，warming 無法防 stampede。
  - （原文後文另提）probabilistic early expiration。

**2. Cache Consistency**
- 大多數系統讀 cache、先寫 DB，所以存在 cache 仍是舊值的視窗。例：更新大頭貼後，別人暫時看到舊的。
- 沒有完美解，依資料需要多新鮮決定：
  - 寫入後 invalidate（刪除 cache entry，下次讀重新填）。
  - 短 TTL 容忍些許 stale。
  - 接受最終一致（feed、metrics、analytics 延遲沒關係）。

**3. Hot Keys**
- 單一 key 流量遠高於其他，即使 hit rate 高也會壓垮單一 cache node / Redis shard。例：Twitter 上人人看 Taylor Swift 的 profile（`user:taylorswift`）每秒數百萬請求。
- 處理：複製 hot key 到多個 node 並 load balance 讀取；加 in-process 本地 fallback cache；對特定 key 做 rate limiting。
- 延伸：Scaling Reads pattern（病毒式內容同時被大量請求，傳統 caching 假設會失效）。

## Caching in Interviews
### 何時提
別直接跳到 cache，先建立必要性。四種觸發情境（原文話術皆要「量化」）：
- **Read-heavy**：10M DAU × 20 req/day = 200M reads 打 DB；有 index 仍 20-50 ms/query；cache 可降到 2 ms 以下。
- **Expensive queries**：個人化 feed 要 join posts/followers/likes，200 ms；cache 60 秒，Redis 1 ms 回。
- **High DB CPU**：尖峰 80% CPU 都在重複的讀；cache 熱 query 可降 70-80% DB 負載。
- **Latency requirement**：需要 sub-10 ms，DB 30-50 ms，必須 cache。
- 公式：找出效能問題 → 用粗略數字量化 → 說明 cache 如何解決。可參考 Numbers to Know。

### 怎麼引入（五步）
1. **Identify the bottleneck**：例「user profile 尖峰每秒打 DB 500 次，每次 30 ms」。
2. **Decide what to cache**：常讀、少變、取得/計算貴的資料；設計 key（`user:123:profile`、`trending:posts:global`）。
3. **Choose architecture**：「我用 cache-aside…」；靜態媒體提 CDN；極熱 key 提 in-process。強一致要求→write-through；高寫入可容忍風險→write-behind。
4. **Eviction policy**：LRU 預設 + TTL（例：profile TTL 10 分鐘，使用者更新時立即 invalidate）。
5. **Address downsides**：invalidation 策略；cache failure（Redis 掛了請求 fallback 到 DB，加 circuit breaker 避免 DB 被沖垮，可留小型 in-process cache 作最後一層）；thundering herd（probabilistic early expiration 或 request coalescing）。
- 只挑一兩個與該系統相關的問題講；Staff 級要講重要但不顯而易見的情境。

## 面試怎麼用
- 時機：識別 DB 瓶頸之後，先量化再提 cache。
- 說法：「User profile 讀多寫少，我用 Redis cache-aside，LRU + 10 分鐘 TTL，更新時刪 key；Redis 掛掉時 fallback DB 並用 circuit breaker。」
- 陷阱：沒說為什麼需要就提 cache；只講好處不講 invalidation / failure；一開始就講 read-through/write-through 等冷門模式；把 in-process cache 當 Redis 替代品；忽略 hot key 與 cache 掛掉打爆 DB。

## 關鍵數字
- Postgres 讀 ~50 ms vs Redis ~1 ms（約 50x）。
- CDN：跨洲 origin 多 250–300 ms，CDN edge 20–40 ms。
- 範例：DB query 20-50 ms → cache < 2 ms；cache 熱 query 降 DB 負載 70-80%（原文話術範例）。

## 相關題目
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)
- [fb-news-feed](../../hellointerview-breakdowns/fb-news-feed.md)
- [youtube](../../hellointerview-breakdowns/youtube.md)（CDN）
- [bitly](../../hellointerview-breakdowns/bitly.md)
- [strava](../../hellointerview-breakdowns/strava.md)（client-side）

## 自測問題
1. 為何 cache-aside 是預設？缺點？答：只在需要時快取、邏輯簡單；miss 多一次延遲、有 stale 風險。
2. Write-through 與 write-behind 差別？答：前者同步寫 DB（慢但新鮮，仍有 dual-write 問題）；後者非同步批次（快，但 cache 掛了會丟資料）。
3. 什麼是 cache stampede？如何解？答：熱 key 過期時大量請求同時打 DB；用 request coalescing（single flight）、cache warming、probabilistic early expiration。
4. 單一 hot key 壓垮一個 Redis node 怎麼辦？答：複製該 key 到多 node 分流、本地 in-process fallback、rate limiting。
5. 何時用 CDN、何時用 in-process cache？答：CDN 用於大規模靜態媒體；in-process 用於小而熱、少變的資料，且在 external cache 之上作優化。
