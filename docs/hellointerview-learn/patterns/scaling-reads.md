# Scaling Reads
> 🤖 **by agents**：原文為 Premium，僅公開介紹與章節大綱；除標「（原文）」的段落外，內容皆由 agents 依大綱撰寫／搜尋整理，非 Hello Interview 原文。
> 來源：https://www.hellointerview.com/learn/system-design/patterns/scaling-reads ｜ 分類：patterns

## 一句話重點
讀取擴展依序是：(1) DB 內優化（index、硬體、denormalization）→ (2) 水平擴展 DB（read replica、sharding）→ (3) 外部快取（application cache、CDN）。重點在快取的各種失效模式：hot key、cache stampede、invalidation。

## 原文大綱（原文）
- 介紹（原文）：Scaling Reads addresses the challenge of serving high-volume read requests when your application grows from hundreds to millions of users. While writes create data, reads consume it - and read traffic often grows faster than write traffic.
- The Problem（原文重點）：Instagram feed 一次載入需上百次讀取，而使用者一天可能只發一張照片；讀寫比常見 10:1，內容型應用可達 100:1 以上。資料庫撐不住是物理限制（CPU、記憶體、磁碟 I/O），不是靠 debug 能解決。
- 原文列出的相關題目：Ticketmaster、Bitly、Instagram、FB News Feed、YouTube Top K、Yelp、Distributed Cache、Rate Limiter、YouTube、FB Post Search、Local Delivery Service、News Aggregator、Metrics Monitoring
- The Solution（原文）：自然演進 1. Optimize read performance within your database 2. Scale your database horizontally 3. Add external caching layers
- 章節：Optimize Within Your Database（Indexing / Hardware Upgrades / Denormalization Strategies）；Scale Your Database Horizontally（Read Replicas / Database Sharding）；Add External Caching Layers（Application-Level Caching / CDN and Edge Caching）
- When to Use in Interviews：Common Interview Scenarios / When NOT to Use
- Common Deep Dives：「What happens when your queries start taking longer as your dataset grows?」「How do you handle millions of concurrent reads for the same cached data?」「What happens when multiple requests try to rebuild an expired cache entry simultaneously?」「How do you handle cache invalidation when data updates need to be immediately visible?」
- Conclusion

## 內容（by agents）
### 1. Optimize Within Your Database
- **Indexing**：B-tree 解決等值／範圍查詢；複合索引遵守最左前綴；covering index 避免回表；代價是寫入變慢、佔空間。用 `EXPLAIN` 驗證。特殊索引：全文（inverted index/Elasticsearch）、地理（geohash/quadtree/R-tree，Yelp）。
- **Hardware Upgrades**：更多 RAM（讓 working set 全在記憶體）、NVMe SSD、更多 CPU。簡單但有天花板且貴，單點風險。
- **Denormalization**：預先 join、冗餘欄位（like_count）、materialized view、預計算聚合表。以寫入複雜度與一致性換讀取速度；需決定更新機制（trigger、CDC、非同步 job）。

### 2. Scale Your Database Horizontally
- **Read Replicas**：primary 寫、replicas 讀，application 或 proxy 做讀寫分離。注意 **replication lag**：剛寫完立刻讀可能讀到舊資料 → read-your-writes（寫後短時間路由回 primary、sticky、帶 LSN/version）。只擴讀，不擴寫，資料集仍需單機容納。
- **Sharding**：依 key 切分資料（hash / range / directory）；擴展資料量與讀寫。挑 shard key 要避免熱點與跨 shard query；resharding 用 consistent hashing 或虛擬節點；跨 shard join／transaction 昂貴。能不 shard 就不 shard，先 replica + cache。

