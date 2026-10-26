# Bitly（URL Shortener）
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/bitly ｜ 難度：Easy ｜ 類別：Scaling Reads

## 一句話核心
極度偏讀（約 1000 次點擊 : 1 次建立）的 key-value 映射服務：用「Counter + Base62」保證 short code 唯一，用「Index → Redis cache → CDN/Edge」把 redirect 壓到 < 100ms，讀寫服務分離各自水平擴展。

## 需求
**Functional（Core）**
- 使用者提交 long URL，取得 short URL
- （選配）自訂 alias，例如 `short.ly/my-custom-alias`
- （選配）設定過期時間
- 用 short URL 存取（redirect 到）原始 URL

Out of scope：user auth / 帳號管理、點擊分析（click count、地理資料）。

**Non-functional**
- short code 唯一（一個 code 只對應一個 long URL）
- Redirect 延遲 < 100ms
- 可用性 99.99%（availability > consistency）
- 規模：1B 筆 shortened URL、100M DAU

Out of scope：即時分析的一致性、進階安全（spam / 惡意 URL 過濾）。

**規模數字**：讀寫比約 1000:1。

## Core Entities & API
Entities：Original URL、Short URL、User（面試時列個簡單清單即可，欄位之後再補）。

```
// 建立短網址
POST /urls
{ "long_url": "...", "custom_alias": "optional", "expiration_date": "optional" }
-> { "short_url": "http://short.ly/abc123" }

// Redirect
GET /{short_code}
-> HTTP 302 Redirect to long URL
```
- POST 因為是新增 mapping；GET 因為是讀取既有 mapping。

## High-Level Design
```
Client --POST /urls--> Primary Server --(validate, gen code)--> DB
Client --GET /abc123--> Primary Server --lookup--> DB --> 302 Location: long_url
```
**建立流程**
1. Server 驗證 long URL 格式（is-url 之類的函式庫）。
2. 可選：dedup（同一 long URL 回傳既有 code）。但多數服務允許同一 URL 有多個 code（不同使用者要各自的過期時間、分析、alias），dedup 是用儲存效率換這些功能。
3. 有 custom alias 就先檢查不存在後直接當 short code；為避免 alias 與日後 counter 產生的 code 碰撞，可給產生碼加一個 alias 不能用的前綴字元，或用不同 namespace。
4. 寫入 DB（short code / alias、long URL、expiration）並回傳。

**Redirect 流程**
1. 瀏覽器 GET `/abc123` → Server 查 DB。
2. 找到且未過期 → 回 redirect；過期 → 回 **410 Gone**。
3. 背景 job 定期清除過期資料（或保留並帶 expiration）；更重要的是 **cache TTL 設成 ≤ URL 過期時間**，讓過期 entry 自動被 evict。

**301 vs 302**
- 301 Permanent：瀏覽器會 cache，之後直接跳 long URL、繞過我們的 server。
- 302 Found：瀏覽器不 cache，每次都經過我們。
- 偏好 **302**：可更新/過期連結、避免 browser cache 造成無法變更/刪除、可追蹤點擊（雖然本題 out of scope）。

## Deep Dives

### 1) 如何確保 short URL 唯一？
限制：唯一、越短越好、產生要有效率。

**爛解：Long URL prefix**
- 取 long URL 前 N（如 8）字元當 code。
- 問題：共用前綴的 URL 會撞同一個 code（`www.link` 無法分辨 linkedin 的各個頁面），違反唯一性。

**好解：Hash function（+ Base62）**
- 需要 entropy。純亂數產生器熵不夠；改用 hash（如 SHA-256）→ base62 encode → 取前 N 字元（8 字元 = 62^8 ≈ 218 兆種）。
- 先對 URL 做 canonicalize（host 小寫、去預設 port、正規化尾斜線等）。
- 純 hash 是 deterministic：同 URL 永遠同 code（天然 dedup，不用查 DB）；若不想要（需多個 code、防猜測 / adversarial preimage）就加 secret salt / nonce（HMAC）。
- 為何 base62 不用 base64：base64 的 `+` 可能被當空白、`/` 是路徑分隔符。
- 缺點：儲存量增加後碰撞機率約 n/|S|；要降低碰撞就得加長 code，違背「短」；碰撞偵測需額外 DB 查詢。
- 處理碰撞：short code 欄位加 **UNIQUE constraint**，失敗就加隨機 salt 重試，**有上限（如 3-5 次）**，之後換策略或回錯誤。

**好解：Unique counter + Base62**
- 每個新 URL 遞增計數器，結果 base62 編碼。Redis `INCR` 是單執行緒的原子操作，兩個同時呼叫必拿到不同值。
- 優點：保證無碰撞、無需額外檢查、高吞吐、可水平擴展、code 可 decode 回 ID。
- 缺點：
  - 分散式環境需要單一 counter 真相來源（見 Deep Dive 3）。
  - 序號可預測 → 可被列舉掃描。緩解：base62 前先做可逆轉換（如 XOR secret key），或接受（短網址本來就是要公開分享）。
  - code 長度隨時間增長。數學：1B 的 base62 是 `15ftgG`（6 字元）；62^6 ≈ 56B 之後才要 7 字元，62^7 > 3.5 兆。

### 2) 如何讓 redirect 夠快？
沒優化時要 full table scan。

**好解：加 Index**
- B-tree index（O(log n)）；把 short code 設成 **primary key**，自動建 index 並保證唯一。
- 問題：SSD 約 100k IOPS；估算 100M DAU × 5 redirect/天 = 500M/天 ≈ 5,787 RPS（平均），尖峰乘 100x ≈ **~600k 讀/秒**，單一 DB 撐不住，還會拖累寫入。

