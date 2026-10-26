# FB Post Search
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/fb-post-search ｜ 難度：hard ｜ 類別：Scaling Reads + Scaling Writes（作者 Stefan Mai）

## 一句話核心
在「不能用 Elasticsearch / Postgres full-text」的限制下，自己用 Redis 做 inverted index（keyword → postId），並為 recency 與 likes 各建一份 index（list vs sorted set）；先算規模發現這是 write-heavy（likes 100k/s）且儲存高達數 PB，因此靠 cache/CDN 撐讀、Kafka + keyword sharding 撐寫、「對數里程碑更新 like + 兩階段重排」降 like 寫入，再用 index 上限與冷熱分層壓儲存。

## 需求
**Functional（Core）**
- 建立與按讚 post
- 以 keyword 搜尋 post
- 搜尋結果可依 recency 或 like count 排序

**Out of scope**：fuzzy matching（如 "bird" 配到 "ostrich"）、搜尋個人化、隱私規則與過濾、複雜相關性排序、圖片/媒體、搜尋頁即時更新

原文：去個人化大幅簡化問題並讓 caching 更有效，值得向面試官確認是否為硬需求。也假設面試官明確禁止使用 Elasticsearch 或預建 full-text index——這是真實會發生的做法，用意在考基礎資料組織與索引。

**Non-functional（Core）**
- 快：median query < 500ms
- 高請求量（稍後估算）
- 新 post 在 < 1 分鐘內可被搜尋
- 所有 post 都要可被找到，包含舊的/冷門的（可花更久）——這是伏筆，預示冷熱資料設計
- 高可用

**規模估算**（假設 1B users、每人平均 1 post/day、按讚 10 次/day、1 天 = 100k 秒）
- Posts：1B × 1 / 100k = 10k posts/s
- Likes：1B × 10 / 100k = 100k likes/s（明顯多於 posts，要向面試官點出）
- Searches：1B × 1 / 100k = 10k searches/s（可能 burst 10x 以上）；系統是 write-heavy 而非 read-heavy
- 儲存：假設 Facebook 10 年、post metadata 1KB（可能高估）→ 1B/day × 365 × 10 = 3.6T posts × 1KB = 3.6 PB
- 原文提醒：常見錯誤是只盯著 search 以為讀最重要；估算是為了決定設計，不是為估而估。

## Core Entities & API
**Entities**：User（建立 post）、Post（被搜尋的對象，有內容、作者，隱含 like count）、Like（主要關心計數）。

**API**：兩條路徑——查詢路徑（search）與寫入路徑（建立 post、like）。原文只用圖示，未列出具體 URL。實務上可能從 Kafka 等 event bus 消費這兩類事件，這裡為清楚起見拆成獨立 endpoint，可告知面試官之後會併入。

## High-Level Design
```
Write:  Client -> Post Service / Like Service -> Ingestion Service (tokenize) -> Index (Redis)
Read :  Client -> API GW (auth, rate limit) -> Search Service -> Index (Redis)
```
1. **建立與按讚**：假設已有內部 Post Service / Like Service。由於 likes 與 posts 量差很多，Ingestion service 目前簡單合一，但要向面試官註記潛在問題。原文強調：要主動承認設計過度簡化，否則面試官會認為你沒看到問題。
2. **Keyword 搜尋**：
   - **Bad：未建索引的 DB** `SELECT * FROM Posts LIKE '%$keyword%'`。查詢時掃每筆 post，PB 級資料不可行；sharding/replication 只是 N/M，仍然太慢，死路。
   - **Great：Inverted Index**。keyword → 含該字的 posts。用 Redis（記憶體，極快），以 list 存每個 keyword 的 postId。Ingestion Service 對新 post 做 tokenization，把 postId append 到每個 keyword。Redis 有 durability 疑慮，可用 MemoryDB 或後續深入。挑戰：常見字的 postId list 會非常大；每個 post 有 10-1,000 個 keyword，一次要寫很多 key。
3. **排序（recency / likes）**：
   - **Bad：Request-time sorting**。取回某 keyword 全部 postId，逐一查 timestamp/like 數，在記憶體排序。常見字（如 "Taylor"）可能上千萬結果，payload 達數百 MB、上千萬次查詢、排序延遲。
   - **Great：Multiple indexes**。兩套 index：creation index（Redis list，只 append、只取尾端）與 likes index（Redis sorted set，score = like 數）。新 post 寫入兩邊；like 事件更新 sorted set 的 score。挑戰：儲存翻倍；likes 頻繁，每個 like 要更新多個 score，壓力大，後面處理。

## Deep Dives

### 1) 如何處理大量請求？
關鍵前提：無個人化（相同查詢結果相同）、新 post 有 1 分鐘容忍。→ caching。
- **Good：搜尋服務旁加分散式 cache**。存查詢結果，TTL < 1 分鐘（對應 1 分鐘 SLA，確保不會永遠看不到新 post）。
- **Great：CDN 邊緣快取**（Cloudflare / CloudFront）。在 `/search` response 加 cache-control header，使用者經就近 CDN；命中時是數十毫秒，對比經 API gateway → search service → cache 的數百毫秒。

