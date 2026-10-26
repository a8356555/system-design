# Distributed Rate Limiter
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/distributed-rate-limiter ｜ 難度：Medium ｜ 類別：Dealing with Contention、Scaling Writes、Scaling Reads

## 一句話核心
在 API Gateway 層用 Token Bucket 演算法、把每個 client 的 bucket 狀態集中放 Redis（以 Lua script 讓 read-calculate-update 原子化），再依 client key 做 consistent hashing 分片（約 10 個 shard 撐 1M RPS），並用 replica、fail-open/closed 決策、連線池與動態規則設定補足可用性與延遲。

## 需求
本題：為社群平台 API 設計 **request-level** rate limiter（限制個別 HTTP 請求，而非高層業務操作）；聚焦 server-side（client 不可信，client-side 限流僅是補充）。

**Functional（Core）**
- 以 user ID、IP、API key 識別 client 以套用適當限制
- 依可設定規則限制 HTTP 請求（如每用戶每分鐘 100 次）
- 超限時回 HTTP 429，並附有用的 header（剩餘額度、重置時間）

Out of scope：對限流資料做複雜查詢/分析、限流資料的長期持久化。

**Non-functional（Core）**
- 低延遲開銷（每次檢查 < 10ms）
- 高可用；eventual consistency 可接受（跨節點限流執行略有延遲沒關係）
- 規模：**1M requests/second、100M DAU**

Out of scope：跨所有節點的強一致。

原文提醒：應先問面試官規模（新創每天數千請求 vs 每秒數百萬），規模會完全改變設計。
（註：原文 deep dive 段落另寫「1M requests/second across 10M users」，與需求的 100M DAU 不一致，以需求段為準。）

## Core Entities & API
**Entities**
- **Rules**：限流政策（時間窗口請求數、適用對象、涵蓋 endpoint），如「認證用戶 1000 次/小時」「搜尋 API 每 IP 10 次/分」
- **Clients**：被限流的對象（user ID、IP、API key 或組合），每個 client 有目前用量狀態
- **Requests**：帶有 client 身分、endpoint、時間戳的請求

流程：Request 到達 → 識別 Client → 查適用 Rules → 比對用量 → 放行或拒絕。

**System Interface**（基礎設施元件，供其他服務呼叫）
```
isRequestAllowed(clientId, ruleId) -> { passes: boolean, remaining: number, resetTime: timestamp }
```
回傳資訊用於 `X-RateLimit-Remaining` / `X-RateLimit-Reset` header。

## High-Level Design

### 1) 識別 client —— 限流器放哪裡？
- **爛解：In-process**。每台 app server 內建本地記憶體計數器，快但每台只知道自己的流量。例：5 台 server、限 100/分，每台看到 20 就放行；LB 改變路由或負載不均，限制完全不可預測（可能每台各 100，共 200）。只適用單一 server 或可接受誤差達 server 數倍的情況。
- **好解：Dedicated service**。獨立 microservice，app server 先呼叫它。優點：可帶豐富 context（訂閱等級、帳號狀態、endpoint、業務邏輯如黑色星期五加額），全域狀態精確。缺點：每個請求多一次網路往返（延遲）、新增單點故障（fail-open vs fail-closed 抉擇）、維運複雜度、網路問題（慢、partition）怎麼處理。
- **最佳解：API Gateway / Load Balancer**（作者選擇）。在系統最邊緣，被擋的請求根本到不了 app server，像夜店保鑣。生產環境最常見。缺點：只能存取 request 本身的資訊（header、URL、IP、基本 auth token），難做「付費用戶 10 倍額度」除非編碼進 JWT；且狀態需放 Redis 等外部儲存，要處理其慢/掛。

**Client 識別**（只用 request 內資訊，避免額外外部呼叫的延遲）
- User ID：認證 API，通常在 Authorization header 的 JWT
- IP：公開 API，注意 NAT / 企業防火牆；通常在 `X-Forwarded-For`
- API Key：開發者 API，`X-API-Key`
- 實務會**分層組合規則**：per-user、per-IP、global（如 API 總量 50,000 RPS）、endpoint-specific（搜尋 10/分、更新 profile 100/分）；檢查所有適用規則並採**最嚴格**者（例：Alice 用了 50/1000 但其 IP 已達 100 上限 → 被擋）。
- 此時可問面試官：是否全部用戶都已認證？是否為開發者 API？

