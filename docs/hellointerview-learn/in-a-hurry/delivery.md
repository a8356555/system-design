# System Design Delivery Framework
> 來源：https://www.hellointerview.com/learn/system-design/in-a-hurry/delivery ｜ 分類：in-a-hurry

## 一句話重點
中階候選人最常失敗的原因是「沒交付可運作系統」（常被包裝成 time management）；用固定步驟與時間配置：Requirements → Core Entities → API → (Data Flow) → High Level Design → Deep Dives。

## 核心內容
### 整體結構與時間
| 步驟 | 時間 |
|---|---|
| Requirements | ~5 min |
| Core Entities | ~2 min |
| API / System Interface | ~5 min |
| [Optional] Data Flow | ~5 min |
| High Level Design | ~10-15 min |
| Deep Dives | ~10 min |

結構的好處：聚焦面試官在意的點；緊張時有路可退；線性累積解法。

### 1. Requirements
**Functional**：「Users/Clients should be able to...」。像對客戶/PM 提問來取得優先順序；只挑前 3 項核心功能——需求太長弊大於利，FAANG 直接評估「聚焦重點」的能力。
- Twitter 例：發推、追蹤、看追蹤者的推文。Cache 例：insert、set expiration、read。

**Non-functional**：「The system should be...」；要放進系統脈絡並量化。「low latency」太空泛，「search < 500ms」才有意義。挑 3-5 個最相關的，檢查清單：
- CAP Theorem：一致性 vs 可用性（partition tolerance 在分散式中是前提）
- Environment Constraints：行動裝置電量、記憶體、頻寬（如 3G 串流）
- Scalability：是否有 bursty 流量、節日；read/write 比例，要 scale 讀還是寫
- Latency：需要大量計算的請求（如 Yelp 搜尋）
- Durability：資料遺失容忍度（社群 vs 銀行）
- Security：資料保護、存取控制、法規
- Fault Tolerance：冗餘、failover、recovery
- Compliance：法律/產業標準
- Twitter 例：可用性優先於一致性；支援 100M+ DAU；feed 渲染 < 200ms。

**Capacity Estimation**：原文認為常不必要。只在會直接影響設計時才算；告知面試官「先跳過，設計中需要再算」。例：Top-K 要估主題數量，決定單一 min-heap 夠不夠或要 shard。

### 2. Core Entities
- 條列即可，當作草稿；不一次列完整 data model，因為「不知道自己不知道」，進入 HLD 後再補欄位。
- 問自己：系統裡有哪些 actor？滿足需求需要哪些名詞/資源？
- 命名要好（有些面試官看這個）。Twitter：User、Tweet、Follow。

### 3. API / System Interface
- 協定選擇：REST（預設，HTTP verbs CRUD）；GraphQL（多樣 client、避免 over/under-fetching）；RPC/gRPC（內部服務、效能關鍵）。即時功能再加 WebSocket / SSE，但先設計核心 API。
- 資源用複數名詞：`POST /v1/tweets`、`GET /v1/tweets/{tweetId}`、`POST /v1/follows`（body: followee_id）、`GET /v1/feed -> Tweet[]`。
- 當前使用者由 auth token 推導，絕不從 request body / path 取敏感資訊（user ID）。

### 4. [Optional] Data Flow
- 資料處理型後端系統才需要；用簡單清單描述。Web crawler：抓 seed URL → parse HTML → 抽 URL → 存資料 → 重複。

### 5. High Level Design
- 畫方框箭頭（server、DB、cache…）。目標：設計出滿足 API → 滿足需求的架構；可逐個 endpoint 建構。
- 不要太早加複雜度！先簡單滿足功能需求，複雜度（cache、MQ）只口頭+筆記標記，留到 deep dive 處理 non-functional。
- 邊畫邊說：資料如何流動、每個請求改了哪些 state。碰到 DB 時寫出相關欄位（只寫對設計重要的，如 User 表的 name/email/password hash 不必寫）。
- 提前問 recruiter 白板工具並練習。

### 6. Deep Dives
- 用剩餘約 10 分鐘強化設計：滿足所有 non-functional、處理 edge case、找瓶頸、回應面試官探測。
- 主動程度隨資歷增加：junior 面試官會點出問題；senior 要自己找出並帶領討論。
- Twitter 例：scale 100M DAU → 水平擴展、cache、DB sharding；低延遲 feed → fanout-on-read vs fanout-on-write 與 cache（最有趣的點）。
- 陷阱：搶話。要留空間讓面試官提問，他們有想取得的特定訊號；否則傷 communication 評分。

## 面試怎麼用
- 開場先講「我會先做 requirements，估算先略過、需要時再算」。
- HLD 逐 endpoint 建構；想到優化只標註不展開。
- 關鍵陷阱：需求列太多、太早加複雜度、做無意義的 QPS 計算、API 用 body 傳 user ID、deep dive 時獨白。

## 關鍵數字
- 時間配置見上表；NFR 挑 3-5 個；功能需求聚焦前 3；範例 NFR：100M+ DAU、feed < 200ms、search < 500ms。

## 相關題目
[top-k](../../hellointerview-breakdowns/top-k.md)、[web-crawler](../../hellointerview-breakdowns/web-crawler.md)、[fb-news-feed](../../hellointerview-breakdowns/fb-news-feed.md)、[yelp](../../hellointerview-breakdowns/yelp.md)

## 自測問題
1. 為什麼 capacity estimation 常可略過？（算出「很大」不提供訊號；只在影響設計時才算，如決定是否 shard）
2. 好的 NFR 長怎樣？（量化且放在系統脈絡，如 search < 500ms）
3. API 為何不從 body 取 user ID？（應由 auth token 推導，避免偽造/安全問題）
4. HLD 階段想到 cache 該怎麼辦？（口頭標註、寫筆記，留到 deep dive）
5. Twitter feed 的 deep dive 重點？（fanout-on-read vs write、cache）