### 3. External Caching Layers
- **Application-Level Caching**：Redis／Memcached。Pattern：cache-aside（最常用）、read-through、write-through、write-behind。設 TTL、容量與 eviction（LRU/LFU）。以 key = 查詢結果；命中率是核心指標。
- **CDN / Edge Caching**：靜態資源與可快取的 API（`Cache-Control`、`s-maxage`、`stale-while-revalidate`）在離使用者近的 edge 回應；降低 origin 負載與延遲。使用者專屬資料通常不適合；用 versioned URL 或 purge 處理更新。
- 另有 client-side cache、HTTP ETag／304。

## 常見深入題（by agents）
- **資料變大查詢變慢？** 檢查 index 與 query plan；分區表（partitioning）、歸檔冷資料、拆表；到極限再 shard；搜尋類改用專用引擎。
- **百萬並發讀同一個 cached 資料（hot key）？** 單一 Redis shard 被打爆 → 本地 in-process cache（短 TTL）、key 複製成多份（`key#1..N` 隨機讀）、client-side/CDN 快取、讀 replica；請求合併。
- **同時重建過期 cache（stampede／thundering herd）？** request coalescing／single-flight、分散式鎖只讓一個請求重建、TTL 加 jitter、stale-while-revalidate（先回舊值背景刷新）、提前主動刷新（probabilistic early expiration）。
- **更新需立即可見的 invalidation？** write-through／寫後 delete key（cache-aside 先寫 DB 再刪快取）、CDC 事件驅動失效、短 TTL、版本化 key；承認「cache invalidation 很難」，對強一致需求直接讀 primary；注意刪除與回填的 race（可用延遲雙刪或版本號）。

## 面試怎麼用（by agents）
- 先量化：QPS、讀寫比、資料大小、延遲目標，再決定要不要上層級。
- 遵循演進順序，逐層說明「為什麼上一層不夠」。快取不是萬靈丹：先講命中率、一致性可容忍度、失效策略。
- 常見場景：URL shortener（讀遠大於寫）、feed、商品頁、票務座位圖、搜尋、排行榜。
- 不要用：寫密集（改看 [scaling-writes](./scaling-writes.md)）、需強一致即時資料、資料量小且 QPS 低時別過早引入快取。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)
- [bitly](../../hellointerview-breakdowns/bitly.md)
- [instagram](../../hellointerview-breakdowns/instagram.md)
- [fb-news-feed](../../hellointerview-breakdowns/fb-news-feed.md)
- [top-k](../../hellointerview-breakdowns/top-k.md)
- [yelp](../../hellointerview-breakdowns/yelp.md)
- [distributed-cache](../../hellointerview-breakdowns/distributed-cache.md)
- [distributed-rate-limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)
- [youtube](../../hellointerview-breakdowns/youtube.md)
- [fb-post-search](../../hellointerview-breakdowns/fb-post-search.md)
- [metrics-monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)

## 自測問題（by agents）
1. 讀寫比 100:1 時第一步做什麼？答：先確認 index／query plan，再 read replica 與 cache。
2. read replica 的主要陷阱？答：replication lag 造成讀到舊資料；用 read-your-writes 路由。
3. cache stampede 如何防止？答：single-flight／鎖、TTL jitter、stale-while-revalidate、提前刷新。
4. hot key 怎麼辦？答：本地快取、key 複製分散、CDN、請求合併。
5. cache-aside 更新流程？答：先寫 DB，再刪除 cache，下次 miss 回填；注意 race 與 TTL 保底。

## 參考來源
- https://aws.amazon.com/builders-library/caching-challenges-and-strategies/
- https://www.postgresql.org/docs/current/indexes.html
- https://redis.io/docs/latest/develop/use/client-side-caching/
- https://engineering.fb.com/2013/04/15/core-infra/scaling-memcache-at-facebook/ （Scaling Memcache at Facebook，論文 NSDI'13）
- https://developers.cloudflare.com/cache/concepts/cache-control/
- 註：以上為 agents 憑既有知識列出的公開文件；2026-10-19 已逐一確認連結可開啟（HTTP 200），但內容未逐條比對。