### 2) 限流演算法
原文說明：SD 面試通常只需表明了解選項並做選擇，不太需要實作或寫 pseudocode（不同於 LLD 面試）。

| 演算法 | 作法 | 優點 | 缺點 |
|---|---|---|---|
| Fixed Window Counter | 固定時間桶（如 1 分鐘）內計數，新窗口歸零；hash table 存 (counter, window_start) | 極簡單 | 邊界效應（12:00:59 打 100、12:01:00 再打 100，2 秒內 200）；早用完額度會「飢餓」 |
| Sliding Window Log | 每 client 記錄請求時間戳，新請求時移除過期，再數剩餘 | 完全精確，無邊界效應 | 記憶體大（1000 req/min 要存 1000 個 timestamp，乘上百萬用戶）、每次掃描 log 的計算成本 |
| Sliding Window Counter | 保存當前與前一窗口計數，依在當前窗口的進度加權（如 30% 進度 = 前窗 70% + 當前 100%） | 比 fixed 準確，只要兩個計數器 | 是近似，假設窗口內均勻分布；數學實作易錯 |
| Token Bucket | bucket 容量=burst 上限，以固定速率補 token，每請求扣 1，沒 token 拒絕 | 同時處理持續負載（補充速率）與突發（容量）；只存 (tokens, last_refill) | 要選對容量/速率；idle client 冷啟動即滿桶 |

**選擇 Token Bucket**：簡單、記憶體省、符合真實突發流量；Stripe 等公司採用。

**狀態存哪？** bucket 存在每個 gateway 記憶體會回到 in-process 的協調問題（Alice 50 次打 Gateway A、50 次打 B，各自以為只用 50）。需集中式狀態 → **Redis**。

Redis 流程：
1. 請求到 Gateway A（user alice）。
2. `HMGET alice:bucket tokens last_refill` 取狀態。
3. 依經過時間計算要補多少 token（例：30 秒前更新、速率 1/秒 → +30，上限為容量）。
4. 用 `MULTI / HSET tokens / HSET last_refill / EXPIRE alice:bucket 3600 / EXEC` 原子更新（EXPIRE 讓閒置 1 小時的 bucket 自動清除，避免記憶體洩漏）。
5. 有 ≥1 token 就放行並扣 1，否則拒絕。

**Race condition**：HMGET 在 transaction 之外；兩個同時請求讀到同樣的 token 數、都算出可放行，結果 1 個 token 放行 2 個請求。
**解法**：把整個 read-calculate-update 放進 **Redis Lua script**（原子執行）。這是 Dealing with Contention 的典型：把 atomic boundary 擴大到整個 read-modify-write 序列。
Redis 適合的理由：亞毫秒速度、EXPIRE 自動清理、可複製達成高可用、原子操作。

### 3) 超限回應
- **丟棄 vs 排隊**：多數採 **fail fast** 直接回 429。排隊看似友善但耗記憶體與處理資源、使用者以為失敗而重試加重負載、讓 API 回應時間不可預測；僅適用於可等待的批次系統。
- 回應 header：
  - `X-RateLimit-Limit`（上限，如 100）
  - `X-RateLimit-Remaining`（剩餘，如 0）
  - `X-RateLimit-Reset`（Unix timestamp 重置時間）
  - `Retry-After`（部分系統提供，建議等待秒數）
  - body：`{"error": "Rate limit exceeded", "message": "..."}`
- 讓 well-behaved client 實作正確的 backoff。面試中點出 429 + 適當 header 即可。

## Deep Dives