**好解：In-memory cache（Redis / Memcached）**
- 流程：查 cache → hit 直接回；miss 查 DB 後回填。
- 速度：記憶體 ~100ns、SSD ~0.1ms、HDD ~10ms；IOPS：記憶體百萬級、SSD ~100k、HDD ~100-200。
- 挑戰：invalidation（但 URL 很少更動，影響小）、冷啟動 warm-up、記憶體有限需選 eviction（LRU）與要放哪些 entry、增加架構複雜度。

**好解：CDN + Edge computing**
- short domain 走 CDN，PoP 快取 mapping；用 Cloudflare Workers / AWS Lambda@Edge 在 edge 直接 redirect，熱門 code 根本不到 origin。
- 挑戰：全 CDN 節點的 invalidation 一致性、edge 設定複雜、成本、edge function 的執行時間/記憶體/函式庫限制、除錯與監控較難。
- 取捨：用成本與複雜度換效能，視公司成本敏感度、UX 需求、流量型態決定。

### 3) 如何擴展到 1B URL / 100M DAU？
**儲存估算**：每 row ≈ 200 bytes（short code ~8、long URL ~100、creationTime ~8、alias ~100、expiration ~8），保守抓 **500 bytes**（含 creator id、analytics id 等）→ 500B × 1B = **500GB**，單顆現代 SSD 可容納；真不夠再 shard。

**DB 選擇**：幾乎都行（Postgres / MySQL / DynamoDB）。讀被 cache 擋掉，寫入量估 100k 新 URL/天 ≈ 1 row/s。沒經驗就選 Postgres。

**DB 掛掉怎麼辦**
- Replication：多副本，主掛了切換；但 Primary Server 要能與任何 replica 互動，有維運成本。
- Backup：定期 snapshot 到別處。

**Primary Server 擴展**
- 讀寫分離為 **Read Service**（redirect）與 **Write Service**（建立），各自水平擴展。

**Counter 問題**
- 多個 Write Service 需要共用單一 counter → 集中式 Redis 做原子 INCR。額外一次 network call 通常可忽略。
- **Counter batching**：每個 instance 一次領一批（如 1000）；Redis 原子地 +1000 並回傳批次起點；instance 本地用完再領。降低 Redis 負載與網路呼叫。
- HA：Redis Sentinel 或 Redis Cluster 自動 failover；單一 Redis 可處理 100k+ ops/s，遠超需求。
- 多區域：各 region 配發互不重疊的 counter 區間（A: 0-1B、B: 1B-2B），免跨區協調；寫本地 Redis，讀可經全球分散式 cache。
- Redis 在複製前掛掉可能丟幾個值，但我們只需要唯一、不需連續；DB 的 UNIQUE constraint 是最後防線。

## 關鍵數字與 back-of-envelope
- 1B URL × 500 B = 500GB
- 500M redirect/天 ÷ 86,400 ≈ 5,787 RPS；×100 尖峰 ≈ 600k RPS
- 寫入：~100k 新 URL/天 ≈ 1 row/s
- Base62：8 字元 ≈ 218 兆；1B → 6 字元；62^6 ≈ 56B；62^7 > 3.5 兆
- 延遲：memory ~100ns / SSD ~0.1ms / HDD ~10ms
- 目標：redirect < 100ms，可用性 99.99%
- Redis 單機 100k+ ops/s

## 面試官期待
- **Mid**：能做出可運作的 HLD；知道唯一性要處理並提出 hash 或 counter 至少一種；理解為何 302、基本 index；經提示能想到 cache。
- **Senior**：主導討論並主動點出唯一碼生成、快速 redirect、水平擴展；清楚講 hash（碰撞）vs counter（協調成本）取捨；細談 cache 與過期 invalidation；合理選 DB；讀寫服務分離、用 Redis 等擴展 counter。
- **Staff+**：看穿「教科書解」談真實生產問題；主動談多區域、counter range 分配、Redis failover；了解可預測 code 的安全含意與緩解；談 custom alias 碰撞預防、過期清理策略、需求演進。

## 可遷移的 pattern
1. **Scaling Reads 階梯**：index → in-memory cache → CDN/edge；先算出尖峰 QPS 再決定要爬到哪一層。
2. **讀寫服務分離**：讀寫比懸殊時拆成獨立服務，各自獨立擴展。
3. **Counter batching / range 分配**：用原子遞增的中心 counter 配 local batch，降低協調成本；多區域用不重疊區間。
4. **唯一性由 DB constraint 兜底**：演算法（hash / counter）負責大多數情況，UNIQUE constraint + 有上限重試當最後防線。
5. **用 TTL 對齊業務過期時間**：cache TTL ≤ 資源過期時間，省去主動 invalidation。

## 常見追問
- **為什麼用 302 不用 301？** 301 被瀏覽器永久 cache，之後繞過我們，無法更新/過期/追蹤點擊；302 每次都經過 server。
- **Hash 碰撞怎麼辦？** UNIQUE constraint 偵測，加隨機 salt 重試，上限 3-5 次，超過換策略或回錯。
- **Counter 會被猜出所有 URL 嗎？** 會有可預測性；可在 base62 前對 counter 做可逆轉換（如 XOR secret key），或接受因為短連結本來就公開。
- **Redis counter 掛了怎麼辦？** Sentinel / Cluster 自動 failover；可能丟幾個值但只需唯一不需連續；DB UNIQUE 兜底。
- **過期 URL 怎麼處理？** Redirect 回 410 Gone；背景 job 清理；cache TTL 對齊過期時間。
- **自訂 alias 與產生碼衝突？** 產生碼加 alias 不可用的前綴字元或分 namespace。