### 2) 多關鍵字 / 片語查詢怎麼處理？
假設只需簡單的多字片語（如 "Taylor Swift"），不做 boolean 語法。
- **Good：Intersection and Filter**。取各字的 postId → 取交集 → 抓 post 內容確認真的包含片語（排除 "My friend Taylor made a swift exit"）→ 依序回傳。挑戰：各字的 postId 集合可能有數百萬筆，網路傳輸與 hash 交集困難，難達 500ms；若關鍵字高度重疊但不相鄰，會濾掉大量結果，運算昂貴。
- **Great：Bigrams / Shingles（Lucene 用語）**。為每對相鄰字建立 token（"I saw"、"saw Taylor"、"Taylor Swift"…），放入 likes 與 creation index；查 "Taylor Swift" 直接取該 entry。挑戰：index 暴增，bigram 更稀疏更獨特，單字 10m keys 可能變成 100m+。補救：只抽取可能被搜尋的 bigram，沒有 entry 時退回 intersection；可用 count-min sketch 等機率結構估計 bigram 出現頻率；但增加複雜度。

### 3) 如何處理大量寫入？
**Post 創建**：一個 post 100 字可觸發 100+ 次寫入；同時大量 post 可能壓垮 ingestion，最壞情況掉 post/事件。
- 加容量並分區：用 Kafka 之類 log/stream 將建立請求 fan out 到多個 ingestion instance、緩衝突發流量；index 依 **keyword shard**，讓寫入分散到多個 Redis。

**Like 事件**：likes 遠多於 posts，且每次 like 要寫多個 index。
- **Good：批次合併 like**。獨立 "batcher" service 以固定窗口（如 30 秒）聚合同一 postId 的 likes，再寫回 Kafka 交給 ingestion：病毒貼文 500 次寫入變成 1 次 +500。缺點：大多數 post 不是 viral，例如每分鐘 1 個 like 一整天 1,440 個，批次沒好處還多了開銷。
- **Great：Two-stage architecture**。只在 like 數經過里程碑（2 的冪或 10 的冪：1、2、4…）時更新 index，1000 個 like 只需約 10 次寫入（寫入量指數下降）。代價：index 是過時的，但順序近似正確（10k likes 的肯定排在 0-1 likes 前）。查詢 top N 時，從 likes index 取 top N×2，向 Like Service 查最新 like 數，再重排後回傳——儲存是近似的，結果是精確的。這種「近似服務 + 昂貴 re-ranking」的兩階段是 IR 與推薦系統常見模式。挑戰：工程更複雜；index 內的語意改變，宜命名為 "logLikes" 或 "approxLikes"。

### 4) 如何優化儲存？
- 對每個 inverted index 設上限：不需要含 "Mark" 的全部 10M posts，保留 1k-10k 筆，儲存可降數個量級。
- 冷熱分層：多數 keyword 很少被搜尋。依搜尋分析，批次作業把過去一個月很少/沒被存取的 keyword index 從記憶體 Redis 搬到 S3/R2 等 blob 冷儲存；查詢先 Redis，沒有再查 blob（小延遲代價）。呼應 NFR「舊/冷門 post 可以更久」。

### Final Design
Post/Like Service → Kafka → Ingestion（tokenize、bigram）→ keyword-sharded Redis（creation list + likes sorted set，含 cap）；冷 index 在 blob；Search Service 前有 Redis result cache 與 CDN；Like Service 供 re-rank。

## 關鍵數字與 back-of-envelope
- 10k posts/s、100k likes/s、10k searches/s（可能 burst 10x+）
- 3.6T posts、3.6 PB（1KB/post，10 年，假設 1 天 100k 秒）
- 一個 post 觸發 10-1,000 次 keyword 寫入
- Search latency：median < 500ms；新 post 可搜尋 < 1 分鐘；cache TTL < 1 分鐘
- CDN 命中：數十毫秒 vs 數百毫秒
- Like batch 窗口範例：30 秒；milestone：1、2、4…（1000 likes → ~10 次寫入）
- Index cap：1k-10k items/keyword
- 單字 keys ~10m → bigram 後 100m+

## 面試官期待
- **Mid-level**（80/20）：定義清楚 API 與資料模型，建立 ingestion 與 query 兩側；使用 Bad 解時，應能有好的討論，不要求立即跳到 Good/Great。
- **Senior**（60/40）：快速完成 HLD，花時間優化關鍵路徑；一眼看出寫入量、儲存、大量重複輸入；最低要求是詳述 ingestion 與 query、合理的 inverted index、適當的 caching 策略。
- **Staff+**（40/60）：完成數個 deep dive，展現創新與最佳解；以「面試官是否學到新東西」為衡量；解法多樣。

## 可遷移的 pattern
1. **先估算再決定設計**：用 back-of-envelope 發現「likes > posts、系統 write-heavy、3.6PB」，並口頭告訴面試官。
2. **Inverted index + 多份預排序 index**：以空間換讀取延遲（list 對 recency、sorted set 對 score），避免 request-time sort。
3. **近似索引 + 精確重排（two-stage）**：index 只做粗排（對數里程碑），top-2N 候選再向權威資料源取最新值重排。
4. **降低高頻寫入的寫放大**：batching、閾值/里程碑更新、keyword sharding、Kafka 緩衝。
5. **無個人化 + 可容忍陳舊 → 多層 cache（Redis 結果快取 + CDN）**，TTL 由 freshness SLA 決定；冷熱資料分層並設置 index 上限。

## 常見追問
- **為什麼不用 Elasticsearch？** 本題假設面試官禁止，用意是考 data layout 與 indexing 基礎；實務上可直接使用。
- **Redis 資料遺失？** 使用 MemoryDB 之類持久版本，或在深入討論時處理 durability（原文未展開細節）。
- **Like 排序不精確怎麼辦？** 取 top N×2 後向 Like Service 查最新數並重排。
- **多字查詢如何避免大集合交集？** Bigram/shingle 直接查片語；只索引可能被搜尋的 bigram，沒有則退回 intersection（可用 count-min sketch 估頻）。
- **為什麼 cache TTL 要 < 1 分鐘？** 因 NFR 要求新 post 1 分鐘內可被搜尋。