### 1) 如何擴展到 1M requests/second？
- 單一 Redis 約 100k-200k ops/s；每次檢查至少 HMGET + HSET 多個操作，實際約 **50k-100k 次檢查/秒**即達瓶頸。
- 需分片，且要確保**同一 client 的請求永遠打到同一 shard**（否則狀態被切碎）。
- 用 **consistent hashing**：認證用戶 hash user ID、匿名 hash IP、API key 請求 hash key。每個 client 的狀態只存在一個 shard，負載均勻分散。
- Gateway 內需路由邏輯：抽取識別碼 → 套用分配演算法 → 送到對應 Redis；Token Bucket 本身不變。
- **10 個 shard × ~100k ops/s** ≈ 滿足 1M RPS。
- 生產環境用 **Redis Cluster**：16,384 個 hash slots 分散在多節點，自動依 key（如 `alice:bucket`）路由，不需自己在 gateway 實作 consistent hashing。

### 2) 如何確保高可用與容錯？
shard 掛掉 → 該 shard 上所有用戶失去限流；若用戶激進重試可能造成級聯故障。需決定 failure mode：
- **Fail-closed**（好解）：連不上 Redis 就拒絕所有請求（503 或 429）。沒有無法驗證的請求通過。缺點：等同讓 API 下線（即使後端健康），用戶重試加重負載。合理場景：金融支付、高安全環境，寧可停機也不要不受控存取。
- **Fail-open**（好解）：連不上 Redis 就當作沒限流全放行。保持可用。缺點：暫時失去保護；若 Redis 掛是因為已經高負載，全部流量湧入後端，可能整體崩潰（社群平台病毒事件尤其危險）。
- 兩者都是「好解」，依需求而定。**本題選 fail-closed**：限流故障常與流量尖峰同時發生，此時最需要保護；短暫拒絕請求勝過後端崩潰。
- 但 failure mode 只是損害控制，更好的是預防：**master-replica replication**，master 掛了自動 promote replica（Redis Cluster 內建 failover）；代價是基礎設施成本與複製延遲（通常很快）。
- **Monitoring / alerting**：Redis CPU、記憶體、網路連線；應用層限流成功率、延遲；進入 fail-open 模式時告警。

### 3) 如何降低延遲開銷？
- **連線池**（最重要）：長連線重用，省去 TCP handshake（可能 20-50ms，視網路距離）；多數 Redis client 內建，但要依請求量與 Redis 回應時間調整池大小。
- **地理分散**（最大收益）：API gateway 與 Redis cluster 部署在多 region，靠近使用者（東京用戶打維吉尼亞 Redis 延遲高）。代價是跨 region 一致性複雜度，但限流可接受 region 間 eventual consistency。
- 其他（簡述，面試除非被問否則避免）：本地快取限流狀態（stale 資料風險）、Redis pipelining / Lua 批次減少往返、request batching；增加複雜度，做好連線池與地理分散通常不需要。

### 4) 如何處理 hot key？
Hot key 來自濫用流量或合法高流量 client（分析系統、data pipeline、積極刷新的 mobile app），需要單一來源數萬 RPS 才會壓垮一個 shard。

**合法高流量 client**
- **Client-side rate limiting**：鼓勵 client（SDK 內建並遵守 server 回傳的 header）自行平滑流量。
- **Request queuing / batching**：允許 client 批次多個操作，減少限流檢查次數。
- **Premium tiers**：給重度用戶更高額度，可能搭配專用基礎設施。

**濫用流量**
- **自動封鎖**：持續撞限（如一分鐘內 10 次）就暫時封鎖該 IP/API key（blocklist 可放某個 Redis shard，僅在 cache miss 時檢查）。
- **DDoS 防護**：Cloudflare / AWS Shield 在到達限流器前擋掉惡意流量。

關鍵觀念：client-side 限流是 server-side 保護的補充，不是替代。共享 IP（企業 NAT、公共 WiFi）要在設計規則時預先調高 IP 限額，更依賴認證用戶限額。

### 5) 如何處理動態規則設定？
- **好解：Poll-based**。規則放 DB / config service，gateway 定期 poll（如每 30 秒）並本地快取；簡單、最常見。缺點：更新有延遲窗口（緊急降限額最久等 30 秒），一般運維可接受。
- **最佳解：Push-based**。用 **ZooKeeper**（設計目的就是分散式設定管理 + 即時通知）、Redis pub/sub 或自建 config service 維持長連線；規則改變數秒內通知所有 gateway。缺點：複雜（連線失敗、部分 gateway 更新失敗、需要 fallback）；通常僅在需要極快更新（安全事件、高頻交易）時才值得。

## 關鍵數字與 back-of-envelope
- 目標：1M RPS、100M DAU、檢查延遲 < 10ms
- 單 Redis：100k-200k ops/s；每次限流檢查 ≥ 2 個操作 → 實際 50k-100k checks/s
- 10 個 shard × ~100k ≈ 1M RPS
- Redis Cluster：16,384 hash slots
- EXPIRE 範例：閒置 3600 秒自動刪除 bucket
- 設定 poll 範例：30 秒
- TCP handshake 可能 20-50ms
- blocklist 範例條件：一分鐘內 10 次超限

## 面試官期待
- **Mid（80/20）**：清楚解釋一種限流演算法（Token Bucket 即可）；將限流器合理放在架構中（API Gateway）；指出 Redis 作為共享狀態；被問到擴展時知道要 shard Redis 並大致說明方式。
- **Senior（60/40）**：自信比較演算法取捨；不需引導就懂 consistent hashing、Redis Cluster、連線池；知道 Redis 操作需原子（提出 MULTI/EXEC）；清楚說明 fail-open vs fail-closed、各種放置位置優缺點；主動識別 hot key、Redis 可用性與延遲優化；能快速帶過演算法，花時間在分散式挑戰、shard 與 failover，並對設定管理有意見。
- **Staff+（40/60）**：展現生產環境的深度，引用相似規模的真實經驗；主動談邊界情況、observability、維運程序；對技術選擇有強意見；自然談 multi-region 與跨地理一致性、灰度發布與 canary；通常不會被問此題，若被問則快速建立基本設計，把時間花在生產運維、failure mode 與系統整合。

## 可遷移的 pattern
1. **擴大 atomic boundary（Dealing with Contention）**：read-modify-write 競爭用 Redis Lua script（或 CAS）把整段變成原子，不要只把「寫」放進 transaction。
2. **以 entity key 做 consistent hashing 分片（Scaling Writes）**：同一實體的狀態只在一個 shard；用 Redis Cluster 的 hash slot 取代自建路由。
3. **Fail-open vs fail-closed 作為顯式決策**：依業務風險選擇，並用 replica + 自動 failover + 告警降低觸發機率。
4. **邊緣 / 中央閘道集中橫切關注點**：把限流、認證等放在 API Gateway，讓 app server 只處理合法流量。
5. **Hot key 的多層處理**：client-side 限流、批次、tiering、自動封鎖、DDoS 服務；以及設計規則時預先考慮共享 IP。
6. **設定更新：poll 為預設，push 作升級**：以更新延遲需求決定複雜度。

## 常見追問
- **為什麼選 Token Bucket？** 同時支援持續速率與突發、狀態只需 (tokens, last_refill)、記憶體省；Fixed window 有邊界 2x 突發、Sliding log 太吃記憶體、Sliding counter 是近似且數學較易錯。
- **多個 gateway 同時處理同一用戶，如何避免超放？** 狀態集中在 Redis，並把讀取、計算、更新放進 Lua script 原子執行（MULTI/EXEC 無法涵蓋 transaction 外的讀取）。
- **Redis 掛了怎麼辦？** 預防靠 master-replica + Cluster 自動 failover；失效時依需求選 fail-open 或 fail-closed（本題選 fail-closed，因為故障常與尖峰同時發生）。
- **單一 Redis 撐不住 1M RPS？** 分片：依 user ID / IP / API key 做 consistent hashing（或 Redis Cluster），約 10 個 shard。
- **如何即時調整限額（如遭受攻擊）？** 預設 poll（~30 秒延遲）；需要秒級生效就用 ZooKeeper 等 push 機制，代價是複雜度。
- **為什麼超限不排隊？** 排隊耗資源、導致重試、回應時間不可預測；互動式 API 應 fail fast 回 429 + header。
